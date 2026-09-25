---
name: aveyroni-entity-resolver
description: "Use when confirming a company's exact legal identity in its jurisdiction."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [entity-resolution, company-registry, origination]
    related_skills: [research, evidence, aveyroni-ownership]
---

# Entity resolution

Separate the candidate from similarly named companies before any ownership, financial, or fit work.

## Steps

1. List the strings you were given: trade name, legal name, city, domain.
2. Search the legal name in quotes and the domain. Use `research` for source order.
3. Accept a canonical identity only when two independent attributes agree, chosen from: jurisdictional registration number, registered domain, operating location plus product, or owner name on a primary source.
4. Record aliases that those sources also use. Do not merge different legal forms or similarly named firms in different jurisdictions.
5. Write `legal_name`, `aliases`, `domain`, `registration_id` (or null), `registration_jurisdiction`, and `locations`. For India, the CIN is the registration ID. Each non-null field has evidence ids.

Done when either the identity is canonical, or the status is `unresolved` and the candidate is out of scoring. An unresolved company is not "close enough".

## Rejection cases

- Same first word, different legal suffix.
- Same brand, different registration number.
- A group company that owns the brand but is not the manufacturing entity the mandate would buy.
- A directory row with no domain and no registration identity.

## Common pitfalls

1. Using the richest search result instead of the entity that matched the plant or domain you started with.
2. Copying a registration number from a namesake. The registry company name must match the legal name you are keeping.
## Inputs

A name as found, plus any URL, city, or registration hint from search.

## Outputs

One canonical name and entity id, or status unresolved. Similar names stay separate until a source ties them together.

## Workflow

1. Strip legal suffixes only for matching.
2. Require a source that the legal entity is the one in the snippet.
3. Leave the row unresolved when two companies still fit.

## Rules

Do not merge on a similar trade name alone. Do not invent a CIN. Unresolved rows skip ownership, fit, and seller work.

## Failure conditions

Stop the entity when the source names a different company, the page is a directory with several matches, or no page confirms the legal name.

## Examples

"Punch Ratna Fasteners" and "Punch Ratna Fasteners Pvt Ltd" match after the suffix is removed, and only if one source covers both. Format example only. Not a researched identity.
