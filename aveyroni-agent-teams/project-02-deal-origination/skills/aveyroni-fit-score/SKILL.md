---
name: aveyroni-fit-score
description: "Use when scoring a company against a buy-box."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [mandate-fit, scoring, buy-box, origination]
    related_skills: [aveyroni-mandate, aveyroni-ownership, aveyroni-transaction-status]
---

# Mandate fit

Score one resolved company against one buy-box. Write `schemas/screening.json`. Mandate fit and transaction status stay in separate fields.

## Mandatory checks

For each `mandatory_checks` entry, set `pass`, `fail`, or `unknown`.

| Check | pass | fail | unknown |
| --- | --- | --- | --- |
| Geography | Evidence the operations are in the buy-box geography | Evidence they are not | No plant or registered-office evidence |
| Sector | Products match the sector | Evidence of a different business | Products not established |
| Ownership | Holders match `ownership` and do not match `exclude_ownership` | A named excluded owner | Ownership unverified |
| Size | Reported revenue sits inside the mandate's currency and scale band, or overlaps it | Comparable reported revenue is entirely outside the band | Revenue missing, or currency/unit cannot be compared from the evidence |
| Business model | Evidence of the required model, such as manufacturing for OEM or Tier-1 | Evidence it is only a trader or a different model | Not established |

An inferred claim cannot produce `pass`.
Do not silently treat one currency or unit as another. Use a sourced conversion or mark size unknown.

## Label

- Any mandatory `fail` → `FAILS_MANDATORY`.
- Any mandatory `unknown` → `INSUFFICIENT_EVIDENCE`. Set `financial_confirmation_required` when size is the unknown check.
- All mandatory `pass`, and at least one preference `met` → `HIGH_MANDATE_FIT`.
- All mandatory `pass` → `MANDATE_FIT`.
- Do not use `PARTIAL_FIT` to hide a failed mandatory check.

Preferences are `met`, `unmet`, or `unknown`. They do not override a fail.

## Display score

Leave `fit_score` null unless every mandatory check is `pass`. Then you may show an integer that a reader can recompute from the checklist: 70 for all mandatory passes, plus 6 for each preference `met`, minus 6 for each preference `unmet`, capped at 100. Unknown preferences add nothing. Do not publish a score the checklist does not explain.

## Completion

Copy `transaction_status` from the transaction skill.
## Inputs

Sourced claims and one mandate object.

## Outputs

screening.json fields: mandatory checks, fit_label, fit_score, and transaction_status.

## Workflow

1. The Fit Scorer agent reads every excerpt and marks each mandatory check pass, fail, or unknown. Ordinary wording counts. "Manufacturer" and "OEMs" can pass a business-model check when the excerpt says the company makes products for OEMs.
2. Code does not replace that judgment with a keyword list.
3. Any fail becomes FAILS_MANDATORY. Any unknown becomes INSUFFICIENT_EVIDENCE. All passes become MANDATE_FIT. fit_score is 70 only then, otherwise null.

## Rules

An excerpt has to support a pass. Preferences do not hide a failed mandatory check. A missing check from the scorer stays unknown.

## Failure conditions

Reject a score when any mandatory check is unknown or fail. Reject a no-public-process note that omits the off-market caveat.

## Examples

Revenue missing, everything else passing: INSUFFICIENT_EVIDENCE, fit_score null, financial confirmation required. Revenue 40 against a 300–1500 band: FAILS_MANDATORY, fit_score null. Format example only. Checks live in orchestrator/test_orchestrator.py.
