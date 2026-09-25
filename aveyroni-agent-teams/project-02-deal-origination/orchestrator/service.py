"""Run one origination pass.

Orchestrating roles: Origination Controller, Research Coordinator, Fit Scorer, Evidence Reviewer.
Delegated workers: the five researchers in roles.WORKERS, via Hermes delegate_task.
Deterministic code: mandate parsing, entity and evidence normalization,
deduplication, validation, the MCA-registry discovery lookup, and the run file.
The fit scorer is a Hermes turn. Code publishes the label from its checklist.
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator import mca_registry
from orchestrator.deterministic import (
    dedupe_entities,
    entity_key,
    extract_json,
    parse_fit_judgments,
    parse_mandate,
    parse_worker_summary,
    public_targets,
    render_report,
    screen_entities,
    store_run,
)
from orchestrator.roles import (
    AFTER_SCORE,
    BATCH_SIZE,
    DISCOVERY_ID,
    FILL_ORDER,
    WORKERS,
    controller_message,
    fit_scorer_message,
    gap_plan,
    reviewer_message,
    tasks_for,
    WORKER_BY_ID,
    worker_task,
)

DETERMINISTIC_STEPS = (
    "mandate_parse",
    "mca_registry_query",
    "entity_normalize",
    "evidence_normalize",
    "deduplication",
    "data_validation",
    "database_store",
)

# Hermes progress-event types delegate_task relays from a live worker
# (tools/delegate_tool.py: _build_child_progress_callback). We surface a
# subset live in the trace; "thinking"/"progress"(batched digest)/"text"
# are intentionally not forwarded to the UI to keep the trace focused on
# actual tool calls rather than reasoning noise.
_SUBAGENT_PHASES = {
    "subagent.start": "start",
    "subagent.tool": "tool",
    "subagent.complete": "complete",
}


def _public_preview(value: object) -> str:
    """A worker's live line in the trace. Never a JSON payload or a code snippet."""
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if text[0] in "{[":
        return ""
    lowered = text.lower()
    if lowered.startswith(("import ", "from ", "def ", "class ")) or "hermes_tools" in lowered:
        return ""
    if "{" in text or "}" in text:
        return ""
    return _clip(text, 80)


def _clip(value: object, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _hermes_delegate(tasks: list[dict], parent_agent) -> str:
    from tools.delegate_tool import delegate_task

    return delegate_task(tasks=tasks, role="leaf", background=False, parent_agent=parent_agent)


class Orchestrator:
    def __init__(
        self, agent, on_event, runs_root: Path, system_prompt: str = "", history=None,
        delegate_fn=None, complete_fn=None, excluded_names=None, batch_index: int = 0,
    ):
        self.agent = agent
        self.on_event = on_event or (lambda _event: None)
        self.runs_root = Path(runs_root)
        self.system_prompt = system_prompt or ""
        self.history = list(history or [])
        self.delegate_fn = delegate_fn or _hermes_delegate
        self.complete_fn = complete_fn or self._hermes_complete
        self.excluded_names = [str(name).strip() for name in (excluded_names or []) if str(name).strip()]
        self.excluded_keys = {entity_key(name) for name in self.excluded_names}
        self.batch_index = max(0, int(batch_index))
        self.last_package: dict = {}

    def run(self, config: dict) -> str:
        # Best-effort: some test/fake agents (e.g. a bare object()) don't
        # support dynamic attribute assignment. Falling back to "no live
        # subagent stream" there is correct -- it's exactly what happened
        # before this feature existed, and it must never break a real run.
        saved_progress_cb = getattr(self.agent, "tool_progress_callback", None)
        try:
            self.agent.tool_progress_callback = self._on_subagent_progress
        except Exception:
            pass
        try:
            return self._run(config)
        finally:
            try:
                self.agent.tool_progress_callback = saved_progress_cb
            except Exception:
                pass

    def _run(self, config: dict) -> str:
        self._event("mandate_parse", "start", "Reading the saved buy box")
        mandate = parse_mandate(config)
        self._event("mandate_parse", "done", mandate["mandate_id"])

        self._event("origination_controller", "start", "Framing the buy box")
        controller_raw = self.complete_fn("controller", controller_message(mandate))
        focus_notes = _focus_notes(controller_raw)
        self._event("origination_controller", "done", "Buy box framed")

        discovery = self._discover(mandate, focus_notes)
        if self.excluded_keys:
            discovery = [
                {
                    **row,
                    "entities": [
                        entity for entity in row.get("entities") or []
                        if entity_key(entity.get("name") or "") not in self.excluded_keys
                    ],
                }
                for row in discovery
            ]
        names = _names(discovery)
        parsed = list(discovery)
        if names:
            for index, worker_ids in enumerate(_chunks(list(FILL_ORDER), BATCH_SIZE), start=1):
                parsed.extend(self._delegate(worker_ids, mandate, focus_notes, names, "fill", f"delegate-fill-{index}"))

        self._event("entity_normalize", "start", "Normalizing names")
        self._event("evidence_normalize", "start", "Dropping claims without a source and an excerpt")
        self._event("deduplication", "start", "Merging the same target")
        entities = dedupe_entities([entity for row in parsed for entity in row["entities"]])
        entities = _keep_named(entities, names)
        gaps = gap_plan(entities, mandate)
        if gaps:
            for index, worker_ids in enumerate(_chunks(list(gaps), BATCH_SIZE), start=1):
                tasks = [
                    worker_task(WORKER_BY_ID[worker_id], mandate, focus_notes, [], "gap", gaps[worker_id])
                    for worker_id in worker_ids
                ]
                labels = [WORKER_BY_ID[worker_id]["name"] for worker_id in worker_ids]
                parsed.extend(self._delegate_tasks(
                    tasks,
                    worker_ids,
                    f"delegate-gap-{index}",
                    "Gap pass · " + " · ".join(labels),
                ))
            entities = _keep_named(
                dedupe_entities([entity for row in parsed for entity in row["entities"]]),
                names,
            )
        self._event("entity_normalize", "done", f"{len(entities)} target{'s' if len(entities) != 1 else ''}")
        self._event("evidence_normalize", "done", f"{sum(len(entity['claims']) for entity in entities)} sourced claims")
        self._event("deduplication", "done", f"{len(entities)} after merge")

        self._event("fit_scorer", "start", "Judging excerpts against the buy box")
        scorer_raw = self.complete_fn("fit-scorer", fit_scorer_message(mandate, entities))
        judgments = parse_fit_judgments(scorer_raw)
        self._event("fit_scorer", "done", "Judged the excerpts")
        self._event("data_validation", "start", "Publishing the label from the scorer's checklist")
        screened = screen_entities(entities, mandate, judgments)
        problems = sum(len(entity["validation_errors"]) for entity in screened)
        self._event("data_validation", "done", "ok" if not problems else f"{problems} validation error{'s' if problems != 1 else ''}")

        if names:
            later = self._delegate(list(AFTER_SCORE), mandate, focus_notes, names, "fill", "delegate-relationship")
            parsed.extend(later)
            screened = _merge_claims(screened, later)

        package = {
            "mandate": mandate,
            "roles": {
                "orchestrating": ["origination-controller", "research-coordinator", "fit-scorer", "evidence-reviewer"],
                "delegated_workers": [worker["id"] for worker in WORKERS],
                "deterministic": list(DETERMINISTIC_STEPS),
            },
            "controller": {"focus_notes": focus_notes, "raw": _clip(controller_raw, 500)},
            "fit_scorer": {"raw": _clip(scorer_raw, 4000)},
            "entities": screened,
            "worker_failures": [row["worker"] for row in parsed if row.get("unparsed")],
            "red_team": "",
            "batch_index": self.batch_index,
        }

        self._event("evidence_reviewer", "start", "Red team")
        package["red_team"] = self.complete_fn("reviewer", reviewer_message(package))
        self._event("evidence_reviewer", "done", "Review filed")
        self._event("database_store", "start", mandate["mandate_id"])
        path = store_run(self.runs_root, package)
        package["path"] = str(path)
        path.write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n")
        self.last_package = package
        self._event("database_store", "done", path.name)

        report = render_report(package)
        self.on_event({"targets": public_targets(package)})
        self.on_event({"delta": report})
        return report

    def _discover(self, mandate: dict, focus_notes: str) -> list[dict]:
        """Name the candidates. The MCA registry (deterministic, no model call)
        pre-filters India operating-company mandates when it is configured and
        the mandate's sector maps to a known NIC range; otherwise the web
        Company Researcher discovers names as before. Either way, every
        worker after this point only researches the names this step returns —
        `_keep_named()` enforces that regardless of which source produced them.
        """
        if mca_registry.applies(mandate):
            self._event("mca_registry_query", "start", "Querying the MCA company registry — India, NIC-filtered, active, not a shell")
            row = mca_registry.discover(
                mandate,
                offset=self.batch_index * 12,
                exclude_names=list(self.excluded_keys),
            )
            if row.get("error"):
                self._event("mca_registry_query", "done", f"Registry unreachable ({row['error']}) — falling back to web discovery")
            else:
                count = len(row["entities"])
                self._event("mca_registry_query", "done", f"{count} candidate{'s' if count != 1 else ''} from the registry")
                if row["entities"]:
                    return [row]
        if self.excluded_keys:
            excluded = ", ".join(self.excluded_names)
            focus_notes = (
                f"{focus_notes} This is sourcing batch {self.batch_index + 1}. "
                f"Do not return any previously screened company: {excluded}."
            )
        return self._delegate([DISCOVERY_ID], mandate, focus_notes, [], "discover", "delegate-discover")

    def _delegate(self, worker_ids: list[str], mandate: dict, focus_notes: str, names: list[str], mode: str, step_id: str) -> list[dict]:
        labels = [worker["name"] for worker in WORKERS if worker["id"] in worker_ids]
        return self._delegate_tasks(
            tasks_for(worker_ids, mandate, focus_notes, names, mode),
            worker_ids,
            step_id,
            "Research Coordinator · " + " · ".join(labels),
        )

    def _delegate_tasks(self, tasks: list[dict], worker_ids: list[str], step_id: str, detail: str) -> list[dict]:
        self._event_named(step_id, "delegate_task", "start", detail)
        raw = self.delegate_fn(tasks, self.agent)
        summaries = _summaries(raw, worker_ids)
        self._event_named(step_id, "delegate_task", "done", _clip(_batch_done(summaries)))
        return summaries

    def _on_subagent_progress(self, event_type, tool_name=None, preview=None, args=None, **kwargs) -> None:
        """Bridges Hermes' live per-worker progress (tools/delegate_tool.py's
        _build_child_progress_callback) into an on_event('subagent', ...)
        the UI renders as a nested, streaming line under the matching
        worker chip — the same live-tool-call visibility Claude Code and
        Hermes' own desktop app show, which delegate_task's blocking
        return value alone never carries. Best-effort: swallow anything
        odd rather than let a bridging problem touch the actual research.
        """
        phase = _SUBAGENT_PHASES.get(str(event_type))
        if not phase:
            return
        try:
            goal = str(kwargs.get("goal") or "")
            worker = goal.split(". ", 1)[0].strip() if goal else ""
            self.on_event({
                "subagent": {
                    "phase": phase,
                    "worker": worker,
                    "tool_name": str(tool_name or ""),
                    "preview": _public_preview(preview),
                }
            })
        except Exception:
            return

    def _hermes_complete(self, role: str, user_message: str) -> str:
        agent = self.agent
        saved_tools = getattr(agent, "tools", None)
        saved_cached = getattr(agent, "_cached_system_prompt", None)
        try:
            agent.tools = []
            result = agent.run_conversation(
                user_message=user_message,
                system_message=self.system_prompt or None,
                conversation_history=list(self.history),
                task_id=str(getattr(agent, "session_id", "") or "") or None,
            )
        finally:
            agent.tools = saved_tools
            if saved_cached is not None:
                agent._cached_system_prompt = saved_cached
            self._restore_stored_prompt(saved_cached)
        return str((result or {}).get("final_response") or "").strip()

    def _restore_stored_prompt(self, prompt: str | None) -> None:
        if not prompt:
            return
        db = getattr(self.agent, "_session_db", None) or getattr(self.agent, "session_db", None)
        session_id = getattr(self.agent, "session_id", None)
        if db is None or not session_id or not hasattr(db, "update_system_prompt"):
            return
        try:
            db.update_system_prompt(session_id, prompt)
        except Exception:
            return

    def _event(self, name: str, phase: str, detail: str) -> None:
        self._event_named(name, name, phase, detail)

    def _event_named(self, step_id: str, name: str, phase: str, detail: str) -> None:
        self.on_event({
            "tool": {
                "phase": phase,
                "id": step_id,
                "name": name,
                "detail": _clip(detail),
            }
        })


def _focus_notes(raw: str) -> str:
    payload = extract_json(raw or "")
    if isinstance(payload, dict):
        notes = payload.get("focus_notes")
        if isinstance(notes, str) and notes.strip():
            return notes.strip()
    text = " ".join(str(raw or "").split())
    return text[:400]


def _summaries(raw: object, worker_ids: list[str]) -> list[dict]:
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        return [_empty(worker_id, "Worker returned nothing usable.") for worker_id in worker_ids]
    if payload.get("error") and not payload.get("results"):
        return [_empty(worker_id, str(payload.get("error"))) for worker_id in worker_ids]
    results = payload.get("results") or []
    by_index = {}
    if isinstance(results, list):
        for entry in results:
            if isinstance(entry, dict) and isinstance(entry.get("task_index"), int):
                by_index[entry["task_index"]] = str(entry.get("summary") or "")
    parsed = []
    for index, worker_id in enumerate(worker_ids):
        summary = by_index.get(index, "")
        row = parse_worker_summary(summary, worker_id)
        if not summary:
            row["unparsed"] = True
        parsed.append(row)
    return parsed


def _empty(worker_id: str, summary: str) -> dict:
    row = parse_worker_summary(summary, worker_id)
    row["unparsed"] = True
    return row


def _chunks(items: list, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _merge_claims(screened: list[dict], rows: list[dict]) -> list[dict]:
    """Attach claims that arrive after the fit score. The score is not recomputed."""
    incoming = dedupe_entities([entity for row in rows for entity in row.get("entities") or []])
    by_id = {entity["entity_id"]: entity for entity in incoming}
    for entity in screened:
        extra = by_id.get(entity.get("entity_id"))
        if not extra:
            continue
        entity["claims"].extend(extra.get("claims") or [])
        entity["unknowns"] = sorted(set(entity.get("unknowns") or []) | set(extra.get("unknowns") or []))
    return screened


def _keep_named(entities: list[dict], names: list[str]) -> list[dict]:
    """Specialists research the company researcher's list. They do not add names."""
    if not names:
        return []
    allowed = {entity_key(name) for name in names}
    return [entity for entity in entities if entity.get("entity_id") in allowed]


def _names(rows: list[dict]) -> list[str]:
    seen = []
    for row in rows:
        for entity in row.get("entities") or []:
            name = entity.get("name")
            if name and name not in seen:
                seen.append(name)
    return seen


def _batch_done(rows: list[dict]) -> str:
    parts = []
    for row in rows:
        count = len(row.get("entities") or [])
        parts.append(f"{row['worker']} {count}")
    return ", ".join(parts)
