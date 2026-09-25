---
name: tavily
description: "Use when origination needs web search, page extract, site map, or crawl."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [tavily, search, extract, crawl, origination]
    related_skills: [research, evidence, deal-sourcing]
---

# Origination web research

Adapted from the Tavily skills (`tavily-search`, `tavily-extract`, `tavily-map`, `tavily-crawl`, `tavily-research`, `tavily-dynamic-search`). Upstream: https://github.com/tavily-ai/skills. If those skills are installed, follow their flag tables. This skill only chooses the primitive and keeps raw payloads out of the mandate file.

Prefer the Tavily MCP tools when they are in the session. Hermes loads them from `https://mcp.tavily.com/mcp/` using `TAVILY_API_KEY` in `~/.hermes/.env` as `Authorization: Bearer`. Call the tool directly. Do not shell out to `tvly` when the MCP tool exists.

| Need | MCP tool | Done when |
| --- | --- | --- |
| No URL yet | `tavily_search` | Each kept hit has title, url, snippet |
| Known URL | `tavily_extract` | Page text, or the URL listed as failed |
| Which page on a known site | `tavily_map`, then `tavily_extract` | A short URL list, then the pages you actually read |
| Many pages on one site | `tavily_crawl` | Chunks returned, limit respected |
| Cited multi-source synthesis | `tavily_research` | Report plus citation URLs |

Use `search_depth` `advanced` for identity, ownership, and transaction checks. Leave `include_raw_content` off until a snippet is worth reading, then extract that URL. Search before research. Research is for a market map or a deep profile, not for checking one fact.

If the MCP tools are absent, fall back to the `tvly` CLI. It reads the same `TAVILY_API_KEY`. If both are missing, stop and say so. Do not browse the open web and pretend it was a Tavily result.

## CLI fallback

| Need | Command |
| --- | --- |
| No URL yet | `tvly search` |
| Known URL | `tvly extract` |
| Which page on a known site | `tvly map`, then `tvly extract` |
| Many pages on one site | `tvly crawl` with `--limit` |
| Cited multi-source synthesis | `tvly research` |
| Large payloads | save with `-o`, then filter |

## Commands

```bash
tvly search "QUERY" --depth advanced --max-results 10 --json -o search.json
tvly extract "https://example.com/page" --extract-depth advanced --json -o page.json
tvly map "https://example.com" --instructions "plants, customers, about, investors" --limit 50 --json
tvly crawl "https://example.com" --instructions "products customers plants exports" --chunks-per-source 3 --limit 20 --json
tvly research "TOPIC" --model pro --json -o research.json
```

Keep queries under 400 characters. One fact per query. `--include-domains` narrows retrieval; still check the hostname of every URL you cite.

## Completion

Write an evidence record for every claim you keep. Discard unused hits. If `failed_results` is non-empty, say which URL failed. Do not fill the gap with an inferred fact.
