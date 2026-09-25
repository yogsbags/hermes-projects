#!/usr/bin/env python3
"""Check Project 02 skills and example files against origination rules."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ROOT.parent
SKILL_FILES = list((ROOT / "skills").glob("*/SKILL.md")) + list(
    (TEAMS / "shared").glob("*/SKILL.md")
)

CONTRACT_SKILLS = {
    "aveyroni-mandate",
    "aveyroni-entity-resolver",
    "aveyroni-ownership",
    "aveyroni-transaction-status",
    "aveyroni-fit-score",
    "aveyroni-evidence-auditor",
    "aveyroni-relationship-map",
    "aveyroni-target-monitor",
    "deal-sourcing",
    "deal-screening",
    "comps-analysis",
    "web-search",
    "web-extract",
    "deep-research",
    "origination-controller",
}
CONTRACT_HEADINGS = (
    "## Inputs",
    "## Outputs",
    "## Workflow",
    "## Rules",
    "## Failure conditions",
    "## Examples",
)

REQUIRED_PHRASES = {
    "aveyroni-transaction-status": ["NO_PUBLIC_PROCESS_FOUND", "not proof"],
    "aveyroni-fit-score": ["transaction_status", "FAILS_MANDATORY", "fit_score"],
    "aveyroni-evidence-auditor": ["inferred", "INSUFFICIENT_EVIDENCE"],
    "aveyroni-ownership": ["institutional_pe_known", "family business"],
    "deal-sourcing": ["not quotas", "candidates.jsonl"],
    "deal-screening": ["unknown", "off-market"],
    "origination-controller": ["transaction status", "mandate.json"],
}


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise SystemExit(f"{path}: frontmatter must start at byte 0")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SystemExit(f"{path}: frontmatter did not close")
    block = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.startswith(" "):
            continue
        key, _, value = line.partition(":")
        block[key.strip()] = value.strip().strip('"')
    if "version" not in block:
        raise SystemExit(f"{path}: version is required")
    if "name" not in block or "description" not in block:
        raise SystemExit(f"{path}: name and description are required")
    if len(block["description"]) > 1024:
        raise SystemExit(f"{path}: description longer than 1024")
    if not block["description"].startswith("Use when"):
        raise SystemExit(f"{path}: description must start with 'Use when'")
    if len(text) > 100_000:
        raise SystemExit(f"{path}: skill longer than 100000 chars")
    return block


def main() -> None:
    names = set()
    for path in SKILL_FILES:
        meta = frontmatter(path)
        names.add(meta["name"])
        text = path.read_text().lower()
        for phrase in REQUIRED_PHRASES.get(meta["name"], []):
            if phrase.lower() not in text:
                raise SystemExit(f"{path}: missing required phrase {phrase!r}")
        if meta["name"] in CONTRACT_SKILLS:
            body = path.read_text()
            for heading in CONTRACT_HEADINGS:
                if heading not in body:
                    raise SystemExit(f"{path}: missing {heading}")

    missing = CONTRACT_SKILLS - names
    if missing:
        raise SystemExit(f"missing contract skills: {', '.join(sorted(missing))}")

    mandate = json.loads((ROOT / "examples/india-auto-components/mandate.json").read_text())
    for key in (
        "sector",
        "geography",
        "revenue_min_inr_cr",
        "revenue_max_inr_cr",
        "ownership",
        "exclude_ownership",
    ):
        if key not in mandate:
            raise SystemExit(f"mandate missing {key}")
    if mandate["revenue_min_inr_cr"] != 300 or mandate["revenue_max_inr_cr"] != 1500:
        raise SystemExit("demo mandate revenue band drifted")
    if "private_equity" not in mandate["exclude_ownership"]:
        raise SystemExit("demo mandate must exclude private equity")

    card = json.loads(
        (ROOT / "examples/india-auto-components/target-card.illustrative.json").read_text()
    )
    if card.get("illustrative") is not True:
        raise SystemExit("sample target card must stay marked illustrative")
    if card["ebitda"] != "unknown":
        raise SystemExit("sample card filled EBITDA")

    screen = json.loads(
        (ROOT / "examples/india-auto-components/screening.illustrative.json").read_text()
    )
    if screen["transaction_status"] != "NO_PUBLIC_PROCESS_FOUND":
        raise SystemExit("sample screen changed transaction status")
    note = screen["transaction_status_note"].lower()
    if "not proof" not in note or "off-market" not in note:
        raise SystemExit("sample screen dropped the off-market caveat")
    if screen["fit_score"] is not None and "unknown" in {
        row["result"] for row in screen["mandatory"]
    }:
        raise SystemExit("fit score published while a mandatory check is unknown")
    print(f"ok {len(names)} skills, demo mandate, illustrative card")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
