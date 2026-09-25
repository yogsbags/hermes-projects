"""Mechanical origination steps. These functions do not call a model."""

from __future__ import annotations

import json
import re
from pathlib import Path

TRANSACTION_STATUSES = (
    "UNKNOWN",
    "NO_PUBLIC_PROCESS_FOUND",
    "PE_BACKED",
    "STRATEGICALLY_OWNED",
    "RECENTLY_ACQUIRED",
    "FUNDRAISING",
    "ACTIVE_SALE_PROCESS",
    "CONFIRMED_OWNER_DIALOGUE",
)
_STATUS_RANK = {status: index for index, status in enumerate(TRANSACTION_STATUSES)}
_LEGAL_SUFFIX = re.compile(
    r"\b(private limited|pvt\.?\s*ltd\.?|pvt\.?|limited|ltd\.?|llc|inc\.?|corp\.?|corporation|lp|llp)\b",
    re.I,
)
_SPACE = re.compile(r"\s+")


def slug(value: object, limit: int = 60) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (text[:limit] or "mandate").strip("-")


def parse_mandate(config: dict) -> dict:
    """Turn a saved desk buy box into the object every later step reads."""
    if not isinstance(config, dict):
        raise ValueError("The buy box must be an object.")
    focus = str(config.get("focus") or "").strip()
    title = str(config.get("title") or "").strip()
    geography = [str(item).strip() for item in config.get("geography") or [] if str(item).strip()]
    if not title:
        raise ValueError("Name the mandate before the team runs.")
    if focus not in ("operating-company", "real-estate"):
        raise ValueError("Choose an operating-company or real-estate buy box.")
    if not geography:
        raise ValueError("Geography is required.")
    mandate = {
        # The server assigns an immutable ID.  Keep the title slug as a
        # compatibility fallback for callers that still pass a bare config.
        "mandate_id": str(config.get("mandate_id") or "").strip() or slug(title),
        "title": title,
        "focus": focus,
        "geography": geography,
        "sector": [str(item).strip() for item in config.get("sector") or [] if str(item).strip()],
        "sector_codes": [str(item).strip() for item in config.get("sector_codes") or [] if str(item).strip()],
        "ownership": [str(item).strip() for item in config.get("ownership") or [] if str(item).strip()],
        "exclude_ownership": [
            str(item).strip() for item in config.get("exclude_ownership") or [] if str(item).strip()
        ],
        "revenue": {
            "min": config.get("revenue_min", config.get("revenue_min_inr_cr")),
            "max": config.get("revenue_max", config.get("revenue_max_inr_cr")),
            "currency": str(config.get("currency") or "INR").upper(),
            "scale": str(config.get("revenue_scale") or "crore").lower(),
        },
        # Legacy aliases remain readable by older run artifacts and India-only tools.
        "revenue_min_inr_cr": config.get("revenue_min_inr_cr"),
        "revenue_max_inr_cr": config.get("revenue_max_inr_cr"),
        "asset_types": [str(item).strip() for item in config.get("asset_types") or [] if str(item).strip()],
        "exclude_assets": [str(item).strip() for item in config.get("exclude_assets") or [] if str(item).strip()],
        "units_min": config.get("units_min"),
        "units_max": config.get("units_max"),
        "price_min": config.get("price_min"),
        "price_max": config.get("price_max"),
        "currency": config.get("currency") or "USD",
        "strategy": str(config.get("strategy") or "").strip(),
    }
    if focus == "operating-company":
        if not mandate["sector"] or not mandate["ownership"]:
            raise ValueError("Sector and ownership are required for an operating-company buy box.")
        low, high = mandate["revenue"]["min"], mandate["revenue"]["max"]
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)) or low >= high:
            raise ValueError("The revenue band must have a minimum below the maximum.")
    else:
        if not mandate["asset_types"]:
            raise ValueError("Choose at least one real-estate asset type.")
    return mandate


def normalize_name(name: str) -> str:
    text = _LEGAL_SUFFIX.sub(" ", name or "")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return _SPACE.sub(" ", text).strip()


def entity_key(name: str) -> str:
    return slug(normalize_name(name) or name, limit=80)


def extract_json(text: str):
    if not text or not str(text).strip():
        return None
    blobs = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
    blobs.append(text)
    for blob in blobs:
        blob = blob.strip()
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            pass
        start, end = blob.find("{"), blob.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(blob[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _claim(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    field = str(raw.get("field") or "").strip()
    value = raw.get("value")
    if not field or value is None or value == "":
        return None
    url = str(raw.get("source_url") or "").strip()
    excerpt = str(raw.get("excerpt") or "").strip()
    claim = {
        "field": field,
        "value": value if isinstance(value, (int, float)) else str(value).strip(),
        "source_url": url,
        "excerpt": excerpt,
    }
    if not url.startswith(("http://", "https://")) or not excerpt:
        claim["confidence"] = "inferred"
    else:
        claim["confidence"] = "sourced"
    return claim


def parse_worker_summary(summary: str, worker_id: str) -> dict:
    payload = extract_json(summary or "")
    entities = []
    if isinstance(payload, dict):
        raw_entities = payload.get("entities")
        if raw_entities is None and payload.get("name"):
            raw_entities = [payload]
        if isinstance(raw_entities, list):
            for raw in raw_entities:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("name") or "").strip()
                if not name:
                    continue
                claims = [claim for item in raw.get("claims") or [] if (claim := _claim(item))]
                unknowns = [str(item).strip() for item in raw.get("unknowns") or [] if str(item).strip()]
                entities.append({
                    "name": name,
                    "worker": worker_id,
                    "claims": claims,
                    "unknowns": unknowns,
                })
    return {
        "worker": worker_id,
        "entities": entities,
        "unparsed": not entities,
    }


def _evidence_id(claim: dict) -> str:
    raw = f"{claim.get('field')}|{claim.get('value')}|{claim.get('source_url')}"
    return "ev-" + slug(raw, limit=48)


def normalize_evidence(claims: list[dict]) -> list[dict]:
    kept = []
    for claim in claims:
        if claim.get("confidence") != "sourced":
            continue
        item = dict(claim)
        item["evidence_id"] = _evidence_id(item)
        kept.append(item)
    return kept


def dedupe_claims(claims: list[dict]) -> list[dict]:
    seen = set()
    kept = []
    for claim in claims:
        key = (
            claim.get("field"),
            str(claim.get("value")).strip().lower(),
            claim.get("source_url"),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(claim)
    return kept


def dedupe_entities(entities: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for entity in entities:
        key = entity_key(entity.get("name") or "")
        if not key:
            continue
        if key not in merged:
            merged[key] = {
                "entity_id": key,
                "name": entity["name"],
                "names": [],
                "claims": [],
                "unknowns": [],
                "workers": [],
            }
            order.append(key)
        bucket = merged[key]
        if entity["name"] not in bucket["names"]:
            bucket["names"].append(entity["name"])
        bucket["claims"].extend(entity.get("claims") or [])
        bucket["unknowns"].extend(entity.get("unknowns") or [])
        if entity.get("worker") and entity["worker"] not in bucket["workers"]:
            bucket["workers"].append(entity["worker"])
    result = []
    for key in order:
        item = merged[key]
        sourced = normalize_evidence(item["claims"])
        item["claims"] = dedupe_claims(sourced)
        item["unknowns"] = sorted(set(item["unknowns"]))
        result.append(item)
    return result


def _sourced(entity: dict, field: str) -> list[dict]:
    return [claim for claim in entity.get("claims") or [] if claim.get("field") == field]


def _check(name: str, result: str, claims: list[dict]) -> dict:
    return {
        "check": name,
        "result": result,
        "evidence_ids": [claim["evidence_id"] for claim in claims if claim.get("evidence_id")],
    }


def map_transaction(value: object) -> str | None:
    text = str(value or "").strip()
    upper = text.upper().replace(" ", "_").replace("-", "_")
    if upper in TRANSACTION_STATUSES:
        return upper
    lowered = text.lower()
    if "no public process" in lowered:
        return "NO_PUBLIC_PROCESS_FOUND"
    if any(phrase in lowered for phrase in ("listing", "for sale", "on the market", "pending sale", "active sale")):
        return "ACTIVE_SALE_PROCESS"
    if "fundrais" in lowered:
        return "FUNDRAISING"
    if "acquired" in lowered or "acquisition" in lowered:
        return "RECENTLY_ACQUIRED"
    if "private equity" in lowered or "pe-backed" in lowered or "pe backed" in lowered:
        return "PE_BACKED"
    if "strategic" in lowered:
        return "STRATEGICALLY_OWNED"
    if "owner dialogue" in lowered or "owner discussion" in lowered:
        return "CONFIRMED_OWNER_DIALOGUE"
    return None


def transaction_status(entity: dict) -> tuple[str, str]:
    found = []
    for claim in _sourced(entity, "transaction_status"):
        status = map_transaction(claim.get("value"))
        if status:
            found.append(status)
    status = max(found, key=lambda item: _STATUS_RANK[item]) if found else "NO_PUBLIC_PROCESS_FOUND"
    if status == "ACTIVE_SALE_PROCESS":
        note = "A public sale process is underway."
    elif status == "NO_PUBLIC_PROCESS_FOUND":
        note = "No public process found in the sourced claims. This is not proof the target is off-market."
    else:
        note = "Transaction status is copied from a sourced claim."
    return status, note


def required_checks(mandate: dict) -> list[str]:
    if mandate.get("focus") == "real-estate":
        checks = ["market", "asset_type"]
        if mandate.get("units_min") is not None:
            checks.append("size_units")
        if mandate.get("price_min") is not None:
            checks.append("size_price")
        return checks
    return ["geography", "sector", "ownership", "listing_status", "size", "business_model"]


def listing_status_check(entity: dict) -> dict:
    """Deterministically enforce the unlisted-company gate from sourced claims."""
    claims = [claim for claim in entity.get("claims") or [] if claim.get("field") == "listing_status"]
    for claim in claims:
        text = " ".join((str(claim.get("value") or ""), str(claim.get("excerpt") or ""))).lower()
        if any(phrase in text for phrase in (
            "unlisted", "not listed", "privately held", "closely held",
            "not publicly traded", "private limited",
        )):
            item = _check("listing_status", "pass", [claim])
            item["reason"] = "A sourced claim confirms the company is unlisted or privately held."
            return item
        if any(phrase in text for phrase in (
            "publicly listed", "publicly traded", "listed on", "stock exchange",
            "nse-listed", "bse-listed", "nse listed", "bse listed",
        )):
            item = _check("listing_status", "fail", [claim])
            item["reason"] = "A sourced claim confirms the company is publicly listed."
            return item
    item = _check("listing_status", "unknown", claims)
    item["reason"] = "No sourced claim confirms that the company is unlisted."
    return item


def listing_gate_passes(entity: dict) -> bool:
    mandatory = (entity.get("screening") or {}).get("mandatory") or []
    return any(
        row.get("check") == "listing_status" and row.get("result") == "pass"
        for row in mandatory
    )


def parse_fit_judgments(raw: str) -> dict[str, dict]:
    payload = extract_json(raw or "")
    scores = payload.get("scores") if isinstance(payload, dict) else None
    judgments = {}
    if isinstance(scores, list):
        for row in scores:
            if isinstance(row, dict) and row.get("entity_id"):
                judgments[str(row["entity_id"])] = row
    return judgments


def _publish_fit(entity: dict, mandate: dict, mandatory: list[dict]) -> dict:
    if any(row["result"] == "fail" for row in mandatory):
        label = "FAILS_MANDATORY"
        score = None
    elif any(row["result"] == "unknown" for row in mandatory):
        label = "INSUFFICIENT_EVIDENCE"
        score = None
    else:
        label = "MANDATE_FIT"
        score = 70
    known = sum(1 for row in mandatory if row["result"] != "unknown")
    status, note = transaction_status(entity)
    return {
        "company_id": entity["entity_id"],
        "mandate_id": mandate["mandate_id"],
        "mandatory": mandatory,
        "preferred": [],
        "evidence_completeness": round(known / len(mandatory), 2) if mandatory else 0,
        "fit_label": label,
        "fit_score": score,
        "transaction_status": status,
        "transaction_status_note": note,
        "financial_confirmation_required": any(
            row["check"] in ("size", "size_units", "size_price") and row["result"] == "unknown" for row in mandatory
        ),
    }


def checklist_from_scorer(entity: dict, mandate: dict, judgment: dict | None) -> list[dict]:
    """Use the Fit Scorer's pass, fail, or unknown. Do not rescore the wording."""
    provided = {}
    for row in (judgment or {}).get("mandatory") or []:
        if isinstance(row, dict) and row.get("check"):
            provided[str(row["check"])] = row
    checklist = []
    for name in required_checks(mandate):
        if name == "listing_status":
            checklist.append(listing_status_check(entity))
            continue
        row = provided.get(name) or {}
        result = row.get("result") if row.get("result") in ("pass", "fail", "unknown") else "unknown"
        item = _check(name, result, [])
        reason = str(row.get("reason") or "").strip()
        if reason:
            item["reason"] = reason[:400]
        checklist.append(item)
    return checklist


def validate_screening(screening: dict, claims: list[dict]) -> list[str]:
    errors = []
    mandatory = screening.get("mandatory") or []
    if screening.get("fit_score") is not None and any(row.get("result") != "pass" for row in mandatory):
        errors.append("fit_score is set while a mandatory check is not pass")
    note = str(screening.get("transaction_status_note") or "").lower()
    if screening.get("transaction_status") == "NO_PUBLIC_PROCESS_FOUND" and (
        "not proof" not in note or "off-market" not in note
    ):
        errors.append("no-public-process result is missing the off-market caveat")
    return errors


def screen_entities(entities: list[dict], mandate: dict, judgments: dict | None = None) -> list[dict]:
    judgments = judgments or {}
    screened = []
    for entity in entities:
        checklist = checklist_from_scorer(entity, mandate, judgments.get(entity["entity_id"]))
        screening = _publish_fit(entity, mandate, checklist)
        screened.append({
            **entity,
            "screening": screening,
            "validation_errors": validate_screening(screening, entity.get("claims") or []),
        })
    return screened


def store_run(runs_root: Path, package: dict) -> Path:
    mandate_id = package["mandate"]["mandate_id"]
    folder = Path(runs_root) / mandate_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "orchestrator-run.json"
    path.write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n")
    lines = [json.dumps(entity["screening"], ensure_ascii=False) for entity in package.get("entities") or []]
    (folder / "screening.jsonl").write_text(("\n".join(lines) + "\n") if lines else "")
    return path


_FIT_LINE = {
    "MANDATE_FIT": "Fits this buy box.",
    "FAILS_MANDATORY": "Does not fit this buy box.",
    "INSUFFICIENT_EVIDENCE": "Not enough evidence to score.",
}
_CHECK_LINE = {
    "geography": "where it operates",
    "sector": "what it makes",
    "ownership": "who owns it",
    "listing_status": "whether it is unlisted",
    "size": "revenue",
    "business_model": "how it sells",
    "market": "the market",
    "asset_type": "the asset type",
    "size_units": "the unit count",
    "size_price": "the price",
}
_TXN_LINE = {
    "ACTIVE_SALE_PROCESS": "A public sale process is underway. That is not a quote that the owner wants to sell.",
    "FUNDRAISING": "A fundraising process showed up in the sources. That is separate from an owner wanting to sell.",
    "RECENTLY_ACQUIRED": "The sources describe a recent acquisition.",
    "PE_BACKED": "The sources describe private-equity ownership.",
    "STRATEGICALLY_OWNED": "The sources describe a strategic owner.",
    "CONFIRMED_OWNER_DIALOGUE": "The sources describe a conversation with the owner. That is not itself an intent to sell.",
}
_FACT_FIELDS = (
    ("geography", "geography"),
    ("ownership", "ownership"),
    ("revenue", "size"),
    ("revenue_inr_cr", "size"),
    ("sector", "sector"),
)
_FIT_ORDER = {"MANDATE_FIT": 0, "INSUFFICIENT_EVIDENCE": 1, "FAILS_MANDATORY": 2}


def _plain_fit(screening: dict) -> str:
    line = _FIT_LINE.get(screening.get("fit_label"), "Not enough evidence to score.")
    if screening.get("fit_score") is not None:
        line = f"{line} Score {screening['fit_score']}."
    return line


def _plain_gap(screening: dict) -> str:
    missing = [_CHECK_LINE.get(row["check"], row["check"]) for row in screening.get("mandatory") or [] if row.get("result") == "unknown"]
    failed = [_CHECK_LINE.get(row["check"], row["check"]) for row in screening.get("mandatory") or [] if row.get("result") == "fail"]
    if failed:
        return "Outside the buy box: " + ", ".join(failed) + "."
    if missing:
        return "Still missing: " + ", ".join(missing) + "."
    return ""


def _plain_transaction(screening: dict, noun: str) -> str:
    status = screening.get("transaction_status")
    if status == "NO_PUBLIC_PROCESS_FOUND":
        return f"No public sale process found. That is not proof the {noun} is off-market."
    line = _TXN_LINE.get(status)
    if line:
        return line
    note = str(screening.get("transaction_status_note") or "").strip()
    return note or f"No public sale process found. That is not proof the {noun} is off-market."


def _fact_line(entity: dict) -> str:
    screening = entity.get("screening") or {}
    passed = {row.get("check") for row in screening.get("mandatory") or [] if row.get("result") == "pass"}
    bits = []
    for field, check in _FACT_FIELDS:
        if passed and check not in passed:
            continue
        claim = next((item for item in entity.get("claims") or [] if item.get("field") == field and item.get("value") not in (None, "")), None)
        if not claim:
            continue
        text = " ".join(str(claim["value"]).split())
        if len(text) > 90:
            text = text[:89] + "…"
        if text not in bits:
            bits.append(text)
    return " · ".join(bits)


_REASON_PREFIX = re.compile(
    r"^(the excerpt (explicitly describes|states that|supports that|supports|reports that|reports|identifies|describes) )",
    re.I,
)
_CLAIM_BY_CHECK = {
    "geography": ("geography",),
    "sector": ("sector",),
    "ownership": ("ownership",),
    "listing_status": ("listing_status",),
    "size": ("revenue", "revenue_inr_cr"),
    "business_model": ("business_model",),
    "market": ("geography", "market"),
    "asset_type": ("asset_type",),
    "size_units": ("units",),
    "size_price": ("price",),
}
_SIGNAL_RULES = (
    (("succession", "next generation", "next-generation", "second generation", "third generation", "son of", "daughter of"),
     "a sourced succession or next-generation leadership mention"),
    (("capacity expansion", "new plant", "brownfield", "greenfield", "new factory"),
     "a sourced capacity-expansion mention"),
    (("fundraising", "fundrais"),
     "a sourced fundraising mention"),
    (("active sale", "for sale", "public sale process", "offer for sale", "ipo"),
     "a sourced public process or share-sale mention"),
    (("promoter transition", "leadership transition", "generation change"),
     "a sourced promoter or leadership-transition mention"),
)


def _claim_value(entity: dict, *fields: str) -> str:
    for field in fields:
        claim = next(
            (
                item for item in entity.get("claims") or []
                if item.get("field") == field and item.get("value") not in (None, "")
            ),
            None,
        )
        if claim:
            return " ".join(str(claim["value"]).split())
    return ""


def _clean_reason(reason: str) -> str:
    text = " ".join(str(reason or "").split())
    if text.lower() in {"pass", "the excerpt supports the buy box."}:
        return ""
    text = _REASON_PREFIX.sub("", text)
    return text.rstrip(".")


def _check_detail(entity: dict, row: dict) -> str:
    cleaned = _clean_reason(row.get("reason") or "")
    if cleaned:
        return cleaned
    value = _claim_value(entity, *_CLAIM_BY_CHECK.get(row.get("check"), ()))
    if value:
        return value
    if row.get("check") == "listing_status":
        return "sourced as unlisted or privately held"
    return ""


def _as_clause(text: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _ownership_phrase(value: str) -> str:
    lowered = value.lower().strip()
    if lowered in {"family", "family-owned", "family owned"}:
        return "family ownership"
    if lowered in {"founder", "founder-owned", "founder owned"}:
        return "founder ownership"
    if lowered in {"promoter", "promoter-owned", "promoter owned"}:
        return "promoter ownership"
    return value


def _why_fit(entity: dict) -> str:
    bits = []
    for row in (entity.get("screening") or {}).get("mandatory") or []:
        if row.get("result") != "pass":
            continue
        detail = _as_clause(_check_detail(entity, row))
        if not detail:
            continue
        bits.append(detail)
    if not bits:
        facts = _fact_line(entity)
        return f"Why it fits: passed every mandatory buy-box check.{' ' + facts if facts else ''}"
    return "Why it fits: " + "; ".join(bits[:6]) + "."


def _seller_signals(entity: dict) -> list[str]:
    found = []
    for claim in entity.get("claims") or []:
        field = str(claim.get("field") or "")
        text = " ".join(f"{claim.get('value') or ''} {claim.get('excerpt') or ''}".split()).lower()
        if not text:
            continue
        if field == "signal":
            value = " ".join(str(claim.get("value") or "").split())
            if value and value not in found:
                found.append(value)
            continue
        for tokens, label in _SIGNAL_RULES:
            if any(token in text for token in tokens) and label not in found:
                found.append(label)
    status = (entity.get("screening") or {}).get("transaction_status")
    if status == "ACTIVE_SALE_PROCESS" and "a sourced public process or share-sale mention" not in found:
        found.append("a public sale process in the sources")
    elif status == "FUNDRAISING" and "a sourced fundraising mention" not in found:
        found.append("a fundraising process in the sources")
    return found[:4]


def _structural_seller_context(entity: dict) -> str:
    ownership = (_claim_value(entity, "ownership") + " " + _claim_value(entity, "relationship")).lower()
    listing = _claim_value(entity, "listing_status").lower()
    family = any(token in ownership for token in ("family", "founder", "promoter"))
    unlisted = any(token in listing for token in ("unlisted", "privately held", "private", "closely held"))
    if family and unlisted:
        return "sourced as a family- or founder-owned unlisted company, so a control conversation is structurally possible"
    if family:
        return "sourced as family- or founder-owned"
    if unlisted:
        return "sourced as unlisted, with no public-market exit already available"
    return ""


def _seller_note(entity: dict) -> str:
    """Signal-based only. Never claim the owner wants to sell."""
    signals = _seller_signals(entity)
    structure = _structural_seller_context(entity)
    if signals:
        lead = "; ".join(signals)
        extra = f" Also {structure}." if structure else ""
        return (
            f"Seller interest (signals only): {lead}.{extra} "
            "That is why a confidential conversation might be useful, not proof the owner wants to sell."
        )
    if structure:
        return (
            f"Seller interest (signals only): {structure}. "
            "No succession, fundraising, or public-process signal was found. "
            "Mandate fit is not proof a seller would take a meeting."
        )
    return (
        "Seller interest (signals only): no sourced engagement signal. "
        "Mandate fit is not proof a seller would take a meeting."
    )


def _as_phrase(text: str) -> str:
    text = " ".join(str(text or "").split())
    if text and text[0].isupper() and (len(text) == 1 or not text[1].isupper()):
        return text[0].lower() + text[1:]
    return text


def _market_label(mandate: dict, entity: dict) -> str:
    title = " ".join(str(mandate.get("title") or "").split())
    sectors = [str(item).strip() for item in mandate.get("sector") or [] if str(item).strip()]
    for geo in mandate.get("geography") or []:
        prefix = str(geo).strip()
        if prefix and title.lower().startswith(prefix.lower() + " "):
            title = title[len(prefix):].strip()
            break
    if len(sectors) == 1:
        return sectors[0]
    if title and title.lower() not in {"buy box"}:
        return title
    niche = _claim_value(entity, "sector")
    if niche:
        match = next((item for item in sectors if item.lower() in niche.lower()), None)
        if match:
            return match
    return sectors[0] if sectors else (niche or "the stated sector")


def _location_clause(entity: dict, mandate: dict) -> str:
    place = _claim_value(entity, "geography") or ", ".join(mandate.get("geography") or []) or "the stated geography"
    match = re.search(r"based in\s+(.+)$", place, re.I)
    if match:
        return f"in {match.group(1)}"
    lowered = place.lower()
    if lowered.startswith(("in ", "at ", "based in ", "based at ")):
        return place
    return f"in {place}"


def _thesis(entity: dict, mandate: dict) -> str:
    """Market/control thesis, not a restatement of the fact line."""
    market = _market_label(mandate, entity).lower()
    geography = ", ".join(mandate.get("geography") or []) or "the stated geography"
    niche = _claim_value(entity, "sector")
    ownership = _ownership_phrase(_claim_value(entity, "ownership") or "closely held ownership")
    if ownership == "family ownership":
        ownership = "family-owned"
    elif ownership == "founder ownership":
        ownership = "founder-owned"
    elif ownership == "promoter ownership":
        ownership = "promoter-owned"
    model = _as_phrase(_claim_value(entity, "business_model") or "an operating business")
    size = _claim_value(entity, "revenue", "revenue_inr_cr")
    name = entity.get("name") or "This company"
    location = _location_clause(entity, mandate)
    if mandate.get("focus") == "real-estate":
        assets = ", ".join(mandate.get("asset_types") or []) or "the stated asset types"
        return (
            f"Market thesis: {geography} {assets} is still a privately negotiated control market. "
            f"{name} fits that book as a sourced asset {location}. "
            "The underwrite is ownership of the real asset, not a listed or sponsor-backed process."
        )
    niche_bit = ""
    if niche and niche.lower() not in market.lower():
        niche_bit = f", focused on {_as_phrase(niche)}"
    size_bit = f", at {size}" if size else ""
    strategy = " ".join(str(mandate.get("strategy") or "").split())
    strategy_bit = f" Mandate strategy: {strategy}." if strategy else ""
    return (
        f"Market thesis: privately held {market} in {geography} is still a control market — "
        f"unlisted {ownership} operators are not already priced as public or PE-sponsored situations. "
        f"{name} is an unlisted {model}{niche_bit} {location}{size_bit}. "
        "The underwrite is long-term industrial cash flow in that supplier market, "
        f"not a listed or sponsor-backed process.{strategy_bit}"
    )


def _source_host(entity: dict) -> str:
    from urllib.parse import urlparse

    for claim in entity.get("claims") or []:
        url = str(claim.get("source_url") or "")
        if url.startswith(("http://", "https://")):
            host = urlparse(url).netloc.removeprefix("www.")
            if host:
                return host
    return ""


def _subject(mandate: dict, count: int) -> str:
    if mandate.get("focus") == "real-estate":
        return "property" if count == 1 else "properties"
    return "company" if count == 1 else "companies"


def public_targets(package: dict) -> list[dict]:
    entities = [
        entity for entity in package.get("entities") or []
        if entity.get("screening", {}).get("fit_label") == "MANDATE_FIT"
        and (
            (package.get("mandate") or {}).get("focus") == "real-estate"
            or listing_gate_passes(entity)
        )
    ]
    entities.sort(key=lambda entity: _FIT_ORDER.get(entity.get("screening", {}).get("fit_label"), 9))
    noun = "property" if (package.get("mandate") or {}).get("focus") == "real-estate" else "company"
    cards = []
    for entity in entities:
        screening = entity.get("screening") or {}
        cards.append({
            "entity_id": entity.get("entity_id") or "",
            "name": entity.get("name") or "Unnamed",
            "fit": _plain_fit(screening),
            "fit_label": screening.get("fit_label") or "",
            "why": _why_fit(entity),
            "thesis": _thesis(entity, package.get("mandate") or {}),
            "gap": _plain_gap(screening),
            "facts": _fact_line(entity),
            "transaction": _plain_transaction(screening, noun),
            "seller": _seller_note(entity),
            "source": _source_host(entity),
        })
    return cards


def render_report(package: dict) -> str:
    mandate = package["mandate"]
    cards = public_targets(package)
    screened = list(package.get("entities") or [])
    thin = sum(
        1 for entity in screened
        if entity.get("screening", {}).get("fit_label") == "INSUFFICIENT_EVIDENCE"
    )
    failed = sum(
        1 for entity in screened
        if entity.get("screening", {}).get("fit_label") == "FAILS_MANDATORY"
    )
    subject = _subject(mandate, len(cards))
    lines = [mandate.get("title") or "Buy box", ""]
    if not cards:
        lines.append(f"No {subject} met every mandatory check.")
        excluded = []
        if thin:
            excluded.append(f"{thin} need more evidence")
        if failed:
            excluded.append(f"{failed} failed a mandatory check")
        if excluded:
            lines.append(
                " and ".join(excluded).capitalize()
                + ". They remain in the audit file but are not shown as matches."
            )
    else:
        summary = [f"{len(cards)} {subject} fit this buy box."]
        hidden = thin + failed
        if hidden:
            summary.append(f"{hidden} other candidate{'s are' if hidden != 1 else ' is'} retained in the audit file but not shown.")
        lines.append(" ".join(summary))
        lines.append("")
    for card in cards:
        lines.append(card["name"])
        lines.append(card["fit"])
        lines.append("")
        if card.get("why"):
            lines.append("Why it fits")
            lines.append(card["why"].removeprefix("Why it fits:").strip())
            lines.append("")
        if card.get("thesis"):
            lines.append("Market thesis")
            lines.append(card["thesis"].removeprefix("Market thesis:").removeprefix("Thesis:").strip())
            lines.append("")
        if card["gap"]:
            lines.append(card["gap"])
            lines.append("")
        if card["facts"]:
            lines.append("Facts")
            lines.append(card["facts"])
            lines.append("")
        lines.append("Process")
        lines.append(card["transaction"])
        lines.append("")
        if card.get("seller"):
            lines.append("Seller interest")
            lines.append(card["seller"].removeprefix("Seller interest (signals only):").strip())
            lines.append("")
        if card["source"]:
            lines.append("Source")
            lines.append(card["source"])
            lines.append("")
    lines.append("Nothing was sent.")
    return "\n".join(lines).strip() + "\n"
