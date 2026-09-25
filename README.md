# Hermes Agent Teams — Portfolio

Multi-agent orchestration built on [Hermes](https://github.com/anthropics/hermes-agent), applied to real buy-side workflows. Each project is a team of purpose-built agents — some run inside a single Hermes turn, some are deterministic code with no model call, some are delegated workers spawned for one research pass — coordinated by an orchestrator that enforces the rules a real investment team would insist on.

## Flagship: Deal Origination

**[`aveyroni-agent-teams/project-02-deal-origination`](aveyroni-agent-teams/project-02-deal-origination)** — an AI origination desk that takes one buy-side mandate (an operating-company buy box or a real-estate buy box) and continuously discovers, verifies, scores, and monitors acquisition targets from public sources.

This is the project to demo. It is a working system, not a mockup:

- **23 passing unit tests** covering the deterministic scoring, deduplication, delegation, and MCA-registry rules (`python3 -m unittest orchestrator.test_orchestrator orchestrator.test_mca_registry`)
- **Two real completed runs on real companies** — an India auto-components mandate (Triton Valves, Rolex Rings, Kiswok Industries, and others, each with FY revenue, ownership, and export facts pulled from investor decks and rating-agency reports) and an Austin, Texas value-add multifamily/single-family mandate
- **A polished chat desk UI** (`chat/`) where a buyer states a mandate, clicks **Run team**, and watches the agent trace live: controller → discovery → specialist research → fit scoring → evidence red-team → saved run
- **20 Hermes skills** (proprietary + adapted open-source), each with a machine-checkable contract (`evals/check.py`)
- **A structured-data discovery source, not just web search**: for India operating-company mandates, discovery can query the 852K-row MCA company registry directly (`orchestrator/mca_registry.py`) instead of relying only on what a search engine surfaces — deterministic, sourced, and it degrades to web search automatically when unconfigured

Read `project-02-deal-origination/README.md` for the architecture, and `project-02-deal-origination/DEMO.md` for the client walkthrough script.

## Why this is a harder problem than "AI web search"

Off-market deal sourcing fails when the AI quietly turns "no evidence of a sale process" into "this company is for sale," or turns "founder-owned for 40 years" into "the owner probably wants to sell." Aveyroni's agents are built specifically to not do that:

- **Mandate fit**, **transaction status**, and **seller interest** are three separate fields, scored by three different mechanisms, and no agent is allowed to collapse them into one number.
- Every claim needs a source URL and an excerpt, or it is dropped by deterministic code before it ever reaches a scoring model — not by asking the model to "be careful." That rule applies identically whether the claim came from a web page or a government registry row.
- `NO_PUBLIC_PROCESS_FOUND` is explicitly not proof a company is off-market, and the code (not the prompt) blocks a screening record from claiming otherwise (`validate_screening` in `orchestrator/deterministic.py`).
- Seller interest stays `unknown` until an excerpt quotes the owner or a mandated adviser — founder ownership, long tenure, and company age are explicitly not signals.
- A company's legal structure (Private/Public) is a registration fact, not an ownership fact — MNC subsidiaries and PE-portfolio companies register as Private too, so the MCA registry pre-filter never asserts ownership itself; the web ownership-researcher still verifies it on every name.
- An Evidence Reviewer agent red-teams the package afterward and cannot override any of the above; it can only flag contradictions.

## Repository layout

```
aveyroni-agent-teams/
  project-02-deal-origination/   ← flagship demo (see above)
  shared/                        ← skills shared across future projects
    research/, evidence/, tavily/, company-intelligence/
```

## Requirements to run live

The desk runs on a local [Hermes](https://github.com/anthropics/hermes-agent) install (`~/.hermes/hermes-agent`) with API credentials for the configured model provider plus Exa (search) and Firecrawl (page extraction). Without those, the codebase is still fully reviewable: the deterministic pipeline, the 23 unit tests, and the three saved runs under `runs/` demonstrate the system end to end without any live calls. The MCA registry pre-filter needs its own Supabase credentials (optional — see the project README) and falls back to web discovery when unset.
