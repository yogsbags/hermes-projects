---
name: web-search
description: "Use when origination needs a web search and a source URL."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [web-search, tavily, origination]
    related_skills: [web-extract, deep-research, tavily, deal-sourcing]
---

# Web search

Adapted from Tavily's `tavily-search` skill. Upstream: https://github.com/tavily-ai/skills. This file does not copy Tavily's source. It chooses when to search and what to keep. Call the Tavily MCP tool `tavily_search` when it is in the session. Do not shell out to `tvly` when that tool exists.

## Inputs

A buy-box query: geography, sector or asset type, and the fact you still need. Not a company name you invented.

## Outputs

Search hits with title, URL, and snippet. A hit is not a claim until `web-extract` quotes the page.

## Workflow

1. Write the query from the buy box and the missing fact.
2. Call `tavily_search`.
3. Keep hits whose snippet matches the geography and the sector or asset type.
4. Hand the URL to `web-extract` before anyone uses a number, an owner, or a sale status.

## Rules

Do not estimate revenue or ownership from a snippet. Do not contact anyone. A directory row is a lead, not identity.

## Failure conditions

Stop when the tool errors, the query is empty, or every hit is outside the buy box. Return no entities rather than a guessed name.

## Examples

Query: `Austin multi-family 10 to 80 units for sale`. Keep a hit only when the snippet names Austin and a unit count or a listing. Drop a hit for an office tower.

Format example only. Not a researched target.
