#!/usr/bin/env python3
"""Local chat for the Aveyroni origination desk.

One Hermes agent stays alive for the life of the page session. Each message
is the next turn of that conversation, not a fresh one-shot process.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
CHAT = Path(__file__).resolve().parent
HERMES_REPO = Path.home() / ".hermes" / "hermes-agent"
MANDATE = ROOT / "examples" / "india-auto-components" / "mandate.json"
CONFIG_PATH = CHAT / "desk-config.json"
MANDATES_PATH = CHAT / "mandates"
REGISTRY_PATH = MANDATES_PATH / "registry.json"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8791"))
SKILLS = ["origination-controller", "tavily"]
# Demo default. The saved Hermes model stays minimax-m3 for other sessions.
DEMO_PROVIDER = "openai-codex"
DEMO_MODEL = "gpt-5.6-luna"
MODEL_CHOICES = [
    {"provider": "openai-codex", "model": "gpt-5.6-luna", "label": "GPT 5.6 Luna"},
    {"provider": "openai-codex", "model": "gpt-5.6-sol", "label": "GPT 5.6 Sol"},
    {"provider": "openai-codex", "model": "gpt-5.6-terra", "label": "GPT 5.6 Terra"},
]
BUY_BOX_MARK = "\n\n---\nDesk user message:\n"
FOCUS_CHOICES = [
    {"id": "operating-company", "label": "Operating company"},
    {"id": "real-estate", "label": "Real estate"},
]
ASSET_TYPES = [
    {"id": "multi-family", "label": "Multi-family", "screen": "units, occupancy, in-place rent, vintage, and basis per unit"},
    {"id": "single-family", "label": "Single-family", "screen": "price, beds and baths or yield, and whether it is one house or a scattered rental portfolio"},
    {"id": "build-to-rent", "label": "Build-to-rent", "screen": "community scale, delivery year, and in-place or pro forma rent"},
    {"id": "mixed-use", "label": "Mixed-use", "screen": "the residential share of income, and the commercial tenants"},
    {"id": "student-housing", "label": "Student housing", "screen": "beds, distance to campus, and pre-lease rate"},
    {"id": "senior-housing", "label": "Senior housing", "screen": "units, care level, and occupancy"},
    {"id": "manufactured-housing", "label": "Manufactured housing", "screen": "pads or homes, lot rent, and community occupancy"},
]
CURRENCIES = ["USD", "INR", "EUR", "GBP"]
REVENUE_SCALES = ["million", "billion", "crore"]

sys.path.insert(0, str(HERMES_REPO))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from orchestrator.deterministic import extract_json, public_targets, render_report, store_run
from orchestrator.mca_registry import NIC_SECTOR_OPTIONS, sector_codes_for_labels
from orchestrator.outreach import (
    approve as approve_outreach,
    default_copy as default_outreach_copy,
    deliver as deliver_outreach,
    list_drafts as list_outreach_drafts,
    prepare as prepare_outreach,
    readiness as outreach_readiness,
    reject as reject_outreach,
    suppress as suppress_outreach,
)
from orchestrator.service import Orchestrator

TURN_LOCK = threading.Lock()
DESKS: dict[str, "Desk"] = {}
ORIGINATION_TARGET_GOAL = max(1, int(os.environ.get("AVEYRONI_TARGET_GOAL", "10")))
# Runaway cap only. The advertised stop is ORIGINATION_TARGET_GOAL mandate-fit
# companies, not a batch count.
ORIGINATION_MAX_BATCHES = max(ORIGINATION_TARGET_GOAL, int(os.environ.get("AVEYRONI_MAX_BATCHES", "100")))
MATERIAL_CONFIG_FIELDS = {
    "focus", "provider", "model", "geography", "sector", "sector_codes",
    "revenue_min", "revenue_max", "revenue_scale", "ownership",
    "exclude_ownership", "asset_types", "units_min", "units_max",
    "price_min", "price_max", "currency", "strategy", "exclude_assets",
}


def load_hermes_env() -> None:
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# A material mandate edit correctly wipes targets_available (see
# _update_mandate) so a stale result never gets shown under a mandate it no
# longer matches. But nothing then re-runs the pipeline automatically, and a
# live "Run team" pass needs a Hermes install, a search credential, a page-
# extraction credential, and a usable model-provider credential -- none of
# which this desk can assume are configured. Rather than let the desk sit at
# "None yet" with no explanation, or let a blocked run fail deep inside
# Desk.ensure() with a raw stack trace, probe readiness up front and report
# exactly what is missing. Read-only: this never starts an agent or spends
# a token.
def orchestrator_readiness(mandate_id: object = None) -> dict:
    load_hermes_env()
    missing: list[str] = []
    if not HERMES_REPO.exists():
        missing.append("Hermes agent is not installed at ~/.hermes/hermes-agent.")
    if not (os.environ.get("EXA_API_KEY") or os.environ.get("TAVILY_API_KEY")):
        missing.append("No search credential (EXA_API_KEY or TAVILY_API_KEY) in ~/.hermes/.env.")
    if not os.environ.get("FIRECRAWL_API_KEY"):
        missing.append("No FIRECRAWL_API_KEY in ~/.hermes/.env for page extraction.")
    provider_label = ""
    try:
        from hermes_cli.runtime_provider import resolve_runtime_provider
        config = load_desk_config(mandate_id)
        provider_label = config.get("provider", "")
        resolve_runtime_provider(requested=config["provider"], target_model=config["model"])
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        label = provider_label or "the configured provider"
        missing.append(f"Model provider not ready ({label}): {detail}")
    return {"ready": not missing, "missing": missing}


def _clip(value: object, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _tool_detail(name: str, args: object) -> str:
    if not isinstance(args, dict):
        return ""
    if name == "delegate_task":
        tasks = args.get("tasks")
        if isinstance(tasks, list) and tasks:
            goals = [
                _clip(task.get("goal"), 80)
                for task in tasks
                if isinstance(task, dict) and task.get("goal")
            ]
            return "parallel · " + " · ".join(goals)
        return _clip(args.get("goal") or args.get("role") or "")
    for key in ("query", "url", "command", "path", "goal", "skill"):
        if args.get(key):
            return _clip(args.get(key))
    return ""


# Tool results the desk's own top-level agent produces during a regular
# chat turn (not the orchestrated "Run team" pipeline, which always builds
# its own clean detail strings) can be arbitrary structured JSON -- e.g.
# skill_view returns {"success": true, "name": ..., "description": ...,
# "tags": [...]}. A raw json.dumps() of that is exactly what a client saw
# in the live trace: an unformatted API payload. Never show that; always
# reduce to a short human phrase, and fall back to something generic
# rather than the raw structure when nothing recognizable is present.
_RESULT_TEXT_KEYS = ("description", "message", "summary", "title")
_RESULT_COUNT_KEYS = ("total_count", "count")


def _result_detail(result: object) -> str:
    if isinstance(result, str):
        text = result.strip()
        if text[:1] in "{[":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return "Done."
            return _result_detail(parsed)
        return _clip(result)
    if isinstance(result, dict):
        for key in _RESULT_TEXT_KEYS:
            text = result.get(key)
            if isinstance(text, str) and text.strip():
                return _clip(text)
        for key in _RESULT_COUNT_KEYS:
            count = result.get(key)
            if isinstance(count, int) and not isinstance(count, bool):
                noun = "file" if isinstance(result.get("files"), list) else "result"
                return _clip(f"{count} {noun}{'s' if count != 1 else ''}")
        name = result.get("name")
        success = result.get("success")
        if isinstance(name, str) and name.strip() and isinstance(success, bool):
            return _clip(f"{name} — {'ok' if success else 'failed'}")
        if isinstance(name, str) and name.strip():
            return _clip(name)
        if isinstance(success, bool):
            return "Done." if success else "Failed."
        return "Done."
    if isinstance(result, list):
        return _clip(f"{len(result)} result{'s' if len(result) != 1 else ''}")
    return "Done."


def _words(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _optional_int(value: object, label: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number.") from None
    if number < 0 or number > 100_000_000_000:
        raise ValueError(f"{label} is out of range.")
    return number


def _pair(low: int | None, high: int | None, label: str) -> None:
    if (low is None) != (high is None):
        raise ValueError(f"Set both {label} bounds, or leave both blank.")
    if low is not None and high is not None and low >= high:
        raise ValueError(f"The {label} minimum must be below the maximum.")


def _default_config() -> dict:
    mandate = json.loads(MANDATE.read_text())
    return {
        "title": "India Auto Components",
        "focus": "operating-company",
        "provider": os.environ.get("AVEYRONI_PROVIDER", "").strip() or DEMO_PROVIDER,
        "model": os.environ.get("AVEYRONI_MODEL", "").strip() or DEMO_MODEL,
        "geography": _words(mandate.get("geography") or ["India"]),
        "sector": _words(mandate.get("sector") or ["auto components"]),
        "sector_codes": ["291", "292", "293"],
        "revenue_min_inr_cr": int(mandate.get("revenue_min_inr_cr") or 300),
        "revenue_max_inr_cr": int(mandate.get("revenue_max_inr_cr") or 1500),
        "revenue_min": int(mandate.get("revenue_min_inr_cr") or 300),
        "revenue_max": int(mandate.get("revenue_max_inr_cr") or 1500),
        "revenue_scale": "crore",
        "ownership": _words(mandate.get("ownership") or ["founder", "family"]),
        "exclude_ownership": _words(mandate.get("exclude_ownership") or ["private_equity"]),
        "asset_types": ["multi-family", "single-family"],
        "units_min": None,
        "units_max": None,
        "price_min": None,
        "price_max": None,
        "currency": "INR",
        "strategy": "",
        "exclude_assets": [],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _mandate_dir(mandate_id: str) -> Path:
    return MANDATES_PATH / mandate_id


def _config_path(mandate_id: str) -> Path:
    return _mandate_dir(mandate_id) / "config.json"


def _history_path(mandate_id: str) -> Path:
    return _mandate_dir(mandate_id) / "history.json"


def _load_registry() -> dict:
    """Load the registry, importing the old singleton config on first use."""
    if REGISTRY_PATH.exists():
        value = json.loads(REGISTRY_PATH.read_text())
        if isinstance(value, dict) and isinstance(value.get("mandates"), dict):
            return value

    config = _default_config()
    if CONFIG_PATH.exists():
        stored = json.loads(CONFIG_PATH.read_text())
        if isinstance(stored, dict):
            config.update(normalize_config(stored, partial=True))
    # This ID deliberately matches the existing runs/india-auto-components
    # directory.  It remains immutable even if the imported title is renamed.
    mandate_id = "india-auto-components"
    config["mandate_id"] = mandate_id
    created = _now()
    registry = {
        "version": 1,
        "active_mandate_id": mandate_id,
        "mandates": {
            mandate_id: {
                "mandate_id": mandate_id,
                "title": config["title"],
                "created_at": created,
                "updated_at": created,
                "targets_available": (ROOT / "runs" / mandate_id / "orchestrator-run.json").exists(),
            }
        },
    }
    _write_json(_config_path(mandate_id), config)
    _write_json(_history_path(mandate_id), {"session_id": "", "messages": [], "visible_messages": []})
    _write_json(REGISTRY_PATH, registry)
    return registry


def _save_registry(registry: dict) -> None:
    _write_json(REGISTRY_PATH, registry)


def active_mandate_id() -> str:
    return str(_load_registry()["active_mandate_id"])


def resolve_mandate_id(mandate_id: object = None) -> str:
    resolved = str(mandate_id or active_mandate_id()).strip()
    if resolved not in _load_registry()["mandates"]:
        raise KeyError("Mandate not found.")
    return resolved


def load_desk_config(mandate_id: object = None) -> dict:
    resolved = resolve_mandate_id(mandate_id)
    stored = json.loads(_config_path(resolved).read_text())
    config = normalize_config(stored, partial=True)
    config["mandate_id"] = resolved
    return config


def load_history(mandate_id: str) -> dict:
    path = _history_path(mandate_id)
    if not path.exists():
        return {"session_id": "", "messages": [], "visible_messages": []}
    value = json.loads(path.read_text())
    return value if isinstance(value, dict) else {"session_id": "", "messages": [], "visible_messages": []}


def save_history(mandate_id: str, messages: list, session_id: str = "") -> None:
    _write_json(_history_path(mandate_id), {
        "session_id": session_id,
        "messages": messages,
        "visible_messages": visible_turns(messages),
        "updated_at": _now(),
    })


def clear_history(mandate_id: str) -> None:
    current = DESKS.pop(mandate_id, None)
    if current is not None:
        current.close(clear_history=False)
    save_history(mandate_id, [], "")


def mandate_summary(mandate_id: str, metadata: dict) -> dict:
    config = load_desk_config(mandate_id)
    return {
        **metadata,
        "focus": config["focus"],
        "geography": config["geography"],
        "sector": config["sector"],
        "asset_types": config["asset_types"],
        "active": mandate_id == active_mandate_id(),
    }


def normalize_config(payload: dict, partial: bool = False) -> dict:
    current = _default_config() if partial else {}
    allowed = {choice["model"]: choice["provider"] for choice in MODEL_CHOICES}
    model = str(payload.get("model") or current.get("model") or DEMO_MODEL).strip()
    if model not in allowed:
        raise ValueError("Choose a Codex model from the list.")
    title = str(payload.get("title") or current.get("title") or "").strip()
    if not title:
        raise ValueError("Name the mandate.")
    if len(title) > 80:
        raise ValueError("Mandate name is too long.")
    focus = str(payload.get("focus") or current.get("focus") or "operating-company").strip()
    if focus not in {item["id"] for item in FOCUS_CHOICES}:
        raise ValueError("Choose an operating-company or real-estate buy box.")
    geography = _words(payload.get("geography", current.get("geography")))
    raw_sector = _words(payload.get("sector", current.get("sector")))
    known_sector_codes = {item["id"] for item in NIC_SECTOR_OPTIONS}
    if "sector_codes" in payload:
        sector_codes = [
            code for code in _words(payload.get("sector_codes"))
            if code in known_sector_codes
        ]
    elif "sector" in payload:
        sector_codes = sector_codes_for_labels(raw_sector)
    else:
        sector_codes = [
            code for code in _words(current.get("sector_codes"))
            if code in known_sector_codes
        ] or sector_codes_for_labels(raw_sector)
    sectors_by_code = {item["id"]: item["sector"] for item in NIC_SECTOR_OPTIONS}
    sector = [sectors_by_code[code] for code in sector_codes] if sector_codes else raw_sector
    ownership = _words(payload.get("ownership", current.get("ownership")))
    if "exclude_ownership" in payload:
        exclude = _words(payload.get("exclude_ownership"))
    else:
        exclude = _words(current.get("exclude_ownership") or ["private_equity"])
    if not geography:
        raise ValueError("Geography is required.")
    if focus == "operating-company" and (not sector or not ownership):
        raise ValueError("Sector and ownership are required for an operating company.")
    currency = str(payload.get("currency") or current.get("currency") or "USD").strip().upper()
    if currency not in CURRENCIES:
        raise ValueError("Choose USD, INR, EUR, or GBP.")
    revenue_scale = str(payload.get("revenue_scale") or current.get("revenue_scale") or "million").strip().lower()
    if revenue_scale not in REVENUE_SCALES:
        raise ValueError("Choose million, billion, or crore for the revenue unit.")
    raw_low = payload.get(
        "revenue_min",
        payload.get("revenue_min_inr_cr", current.get("revenue_min", current.get("revenue_min_inr_cr"))),
    )
    raw_high = payload.get(
        "revenue_max",
        payload.get("revenue_max_inr_cr", current.get("revenue_max", current.get("revenue_max_inr_cr"))),
    )
    if focus == "real-estate":
        revenue_low, revenue_high = None, None
    else:
        try:
            revenue_low = int(raw_low)
            revenue_high = int(raw_high)
        except (TypeError, ValueError):
            raise ValueError("Revenue bounds must be whole numbers.") from None
    if focus == "operating-company" and (
        revenue_low < 0 or revenue_high > 100_000_000_000 or revenue_low >= revenue_high
    ):
        raise ValueError("Revenue minimum must be below the maximum.")
    known_assets = {item["id"] for item in ASSET_TYPES}
    asset_types = [item for item in _words(payload.get("asset_types", current.get("asset_types"))) if item in known_assets]
    if focus == "real-estate" and not asset_types:
        raise ValueError("Choose at least one asset type, such as multi-family or single-family.")
    units_min = _optional_int(payload.get("units_min", current.get("units_min")), "Minimum units")
    units_max = _optional_int(payload.get("units_max", current.get("units_max")), "Maximum units")
    price_min = _optional_int(payload.get("price_min", current.get("price_min")), "Minimum price")
    price_max = _optional_int(payload.get("price_max", current.get("price_max")), "Maximum price")
    _pair(units_min, units_max, "unit")
    _pair(price_min, price_max, "price")
    strategy = str(payload.get("strategy", current.get("strategy") or "") or "").strip()
    if len(strategy) > 160:
        raise ValueError("Strategy is too long.")
    return {
        "title": title,
        "focus": focus,
        "provider": allowed[model],
        "model": model,
        "geography": geography,
        "sector": sector if focus == "operating-company" else [],
        "sector_codes": sector_codes if focus == "operating-company" else [],
        "revenue_min": revenue_low,
        "revenue_max": revenue_high,
        "revenue_scale": revenue_scale,
        "revenue_min_inr_cr": revenue_low if currency == "INR" and revenue_scale == "crore" else None,
        "revenue_max_inr_cr": revenue_high if currency == "INR" and revenue_scale == "crore" else None,
        "ownership": ownership if focus == "operating-company" else [],
        "exclude_ownership": exclude if focus == "operating-company" else [],
        "asset_types": asset_types if focus == "real-estate" else [],
        "units_min": units_min if focus == "real-estate" else None,
        "units_max": units_max if focus == "real-estate" else None,
        "price_min": price_min if focus == "real-estate" else None,
        "price_max": price_max if focus == "real-estate" else None,
        "currency": currency,
        "strategy": strategy if focus == "real-estate" else "",
        "exclude_assets": (
            _words(payload.get("exclude_assets"))
            if focus == "real-estate" and "exclude_assets" in payload
            else (_words(current.get("exclude_assets")) if focus == "real-estate" else [])
        ),
    }


def latest_targets(mandate_id: object = None) -> list:
    mandate_id = resolve_mandate_id(mandate_id)
    metadata = _load_registry()["mandates"][mandate_id]
    if not metadata.get("targets_available"):
        return []
    path = ROOT / "runs" / mandate_id / "orchestrator-run.json"
    if not path.exists():
        return []
    try:
        package = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(package, dict):
        return []
    return public_targets(package)


def current_visible_history(mandate_id: str, messages: list) -> list:
    """Render the latest saved run using the current public-display policy."""
    visible = visible_turns(messages)
    if (
        len(visible) < 2
        or visible[-1].get("role") != "agent"
        or visible[-2].get("role") != "user"
        or visible[-2].get("text") != "Run the origination team on the active buy box."
    ):
        return visible
    path = ROOT / "runs" / mandate_id / "orchestrator-run.json"
    try:
        package = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return visible
    if isinstance(package, dict):
        visible[-1] = {**visible[-1], "text": render_report(package).strip()}
    return visible


def public_config(config: dict | None = None) -> dict:
    config = config or load_desk_config()
    selected = [item for item in ASSET_TYPES if item["id"] in config.get("asset_types", [])]
    return {
        **config,
        "models": MODEL_CHOICES,
        "provider_label": "OpenAI Codex",
        "focuses": FOCUS_CHOICES,
        "asset_catalog": ASSET_TYPES,
        "sector_catalog": NIC_SECTOR_OPTIONS,
        "currencies": CURRENCIES,
        "revenue_scales": REVENUE_SCALES,
        "asset_screen": selected,
        "brief": buy_box_text(config),
        "orchestrator": orchestrator_readiness(config.get("mandate_id")),
    }


def _money(config: dict) -> str:
    if config.get("price_min") is None:
        return "not constrained"
    return f"{config['currency']} {config['price_min']:,}–{config['price_max']:,}"


# A chat turn's agent has full tool access -- including running its own
# scripts and writing files -- and, with the origination-controller skill
# preloaded as its system prompt, will happily interpret a casual "look
# into X" message as an instruction to literally execute that skill's
# steps by hand: writing mandate.json/target-universe.jsonl/etc. straight
# to runs/<invented-id>/, outside the mandate registry, with none of the
# structured pipeline's evidence discipline (no delegate_task fan-out, no
# fit scorer, no data_validation). A real incident: a message asking about
# a food-processing mandate produced runs/india-food-processing-001/ --
# never registered, never reachable from the UI, an unverifiable dead end.
# The skill's own honesty norms held (every field was correctly labeled
# "not_scored"/"verification_pending", nothing was fabricated) but the
# *scope* was wrong. This line is prepended to every chat turn to keep
# "run/research/find companies for this mandate" requests routed to the
# real pipeline instead.
CHAT_SCOPE_GUARDRAIL = (
    "This is a follow-up chat turn, not a research run. If asked to run new "
    "research, discover or refresh candidates, or build this mandate's "
    "target list, do not write mandate/target files or run scripts "
    "yourself -- tell the user to click \"Run team\" in the desk, which runs "
    "the full verified pipeline (delegate_task fan-out, fit scoring, "
    "evidence review) and saves the run under the mandate registry. Answer "
    "only from results already on file, or answer general questions."
)


def buy_box_text(config: dict) -> str:
    if config.get("focus") == "real-estate":
        selected = [item for item in ASSET_TYPES if item["id"] in config.get("asset_types", [])]
        lines = [
            f"Name: {config['title']}",
            "Focus: real estate acquisition. Screen properties, not operating companies.",
            "Ignore factory, OEM, auto-component, and crore-revenue tests from other skills.",
            f"Markets: {', '.join(config['geography'])}",
            "Asset types in the buy box: " + ", ".join(item["label"] for item in selected) + ".",
            "A property is in the box only when a source describes it as one of those types. Do not reclassify it to make it fit.",
            "Tune the search, the comparison, and the write-up to the asset type:",
        ]
        lines.extend(f"- {item['label']}: {item['screen']}." for item in selected)
        units = "not constrained"
        if config.get("units_min") is not None:
            units = f"{config['units_min']}–{config['units_max']}"
        lines.append(f"Units: {units}.")
        lines.append(f"Price: {_money(config)}.")
        if config.get("strategy"):
            lines.append(f"Strategy: {config['strategy']}.")
        if config.get("exclude_assets"):
            lines.append("Exclude: " + ", ".join(config["exclude_assets"]) + ".")
        lines.extend([
            "Keep mandate fit and transaction status separate.",
            "Leave fit blank if asset type, market, or the size measure for that asset type is unknown.",
            "No public listing is not proof the property is off-market.",
            "Do not contact anyone.",
            CHAT_SCOPE_GUARDRAIL,
        ])
        return "\n".join(lines)
    return "\n".join([
        f"Name: {config['title']}",
        "Focus: operating company. Screen businesses, not properties.",
        f"Geography: {', '.join(config['geography'])}",
        f"Sector: {', '.join(config['sector'])}",
        f"Revenue: {config['currency']} {config['revenue_min']}–{config['revenue_max']} {config['revenue_scale']}",
        f"Ownership: {', '.join(config['ownership'])}",
        f"Exclude ownership: {', '.join(config['exclude_ownership'])}",
        "Keep mandate fit and transaction status separate.",
        "Do not contact anyone.",
        CHAT_SCOPE_GUARDRAIL,
    ])


def visible_turns(messages: list) -> list[dict]:
    turns = []
    for message in messages or []:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = message.get("content")
        if isinstance(content, list):
            text = "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in (None, "text")
            )
        else:
            text = str(content or "")
        if BUY_BOX_MARK in text:
            text = text.split(BUY_BOX_MARK, 1)[1]
        text = "\n".join(
            line for line in text.splitlines()
            if line.strip() not in {
                "No quote that the owner wants to sell.",
                "A source quotes the owner, or their adviser, on an intent to sell.",
            }
            and not line.strip().lower().startswith("seller interest:")
        )
        text = text.strip()
        if text:
            turns.append({"role": "user" if role == "user" else "agent", "text": text})
    return turns


class Desk:
    """One ongoing Hermes conversation."""

    def __init__(self, mandate_id: str) -> None:
        self.mandate_id = mandate_id
        self.agent = None
        self.session_db = None
        persisted = load_history(mandate_id)
        self.history: list = persisted.get("messages") or []
        self.system_prompt = ""
        # A newly constructed Hermes agent owns its new runtime session.  The
        # persisted full message list, not Hermes' local task id, resumes the
        # conversation safely after a server restart.
        self.session_id = ""
        self.error = ""

    def ensure(self) -> None:
        if self.agent is not None:
            return
        load_hermes_env()
        os.environ["HERMES_YOLO_MODE"] = "1"
        os.environ["HERMES_ACCEPT_HOOKS"] = "1"
        from gateway.session_context import declare_stateless_channel
        from hermes_cli.config import load_config
        from hermes_cli.fallback_config import get_fallback_chain
        from hermes_cli.mcp_startup import ensure_mcp_discovery_before_agent_build
        from hermes_cli.runtime_provider import resolve_runtime_provider
        from hermes_cli.tools_config import _get_platform_tools
        from hermes_state import SessionDB
        from run_agent import AIAgent
        import logging

        declare_stateless_channel()
        cfg = load_config()
        desk_config = load_desk_config(self.mandate_id)
        requested = desk_config["provider"]
        model = desk_config["model"]
        runtime = resolve_runtime_provider(requested=requested, target_model=model)
        ensure_mcp_discovery_before_agent_build(
            logger=logging.getLogger("aveyroni-desk"),
            single_query=False,
        )
        self.session_db = SessionDB()
        agent = AIAgent(
            api_key=runtime.get("api_key"),
            base_url=runtime.get("base_url"),
            provider=runtime.get("provider"),
            requested_provider=runtime.get("requested_provider"),
            api_mode=runtime.get("api_mode"),
            model=model,
            enabled_toolsets=sorted(_get_platform_tools(cfg, "cli")),
            quiet_mode=True,
            platform="cli",
            session_db=self.session_db,
            credential_pool=runtime.get("credential_pool"),
            fallback_model=get_fallback_chain(cfg) or None,
        )
        agent.suppress_status_output = True
        from agent.skill_commands import build_preloaded_skills_prompt

        prompt, _loaded, _missing = build_preloaded_skills_prompt(SKILLS)
        self.system_prompt = prompt or ""
        self.agent = agent
        self.session_id = str(getattr(agent, "session_id", "") or "")

    def turn(self, message: str, on_event) -> str:
        self.ensure()
        streamed: list[str] = []

        def stream_callback(delta: str) -> None:
            if not delta:
                return
            streamed.append(delta)
            on_event({"delta": delta})

        def on_tool_start(tool_id, name, args) -> None:
            on_event({
                "tool": {
                    "phase": "start",
                    "id": str(tool_id),
                    "name": name,
                    "detail": _tool_detail(name, args),
                }
            })

        def on_tool_done(tool_id, name, args, result) -> None:
            on_event({
                "tool": {
                    "phase": "done",
                    "id": str(tool_id),
                    "name": name,
                    "detail": _result_detail(result),
                }
            })

        self.agent.tool_start_callback = on_tool_start
        self.agent.tool_complete_callback = on_tool_done

        desk_config = load_desk_config(self.mandate_id)
        routed = f"Active buy-box:\n{buy_box_text(desk_config)}{BUY_BOX_MARK}{message}"
        result = self.agent.run_conversation(
            user_message=routed,
            system_message=self.system_prompt if not self.history else None,
            conversation_history=list(self.history),
            stream_callback=stream_callback,
            task_id=self.session_id or None,
        )
        self.history = result.get("messages") or self.history
        self.session_id = str(getattr(self.agent, "session_id", "") or self.session_id)
        save_history(self.mandate_id, self.history, self.session_id)
        final = (result.get("final_response") or "").strip()
        joined = "".join(streamed)
        if final and not joined:
            on_event({"delta": final})
        elif final.startswith(joined) and len(final) > len(joined):
            on_event({"delta": final[len(joined):]})
        return final or joined

    def close(self, clear_history: bool = False) -> None:
        agent = self.agent
        self.agent = None
        self.history = []
        self.session_id = ""
        if clear_history:
            save_history(self.mandate_id, [], "")
        if agent is not None:
            try:
                agent.close()
            except Exception:
                pass
        if self.session_db is not None:
            try:
                self.session_db.close()
            except Exception:
                pass
            self.session_db = None


def desk(mandate_id: object = None) -> Desk:
    resolved = resolve_mandate_id(mandate_id)
    if resolved not in DESKS:
        DESKS[resolved] = Desk(resolved)
    return DESKS[resolved]


def outreach_copy_writer(mandate_id: str):
    """Return an isolated, tool-free writer grounded only in approved inputs."""

    def write(contact: dict, entity: dict, mandate: dict) -> dict:
        fallback = default_outreach_copy(contact, entity, mandate)
        if not TURN_LOCK.acquire(blocking=False):
            raise RuntimeError("Wait for the current desk reply before preparing outreach.")
        active = desk(mandate_id)
        try:
            active.ensure()
            agent = active.agent
            saved_tools = getattr(agent, "tools", None)
            saved_cached = getattr(agent, "_cached_system_prompt", None)
            facts = [
                {"field": row.get("field"), "value": row.get("value")}
                for row in entity.get("claims") or []
                if row.get("field") in {"sector", "geography", "ownership", "business_model", "revenue"}
                and row.get("value") not in (None, "")
            ][:8]
            prompt = json.dumps({
                "contact": {
                    "first_name": contact.get("first_name"),
                    "title": contact.get("title"),
                    "company": contact.get("company"),
                },
                "company": entity.get("name"),
                "sourced_facts": facts,
                "mandate": {
                    "geography": mandate.get("geography"),
                    "sector": mandate.get("sector"),
                    "ownership": mandate.get("ownership"),
                },
                "sender": os.environ.get("OUTREACH_SENDER_NAME", "Yogesh"),
            }, ensure_ascii=False)
            try:
                agent.tools = []
                result = agent.run_conversation(
                    user_message=(
                        "Draft one concise private-equity introduction from this JSON. "
                        "Return JSON only: {\"subject\":\"...\",\"body\":\"...\"}. "
                        "Subject max 50 characters; body max 120 words; peer tone; one CTA. "
                        "Never invent a fact, imply the owner wants to sell, or add unsupported personalization. "
                        "Explicitly avoid assuming a transaction is sought.\n\n" + prompt
                    ),
                    system_message=(
                        "You are Aveyroni's Outreach Writer. You have no tools. "
                        "Use only the supplied facts and return strict JSON."
                    ),
                    conversation_history=[],
                    task_id=None,
                )
                payload = extract_json(str((result or {}).get("final_response") or ""))
                if isinstance(payload, dict) and payload.get("subject") and payload.get("body"):
                    return {"subject": str(payload["subject"]), "body": str(payload["body"])}
                return fallback
            finally:
                agent.tools = saved_tools
                if saved_cached is not None:
                    agent._cached_system_prompt = saved_cached
        except Exception:
            return fallback
        finally:
            TURN_LOCK.release()

    return write


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[chat] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _request(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Send a JSON object.")
        return value

    @staticmethod
    def _route_id(path: str, suffix: str = "") -> str | None:
        prefix = "/api/mandates/"
        if not path.startswith(prefix):
            return None
        rest = path[len(prefix):]
        if suffix:
            marker = "/" + suffix
            if not rest.endswith(marker):
                return None
            rest = rest[:-len(marker)]
        elif "/" in rest:
            return None
        return rest or None

    def _selected_id(self, query: dict, payload: dict | None = None) -> str:
        requested = (payload or {}).get("mandate_id")
        if not requested:
            requested = (query.get("mandate_id") or [None])[0]
        return resolve_mandate_id(requested)

    def do_GET(self) -> None:
        path, query = self._request()
        if path in ("/", "/index.html"):
            self._send(200, (CHAT / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/mandate":
            try:
                config = load_desk_config(self._selected_id(query))
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
                return
            self._json(200, {
                "geography": config["geography"],
                "sector": config["sector"],
                "revenue_min": config["revenue_min"],
                "revenue_max": config["revenue_max"],
                "revenue_scale": config["revenue_scale"],
                "currency": config["currency"],
                "revenue_min_inr_cr": config["revenue_min_inr_cr"],
                "revenue_max_inr_cr": config["revenue_max_inr_cr"],
                "ownership": config["ownership"],
                "exclude_ownership": config["exclude_ownership"],
            })
            return
        if path == "/api/config":
            try:
                self._json(200, public_config(load_desk_config(self._selected_id(query))))
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path == "/api/mandates":
            registry = _load_registry()
            self._json(200, {
                "active_mandate_id": registry["active_mandate_id"],
                "mandates": [mandate_summary(key, value) for key, value in registry["mandates"].items()],
            })
            return
        route_id = self._route_id(path)
        if route_id:
            try:
                resolved = resolve_mandate_id(route_id)
                registry = _load_registry()
                self._json(200, {
                    "mandate": mandate_summary(resolved, registry["mandates"][resolved]),
                    "config": public_config(load_desk_config(resolved)),
                })
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path == "/api/health":
            config = load_desk_config()
            readiness = orchestrator_readiness(config["mandate_id"])
            outreach = outreach_readiness()
            self._json(200, {
                "ok": True,
                "mode": "conversation",
                "provider": config["provider"],
                "model": config["model"],
                "active_mandate_id": config["mandate_id"],
                "orchestrator_ready": readiness["ready"],
                "orchestrator_missing": readiness["missing"],
                "outreach_ready": outreach["ready"],
                "outreach_missing": outreach["missing"],
            })
            return
        if path == "/api/targets":
            try:
                mandate_id = self._selected_id(query)
                self._json(200, {"mandate_id": mandate_id, "targets": latest_targets(mandate_id)})
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path == "/api/outreach":
            try:
                mandate_id = self._selected_id(query)
                self._json(200, {
                    "mandate_id": mandate_id,
                    "readiness": outreach_readiness(),
                    "drafts": list_outreach_drafts(mandate_id, ROOT / "runs"),
                })
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path == "/api/history":
            try:
                mandate_id = self._selected_id(query)
                persisted = load_history(mandate_id)
                current = DESKS.get(mandate_id)
                self._json(200, {
                    "mandate_id": mandate_id,
                    "session_id": current.session_id if current else persisted.get("session_id", ""),
                    "messages": current_visible_history(
                        mandate_id,
                        current.history if current else persisted.get("messages", []),
                    ),
                })
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path, query = self._request()
        try:
            payload = self._payload()
        except json.JSONDecodeError:
            self._json(400, {"error": "Send JSON."})
            return
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        if path == "/api/mandates":
            self._create_mandate(payload)
            return
        activate_id = self._route_id(path, "activate")
        if activate_id:
            self._activate_mandate(activate_id)
            return
        clear_id = self._route_id(path, "clear-thread")
        if clear_id:
            try:
                self._clear_thread(clear_id)
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path == "/api/reset":
            try:
                self._clear_thread(self._selected_id(query, payload))
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path == "/api/config":
            try:
                self._update_mandate(self._selected_id(query, payload), payload)
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path == "/api/orchestrate":
            try:
                self._stream_turn(orchestrated=True, mandate_id=self._selected_id(query, payload))
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            return
        if path.startswith("/api/outreach/"):
            try:
                mandate_id = self._selected_id(query, payload)
                if path == "/api/outreach/prepare":
                    if not _load_registry()["mandates"][mandate_id].get("targets_available"):
                        raise ValueError("Run the team on the current mandate before preparing outreach.")
                    result = prepare_outreach(
                        mandate_id,
                        str(payload.get("entity_id") or ""),
                        runs_root=ROOT / "runs",
                        copy_writer=outreach_copy_writer(mandate_id),
                    )
                elif path == "/api/outreach/approve":
                    result = approve_outreach(
                        mandate_id,
                        str(payload.get("draft_id") or ""),
                        str(payload.get("subject") or ""),
                        str(payload.get("body") or ""),
                        ROOT / "runs",
                    )
                elif path == "/api/outreach/reject":
                    result = reject_outreach(
                        mandate_id,
                        str(payload.get("draft_id") or ""),
                        ROOT / "runs",
                    )
                elif path == "/api/outreach/deliver":
                    if not _load_registry()["mandates"][mandate_id].get("targets_available"):
                        raise ValueError("Run the team again before sending outreach for this mandate.")
                    result = deliver_outreach(
                        mandate_id,
                        str(payload.get("draft_id") or ""),
                        str(payload.get("provider") or ""),
                        runs_root=ROOT / "runs",
                    )
                elif path == "/api/outreach/suppress":
                    result = suppress_outreach(
                        mandate_id,
                        entity_id=str(payload.get("entity_id") or ""),
                        email=str(payload.get("email") or ""),
                        domain=str(payload.get("domain") or ""),
                        reason=str(payload.get("reason") or "user_request"),
                        runs_root=ROOT / "runs",
                    )
                else:
                    self._json(404, {"error": "Not found"})
                    return
                self._json(200, {"ok": True, "draft": result})
            except KeyError as exc:
                self._json(404, {"error": str(exc.args[0])})
            except (ValueError, RuntimeError) as exc:
                self._json(400, {"error": str(exc)})
            return
        if path != "/api/chat":
            self._json(404, {"error": "Not found"})
            return
        message = str(payload.get("message") or "").strip()
        if not message:
            self._json(400, {"error": "Write a message first."})
            return
        if len(message) > 8000:
            self._json(400, {"error": "Message is too long."})
            return
        try:
            self._stream_turn(message, mandate_id=self._selected_id(query, payload))
        except KeyError as exc:
            self._json(404, {"error": str(exc.args[0])})

    def do_PATCH(self) -> None:
        path, _query = self._request()
        mandate_id = self._route_id(path)
        if not mandate_id:
            self._json(404, {"error": "Not found"})
            return
        try:
            payload = self._payload()
            self._update_mandate(resolve_mandate_id(mandate_id), payload)
        except json.JSONDecodeError:
            self._json(400, {"error": "Send JSON."})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except KeyError as exc:
            self._json(404, {"error": str(exc.args[0])})

    def _create_mandate(self, payload: dict) -> None:
        if not TURN_LOCK.acquire(blocking=False):
            self._json(409, {"error": "Wait for the current reply to finish."})
            return
        try:
            raw = payload.get("config", payload)
            if not isinstance(raw, dict):
                raise ValueError("Config must be a JSON object.")
            config = normalize_config({**_default_config(), **raw})
            mandate_id = "mandate-" + uuid.uuid4().hex[:12]
            config["mandate_id"] = mandate_id
            created = _now()
            registry = _load_registry()
            registry["mandates"][mandate_id] = {
                "mandate_id": mandate_id, "title": config["title"],
                "created_at": created, "updated_at": created, "targets_available": False,
            }
            registry["active_mandate_id"] = mandate_id
            _write_json(_config_path(mandate_id), config)
            save_history(mandate_id, [], "")
            _save_registry(registry)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        finally:
            TURN_LOCK.release()
        self._json(201, {
            "ok": True,
            "active_mandate_id": mandate_id,
            "mandate": mandate_summary(mandate_id, registry["mandates"][mandate_id]),
            "config": public_config(config),
        })

    def _update_mandate(self, mandate_id: str, payload: dict) -> None:
        if not TURN_LOCK.acquire(blocking=False):
            self._json(409, {"error": "Wait for the current reply to finish."})
            return
        try:
            current = load_desk_config(mandate_id)
            clean_payload = {key: value for key, value in payload.items() if key != "mandate_id"}
            updated = normalize_config({**current, **clean_payload})
            updated["mandate_id"] = mandate_id
            material = any(updated.get(key) != current.get(key) for key in MATERIAL_CONFIG_FIELDS)
            _write_json(_config_path(mandate_id), updated)
            registry = _load_registry()
            metadata = registry["mandates"][mandate_id]
            metadata["title"] = updated["title"]
            metadata["updated_at"] = _now()
            if material:
                metadata["targets_available"] = False
                clear_history(mandate_id)
            _save_registry(registry)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        finally:
            TURN_LOCK.release()
        self._json(200, {
            "ok": True,
            "thread_reset": material,
            "targets_stale": material,
            "mandate": mandate_summary(mandate_id, registry["mandates"][mandate_id]),
            "config": public_config(updated),
        })

    def _activate_mandate(self, mandate_id: str) -> None:
        if not TURN_LOCK.acquire(blocking=False):
            self._json(409, {"error": "Wait for the current reply to finish."})
            return
        try:
            mandate_id = resolve_mandate_id(mandate_id)
            registry = _load_registry()
            registry["active_mandate_id"] = mandate_id
            _save_registry(registry)
        except KeyError as exc:
            self._json(404, {"error": str(exc.args[0])})
            return
        finally:
            TURN_LOCK.release()
        self._json(200, {"ok": True, "active_mandate_id": mandate_id})

    def _clear_thread(self, mandate_id: str) -> None:
        if not TURN_LOCK.acquire(blocking=False):
            self._json(409, {"error": "Wait for the current reply to finish."})
            return
        try:
            mandate_id = resolve_mandate_id(mandate_id)
            clear_history(mandate_id)
            registry = _load_registry()
            registry["mandates"][mandate_id]["targets_available"] = False
            registry["mandates"][mandate_id]["updated_at"] = _now()
            _save_registry(registry)
        finally:
            TURN_LOCK.release()
        self._json(200, {"ok": True, "mandate_id": mandate_id})

    def _stream_turn(self, message: str = "", orchestrated: bool = False, mandate_id: str | None = None) -> None:
        mandate_id = resolve_mandate_id(mandate_id)
        if not TURN_LOCK.acquire(blocking=False):
            self._json(409, {"error": "The desk is still answering."})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        write_lock = threading.Lock()

        def emit(event: dict) -> None:
            data = json.dumps(event, ensure_ascii=False).encode()
            with write_lock:
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()

        try:
            current = desk(mandate_id)
            if orchestrated:
                readiness = orchestrator_readiness(mandate_id)
                if not readiness["ready"]:
                    emit({"error": "The origination team can't run yet -- " + " ".join(readiness["missing"])})
                    emit({"done": True, "session_id": current.session_id, "mandate_id": mandate_id})
                    return
                current.ensure()
                prior = list(current.history)
                config = load_desk_config(mandate_id)
                reports = []
                entities_by_id = {}
                excluded_names = []
                aggregate = None
                stagnant_batches = 0
                for batch_index in range(ORIGINATION_MAX_BATCHES):
                    batch_number = batch_index + 1
                    if batch_number > 1:
                        emit({"delta": f"\n\nBatch {batch_number}\n\n"})

                    def batch_emit(event: dict, number=batch_number) -> None:
                        if "targets" in event:
                            return
                        event = dict(event)
                        if isinstance(event.get("tool"), dict):
                            event["tool"] = dict(event["tool"])
                            event["tool"]["id"] = f"batch-{number}-{event['tool'].get('id', '')}"
                        emit(event)

                    orchestrator = Orchestrator(
                        agent=current.agent,
                        on_event=batch_emit,
                        runs_root=ROOT / "runs",
                        system_prompt=current.system_prompt,
                        history=prior,
                        excluded_names=excluded_names,
                        batch_index=batch_index,
                    )
                    report = orchestrator.run(config)
                    package = orchestrator.last_package
                    reports.append(report)
                    new_count = 0
                    for entity in package.get("entities") or []:
                        entity_id = str(entity.get("entity_id") or "")
                        if entity_id and entity_id not in entities_by_id:
                            entities_by_id[entity_id] = entity
                            excluded_names.append(str(entity.get("name") or entity_id))
                            new_count += 1
                    stagnant_batches = 0 if new_count else stagnant_batches + 1

                    aggregate = {
                        **package,
                        "entities": list(entities_by_id.values()),
                        "batch_count": batch_number,
                        "batch_reports": list(reports),
                    }
                    batch_path = ROOT / "runs" / mandate_id / f"orchestrator-batch-{batch_number:02d}.json"
                    _write_json(batch_path, package)
                    store_run(ROOT / "runs", aggregate)
                    targets = public_targets(aggregate)
                    emit({"targets": targets})
                    if len(targets) >= ORIGINATION_TARGET_GOAL:
                        emit({"delta": f"\n\nStopped: {len(targets)} companies fit the buy box."})
                        break
                    if stagnant_batches >= 2:
                        emit({
                            "delta": (
                                f"\n\nStopped because two consecutive batches found no new companies. "
                                f"{len(targets)} of {ORIGINATION_TARGET_GOAL} companies fit the buy box."
                            )
                        })
                        break
                    emit({
                        "delta": (
                            f"\n\n{len(targets)} of {ORIGINATION_TARGET_GOAL} fit so far. "
                            "Starting the next batch without previously screened companies."
                        )
                    })
                else:
                    targets = public_targets(aggregate or {"mandate": config, "entities": []})
                    emit({
                        "delta": (
                            f"\n\nStopped after {ORIGINATION_MAX_BATCHES} batches without reaching "
                            f"{ORIGINATION_TARGET_GOAL} mandate-fit companies. "
                            f"{len(targets)} companies fit the buy box."
                        )
                    })

                text = "\n\n".join(reports)
                current.history = prior + [
                    {"role": "user", "content": "Run the origination team on the active buy box."},
                    {"role": "assistant", "content": text},
                ]
                save_history(mandate_id, current.history, current.session_id)
                registry = _load_registry()
                registry["mandates"][mandate_id]["targets_available"] = True
                registry["mandates"][mandate_id]["updated_at"] = _now()
                _save_registry(registry)
            else:
                current.turn(message, emit)
            emit({"done": True, "session_id": current.session_id, "mandate_id": mandate_id})
        except Exception as exc:
            emit({"error": str(exc)})
        finally:
            TURN_LOCK.release()


def main() -> None:
    # Hermes (hermes_cli, agent.*) requires Python 3.11+ and is only
    # installed into the Hermes venv -- a bare system `python3` (3.9 on this
    # machine) imports this module fine (the hermes_cli imports are all
    # lazy, inside Desk.ensure()) but then fails confusingly, per request,
    # the first time a chat turn or "Run team" actually needs the agent.
    # Fail once, loudly, at startup instead.
    if sys.version_info < (3, 11):
        venv_python = HERMES_REPO / ".venv" / "bin" / "python"
        version = ".".join(str(part) for part in sys.version_info[:3])
        lines = [f"chat/server.py needs Python 3.11+ (Hermes requires it); this interpreter is {version}."]
        if venv_python.exists():
            lines.append("Start it with the Hermes venv's python instead:")
            lines.append(f"  PORT={PORT} {venv_python} {Path(__file__).resolve()}")
        else:
            lines.append(f"Expected a Hermes venv at {venv_python}, but it is not there. Install Hermes first.")
        print("\n".join(lines), file=sys.stderr, flush=True)
        raise SystemExit(1)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Origination desk  http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
