---
name: web-extract
description: "Use when a sourced claim needs an excerpt from a page."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [web-extract, tavily, evidence, origination]
    related_skills: [web-search, tavily, aveyroni-evidence-auditor]
---

# Web extract

Adapted from Tavily's `tavily-extract` skill. Upstream: https://github.com/tavily-ai/skills. This file does not copy Tavily's source. Call the Tavily MCP tool `tavily_extract` on a URL that search already returned.

## Inputs

One `http` or `https` URL from `web-search`, plus the field you are trying to support.

## Outputs

An excerpt copied from that page, the URL, and the field it supports. No excerpt, no claim.

## Workflow

1. Extract the page.
2. Copy the shortest sentence that supports the field.
3. If the page does not say it, leave the field unknown.
4. Pass the excerpt, URL, and field to the worker JSON. Do not paraphrase a number.

## Rules

A listing page can support transaction status. Founder or family wording supports ownership only. Do not contact anyone.

## Failure conditions

Stop on a non-http URL, a failed extract, a login wall, or a page that does not contain the fact. Do not fill the gap from memory.

## Examples

URL returns "Active listing" for a 24-unit property. Claim field `transaction_status`, value `active listing`, excerpt `Active listing`.

Format example only. Not a researched target.
