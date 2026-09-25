---
name: comps-analysis
description: "Use when benchmarking a manufacturer against public peers."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [comps, manufacturing, valuation, origination]
    related_skills: [company-intelligence, deal-screening, evidence]
---

# Manufacturing comps

Adapted from Anthropic's `comps-analysis` skill in [anthropics/financial-services](https://github.com/anthropics/financial-services/blob/main/plugins/agent-plugins/market-researcher/skills/comps-analysis/SKILL.md). Upstream builds an institutional trading-comps sheet and prefers market-data MCPs over the web. Use that priority when those sources are connected. This adaptation is for an Indian private manufacturer that will not have a trading multiple of its own.

## When

Run only on a shortlisted company, after identity is resolved. Skip when the user only asked for discovery.

## Peer set

Pick 4 to 6 peers with a similar process and end market. Prefer listed Indian auto-component manufacturers, then global listed peers if the process is specialized. Say why each peer is in the set and why a closer namesake was left out. Mixed conglomerates and pure traders are not peers.

## Metrics

Manufacturing set, from the upstream skill:

- Required: EBITDA margin, asset turnover, capex/revenue.
- Optional: ROA, inventory turns, backlog.
- Do not import SaaS metrics (Rule of 40, net retention) or bank metrics (ROE as the lead metric, efficiency ratio).

Each peer figure is `reported` with source and period, or omitted. Do not fill a blank with the peer median and then treat it as the target's number.

## Target

The private company gets a column only for figures `company-intelligence` already marked reported. Revenue and EBITDA stay `unknown` when unknown. You may show the peer median beside the gap so a reader sees what is missing. Label that column `peer median, not the target`.

## Completion

A table with peers, metrics, periods, sources, and a one-line conclusion of the form "peers cluster at X; the target's figure is unknown" or "the target's reported margin is Y versus peer median Z". No enterprise value for the target unless a source states it.

## Common pitfalls

1. Using the web as the primary number when a filing or rating report is in the file.
2. Applying an EV/EBITDA median to an unknown EBITDA and presenting a valuation.
## Inputs

One shortlisted manufacturer with a resolved identity, plus public peer names the user or a source already supplied.

## Outputs

A comps note: peer, metric, period, URL, and excerpt. The private target's own multiple stays unknown unless it is listed.

## Workflow

1. Run only after identity is resolved and the user wants comps.
2. Take peer metrics from filings or market data, not from a snippet estimate.
3. Label every gap unknown.

## Rules

Do not invent an EV/EBITDA for a private company. Do not use comps to override a failed mandatory check. Upstream preference for market-data tools still applies when those tools are connected.

## Failure conditions

Skip the skill during discovery. Stop when no public peer is sourced. Do not fill a peer multiple from memory.

## Examples

A listed peer's filing states a revenue figure. Record the peer, the figure, the period, and the filing URL. The private target's multiple stays unknown. Format example only.
