"""Load NIC 2025 industry / sector / niche lists from JSON. No hardcoded roster."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "config" / "nic"


def _read(name: str) -> dict:
    path = ROOT / name
    if not path.exists():
        raise FileNotFoundError(f"NIC catalog missing: {path}")
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def industries() -> list[dict]:
    return list(_read("industries.json").get("items") or [])


@lru_cache(maxsize=1)
def sectors() -> list[dict]:
    return list(_read("sectors.json").get("items") or [])


@lru_cache(maxsize=1)
def niches() -> list[dict]:
    return list(_read("niches.json").get("items") or [])


@lru_cache(maxsize=1)
def aliases() -> dict[str, list[str]]:
    raw = _read("aliases.json").get("items") or {}
    return {str(key).strip().lower(): list(values) for key, values in raw.items()}


def catalog() -> dict:
    return {
        "industries": industries(),
        "sectors": sectors(),
        "niches": niches(),
    }


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {str(row["id"]): row for row in rows}


def industry_by_id() -> dict[str, dict]:
    return _by_id(industries())


def sector_by_id() -> dict[str, dict]:
    return _by_id(sectors())


def niche_by_id() -> dict[str, dict]:
    return _by_id(niches())


def catalog_options() -> list[dict]:
    """Group-level options in the shape older MCA code expected."""
    return [
        {
            "id": row["id"],
            "label": f"NIC {row['id']} — {row['label']}",
            "sector": row["label"],
        }
        for row in niches()
    ]


def labels_for_codes(codes: list[str]) -> list[str]:
    lookup = niche_by_id()
    sectors_lookup = sector_by_id()
    industries_lookup = industry_by_id()
    labels = []
    for code in codes:
        row = lookup.get(code) or sectors_lookup.get(code) or industries_lookup.get(code)
        if row and row["label"] not in labels:
            labels.append(row["label"])
    return labels


def codes_for_selection(industry_id: str = "", sector_id: str = "", niche_id: str = "") -> list[str]:
    if niche_id and niche_id in niche_by_id():
        return [niche_id]
    if sector_id:
        return [row["id"] for row in niches() if row.get("sector_id") == sector_id]
    return []


def infer_selection(sector_codes: list[str] | None = None) -> dict[str, str]:
    codes = [str(code).strip() for code in sector_codes or [] if str(code).strip()]
    if not codes:
        return {"industry_code": "", "sector_code": "", "niche_code": ""}
    groups = [niche_by_id()[code] for code in codes if code in niche_by_id()]
    if not groups:
        if codes[0] in sector_by_id():
            sector = sector_by_id()[codes[0]]
            return {"industry_code": sector["industry_id"], "sector_code": sector["id"], "niche_code": ""}
        if codes[0] in industry_by_id():
            return {"industry_code": codes[0], "sector_code": "", "niche_code": ""}
        return {"industry_code": "", "sector_code": "", "niche_code": ""}
    industry_ids = {row["industry_id"] for row in groups}
    sector_ids = {row["sector_id"] for row in groups}
    return {
        "industry_code": next(iter(industry_ids)) if len(industry_ids) == 1 else "",
        "sector_code": next(iter(sector_ids)) if len(sector_ids) == 1 else "",
        "niche_code": groups[0]["id"] if len(groups) == 1 else "",
    }


def resolve(config: dict) -> dict:
    industry_code = str(config.get("industry_code") or "").strip()
    sector_code = str(config.get("sector_code") or "").strip()
    niche_code = str(config.get("niche_code") or "").strip()
    if industry_code and industry_code not in industry_by_id():
        industry_code = ""
    if sector_code and sector_code not in sector_by_id():
        sector_code = ""
    if niche_code and niche_code not in niche_by_id():
        niche_code = ""
    if sector_code and industry_code and sector_by_id()[sector_code]["industry_id"] != industry_code:
        sector_code = ""
        niche_code = ""
    if niche_code:
        niche = niche_by_id()[niche_code]
        if sector_code and niche["sector_id"] != sector_code:
            niche_code = ""
        elif not sector_code:
            sector_code = niche["sector_id"]
            industry_code = niche["industry_id"]
    codes = codes_for_selection(industry_code, sector_code, niche_code)
    if not codes:
        codes = [str(code).strip() for code in config.get("sector_codes") or [] if str(code).strip() in niche_by_id()]
        inferred = infer_selection(codes)
        industry_code = industry_code or inferred["industry_code"]
        sector_code = sector_code or inferred["sector_code"]
        niche_code = niche_code or inferred["niche_code"]
        codes = codes_for_selection(industry_code, sector_code, niche_code) or codes
    labels = labels_for_codes([niche_code] if niche_code else ([sector_code] if sector_code else codes))
    if not labels and industry_code:
        labels = [industry_by_id()[industry_code]["label"]]
    return {
        "industry_code": industry_code,
        "sector_code": sector_code,
        "niche_code": niche_code,
        "sector_codes": codes,
        "sector": labels,
    }


def prefixes_from_labels(sectors: list[str]) -> list[str]:
    prefixes: list[str] = []
    mapping = aliases()
    for sector in sectors:
        key = str(sector).strip().lower()
        for known, values in mapping.items():
            if known in key or key in known:
                prefixes.extend(value for value in values if value not in prefixes)
    return prefixes
