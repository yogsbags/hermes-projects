---
name: research
description: "Use when researching an Indian private company's identity or filings."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [india, private-company, sources, origination]
    related_skills: [tavily, evidence, company-intelligence, aveyroni-entity-resolver]
---

# Indian private-company research

Search in this order. Stop when a primary source answers the question. Record the source you actually used.

1. The company's own site: about, plants, customers, investors, CIN or GST in the footer.
2. Credit rating reports (CRISIL, ICRA, CARE, India Ratings, Acuité) and exchange filings if any group entity is listed.
3. MCA-indexed records and annual-return extracts where Aveyroni has a lawful login. Do not scrape a portal the mandate is not allowed to use.
4. Trade-association directories (ACMA for auto components) and OEM supplier or award lists.
5. Import/export records for an IEC you already tied to the legal entity.
6. News and transaction databases. These suggest leads. They do not settle identity, ownership, or seller intent.

## Query shape

Use the legal name in quotes, then one facet: CIN, plant city, promoter, "private equity", "rating", "acquisition", "expansion". Run a second query with the website domain. Reject hits about a different suffix (Pvt Ltd vs Ltd vs LLP), a different city, or a different promoter unless an alias is already verified.

## Completion

Each kept fact has an evidence record. Unresolved identity stays unresolved. Do not pick the best-known company with a similar name.

## Source boundaries

MCA extracts, rating reports, and the company site outrank LinkedIn, Tofler teasers, Tracxn cards, and news. If only a teaser is available, confidence is `low` and the field stays qualified ("directory lists…", not "the company is…").

Full source notes: `references/india-sources.md`.
