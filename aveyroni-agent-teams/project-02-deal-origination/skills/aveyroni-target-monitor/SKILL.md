---
name: aveyroni-target-monitor
description: "Use when watching priority targets for a new sourced change."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [monitoring, alerts, origination]
    related_skills: [tavily, aveyroni-fit-score, aveyroni-transaction-status]
---

# Target monitor

Re-check companies already on the priority list. Do not rediscover the universe on a monitoring run.

## Watchlist

For each company, search the legal name since the last run date for: director or promoter change, fundraise, debt issue, plant expansion, acquisition, new geography, management hire, strategic review, adviser appointment, customer win or loss, and a competitor transaction in the same niche.

## Alert rule

Write an alert only when a new evidence record supports one of those events. The alert contains the company id, the event, the evidence id, and whether fit or transaction status must be recomputed.

No alert for: repeated articles about a known fact, founder age, "still founder-owned", or a search that returned nothing. A quiet week produces a one-line "no material change" for that company, not a signal.

## Re-score

Re-run only the skills the event touches. A plant expansion can update the company profile. An acquisition of the company sets transaction status to `RECENTLY_ACQUIRED` and can fail the ownership check.

Done when every priority company is either alerted with evidence or marked unchanged, and recomputed scores replace the old ones instead of sitting beside them.
## Inputs

A prior run file for a mandate and the list of targets already screened.

## Outputs

A change note per target, or an explicit no-change. A meaningful sourced change can ask for a new fit pass. It does not silently rewrite the old score.

## Workflow

1. Read the last orchestrator run.
2. Check the same sources for director, ownership, process, or size changes.
3. Write the alert with the new excerpt, or write that nothing sourced changed.

## Rules

Do not raise an alert from memory. Do not contact the company.

## Failure conditions

No alert when the new page fails to load or the excerpt does not show a change. Do not monitor a target that was never sourced.

## Examples

Last run said no public process. A new page says "Active listing". The alert updates transaction status. Format example only.
