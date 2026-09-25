---
name: evidence
description: "Use when attaching a source, date, and confidence to a claim."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [evidence, citations, origination]
    related_skills: [aveyroni-evidence-auditor, tavily, research]
---

# Evidence record

Every origination claim that reaches a target card, score, or alert is one object matching `schemas/evidence.json`.

## Write the record

1. Set `kind` to `reported` when the source states it, `calculated` when you did arithmetic from reported figures, or `inferred` when you concluded it.
2. Copy a short `excerpt`. Paraphrase belongs in `claim`, not in `excerpt`.
3. Set `source_date` from the document period and `publication_date` from when it was published. Use null when the page has no date, and set confidence to `low`.
4. Set confidence to `high` only for a primary document (filing, rating report, company page, exchange disclosure) whose excerpt matches the claim. A news recap of a filing is `medium`. A directory, database teaser, or undated blog is `low`.
5. List contradicting excerpts in `contradictions`. Do not average them into a smoother claim.

Done when the claim can be checked without opening the rest of the run, and the schema required fields are present.

## Rules that override tone

- No evidence id, no claim on the card.
- An inferred claim cannot satisfy a mandatory buy-box check.
- Two sources that disagree stay as two records. The card states the conflict.
- Do not upgrade confidence because several secondary sites repeat one another.

## Common pitfalls

1. Putting the company's marketing line in `excerpt` and a stronger conclusion in `claim` with kind `reported`.
2. Citing the search snippet when the page itself was not extracted. Label those `low` and say the body was not read.
