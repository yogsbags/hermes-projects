"""Contract origination desk for a boarded company.

The PE target is the account (a possible buyer). The JSON client profile is
the seller Aveyroni represents. Signals and people come from the last
origination package only — no invented emails, awards, or names.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote

from orchestrator.deterministic import public_targets, slug

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "contracts"


def _read(name: str) -> dict:
    path = CONFIG / name
    if not path.exists():
        raise FileNotFoundError(f"Contract catalog missing: {path}")
    return json.loads(path.read_text())


def client_profile() -> dict:
    return dict(_read("client-profile.json"))


def agent_roster() -> dict:
    return dict(_read("agents.json"))


def _claims(entity: dict) -> list[dict]:
    return [claim for claim in entity.get("claims") or [] if isinstance(claim, dict)]


def _values(entity: dict, *fields: str) -> list[dict]:
    wanted = {field.lower() for field in fields}
    rows = []
    for claim in _claims(entity):
        field = str(claim.get("field") or "").strip().lower()
        if field in wanted or any(token in field for token in wanted):
            rows.append(claim)
    return rows


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _plain(value) -> str:
    if isinstance(value, list):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    text = " ".join(str(value or "").split())
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text
        if isinstance(parsed, list):
            return "; ".join(str(item).strip() for item in parsed if str(item).strip())
    return text


def _short(text: str, limit: int = 92) -> str:
    value = _plain(text)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


def _day(year: int, month: int, day: int = 1) -> datetime | None:
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _collect_dates(text: str) -> list[tuple[int, datetime]]:
    blob = unquote(_plain(text).replace("%20", " "))
    found: list[tuple[int, datetime]] = []
    for match in re.finditer(r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})\b", blob):
        parsed = _day(int(match[1]), int(match[2]), int(match[3]))
        if parsed:
            found.append((3, parsed))
    for match in re.finditer(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?\s+(20\d{{2}}|19\d{{2}})\b",
        blob,
        re.I,
    ):
        parsed = _day(int(match[3]), _MONTHS[match[2].lower()], int(match[1]))
        if parsed:
            found.append((3, parsed))
    for match in re.finditer(
        rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}}|19\d{{2}})\b",
        blob,
        re.I,
    ):
        parsed = _day(int(match[3]), _MONTHS[match[1].lower()], int(match[2]))
        if parsed:
            found.append((3, parsed))
    for match in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2}|19\d{2})\b", blob):
        day, month, year = int(match[1]), int(match[2]), int(match[3])
        if month > 12 and day <= 12:
            day, month = month, day
        parsed = _day(year, month, day) if month <= 12 else None
        if parsed:
            found.append((3, parsed))
    if not any(precision >= 3 for precision, _ in found):
        for match in re.finditer(rf"\b({_MONTH_RE})\.?\s+(20\d{{2}}|19\d{{2}})\b", blob, re.I):
            parsed = _day(int(match[2]), _MONTHS[match[1].lower()])
            if parsed:
                found.append((2, parsed))
    if not found:
        for match in re.finditer(r"\b(?:in|of|on|as of)\s+(20\d{2}|19\d{2})\b", blob, re.I):
            parsed = _day(int(match[1]), 1, 1)
            if parsed:
                found.append((1, parsed))
        if not found:
            for match in re.finditer(r"\b(20\d{2}|19\d{2})\b", blob):
                parsed = _day(int(match[1]), 1, 1)
                if parsed:
                    found.append((1, parsed))
                    break
    return found


def _dated(*texts: object) -> dict:
    found: list[tuple[int, datetime]] = []
    for text in texts:
        found.extend(_collect_dates(str(text or "")))
    if not found:
        return {"date": "", "date_label": "Date not sourced"}
    found.sort(key=lambda item: (-item[0], item[1]))
    precision, parsed = found[0]
    if precision >= 3:
        return {"date": parsed.date().isoformat(), "date_label": f"{parsed.day} {parsed.strftime('%b %Y')}"}
    if precision == 2:
        return {"date": parsed.strftime("%Y-%m"), "date_label": parsed.strftime("%b %Y")}
    return {"date": str(parsed.year), "date_label": str(parsed.year)}


def _event_date(value: str) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _age_months(value: str, today: date) -> int | None:
    start = _event_date(value)
    if not start:
        return None
    return (today.year - start.year) * 12 + today.month - start.month


def _mark_freshness(signals: list[dict], client: dict, today: date | None = None) -> list[dict]:
    today = today or date.today()
    limit = int(client.get("timing_months") or 18)
    marked = []
    for row in signals:
        item = dict(row)
        age = _age_months(item.get("date") or "", today)
        fresh = age is not None and 0 <= age <= limit
        item["fresh"] = fresh
        item["age_months"] = age
        if fresh:
            item["fresh_note"] = f"Inside the {limit}-month mandate."
        elif item.get("date"):
            item["fresh_note"] = (
                f"Historical ({item.get('date_label')}). Outside the {limit}-month "
                "mandate — not a live contract."
            )
        else:
            item["fresh_note"] = "Date not sourced, so this is not treated as a live contract."
        marked.append(item)
    return marked


_STOP = {
    "the", "a", "an", "of", "to", "and", "with", "its", "on", "in", "for", "by",
    "llp", "pvt", "ltd", "limited", "india", "company", "private", "inc",
    "formerly", "known", "as", "into", "from",
}


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", _norm(text))
        if token not in _STOP and len(token) > 2
    }


def _alike(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    a, b = _tokens(left), _tokens(right)
    if len(a) < 3 or len(b) < 3:
        return False
    return len(a & b) / max(len(a | b), 1) >= 0.45


def _dedupe(rows: list[dict], key_fn) -> list[dict]:
    seen: list[str] = []
    unique = []
    for row in rows:
        key = key_fn(row)
        if not key or any(_alike(key, old) for old in seen):
            continue
        seen.append(key)
        unique.append(row)
    return unique


def _people(entity: dict) -> list[dict]:
    people = []
    for claim in _values(entity, "relationship"):
        value = " ".join(str(claim.get("value") or "").split())
        if not value:
            continue
        name = value.split("—", 1)[0].split("-", 1)[0].strip()
        people.append({
            "name": name,
            "role": value,
            "source_url": claim.get("source_url") or "",
            "excerpt": claim.get("excerpt") or "",
        })

    def person_key(row: dict) -> str:
        cleaned = _norm(row["name"]).replace("bhai", " ")
        parts = [part for part in cleaned.split() if part]
        if not parts:
            return ""
        return parts[0][:8] + " " + parts[-1]

    return _dedupe(people, person_key)


def _signal(kind: str, claim: dict, inferred: str) -> dict:
    value = _plain(claim.get("value"))
    title = _short(value) or kind
    dated = _dated(claim.get("date"), claim.get("as_of"), value, claim.get("excerpt"))
    return {
        "id": slug(f"{kind}-{title}", 48),
        "kind": kind,
        "title": title,
        "value": value,
        "inferred": inferred,
        "date": dated["date"],
        "date_label": dated["date_label"],
        "source_url": claim.get("source_url") or "",
        "excerpt": claim.get("excerpt") or "",
        "field": claim.get("field") or "",
    }


def _signals(entity: dict) -> list[dict]:
    rows = []
    for claim in _values(entity, "monitor", "plant expansion", "plant_expansion"):
        rows.append(_signal(
            "capacity",
            claim,
            "What equipment or line automation might this change require?",
        ))
    for claim in _values(entity, "maa"):
        rows.append(_signal(
            "transaction",
            claim,
            "Does the new line or partner create a package the client could bid?",
        ))
    for claim in _values(entity, "plants", "locations"):
        rows.append(_signal(
            "footprint",
            claim,
            "Which site would actually procure, and is an EPC in the middle?",
        ))
    for claim in _values(entity, "products"):
        rows.append(_signal(
            "process",
            claim,
            "Which of the client's robotics or automation products could attach?",
        ))
    for claim in _values(entity, "customers"):
        rows.append(_signal(
            "demand",
            claim,
            "OEM awards can pull through plant upgrades. This is not a live RFP.",
        ))
    for claim in _values(entity, "signal", "funding"):
        value = _norm(claim.get("value") or "")
        if "unfunded" in value or "no external funding" in value:
            continue
        rows.append(_signal(
            "trigger",
            claim,
            "Is there a time-bound buy, or only a historical note?",
        ))
    return _dedupe(rows, lambda row: row["kind"] + ":" + _norm(row["value"]))


def _score(entity: dict, signal: dict, client: dict) -> dict:
    reasons = []
    score = 40
    geography = " ".join(str(claim.get("value") or "") for claim in _values(entity, "geography")).lower()
    if any(place.lower() in geography for place in client.get("geography") or []) or "india" in geography:
        score += 20
        reasons.append("Account geography overlaps the client mandate.")
    sector = " ".join(str(claim.get("value") or "") for claim in _values(entity, "sector", "products")).lower()
    if any(item.lower() in sector for item in client.get("industries") or []):
        score += 15
        reasons.append("Account industry overlaps the client mandate.")
    if signal["kind"] in {"capacity", "transaction"}:
        score += 15
        reasons.append("The trigger is a sourced capacity or transaction event.")
    if _people(entity):
        score += 8
        reasons.append("At least one named person is already on the account.")
    else:
        reasons.append("No named buyer of the package is sourced yet.")
    score = min(score, 92)
    window = signal.get("fresh_note") or (
        f"Client mandate is opportunities inside {client.get('timing_months') or 18} months."
    )
    return {
        "score": score,
        "label": "QUALIFIED" if score >= 70 else "WATCH",
        "reasons": reasons,
        "window": window,
        "value_note": (
            f"Package value is not sourced. Client mandate is "
            f"₹{client.get('contract_min_inr_cr')}–{client.get('contract_max_inr_cr')} crore."
        ),
    }


def _opportunity(entity: dict, signal: dict, client: dict, people: list[dict]) -> dict:
    fit = _score(entity, signal, client)
    chain = [
        {"role": "Project owner / account", "name": entity.get("name") or "Unnamed", "known": True},
        {"role": "EPC / consultant", "name": "Not sourced", "known": False},
        {"role": "Package contractor", "name": "Not sourced", "known": False},
        {"role": "Automation buy", "name": "Client products: " + ", ".join(client.get("products") or []), "known": False},
    ]
    stage = "Signal" if fit["label"] == "WATCH" else "Qualified opportunity"
    action = (
        "Hold until a named procurement or EPC contact is sourced."
        if not people
        else "Approach a sourced designated partner or director about the plant change. Do not invent an email. Nothing is sent."
    )
    return {
        "id": slug(f"{entity.get('entity_id')}-{signal['id']}", 56),
        "title": f"{entity.get('name') or 'Account'} — {signal['title']}",
        "account": entity.get("name") or "Unnamed",
        "trigger": signal["title"],
        "date": signal.get("date") or "",
        "date_label": signal.get("date_label") or "Date not sourced",
        "stage": stage,
        "fit": fit,
        "signal": signal,
        "procurement_chain": chain,
        "people": people,
        "warm_paths": 0,
        "recommended_action": action,
        "pursuit": agent_roster().get("pursuit") or [],
        "note": "This is a contract the demo client might pursue at this account. It is not a claim that a process is live.",
    }


def build_desk(package: dict, entity_id: str, today: date | None = None) -> dict:
    cards = {card.get("entity_id"): card for card in public_targets(package)}
    if entity_id not in cards:
        raise ValueError("Open contract origination only on a mandate-fit company already on the board.")
    entity = next(
        (row for row in package.get("entities") or [] if row.get("entity_id") == entity_id),
        None,
    )
    if not entity:
        raise ValueError("That company is not in the last origination package.")
    client = client_profile()
    roster = agent_roster()
    people = _people(entity)
    signals = _mark_freshness(_signals(entity), client, today)
    opportunities = [
        _opportunity(entity, signal, client, people)
        for signal in signals
        if signal.get("fresh") and signal["kind"] in {"capacity", "transaction", "trigger"}
    ]
    qualified = [row for row in opportunities if row["fit"]["label"] == "QUALIFIED"]
    return {
        "account": {
            "entity_id": entity_id,
            "name": entity.get("name") or cards[entity_id]["name"],
            "fit": cards[entity_id].get("fit") or "",
        },
        "client": client,
        "funnel": {
            "signals": len(signals),
            "potential": len(opportunities),
            "qualified": len(qualified),
        },
        "agents": roster.get("agents") or [],
        "hermes_layers": roster.get("hermes_layers") or [],
        "pursuit": roster.get("pursuit") or [],
        "signals": signals,
        "opportunities": opportunities,
        "people": people,
        "note": (
            "Signal Hunter reads the last origination package for this account. "
            "Hermes layers (parallel-cli, rss-feeds, blogwatcher, qmd, pinecone, OSINT) "
            "are attached for the next live pass. Nothing was sent."
        ),
    }


def store_desk(runs_root: Path, mandate_id: str, desk: dict) -> Path:
    folder = Path(runs_root) / mandate_id / "contracts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{desk['account']['entity_id']}.json"
    path.write_text(json.dumps(desk, indent=2, ensure_ascii=False) + "\n")
    return path
