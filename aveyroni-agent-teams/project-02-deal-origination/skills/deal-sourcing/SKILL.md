---
name: deal-sourcing
description: "Use when discovering companies for a proprietary buy-side mandate."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [deal-sourcing, market-map, candidates, origination]
    related_skills: [aveyroni-mandate, tavily, research, aveyroni-entity-resolver]
---

# Deal sourcing

Adapted from Anthropic's `deal-sourcing` skill in [anthropics/financial-services](https://github.com/anthropics/financial-services/blob/main/plugins/vertical-plugins/private-equity/skills/deal-sourcing/SKILL.md). The upstream skill discovers companies, checks a CRM, and drafts founder email. This version stops at a sourced candidate universe for an off-market mandate. Outreach is `aveyroni-relationship-map`, and only after the user asks.

## Inputs

A buy-box from `aveyroni-mandate`. If `mandate.json` is missing, run that skill first. Do not interview the user again for sector and revenue.

## Market map

1. Split the sector into subsectors the buy-box can actually screen. Keep only slices the mandate's products imply.
2. Identify relevant industrial clusters and company registries for the mandate geography. Use `research/references/india-sources.md` only for India; for every other geography, use that jurisdiction's registry, trade associations, and local terminology. A cluster is a search space, not evidence a company operates there.
3. Write geography-specific queries: registry and association directories, filing or credit-report phrases, customer supplier lists, export awards, and `"<subsector>" "<city or region>" manufacturer`.

Done when `market-map.md` has subsectors, clusters, and the query list.

## Discovery

1. Run `tavily` search per query. Save raw JSON under `runs/<mandate_id>/raw/`.
2. Keep a company when the snippet shows a manufacturer in the buy-box geography and sector. Record name, url, city if present, and why it was kept.
3. Deduplicate by domain. Similar names with different domains stay as separate candidates until entity resolution.
4. Do not estimate revenue or ownership in this skill. Do not drop a company for "probably PE-backed" or "probably too small".

The demo funnel (150 → 80 → 45 → 20 → 10 → 5) is a capacity target, not quotas. Never add weak names to reach a count, and never hide a sourced candidate to make the funnel look selective.

## Output

`candidates.jsonl`, one object per line: `candidate_id`, `name_as_found`, `url`, `query`, `snippet`, `source_url`. CRM or prior-contact status is `unknown` until someone checks Aveyroni's notes. Do not draft emails.

## Completion

Every row traces to a query and a URL. The market map and the candidate file are consistent. Identity, ownership, and fit have not been claimed.
## Inputs

A buy box from aveyroni-mandate. Sector or asset type, geography, and the open questions. Not a revenue guess.

## Outputs

candidates.jsonl rows with name_as_found, url, query, snippet, and source_url. Market map of subsectors and queries. No fit score and no emails.

## Workflow

1. Split the buy box into searchable slices.
2. Run web-search. Keep a hit only when the snippet matches geography and sector or asset type.
3. Deduplicate by domain. Leave similar names with different domains for entity resolution.

## Rules

Funnel counts are capacity targets, not quotas. Do not add weak names to reach 150. Do not drop a name for "probably too small" or "probably PE-backed".

## Failure conditions

Stop the slice when search fails. An empty candidate file is valid. Do not invent companies to fill it.

## Examples

A query for auto-component manufacturers in the mandate geography returns a filing or company URL. Keep the name and URL. Leave revenue blank. Format example only.
