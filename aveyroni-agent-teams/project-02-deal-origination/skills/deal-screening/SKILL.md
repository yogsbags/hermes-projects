---
name: deal-screening
description: "Use when extracting deal facts from a discovered company."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [deal-screening, facts, origination]
    related_skills: [company-intelligence, aveyroni-fit-score, aveyroni-ownership, comps-analysis]
---

# Deal screening

Adapted from Anthropic's `deal-screening` skill in [anthropics/financial-services](https://github.com/anthropics/financial-services/blob/main/plugins/vertical-plugins/private-equity/skills/deal-screening/SKILL.md). Upstream extracts a CIM and returns pass, further diligence, or hard pass. Proprietary origination has no CIM. This skill extracts the same fact list from the research file and stops. `aveyroni-fit-score` decides mandate fit.

## Extract

From evidence already gathered, fill what the source supports and write `unknown` for the rest:

- Legal name, location, sector
- What it makes, in one or two sentences tied to evidence
- Revenue, EBITDA, margins, growth, each with year and evidence id or `unknown`
- Customers and concentration
- Ownership summary and transaction status, copied from those skills, not re-decided here
- Risks that are already in evidence

There is no asking price unless a source states one. Do not invent a valuation multiple.

## Do not

- Mark pass or hard pass. Those words belong to a CIM screen.
- Treat missing EBITDA as a fail. Record it as unknown.
- Treat founder ownership as seller motivation.
- Call `NO_PUBLIC_PROCESS_FOUND` an off-market confirmation.

## Completion

A fact sheet the fit skill can consume without rereading the raw pages. Every filled field has evidence ids. Empty financials stay `unknown`.

## Bull, bear, questions

After the fact sheet, three bullets of bull case and three of bear case, each bullet citing an evidence id or the word `gap`. Then the questions a first conversation would need. Gaps are questions, not reasons to reject.
## Inputs

Evidence already gathered for one resolved target. Not a CIM.

## Outputs

Fact fields with value or unknown: revenue, EBITDA, ownership, products, plants, customers, transaction status. Unknown stays unknown.

## Workflow

1. Read the excerpts.
2. Copy figures that the excerpt states.
3. Hand the facts to aveyroni-fit-score. This skill does not publish the fit label.

## Rules

Do not compute a blended attractiveness score. Off-market is not a fact you may fill from an empty search. A listing is transaction status.

## Failure conditions

Leave the field unknown when the excerpt is missing, the unit is ambiguous, or two sources disagree and neither is a filing or rating report.

## Examples

A report states operating income of 548 crore. Record 548. EBITDA unstated stays unknown. Format example only. Not a live screen.
