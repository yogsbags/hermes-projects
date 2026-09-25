"""Prompts for the coordinating roles and the six research workers.

The research coordinator does not get its own model call. It is the service
that batches delegate_task. The controller, the fit scorer, and the evidence
reviewer do.
"""

from __future__ import annotations

import json

from orchestrator.deterministic import required_checks

WORKERS = (
    {
        "id": "company-researcher",
        "name": "Company Researcher",
        "skill": "deal-sourcing",
        "asks": "Find real targets that match this buy box. Return claims for geography and, depending on the buy box, sector plus business_model, or asset_type. Do not estimate revenue, price, or ownership.",
    },
    {
        "id": "ownership-researcher",
        "name": "Ownership Researcher",
        "skill": "aveyroni-ownership",
        "asks": (
            "Find who owns each named target and whether its equity is publicly traded. "
            "Use claim field ownership for the owner and listing_status with value unlisted or listed. "
            "A family or promoter stake does not prove a company is unlisted. Confirm listing_status from a reliable "
            "company, exchange, registry, or filing source. If either fact is unsupported, put that field in unknowns."
        ),
    },
    {
        "id": "financial-researcher",
        "name": "Financial Researcher",
        "skill": "deal-screening",
        "asks": "Find a sourced size figure for each named target. Operating companies use field revenue and preserve the source currency and unit in the value. Real estate uses units or price, whichever the source states. Do not invent EBITDA or silently convert currencies. If the source has no figure, put the field in unknowns.",
    },
    {
        "id": "transaction-researcher",
        "name": "Transaction Researcher",
        "skill": "aveyroni-transaction-status",
        "asks": (
            "For each named target, find whether a public process exists. Use claim field transaction_status. "
            "A listing or pending sale is an active sale process. If you find no process, value is NO_PUBLIC_PROCESS_FOUND "
            "and the excerpt must say that is not proof the target is off-market. "
            "Also return claim field signal when a sourced excerpt shows succession, next-generation management, "
            "a capacity expansion, a promoter transition, fundraising, or a public process. "
            "Do not infer that the owner wants to sell."
        ),
    },
    {
        "id": "relationship-researcher",
        "name": "Relationship Researcher",
        "skill": "aveyroni-relationship-map",
        "asks": (
            "Screening pass. One web_search per company. Use ownership and leadership terms from the target's jurisdiction. "
            "If the snippet names a person and a role, record that and do not web_extract. "
            "Return at most the owner, founder, or promoter and one other named person, field relationship. "
            "If the snippet names a next-generation family member, include that in the relationship value. "
            "One unknown covers a missing adviser, auditor, or lender. Do not write an outreach brief. "
            "Do not draft or send a message. Do not infer that the owner wants to sell."
        ),
    },
)

WORKER_BY_ID = {worker["id"]: worker for worker in WORKERS}
DISCOVERY_ID = "company-researcher"
FILL_ORDER = (
    "ownership-researcher",
    "financial-researcher",
    "transaction-researcher",
)
AFTER_SCORE = ("relationship-researcher",)
BATCH_SIZE = 3

WEB_TOOLS = (
    "Use web_search and web_extract only. Search runs on Exa. Page extracts run on Firecrawl. "
    "Do not call Apify, Tavily, Brave, or Parallel."
)

OUTPUT_SHAPE = """
Return one JSON object and nothing else:
{"entities":[{"name":"","claims":[{"field":"","value":"","source_url":"https://...","excerpt":"short quote"}],"unknowns":[]}]}
Every claim needs an http(s) source_url and an excerpt copied from that page. No excerpt means the claim will be dropped. Do not invent names, numbers, or intent. If you cannot source a field for a named target, put that field in unknowns for that name.
""".strip()


def dossier_fields(mandate: dict) -> dict[str, list[str]]:
    """Fields each worker must fill before a company is scored."""
    if mandate.get("focus") == "real-estate":
        financial = []
        if mandate.get("units_min") is not None:
            financial.append("units")
        if mandate.get("price_min") is not None:
            financial.append("price")
        fields = {"company-researcher": ["geography", "asset_type"]}
        if financial:
            fields["financial-researcher"] = financial
        return fields
    return {
        "company-researcher": ["geography", "sector", "business_model"],
        "ownership-researcher": ["ownership", "listing_status"],
        "financial-researcher": ["revenue"],
    }


def missing_fields(entity: dict, fields: list[str]) -> list[str]:
    found = {claim.get("field") for claim in entity.get("claims") or []}
    unknown = set(entity.get("unknowns") or [])
    if "revenue_inr_cr" in found:
        found.add("revenue")
    if "revenue_inr_cr" in unknown:
        unknown.add("revenue")
    return [field for field in fields if field not in found and field not in unknown]


def gap_plan(entities: list[dict], mandate: dict) -> dict[str, list[tuple[str, list[str]]]]:
    """Names still missing a dossier field, grouped by the worker who owns it.

    A field already present as a sourced claim, or already listed in unknowns, is not sent back.
    """
    plan: dict[str, list[tuple[str, list[str]]]] = {}
    owned = dossier_fields(mandate)
    for entity in entities:
        name = entity.get("name")
        if not name:
            continue
        for worker_id, fields in owned.items():
            missing = missing_fields(entity, fields)
            if missing:
                plan.setdefault(worker_id, []).append((name, missing))
    return plan


def controller_message(mandate: dict) -> str:
    return (
        "You are the Origination Controller. Tools are off for this turn. Do not search and do not invent targets.\n"
        "Read the buy box and return only this JSON object: "
        '{"focus_notes":"one sentence naming the constraint the workers must not relax"}\n'
        "Do not skip workers. The service will delegate all five.\n\n"
        f"Buy box:\n{json.dumps(mandate, ensure_ascii=False, indent=2)}"
    )


def fit_scorer_message(mandate: dict, entities: list[dict]) -> str:
    packet = [
        {
            "entity_id": entity.get("entity_id"),
            "name": entity.get("name"),
            "claims": [
                {
                    "field": claim.get("field"),
                    "value": claim.get("value"),
                    "source_url": claim.get("source_url"),
                    "excerpt": claim.get("excerpt"),
                }
                for claim in entity.get("claims") or []
            ],
        }
        for entity in entities
    ]
    checks = required_checks(mandate)
    return (
        "You are the Fit Scorer. Tools are off. Do not search and do not invent facts.\n"
        "Judge each required check from the excerpts. Ordinary wording counts: "
        "\"manufacturer\", \"OEMs\", \"forged components\", and \"family-owned\" can pass when the excerpt supports the buy box.\n"
        "Pass only when an excerpt supports the check. If no excerpt supports it, use unknown. "
        "If an excerpt contradicts the buy box, use fail.\n"
        "For listing_status, only an unlisted or privately-held sourced claim can pass. "
        "A listed/publicly traded company fails even when a founder or family remains the controlling promoter.\n"
        "For operating-company size, compare revenue against the mandate's currency and scale. "
        "Do not silently treat one currency or unit as another; if conversion cannot be supported from the excerpt, use unknown.\n"
        "A missing revenue, unit, or price figure is unknown, not a guess.\n"
        "Return only this JSON object, with every entity_id and every required check:\n"
        '{"scores":[{"entity_id":"","mandatory":[{"check":"","result":"pass","reason":"one sentence citing the excerpt"}]}]}\n'
        "result is pass, fail, or unknown. Do not set fit_score.\n\n"
        f"Required checks: {json.dumps(checks)}\n"
        f"Buy box:\n{json.dumps(mandate, ensure_ascii=False, indent=2)}\n\n"
        f"Targets:\n{json.dumps(packet, ensure_ascii=False, indent=2)}"
    )


def reviewer_message(package: dict) -> str:
    brief = {
        "mandate": package.get("mandate"),
        "entities": [
            {
                "name": entity.get("name"),
                "screening": entity.get("screening"),
                "claims": [
                    {
                        "field": claim.get("field"),
                        "value": claim.get("value"),
                        "source_url": claim.get("source_url"),
                        "excerpt": claim.get("excerpt"),
                    }
                    for claim in entity.get("claims") or []
                ],
            }
            for entity in package.get("entities") or []
        ],
    }
    text = json.dumps(brief, ensure_ascii=False, indent=2)
    if len(text) > 12000:
        text = text[:12000] + "\n…"
    return (
        "You are the Evidence Reviewer. Tools are off. Do not search.\n"
        "Red-team the package. Name contradictions, missing excerpts, and weak transaction-status claims.\n"
        "You cannot change the fit scorer's checks, fit_label, fit_score, or transaction_status.\n"
        "No public process found is not proof the target is off-market.\n"
        "Do not tell anyone to send outreach.\n\n"
        f"Package:\n{text}"
    )


def worker_task(
    worker: dict,
    mandate: dict,
    focus_notes: str,
    names: list[str],
    mode: str,
    missing: list[tuple[str, list[str]]] | None = None,
) -> dict:
    focus = mandate.get("focus")
    subject = "properties" if focus == "real-estate" else "operating companies"
    if mode == "fill" and worker["id"] == "relationship-researcher":
        assignment = (
            "Screening pass. One web_search per name. If the snippet names a person and a role, "
            "record it and do not web_extract. At most the owner, founder, or promoter and one other named person. "
            "One unknown covers a missing adviser, auditor, or lender. Do not write an outreach brief. "
            "Do not add a company.\n"
            "Names:\n" + "\n".join(f"- {name}" for name in names) + "\n"
        )
    elif mode == "discover":
        assignment = f"Find {subject} that match this buy box. Return the name list the other workers will share.\n"
    elif mode == "gap":
        lines = [f"- {name}: {', '.join(fields)}" for name, fields in (missing or [])]
        assignment = (
            "Gap pass. These names are already on the list. Fill only the fields after each name. "
            "Do not add a company.\n"
            + "\n".join(lines) + "\n"
        )
    else:
        assignment = (
            "Research only these names. Cover every name. Return a sourced claim for your field, "
            "or put that field in unknowns for that name. Do not add a company that is not on this list.\n"
            "Names:\n" + "\n".join(f"- {name}" for name in names) + "\n"
        )
    goal = (
        f"{worker['name']}. Follow {worker['skill']}. {worker['asks']} "
        f"{WEB_TOOLS} Do not contact anyone."
    )
    context = (
        f"{assignment}"
        f"Controller note: {focus_notes or 'Stay inside the buy box.'}\n"
        f"Buy box:\n{json.dumps(mandate, ensure_ascii=False)}\n\n"
        f"{OUTPUT_SHAPE}"
    )
    return {"goal": goal, "context": context, "role": "leaf"}


def tasks_for(worker_ids: list[str], mandate: dict, focus_notes: str, names: list[str], mode: str) -> list[dict]:
    return [
        worker_task(WORKER_BY_ID[worker_id], mandate, focus_notes, names, mode)
        for worker_id in worker_ids
    ]
