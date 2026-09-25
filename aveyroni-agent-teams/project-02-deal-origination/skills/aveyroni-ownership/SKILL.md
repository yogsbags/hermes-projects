---
name: aveyroni-ownership
description: "Use when verifying promoter, family, or PE ownership."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [ownership, promoter, private-equity, origination]
    related_skills: [aveyroni-entity-resolver, evidence, aveyroni-transaction-status]
---

# Ownership verification

Produce an ownership object matching `schemas/ownership.json` for one resolved legal entity. A group chart is in scope only to stop you attributing a parent's shareholders to the subsidiary.

## Steps

1. Refuse to run if entity resolution is `unresolved`.
2. Use ownership sources appropriate to the jurisdiction: a share register or filing, company registry, credit report, or primary investor announcement. Prefer the operating company's holders over the holding company's.
3. Add a holder only with a name, `holder_type`, percent or null, confidence, and evidence ids. Percentages that do not come from a table stay null.
4. Set `institutional_pe_known` to true only when a named PE fund is a holder or is described as the controlling investor in a primary source. Otherwise false. False means "not found in the sources checked", and the note must say which sources were checked.
5. Do not infer owner, promoter, or family control from a founder surname on the website, a 30-year history, or "family business" copy.

Done when every holder row has evidence, or the holders array is empty and the summary says ownership is unverified.

## Holder types

`promoter_family`, `founder`, `esop`, `corporate`, `private_equity`, `public`, `other`, `unknown`.

Use `unknown` rather than forcing a founder story. `founder` and `promoter_family` require the source to say so.

## Common pitfalls

1. Marking a company founder-owned because no PE article appeared in search.
2. Treating a minority PE cheque as "PE-backed control" without a stake or control statement. Record the holder, and let transaction status decide the label.
## Inputs

A resolved entity and the buy box ownership list, including exclusions.

## Outputs

Claim field ownership with URL and excerpt, or unknown. Values map onto founder, family, promoter, corporate, private_equity, or public.

## Workflow

1. Read the filing, rating report, or annual report.
2. Quote the holder sentence.
3. Fail the check when the holder matches an excluded owner.

## Rules

A family business stays family when the source says so. institutional_pe_known language is an exclusion, not a seller signal. Founder-owned is not intent to sell.

## Failure conditions

Unknown when the holder is unnamed, the excerpt is missing, or the only source is a directory. Do not guess from the company's age.

## Examples

Excerpt "A family holds the shares" supports family. Excerpt "A private equity fund controls the company" fails a buy box that excludes private equity. Format example only.
