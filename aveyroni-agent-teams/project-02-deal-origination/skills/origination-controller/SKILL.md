---
name: origination-controller
description: "Use when running an Aveyroni buy-side origination mandate."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [orchestration, mandate, origination, kanban]
    related_skills: [aveyroni-mandate, deal-sourcing, deal-screening, aveyroni-entity-resolver, aveyroni-ownership, aveyroni-transaction-status, aveyroni-fit-score, aveyroni-evidence-auditor, aveyroni-relationship-map, aveyroni-target-monitor]
---

# Origination controller

Coordinate one mandate. Do the routing and the file hygiene. Call the specialist skill for the judgment. Do not screen, resolve, or score inside this skill.

Write the run under `runs/<mandate_id>/`.

## Order

1. `aveyroni-mandate` → `mandate.json`. Stop if required buy-box fields are missing.
2. `deal-sourcing` → `market-map.md` and `candidates.jsonl`. Funnel counts in the example are targets, not quotas. Do not add companies to hit 150.
3. For each candidate you will spend verification on: `aveyroni-entity-resolver`. Unresolved rows stay in the universe with status `unresolved` and skip later steps.
4. For resolved companies: `company-intelligence`, then `aveyroni-ownership`, then `aveyroni-transaction-status`.
5. `deal-screening` extracts the facts. `aveyroni-fit-score` writes the result. Do not merge fit and transaction status into one "attractiveness" number.
6. Deep work only for companies labeled `HIGH_MANDATE_FIT` or `MANDATE_FIT` that the user asks to prioritize. Then `comps-analysis` if public peers exist, then `aveyroni-evidence-auditor`.
7. `aveyroni-relationship-map` for the priority set. Stop before any message is sent.
8. On a later run, `aveyroni-target-monitor` instead of repeating discovery.

`dd-checklist` and `ic-memo` stay unused until the user opens diligence on one company.

## Artifacts

| File | Contents | Done when |
| --- | --- | --- |
| `mandate-dashboard.md` | Buy-box, counts by stage, blockers | Counts match the files |
| `market-map.md` | Subsectors, clusters, search queries used | Each cluster has a reason |
| `target-universe.jsonl` | One company per line | Unresolved companies included |
| `profiles/<company_id>.md` | Target card | Evidence ids on every claim |
| `weekly-signal-brief.md` | Alerts or explicit no-change | No unsourced alert |

## Target card order

Name, mandate fit checklist, ownership, revenue, EBITDA, products, customers, exports, plants, why it fits, transaction status with the off-market caveat, value-creation hypotheses marked as hypotheses, evidence counts, red team, next action.

## Human stop

Ask before outreach, before a company is dropped for a reason other than a failed mandatory check, and before a monitoring alert goes to the client.

## Hermes workers

The Aveyroni orchestrator service is the runtime. Hermes executes the model turns. Do not create a permanent profile for every skill.

Orchestrating agents:

- Origination Controller — frames the buy box and does not research.
- Research Coordinator — delegates independent research. It does not get a planning model call; the service batches `delegate_task`.
- Fit Scorer — reads the excerpts and marks each mandatory check. It does not search.
- Evidence Reviewer — red-teams the package after the fit scorer and cannot rewrite fit or transaction status.

Delegated research workers, spawned for one pass and then discarded:

- Company Researcher, Ownership Researcher, Financial Researcher
- Transaction Researcher, Relationship Researcher

Deterministic code, not model calls: mandate parsing, entity normalization, evidence normalization, deduplication, data validation, and saving the run file. Code publishes the fit label from the scorer's checklist. It does not rescore the wording.

The company researcher finds the names first. Ownership, financial, and transaction workers then cover that same list, at most three at a time. They use web_search and web_extract, which run on Exa and Firecrawl. Before scoring, a gap pass sends any name still missing geography, sector, business model, ownership, or revenue back to the worker who owns that field. The fit scorer runs next. The relationship worker runs after that score: one search per company, and it does not open a page when the snippet already names a person and a role. Leaf workers research; they do not delegate again.
## Inputs

The saved buy box and, on a later pass, an existing run file.

## Outputs

A worker plan. The service delegates all five research workers. Artifacts land in runs/<mandate_id>/orchestrator-run.json.

## Workflow

1. Frame the buy box in one constraint. Do not search.
2. Let the research coordinator delegate company, ownership, and financial research, then transaction and relationship research.
3. After code scores the package, the evidence reviewer red-teams it.

## Rules

Orchestrating roles are the controller, the research coordinator, the fit scorer, and the evidence reviewer. Five workers research. Code parses, normalizes, deduplicates, validates, and stores. The fit scorer is a model turn: it reads excerpts and marks each check pass, fail, or unknown. Code then publishes the label from that checklist. It does not rescore the wording. Do not send outreach.

## Failure conditions

Stop when the buy box is missing required fields. A worker that returns prose instead of sourced JSON adds no entity. The reviewer cannot repair a score by saying so.

## Examples

A controller note "Stay inside the revenue band" is passed to every worker. A reviewer cannot change deterministic screening fields. Format example only.
