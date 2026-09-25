---
name: aveyroni-mandate
description: "Use when turning a buy-side thesis into a buy-box."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [mandate, buy-box, screening-rules, origination]
    related_skills: [deal-sourcing, aveyroni-fit-score, origination-controller]
---

# Mandate normalization

Turn the client's prose into one object that validates against `schemas/mandate.json`. Later skills read that object. They do not re-interpret the email.

## Steps

1. Quote the source text into `source_text`. Do not tidy it into a stronger mandate.
2. Fill only constraints the text states. Sector, geography, revenue bounds, included ownership, and excluded ownership are required. If a required field is missing, ask one question and stop.
3. Put hard constraints in `mandatory_checks`: geography, sector, ownership, size, business model. Put "attractive", "niche", "export capability", and "value creation" in `preferences`, not in mandatory checks, unless the client said they are required.
4. Map ownership words onto `founder`, `family`, `promoter`, `corporate`, `private_equity`, `public`. "No institutional PE" goes in `exclude_ownership`, not in a note.
5. Preserve the mandate's revenue currency and scale in `revenue`: `min`, `max`, ISO currency, and `scale` (`million`, `billion`, or `crore`). "USD 50–200 million" stays USD million. "₹300–1,500 crore" stays INR crore. Do not silently convert currencies and do not invent an EBITDA gate the client did not set.
6. Validate the JSON against the schema. Fix it before handoff.

Done when a second agent can screen without reading the original paragraph, and no preference has been promoted to a mandatory check.

## Common pitfalls

1. Treating "potential for value creation" as a screen that rejects companies.
2. Adding "founder age" or "willing to sell" because the buyer wants off-market deals. Those are not buy-box fields.
## Inputs

Client prose or the desk buy box: title, focus, geography, and either sector, ownership, and a revenue band, or asset types.

## Outputs

One mandate object. Preferences stay out of mandatory checks. Missing required fields stop the run.

## Workflow

1. Quote the source. Do not strengthen it.
2. Fill only stated constraints.
3. Validate before any worker starts.

## Rules

"Attractive" and "value creation" are preferences. Founder age and willingness to sell are not buy-box fields. Do not invent an EBITDA gate.

## Failure conditions

Stop when geography is missing, when an operating-company box has no sector, ownership, or revenue band, or when a real-estate box has no asset type.

## Examples

"USD 50–200 million, founder or family, Vietnam, auto components, no institutional PE" becomes revenue `{min: 50, max: 200, currency: USD, scale: million}`, ownership founder and family, exclude_ownership private_equity. An INR-crore mandate uses the same shape with currency INR and scale crore. Format examples only.
