---
name: deep-research
description: "Use when a named target needs a multi-page pass after the user approves it."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [deep-research, tavily, origination]
    related_skills: [web-search, web-extract, tavily, aveyroni-evidence-auditor]
---

# Deep research

Adapted from Tavily's `tavily-research` skill. Upstream: https://github.com/tavily-ai/skills. This file does not copy Tavily's source. Call the Tavily MCP tool `tavily_research` only after the user approves a longer pass on targets already named from sources.

## Inputs

One or more target names that already appear in the run, the buy box, and the questions still open. Not a fresh universe.

## Outputs

A sourced note per open question: URL, excerpt, and field. Unknown stays unknown. The note does not set fit; fit calculation does.

## Workflow

1. Confirm the user approved this pass.
2. List the open questions: identity, ownership, size, transaction status, and relationships.
3. Call `tavily_research` or a series of `web-search` plus `web-extract` steps.
4. Return worker JSON. Drop any statement without an excerpt.

## Rules

Do not add names to hit a funnel count. Do not treat a listing as owner intent. No public process found is not proof the target is off-market. Do not contact anyone.

## Failure conditions

Stop if the user has not approved the pass, if no target has been named yet, or if the research tool fails. Say what is still unknown.

## Examples

Approved follow-up on a company already in the run: extract the rating-report revenue line and the ownership sentence. Leave EBITDA unknown if the page has no EBITDA line.

Format example only. Not a researched target.
