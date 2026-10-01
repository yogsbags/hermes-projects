"""Read-only MCA company browser and Foxlabs enrichment.

Queries `mca_companies` in the Syndiq Supabase extract. Enrichment calls the
Foxlabs Apify actor (`foxlabs~indian-company-data`) once per CIN and caches
the delivered row under `runs/mca-enrichment/{cin}.json` so a second click
does not re-bill. Failed lookups are not cached as successes.

Keys stay on the server. The frontend only sees public table rows. Emails
appear only when Foxlabs or the existing enrichment table already has one.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from orchestrator import nic
from orchestrator.outreach import APIFY_BASE, _load_env as _load_outreach_env


FOXLABS_ACTOR = "foxlabs~indian-company-data"
CACHE_DIRNAME = "mca-enrichment"
CIN_RE = re.compile(r"^[A-Za-z0-9]{21}$")
TABLE = "mca_companies"
ENRICH_TABLE = "mca_company_enrichment"
SELECT = (
    "cin,company_name,company_roc_code,company_category,company_sub_category,"
    "company_class,authorized_capital,paidup_capital,registration_date,"
    "registered_office_address,listing_status,company_status,company_state_code,"
    "company_origin,nic_code,industrial_classification,source,updated_at"
)
PAGE_SIZE_MAX = 100
COMPANY_CLASSES = ["Public", "Private", "One Person Company"]
LISTING_STATUSES = ["Unlisted", "Listed"]
COMPANY_STATUSES = [
    "Active",
    "Strike Off",
    "Amalgamated",
    "Converted to LLP",
    "Under process of striking off",
    "Dissolved (Liquidated)",
    "Inactive for e-filing",
    "Under Liquidation",
    "Dormant under section 455",
    "Converted and Dissolved",
    "Under CIRP",
    "Dissolved",
]
DEFAULT_SQLITE = Path.home() / "Downloads" / "Syndiq" / "data" / "mca" / "mca_companies.db"
CATEGORIES = [
    "Company limited by shares",
    "Company limited by guarantee",
    "Unlimited company",
]
SUB_CATEGORIES = [
    "Non-government company",
    "subsidiary of company incorporated outside India",
    "Guarantee and association Company",
    "State government company",
    "Union government company",
]
ORIGINS = [
    {"id": "india", "label": "Indian"},
    {"id": "foreign", "label": "Foreign"},
]
ROC_OFFICES = [
    "ROC Delhi", "ROC Mumbai", "ROC Kolkata", "ROC Kanpur", "ROC Hyderabad",
    "ROC Bangalore", "ROC Ahmedabad", "ROC Chennai", "ROC Pune", "ROC Jaipur",
    "ROC Ernakulam", "ROC Patna", "ROC Chandigarh", "ROC Gwalior", "ROC Mumbai I",
    "ROC Vijayawada", "ROC Cuttack", "ROC Coimbatore", "ROC Delhi I", "ROC Guwahati",
    "ROC Mumbai II", "ROC Uttarakhand", "ROC Ranchi", "ROC Delhi II", "ROC Kolkata I",
    "ROC Uttar Pradesh II", "ROC Haryana", "ROC Uttar Pradesh I", "ROC Jammu",
    "ROC Goa", "ROC Himachal Pradesh", "ROC Kolkata II", "ROC Pondicherry",
    "ROC Nagpur", "ROC Andaman",
]
STATES = [
    "andaman and nicobar islands", "andhra pradesh", "arunachal pradesh",
    "assam", "bihar", "chandigarh", "chhattisgarh",
    "dadra and nagar haveli and daman and diu", "delhi", "goa", "gujarat",
    "haryana", "himachal pradesh", "jammu and kashmir", "jharkhand",
    "karnataka", "kerala", "ladakh", "lakshadweep", "madhya pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha",
    "puducherry", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana",
    "tripura", "uttar pradesh", "uttarakhand", "west bengal",
]


def _load_mca_env() -> None:
    """Read MCA keys even when they sit on a DISABLED comment in ~/.hermes/.env."""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return
    wanted = (
        "AVEYRONI_MCA_SUPABASE_URL",
        "AVEYRONI_MCA_SUPABASE_KEY",
        "AVEYRONI_MCA_SQLITE",
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
        "MOTHERDUCK_TOKEN",
    )
    for raw in env_path.read_text().splitlines():
        if "=" not in raw:
            continue
        line = raw.strip()
        if line.startswith("#"):
            idx = min(
                (line.find(name) for name in wanted if name in line),
                default=-1,
            )
            if idx < 0:
                continue
            line = line[idx:]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in wanted and value and not os.environ.get(key):
            os.environ[key] = value


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def sqlite_path() -> Path:
    _load_mca_env()
    override = _env("AVEYRONI_MCA_SQLITE")
    path = Path(override).expanduser() if override else DEFAULT_SQLITE
    return path


def turso_configured() -> bool:
    _load_mca_env()
    return bool(_env("TURSO_DATABASE_URL") and _env("TURSO_AUTH_TOKEN"))


def configured() -> bool:
    _load_mca_env()
    if turso_configured():
        return True
    if sqlite_path().exists():
        return True
    return bool(_env("AVEYRONI_MCA_SUPABASE_URL") and _env("AVEYRONI_MCA_SUPABASE_KEY"))


def enrich_configured() -> bool:
    _load_outreach_env()
    return bool(_env("APIFY_TOKEN"))


def readiness() -> dict:
    missing = []
    if not configured():
        missing.append("Turso credentials, local MCA SQLite, or MCA Supabase URL and key")
    enrich_missing = []
    if not enrich_configured():
        enrich_missing.append("Apify token for Foxlabs")
    return {
        "ready": not missing,
        "missing": missing,
        "enrich_ready": not enrich_missing,
        "enrich_missing": enrich_missing,
        "extract": (
            "turso:mca_companies" if turso_configured()
            else f"sqlite:{sqlite_path().name}" if sqlite_path().exists()
            else "mca_companies"
        ),
        "actor": FOXLABS_ACTOR,
        "cost_per_cin_usd": 0.004,
    }


def options() -> dict:
    sectors = [{"id": row["id"], "label": f"NIC {row['id']} — {row['label']}"} for row in nic.sectors()]
    return {
        "company_class": COMPANY_CLASSES,
        "listing_status": LISTING_STATUSES,
        "company_status": COMPANY_STATUSES,
        "state": [{"id": name, "label": name.title()} for name in STATES],
        "nic": sectors,
        "roc": ROC_OFFICES,
        "category": CATEGORIES,
        "sub_category": SUB_CATEGORIES,
        "origin": ORIGINS,
    }


def parse_filters(raw: dict | None) -> dict:
    src = raw or {}
    page = max(1, _int(src.get("page"), 1))
    page_size = min(PAGE_SIZE_MAX, max(1, _int(src.get("page_size"), 25)))
    plc = src.get("plc")
    if isinstance(plc, str):
        plc = plc.strip().lower() in {"1", "true", "yes", "on"}
    else:
        plc = bool(plc)
    return {
        "search": str(src.get("search") or "").strip(),
        "q": str(src.get("q") or "").strip(),
        "cin": str(src.get("cin") or "").strip().upper(),
        "company_class": str(src.get("company_class") or "").strip(),
        "listing_status": str(src.get("listing_status") or "").strip(),
        "company_status": str(src.get("company_status") or "").strip(),
        "state": str(src.get("state") or "").strip().lower(),
        "nic": str(src.get("nic") or "").strip(),
        "roc": str(src.get("roc") or "").strip(),
        "category": str(src.get("category") or "").strip(),
        "sub_category": str(src.get("sub_category") or "").strip(),
        "origin": str(src.get("origin") or "").strip().lower(),
        "address": str(src.get("address") or "").strip(),
        "industry": str(src.get("industry") or "").strip(),
        "paidup_min_cr": _num(src.get("paidup_min_cr")),
        "paidup_max_cr": _num(src.get("paidup_max_cr")),
        "authorized_min_cr": _num(src.get("authorized_min_cr")),
        "authorized_max_cr": _num(src.get("authorized_max_cr")),
        "registered_from": str(src.get("registered_from") or "").strip(),
        "registered_to": str(src.get("registered_to") or "").strip(),
        "plc": plc,
        "page": page,
        "page_size": page_size,
    }


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_bound(value, end: bool = False) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-12-31" if end else f"{text}-01-01"
    return text


def query_params(filters: dict) -> list[tuple[str, str]]:
    params = [("select", SELECT), ("order", "company_name.asc")]
    if filters.get("search"):
        term = filters["search"].replace(",", " ")
        params.append(("or", f"(company_name.ilike.*{term}*,cin.ilike.*{term}*)"))
    if filters.get("q"):
        params.append(("company_name", f"ilike.*{filters['q']}*"))
    cin = filters.get("cin") or ""
    if CIN_RE.match(cin):
        params.append(("cin", f"eq.{cin}"))
    elif cin:
        params.append(("cin", f"ilike.*{cin}*"))
    for field in ("company_class", "listing_status", "company_status"):
        if filters.get(field):
            params.append((field, f"eq.{filters[field]}"))
    if filters.get("state"):
        params.append(("company_state_code", f"eq.{filters['state']}"))
    if filters.get("nic"):
        params.append(("nic_code", f"like.{filters['nic']}*"))
    if filters.get("roc"):
        params.append(("company_roc_code", f"eq.{filters['roc']}"))
    if filters.get("category"):
        params.append(("company_category", f"ilike.{filters['category']}"))
    if filters.get("sub_category"):
        params.append(("company_sub_category", f"ilike.{filters['sub_category']}"))
    if filters.get("address"):
        params.append(("registered_office_address", f"ilike.*{filters['address']}*"))
    if filters.get("industry"):
        params.append(("industrial_classification", f"ilike.*{filters['industry']}*"))
    if filters.get("origin") == "india":
        params.append(("company_origin", "in.(India,91)"))
    elif filters.get("origin") == "foreign":
        params.append(("company_origin", "neq.India"))
    if filters.get("paidup_min_cr") is not None:
        params.append(("paidup_capital", f"gte.{filters['paidup_min_cr'] * 10_000_000}"))
    if filters.get("paidup_max_cr") is not None:
        params.append(("paidup_capital", f"lte.{filters['paidup_max_cr'] * 10_000_000}"))
    if filters.get("authorized_min_cr") is not None:
        params.append(("authorized_capital", f"gte.{filters['authorized_min_cr'] * 10_000_000}"))
    if filters.get("authorized_max_cr") is not None:
        params.append(("authorized_capital", f"lte.{filters['authorized_max_cr'] * 10_000_000}"))
    if filters.get("registered_from"):
        params.append(("registration_date", f"gte.{_date_bound(filters['registered_from'])}"))
    if filters.get("registered_to"):
        params.append(("registration_date", f"lte.{_date_bound(filters['registered_to'], end=True)}"))
    if filters.get("plc") and not cin:
        params.append(("cin", "like.*PLC*"))
    offset = (filters["page"] - 1) * filters["page_size"]
    params.append(("limit", str(filters["page_size"])))
    params.append(("offset", str(offset)))
    return params


def sql_query(filters: dict) -> tuple[str, list, str, list]:
    """Return (select_sql, select_args, count_sql, count_args) for SQLite/Turso."""
    clauses = ["1=1"]
    args: list = []
    if filters.get("search"):
        term = filters["search"]
        if CIN_RE.match(term.upper()):
            clauses.append("upper(cin) = ?")
            args.append(term.upper())
        else:
            clauses.append("(company_name LIKE ? OR cin LIKE ?)")
            args.extend([f"%{term}%", f"%{term}%"])
    if filters.get("q"):
        clauses.append("company_name LIKE ?")
        args.append(f"%{filters['q']}%")
    cin = filters.get("cin") or ""
    if CIN_RE.match(cin):
        clauses.append("upper(cin) = ?")
        args.append(cin)
    elif cin:
        clauses.append("cin LIKE ?")
        args.append(f"%{cin}%")
    elif filters.get("plc"):
        clauses.append("cin LIKE ?")
        args.append("%PLC%")
    for field in ("company_class", "listing_status", "company_status"):
        if filters.get(field):
            clauses.append(f"{field} = ?")
            args.append(filters[field])
    if filters.get("state"):
        clauses.append("company_state_code = ?")
        args.append(filters["state"])
    if filters.get("nic"):
        clauses.append("CAST(nic_code AS TEXT) LIKE ?")
        args.append(f"{filters['nic']}%")
    if filters.get("roc"):
        clauses.append("company_roc_code = ?")
        args.append(filters["roc"])
    if filters.get("category"):
        clauses.append("lower(company_category) = lower(?)")
        args.append(filters["category"])
    if filters.get("sub_category"):
        clauses.append("lower(company_sub_category) = lower(?)")
        args.append(filters["sub_category"])
    if filters.get("origin") == "india":
        clauses.append("company_origin IN ('India', '91')")
    elif filters.get("origin") == "foreign":
        clauses.append("company_origin IS NOT NULL AND trim(company_origin) NOT IN ('', 'India', '91', 'Blank')")
    if filters.get("address"):
        clauses.append("registered_office_address LIKE ?")
        args.append(f"%{filters['address']}%")
    if filters.get("industry"):
        clauses.append("industrial_classification LIKE ?")
        args.append(f"%{filters['industry']}%")
    if filters.get("paidup_min_cr") is not None:
        clauses.append("paidup_capital >= ?")
        args.append(filters["paidup_min_cr"] * 10_000_000)
    if filters.get("paidup_max_cr") is not None:
        clauses.append("paidup_capital <= ?")
        args.append(filters["paidup_max_cr"] * 10_000_000)
    if filters.get("authorized_min_cr") is not None:
        clauses.append("authorized_capital >= ?")
        args.append(filters["authorized_min_cr"] * 10_000_000)
    if filters.get("authorized_max_cr") is not None:
        clauses.append("authorized_capital <= ?")
        args.append(filters["authorized_max_cr"] * 10_000_000)
    if filters.get("registered_from"):
        clauses.append("registration_date >= ?")
        args.append(_date_bound(filters["registered_from"]))
    if filters.get("registered_to"):
        clauses.append("registration_date <= ?")
        args.append(_date_bound(filters["registered_to"], end=True))
    where = " AND ".join(clauses)
    offset = (filters["page"] - 1) * filters["page_size"]
    select = (
        f"SELECT {SELECT} FROM {TABLE} WHERE {where} "
        f"ORDER BY company_name ASC LIMIT ? OFFSET ?"
    )
    count = f"SELECT COUNT(*) FROM {TABLE} WHERE {where}"
    return select, [*args, filters["page_size"], offset], count, list(args)


def public_company(row: dict) -> dict:
    cin = str(row.get("cin") or "").strip().upper()
    return {
        "cin": cin,
        "name": _text(row.get("company_name")),
        "roc": _text(row.get("company_roc_code")),
        "category": _text(row.get("company_category")),
        "sub_category": _text(row.get("company_sub_category")),
        "company_class": _text(row.get("company_class")),
        "authorized": _money(row.get("authorized_capital")),
        "paidup": _money(row.get("paidup_capital")),
        "registration_date": _text(row.get("registration_date")),
        "address": _text(row.get("registered_office_address")),
        "listing_status": _text(row.get("listing_status")),
        "company_status": _text(row.get("company_status")),
        "state": _text(row.get("company_state_code")),
        "origin": _text(row.get("company_origin")),
        "nic_code": _text(row.get("nic_code")),
        "industry": _text(row.get("industrial_classification")),
        "source": _text(row.get("source")),
        "updated_at": _text(row.get("updated_at")),
        "plc": "PLC" in cin,
        "enriched": False,
    }


def public_enrichment(payload: dict) -> dict:
    raw = payload.get("raw_payload") if isinstance(payload.get("raw_payload"), dict) else payload
    directors = _rows(
        payload.get("directors") or raw.get("directors"),
        ("name", "din", "designation", "tenure"),
    )
    charges = _rows(
        payload.get("charges") or raw.get("charges"),
        ("date", "amount", "holder"),
    )
    locations = _rows(
        payload.get("locations") or raw.get("locations"),
        ("type", "address", "state", "pincode"),
    )
    subsidiaries = _rows(
        payload.get("subsidiaries") or raw.get("subsidiaries"),
        ("name", "cin", "status"),
    )
    email = _text(payload.get("email") or raw.get("email"))
    return {
        "cin": _text(payload.get("cin") or raw.get("cin")).upper(),
        "name": _text(payload.get("company_name") or payload.get("name") or raw.get("name")),
        "status": _text(payload.get("company_status") or raw.get("status")),
        "company_class": _text(
            payload.get("company_class")
            or payload.get("company_class_detail")
            or raw.get("companyClass")
        ),
        "description": _text(payload.get("description") or raw.get("description")),
        "revenue": _text(payload.get("operating_revenue_range") or raw.get("operatingRevenueRange")),
        "revenue_fy_end": _text(payload.get("revenue_fy_end") or raw.get("revenueFyEnd")),
        "ebitda_change_pct": _text(payload.get("ebitda_change_pct") or raw.get("ebitdaChangePct")),
        "networth_change_pct": _text(payload.get("networth_change_pct") or raw.get("networthChangePct")),
        "paidup": _text(raw.get("paidUpCapital") or payload.get("paidup")),
        "authorized": _text(raw.get("authorisedCapital")),
        "currency": _text(raw.get("currency")),
        "incorporation_date": _text(raw.get("incorporationDate")),
        "incorporation_year": _text(raw.get("incorporationYear")),
        "age_years": _text(payload.get("age_years") or raw.get("ageYears")),
        "last_agm_date": _text(payload.get("last_agm_date") or raw.get("lastAgmDate") or raw.get("agm")),
        "address": _text(raw.get("registeredAddress") or payload.get("registered_office_address")),
        "registered_state": _text(payload.get("registered_state") or raw.get("registeredState")),
        "registered_pincode": _text(payload.get("registered_pincode") or raw.get("registeredPincode")),
        "email": email,
        "charges_count": _int(payload.get("charges_count") or raw.get("chargesCount"), len(charges)),
        "directors_count": _int(payload.get("directors_count") or raw.get("directorsCount"), len(directors)),
        "locations_count": _int(payload.get("locations_count") or raw.get("locationsCount"), len(locations)),
        "subsidiaries_count": _int(payload.get("subsidiaries_count") or raw.get("subsidiariesCount"), len(subsidiaries)),
        "directors": directors,
        "charges": charges,
        "locations": locations,
        "subsidiaries": subsidiaries,
        "balance_sheet": _text(payload.get("balance_sheet") or raw.get("balanceSheet") or raw.get("balanceSheetText")),
        "matched": raw.get("matched") is not False,
        "source": _text(payload.get("source") or raw.get("source") or "foxlabs"),
        "scraped_at": _text(raw.get("scrapedAt") or payload.get("enriched_at")),
        "cached": bool(payload.get("cached")),
    }


def _text(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _money(value) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number >= 10_000_000:
        return f"₹{number / 10_000_000:.2f} cr"
    if number >= 100_000:
        return f"₹{number / 100_000:.2f} lakh"
    return f"₹{number:,.0f}"


def _rows(items, keys: tuple[str, ...]) -> list[dict]:
    if not isinstance(items, list):
        return []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append({key: str(item.get(key) or "").strip() for key in keys})
    return rows


def _content_range_total(header: str, fallback: int) -> int:
    text = (header or "").split("/")[-1].strip()
    if text.isdigit():
        return int(text)
    return fallback


def _postgrest(path: str, params: list[tuple[str, str]]) -> tuple[list[dict], int]:
    url = _env("AVEYRONI_MCA_SUPABASE_URL")
    key = _env("AVEYRONI_MCA_SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("MCA database is not configured.")
    query = urllib.parse.urlencode(params, safe="(),*.")
    request = Request(
        f"{url.rstrip('/')}/rest/v1/{path}?{query}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "count=exact",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            rows = json.loads(response.read().decode() or "[]")
            total = _content_range_total(response.headers.get("content-range") or "", len(rows))
            return rows, total
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"MCA database returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"MCA database could not be reached: {exc}") from exc


def _rows_from_sqlite(filters: dict) -> tuple[list[dict], int, str]:
    path = sqlite_path()
    if not path.exists():
        raise RuntimeError("MCA SQLite file is missing.")
    select, select_args, count, count_args = sql_query(filters)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        total = int(conn.execute(count, count_args).fetchone()[0])
        rows = [dict(row) for row in conn.execute(select, select_args).fetchall()]
    return rows, total, f"sqlite:{path.name}"


def _turso_sql(sql: str, args: list) -> list:
    url = _env("TURSO_DATABASE_URL").replace("libsql://", "https://").rstrip("/")
    token = _env("TURSO_AUTH_TOKEN")
    payload = {
        "requests": [
            {
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [{"type": "text" if not isinstance(value, (int, float)) else "integer", "value": str(value) if not isinstance(value, (int, float)) else value} for value in args],
                },
            },
            {"type": "close"},
        ]
    }
    request = Request(
        f"{url}/v2/pipeline",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode() or "{}")
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Turso returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Turso could not be reached: {exc}") from exc
    results = body.get("results") or []
    if not results or results[0].get("type") == "error":
        error = (results[0].get("error") if results else {}) or {}
        raise RuntimeError(f"Turso query failed: {error.get('message') or body}")
    result = results[0].get("response", {}).get("result") or {}
    cols = [col.get("name") for col in result.get("cols") or []]
    rows = []
    for item in result.get("rows") or []:
        values = []
        for cell in item:
            if isinstance(cell, dict):
                values.append(cell.get("value"))
            else:
                values.append(cell)
        rows.append(dict(zip(cols, values)))
    return rows


def _rows_from_turso(filters: dict) -> tuple[list[dict], int, str]:
    select, select_args, count, count_args = sql_query(filters)
    total_row = _turso_sql(count, count_args)
    total = int(next(iter(total_row[0].values())) if total_row else 0)
    rows = _turso_sql(select, select_args)
    return rows, total, "turso:mca_companies"


def search(raw_filters: dict | None, fetch: Callable | None = None) -> dict:
    if fetch is None and not configured():
        raise RuntimeError("MCA database is not configured.")
    filters = parse_filters(raw_filters)
    if fetch is not None:
        rows, total = fetch(TABLE, query_params(filters))
        source = TABLE
    elif turso_configured():
        rows, total, source = _rows_from_turso(filters)
    elif sqlite_path().exists():
        rows, total, source = _rows_from_sqlite(filters)
    else:
        rows, total = _postgrest(TABLE, query_params(filters))
        source = TABLE
    companies = [public_company(row) for row in rows if isinstance(row, dict)]
    return {
        "filters": filters,
        "rows": companies,
        "total": total,
        "page": filters["page"],
        "page_size": filters["page_size"],
        "pages": max(1, (total + filters["page_size"] - 1) // filters["page_size"]) if total else 1,
        "source": source,
        "readiness": readiness(),
        "options": options(),
    }


def cache_path(cin: str, runs_root: Path) -> Path:
    return Path(runs_root) / CACHE_DIRNAME / f"{cin.upper()}.json"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _existing_enrichment(cin: str, fetch: Callable | None = None) -> dict | None:
    getter = fetch or _postgrest
    try:
        rows, _total = getter(
            ENRICH_TABLE,
            [("select", "cin,operating_revenue_range,revenue_fy_end,charges,directors,charges_count,directors_count,email,raw_payload,company_class_detail,description,age_years,last_agm_date,locations,locations_count,subsidiaries,subsidiaries_count,balance_sheet,ebitda_change_pct,networth_change_pct,registered_state,registered_pincode,enriched_at,source"), ("cin", f"eq.{cin}"), ("limit", "1")],
        )
    except RuntimeError:
        return None
    if not rows or not isinstance(rows[0], dict):
        return None
    row = dict(rows[0])
    row["source"] = "mca_company_enrichment"
    return row


def _run_foxlabs(cin: str) -> dict:
    if not enrich_configured():
        raise RuntimeError("Foxlabs enrichment is blocked: APIFY_TOKEN is missing.")
    token = _env("APIFY_TOKEN")
    body = json.dumps({"cins": [cin], "maxResults": 1}).encode()
    request = Request(
        f"{APIFY_BASE}/acts/{FOXLABS_ACTOR}/run-sync-get-dataset-items?timeout=180&memory=256&clean=true",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=200) as response:  # noqa: S310 - fixed HTTPS host
            rows = json.loads(response.read().decode() or "[]")
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise RuntimeError(f"Foxlabs returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Foxlabs could not be reached: {exc}") from exc
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise RuntimeError("Foxlabs returned no row for this CIN.")
    row = rows[0]
    if row.get("matched") is False:
        raise RuntimeError("Foxlabs did not find this CIN. Failed lookups are not billed.")
    row["source"] = "foxlabs"
    return row


def enrich(
    cin: str,
    *,
    runs_root: Path,
    fetch_existing: Callable | None = None,
    run_actor: Callable | None = None,
) -> dict:
    cin = str(cin or "").strip().upper()
    if not CIN_RE.match(cin):
        raise ValueError("Enrich needs a 21-character CIN.")
    cached = _read_json(cache_path(cin, runs_root))
    if cached:
        cached["cached"] = True
        return public_enrichment(cached)
    existing = _existing_enrichment(cin, fetch_existing)
    if existing:
        existing["cached"] = True
        _write_json(cache_path(cin, runs_root), existing)
        return public_enrichment(existing)
    actor = run_actor or _run_foxlabs
    payload = actor(cin)
    payload["cached"] = False
    _write_json(cache_path(cin, runs_root), payload)
    return public_enrichment(payload)
