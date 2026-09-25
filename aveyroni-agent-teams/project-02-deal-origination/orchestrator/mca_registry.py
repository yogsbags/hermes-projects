"""Deterministic discovery from the India MCA company registry.

No model call. This replaces the Company Researcher's web discovery step for
India operating-company mandates with a query against `mca_companies_enriched`
in Supabase (852K-row MCA Company Master, data.gov.in resource
4dbe5667-7b6b-41d7-82af-211562424d9a, plus optional paid per-CIN enrichment —
see the sibling Syndiq project's migrations under
`backend/supabase/migrations/`, which this module reads but never writes to).

Everything downstream is unchanged: the names this module surfaces are the
only names the web-search specialists (ownership, financial, transaction,
signal, relationship) are allowed to research — `_keep_named()` in
service.py already enforces that for any discovery source. The registry
cannot answer `business_model`, `revenue_inr_cr` precisely, ownership stake,
or transaction status — those fields stay in `unknowns` here,
which means `gap_plan()` in roles.py automatically routes them to a web
gap-pass, exactly like a thin web discovery pass triggers one today. No
orchestrator changes were needed for that part.

Claims go through the same `deterministic._claim()` normalization every
web-researched claim goes through, so they carry the same "sourced" vs
"inferred" confidence tag and are not silently dropped by
`dedupe_entities()` — a real bug caught by the end-to-end smoke test before
this shipped, not by the unit tests in isolation.

Configure via environment (same `~/.hermes/.env` file chat/server.py already
loads):
  AVEYRONI_MCA_SUPABASE_URL   e.g. https://<project-ref>.supabase.co
  AVEYRONI_MCA_SUPABASE_KEY   a Postgres role key with SELECT on
                              mca_companies_enriched. Use a dedicated
                              read-only role, not the Syndiq service_role key,
                              if this ever runs somewhere less trusted than a
                              local demo machine.

If either variable is unset, `applies()` returns False and the orchestrator
falls back to the existing web-search discovery worker. Nothing breaks for a
reviewer who has never heard of Syndiq's Supabase project.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Callable

from orchestrator.deterministic import _claim as _normalize_claim, entity_key

SOURCE_URL = os.environ.get(
    "AVEYRONI_MCA_SOURCE_URL",
    "https://api.data.gov.in/resource/4dbe5667-7b6b-41d7-82af-211562424d9a",
)
WORKER_ID = "mca-registry"

NIC_SECTOR_OPTIONS = [
    {"id": "10", "label": "NIC 10 — Food products", "sector": "food processing"},
    {"id": "11", "label": "NIC 11 — Beverages", "sector": "beverages"},
    {"id": "13", "label": "NIC 13 — Textiles", "sector": "textiles"},
    {"id": "14", "label": "NIC 14 — Apparel", "sector": "apparel"},
    {"id": "170", "label": "NIC 170 — Paper and paper products", "sector": "paper and paper packaging"},
    {"id": "201", "label": "NIC 201 — Basic chemicals", "sector": "chemicals"},
    {"id": "210", "label": "NIC 210 — Pharmaceuticals", "sector": "pharma contract manufacturing"},
    {"id": "221", "label": "NIC 221 — Rubber products", "sector": "rubber products"},
    {"id": "222", "label": "NIC 222 — Plastic products", "sector": "plastic products and packaging"},
    {"id": "231", "label": "NIC 231 — Glass products", "sector": "glass and building materials"},
    {"id": "239", "label": "NIC 239 — Other non-metallic mineral products", "sector": "building materials"},
    {"id": "241", "label": "NIC 241 — Basic iron and steel", "sector": "iron and steel"},
    {"id": "242", "label": "NIC 242 — Non-ferrous metals", "sector": "non-ferrous metals"},
    {"id": "243", "label": "NIC 243 — Casting of metals", "sector": "metal casting"},
    {"id": "251", "label": "NIC 251 — Structural metal products", "sector": "structural metal products"},
    {"id": "259", "label": "NIC 259 — Other fabricated metal products", "sector": "fabricated metal products"},
    {"id": "271", "label": "NIC 271 — Motors, generators and transformers", "sector": "power transmission equipment"},
    {"id": "273", "label": "NIC 273 — Wiring and wiring devices", "sector": "electrical wiring equipment"},
    {"id": "279", "label": "NIC 279 — Other electrical equipment", "sector": "electrical equipment"},
    {"id": "281", "label": "NIC 281 — General-purpose machinery", "sector": "general-purpose machinery"},
    {"id": "282", "label": "NIC 282 — Special-purpose machinery", "sector": "special-purpose machinery"},
    {"id": "291", "label": "NIC 291 — Motor vehicles", "sector": "motor vehicles"},
    {"id": "292", "label": "NIC 292 — Vehicle bodies and trailers", "sector": "vehicle bodies and trailers"},
    {"id": "293", "label": "NIC 293 — Motor-vehicle parts", "sector": "auto components"},
]

# Sector label (as written in a mandate) -> NIC 2008 code prefixes to match.
# Extend this as more India verticals get demoed. A mandate sector with no
# mapping here just means MCA pre-filtering is skipped for it — the web
# Company Researcher still runs.
SECTOR_NIC_PREFIXES: dict[str, list[str]] = {
    "auto component": ["291", "292", "293"],
    "auto components": ["291", "292", "293"],
    "automotive": ["291", "292", "293"],
    "automotive components": ["291", "292", "293"],
    "auto ancillary": ["291", "292", "293"],
    "forging": ["241", "242", "243", "259"],
    "casting": ["241", "242", "243"],
    "packaging": ["170", "222"],
    "building material": ["231", "239"],
    "power transmission": ["271", "273", "279"],
    "industrial manufacturing": ["251", "259", "281", "282"],
    "pharma": ["210"],
    "pharmaceutical": ["210"],
    "hospital": ["86"],
    "healthcare": ["86"],
    "textile": ["13", "14"],
    "food processing": ["10", "11"],
}

# Mandate ownership label -> mca_companies_enriched.company_class value.
# This is a legal-structure filter only (Private = not publicly traded). It
# is NOT a proxy for family/founder ownership — MNC subsidiaries and PE
# portfolio companies register as Private too. The web ownership-researcher
# still verifies actual ownership on every name this surfaces; this module
# never writes an "ownership" claim itself.
OWNERSHIP_CLASS = {
    "founder": "Private",
    "family": "Private",
    "promoter": "Private",
    "private": "Private",
    "public": "Public",
}

STATE_NAMES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya",
    "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim",
    "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand",
    "west bengal", "delhi",
}

FIELDS = (
    "cin,company_name,company_state_code,nic_code,industrial_classification,"
    "archetype,company_class,company_status,paidup_crores,company_age_years,"
    "registered_office_address,pe_tier,operating_revenue_range"
)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def configured() -> bool:
    return bool(_env("AVEYRONI_MCA_SUPABASE_URL") and _env("AVEYRONI_MCA_SUPABASE_KEY"))


def _nic_prefixes(mandate: dict) -> list[str]:
    valid = {item["id"] for item in NIC_SECTOR_OPTIONS}
    prefixes = [
        str(code).strip()
        for code in mandate.get("sector_codes") or []
        if str(code).strip() in valid
    ]
    for sector in mandate.get("sector") or []:
        key = str(sector).strip().lower()
        for known, values in SECTOR_NIC_PREFIXES.items():
            if known in key or key in known:
                prefixes.extend(v for v in values if v not in prefixes)
    return prefixes


def sector_codes_for_labels(sectors: list[str]) -> list[str]:
    """Infer dropdown selections for legacy free-text mandates."""
    prefixes = _nic_prefixes({"sector": sectors})
    valid = [item["id"] for item in NIC_SECTOR_OPTIONS]
    return [
        code for code in valid
        if any(code.startswith(prefix) or prefix.startswith(code) for prefix in prefixes)
    ]


def _company_class(mandate: dict) -> str | None:
    classes = {
        OWNERSHIP_CLASS[o.strip().lower()]
        for o in mandate.get("ownership") or []
        if o.strip().lower() in OWNERSHIP_CLASS
    }
    if len(classes) == 1:
        return next(iter(classes))
    return None


def _state_filter(mandate: dict) -> str | None:
    for geo in mandate.get("geography") or []:
        key = str(geo).strip().lower()
        if key in STATE_NAMES:
            return key
    return None


def applies(mandate: dict) -> bool:
    """True when the registry can meaningfully pre-filter this mandate."""
    if not configured():
        return False
    if mandate.get("focus") != "operating-company":
        return False
    geography = [str(g).strip().lower() for g in mandate.get("geography") or []]
    if "india" not in geography and not _state_filter(mandate):
        return False
    return bool(_nic_prefixes(mandate))


def _postgrest_get(path: str, params: list[tuple[str, str]], url: str, key: str) -> list[dict]:
    query = urllib.parse.urlencode(params, safe="(),*.")
    request = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/{path}?{query}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _default_fetch(mandate: dict, limit: int, offset: int = 0) -> list[dict]:
    # Deliberately NOT sorted by paidup_crores descending. That sort looked
    # like a reasonable "quality" proxy but isn't: in India, paid-up capital
    # mostly reflects how much equity the owner injected, and a wholly-owned
    # MNC subsidiary gets capitalized heavily by its foreign parent. Sorting
    # by size-descending systematically put MNC subsidiaries first for a
    # founder/family-owned mandate -- a real run surfaced Parker Hannifin
    # India, Vitesco Technologies India, Siemens Energy, CNH Industrial,
    # Danfoss, and Yaskawa as the *first six* candidates, all correctly
    # rejected on ownership, but a wasted, bad-looking pass.
    # company_age_years is an imperfect substitute -- a long-established
    # company is somewhat more likely to be original-promoter-led than one
    # that just registered an India entity, though it is not a guarantee
    # (some of the same MNC subsidiaries above are decades old too). It at
    # least does not carry the same *systematic* size-correlated bias.
    # Ownership verification by the web researcher remains the only real
    # safeguard either way -- this only changes which candidates it spends
    # its research budget checking first.
    url, key = _env("AVEYRONI_MCA_SUPABASE_URL"), _env("AVEYRONI_MCA_SUPABASE_KEY")
    prefixes = _nic_prefixes(mandate)
    nic_filter = ",".join(f"nic_code.like.{prefix}*" for prefix in prefixes)
    params: list[tuple[str, str]] = [
        ("select", FIELDS),
        ("company_status", "eq.Active"),
        ("is_likely_vehicle", "eq.false"),
        ("is_excluded_profile", "eq.false"),
        ("or", f"({nic_filter})"),
        ("order", "company_age_years.desc.nullslast"),
        ("limit", str(limit)),
        ("offset", str(max(0, offset))),
    ]
    company_class = _company_class(mandate)
    if company_class:
        params.append(("company_class", f"eq.{company_class}"))
    state = _state_filter(mandate)
    if state:
        params.append(("company_state_code", f"eq.{state}"))
    return _postgrest_get("mca_companies_enriched", params, url, key)


def _excerpt(row: dict) -> str:
    bits = [
        f"MCA registry: {row.get('company_status') or 'status unknown'}",
        row.get("company_class") or "class unknown",
        f"NIC {row.get('nic_code') or '—'} ({row.get('industrial_classification') or 'unclassified'})",
    ]
    if row.get("company_age_years") is not None:
        bits.append(f"registered {row['company_age_years']} years ago")
    if row.get("paidup_crores") is not None:
        bits.append(f"paid-up capital ₹{row['paidup_crores']} cr — not a revenue figure")
    return ", ".join(bits) + f". CIN {row.get('cin')}."


def _claim(field: str, value: object, excerpt: str) -> dict:
    """Same shape and same confidence rule as every web-researched claim —
    routed through deterministic._claim() so dedupe_entities() keeps it."""
    normalized = _normalize_claim({
        "field": field,
        "value": value,
        "source_url": SOURCE_URL,
        "excerpt": excerpt,
    })
    assert normalized is not None and normalized["confidence"] == "sourced", (
        "MCA registry claims must always have a real https source_url and a non-empty "
        "excerpt — if this assertion fires, a claim would silently vanish downstream."
    )
    return normalized


def _entity(row: dict) -> dict | None:
    name = str(row.get("company_name") or "").strip()
    if not name:
        return None
    excerpt = _excerpt(row)
    claims = [_claim("geography", "India", excerpt)]
    classification = row.get("industrial_classification") or row.get("nic_code")
    if classification:
        claims.append(_claim(
            "sector",
            classification,
            excerpt + " NIC classification is self-declared at registration, not verified operating fact.",
        ))
    revenue_range = row.get("operating_revenue_range")
    if revenue_range:
        claims.append(_claim(
            "revenue_inr_cr",
            revenue_range,
            excerpt + f" Paid enrichment revenue band: {revenue_range} — a band, not a precise figure.",
        ))
    unknowns = ["business_model"]
    if not revenue_range:
        unknowns.append("revenue_inr_cr")
    return {"name": name, "worker": WORKER_ID, "claims": claims, "unknowns": unknowns}


def discover(
    mandate: dict,
    *,
    limit: int = 12,  # was 30 -- a full sourcing pass belongs in a background/scheduled
                       # run (see the README's funnel numbers), not a live client demo.
                       # 12 keeps a "Run team" click watchable in a few minutes.
    fetch_fn: Callable[[dict, int], list[dict]] | None = None,
    offset: int = 0,
    exclude_names: list[str] | None = None,
) -> dict:
    """Return one worker-summary row, same shape as parse_worker_summary()."""
    fetch = fetch_fn or _default_fetch
    try:
        rows = fetch(mandate, limit) if fetch_fn else fetch(mandate, limit, offset)
    except Exception as exc:  # network/credential failure — degrade, don't crash the run
        return {"worker": WORKER_ID, "entities": [], "unparsed": True, "error": str(exc)}
    excluded = {str(name) for name in (exclude_names or [])}
    entities = [
        entity for row in rows
        if (entity := _entity(row)) and entity_key(entity["name"]) not in excluded
    ]
    return {"worker": WORKER_ID, "entities": entities, "unparsed": not entities}
