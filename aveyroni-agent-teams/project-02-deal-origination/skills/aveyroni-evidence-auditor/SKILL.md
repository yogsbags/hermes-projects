---
name: aveyroni-evidence-auditor
description: "Use when challenging unsourced claims on a target."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [evidence-audit, red-team, origination]
    related_skills: [evidence, aveyroni-fit-score, aveyroni-transaction-status]
---

# Evidence audit and red team

Audit after scoring, before a company is called a priority target. Do not add new research except to check a citation you were given.

## Audit

1. List every claim on the card, the fit checklist, the ownership tree, and the signal register.
2. Drop any claim with no evidence id, or whose excerpt does not support the wording. Say what you removed.
3. Recount confidence: high, medium, low.
4. Thesis test: delete every `inferred` claim. If a mandatory check was `pass` only because of an inferred claim, downgrade that check to `unknown` and set the fit label to `INSUFFICIENT_EVIDENCE`.
5. State whether the investment thesis still stands on reported and calculated claims alone. "Stands" means every mandatory check is still `pass`.

Done when the card's counts match the remaining records and the thesis sentence is yes or no.

## Red team

Write the case against pursuing the target. Use only gaps and contrary evidence already in the file, plus standard missing items:

- Customer concentration unknown when customers are unnamed.
- EBITDA unavailable when the field is unknown.
- Succession thesis unsupported when there is no `succession` signal.
- Transaction status overclaimed if the note says off-market while the status is `NO_PUBLIC_PROCESS_FOUND`.

Each red-team line starts with the gap. Do not invent a defect the file does not support, and do not soften a gap to keep the company in the priority list.

## Completion

Return the cleaned card, the confidence counts, the thesis-test result, and the red-team lines. A priority company that fails the thesis test stays in the universe with its label downgraded. It is not deleted.
## Inputs

The screened package: claims, excerpts, URLs, and the code-written scores.

## Outputs

A red-team note. Contradictions and missing excerpts. No rewritten scores.

## Workflow

1. Read each claim against its excerpt.
2. Flag inferred numbers, merged identities, and listings treated as owner intent.
3. Leave fit_label, fit_score, and transaction_status as code wrote them.

## Rules

Inferred is not pass. INSUFFICIENT_EVIDENCE stays when a mandatory check is unknown. No public process found is not proof of off-market. Do not recommend outreach.

## Failure conditions

The review fails if it changes a score or transaction status, or if it adds a company that has no claim.

## Examples

A package with an active listing should retain its sourced transaction status. Format example only.
