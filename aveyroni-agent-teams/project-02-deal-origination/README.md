# Project 02 — Aveyroni AI Deal Origination Team

Take one buy-side investment mandate and continuously discover, verify, score, and monitor off-market acquisition targets.

Skills are in `skills/` and `../../shared/`. Check them with `python3 evals/check.py`. Link them into Hermes with `sh scripts/install-hermes-skills.sh`, then start a new Hermes session and run `origination-controller` on `examples/india-auto-components/mandate.json`. The ABC target card in that folder is a format sample, not a researched company.

Target users: PE funds, family offices, independent sponsors, corporate development teams.

## Run the desk

```sh
python3 evals/check.py                                                    # skill contracts, ~instant
python3 -m unittest orchestrator.test_orchestrator orchestrator.test_mca_registry   # 31 deterministic-pipeline tests
python3 -m unittest chat.test_server                                      # 17 desk-server tests (tool-result formatting, mandate registry)
sh scripts/install-hermes-skills.sh                                       # symlink skills into ~/.hermes/skills
PORT=8791 ~/.hermes/hermes-agent/.venv/bin/python chat/server.py          # http://127.0.0.1:8791 -- use the Hermes venv's python, not a bare python3
```

`chat/server.py` keeps one Hermes agent alive for the page session. `chat/desk-config.json` is the currently saved buy box (defaults to the India auto-components mandate below). **Run team** in the UI drives `orchestrator/service.py`; typing in the composer is a normal conversational turn against the same agent and skills, for follow-up questions on what the team already found.

Presenting this to a client? Use **[`DEMO.md`](DEMO.md)** — a scripted walkthrough with a zero-cost replay path using the saved runs below, so a live search hiccup never derails the meeting.

## Three layers

1. Open-source skills — Tavily research and Anthropic Financial Services. Fork and adapt. Normalize every imported `SKILL.md` to Hermes frontmatter before discovery.
2. Aveyroni proprietary skills — Indian identity, ownership, transaction status, buy-box, scoring, evidence, relationships, monitoring.
3. Aveyroni data connectors — the India MCA company registry is live (see below). Other connectors, where legally available, stay for later: annual reports, rating reports, exchange filings, trade associations, import/export evidence, management information, news, and transaction databases.

No public process found is not proof the company is off-market.

## MCA registry pre-filter (optional, India operating-company mandates)

**Currently disabled** — the credentials are commented out in `~/.hermes/.env`. Re-enable by uncommenting `AVEYRONI_MCA_SUPABASE_URL` / `AVEYRONI_MCA_SUPABASE_KEY` once you're satisfied with the candidate-selection fix below on a live pull.

`orchestrator/mca_registry.py` is a deterministic (no model call) discovery source: it queries `mca_companies_enriched` in a Supabase project — the 852K-row India MCA Company Master (data.gov.in resource `4dbe5667-7b6b-41d7-82af-211562424d9a`), built and maintained by the sibling Syndiq project, not by this one. When configured, it replaces the web-search **Company Researcher** for the discovery step only: it names candidates by NIC code / geography / legal class (excluding likely shells and already-excluded profiles), and every claim it produces still needs a source and an excerpt to survive `evidence_normalize`, exactly like a web claim. `business_model`, a precise revenue figure, real ownership, and transaction status are **not** in the registry — those fields land in `unknowns`, which means the existing gap-pass automatically sends the web specialists after every DB-surfaced name, same as today. This is what "DB first, web search only on names the DB surfaced" means in practice — no change to the rest of the pipeline was needed for it.

Candidates come back sorted by `company_age_years` descending, capped at 12. **Not** sorted by paid-up capital — a real live run on the first version of this (sorted by `paidup_crores` descending, limit 30) rejected **30 of 30** candidates on ownership, because a company's paid-up capital mostly reflects how much its owner injected, and a wholly-owned MNC subsidiary gets capitalized heavily by its foreign parent. That sort put Parker Hannifin India, Vitesco Technologies India, Siemens Energy, CNH Industrial, Danfoss, and Yaskawa as the literal first six candidates for a founder/family-owned mandate — every one correctly rejected with a cited ownership record, but a wasted, bad-looking pass. Sorting by company age instead is a real improvement (a live re-check turned up 11 plausible long-standing Indian engineering firms out of 12, paid-up capital mostly single digits to low double digits in crore) but **not a guarantee** — the same check surfaced Sandvik Coromant India (a real Swedish industrial group's 66-year-old subsidiary) in the new list too. Age is a weaker, less systematically-biased heuristic than capital, not a solved problem. The web `aveyroni-ownership` researcher verifying every named candidate remains the only real safeguard either way; this only changes which candidates it spends its research budget on first, and how much of that budget is wasted on obvious MNC subsidiaries.

Two more honest limits, worth saying to a client before they ask:
- **NIC classification is self-declared at registration** and coarse (registry `industrial_classification` buckets are broad, e.g. "Manufacturing (Machinery and Equipments)" covers far more than auto components) — it's a candidate pre-filter, not proof of what a company actually makes today.
- **`company_class = Private` is a legal-structure fact, not an ownership fact.** MNC subsidiaries and PE-portfolio companies register as Private too. The registry never writes an `ownership` claim; `aveyroni-ownership`'s web research is still the only thing allowed to say who actually owns a company.

### Investigated and ruled out: is there a better ownership pre-filter hiding in this data?

Checked every angle across the free registry, Syndiq's computed flags, and the raw paid-enrichment payload before settling on the age sort above:
- `company_origin` ("Indian/Foreign Company") describes where the *entity* is incorporated, not who owns it — verified against Parker Hannifin India directly: reads `"India"` despite being a 100%-US-owned subsidiary.
- `pe_tier` / `tier3_clean_bootstrap` needs the paid Tofler/foxlabs enrichment, which covers ~3% of companies (907 of 29,650 in the live project) — too thin to lean on today.
- The raw foxlabs payload was inspected field-by-field live: `directors`, `charges`, `balanceSheet`, `subsidiaries` (companies it owns), `operatingRevenueRange` — **no shareholding pattern, no promoter field, no parent-company field anywhere in this pipeline.** Genuine ownership data isn't in this dataset at any tier; it only exists in an actual filing, an LEI record, or a company's own investor material — which is exactly the job `aveyroni-ownership`'s web research already does.

**One real, validated signal that came out of this, not yet built:** when paid enrichment *is* present, a **majority of the board sharing a surname** (via the `directors` JSONB, last name token) correlates with genuine family ownership — real examples from a live query: `AGARWAL x4/5` (patriarch "Ghanshyam Das Agarwal" + sons + one outside professional), `NAYAK x4/4`, `BHARDWAJ x3/3`. The trap: naive "any two directors share a surname" is unreliable — 40% of matches in a live sample were common surnames (Singh, Kumar, Shah, Rao) shared by clearly unrelated directors on mixed boards, e.g. `KUMAR x2/6` on a board of six otherwise-unrelated names. **The signal only holds at a majority-of-the-board ratio, not a bare pair match.** Same 3%-coverage ceiling as `pe_tier`, so it's a future refinement, not a current fix — if built, it must stay a candidate-ranking nudge only, never written as an `ownership` claim (no source URL, no excerpt — it would violate the evidence rule that governs every other claim in this system).

Enable it by adding to `~/.hermes/.env` (same file `chat/server.py` already loads):

```
AVEYRONI_MCA_SUPABASE_URL=https://<project-ref>.supabase.co
AVEYRONI_MCA_SUPABASE_KEY=<a key with SELECT on mca_companies_enriched>
```

Use a scoped read-only role, not a project's `service_role` key, once this runs anywhere less trusted than a local demo machine — `scripts/mca_readonly_role.sql` has the grant statements. Unset or missing credentials just mean `applies()` returns `False` and the pipeline falls back to web discovery; nothing else changes and nothing breaks for a reviewer who has never heard of the other project.

## Hermes shape

Hermes is the execution runtime. The Aveyroni orchestrator in `orchestrator/` controls it. Capabilities are not permanent profiles.

Orchestrating agents: Origination Controller, Research Coordinator, Evidence Reviewer. The controller and the reviewer are Hermes turns. The coordinator is the service calling `delegate_task`.

Delegated research workers, spawned for one pass. The company researcher finds the names — or, for a configured India operating-company mandate, the MCA registry query does (see above), deterministically. Ownership, financial, and transaction then cover that list, at most three at once. A gap pass fills any dossier field that is still empty and was not reported as unknown. The fit scorer runs before the relationship worker. That worker does one search per company and does not open a page when the snippet already names a person and a role. They use web_search and web_extract (Exa and Firecrawl). They do not delegate again.

The Fit Scorer is a Hermes turn. It reads the excerpts and marks each mandatory check. Code publishes the label from that checklist.

Deterministic code, with no model call: mandate parsing, entity normalization, evidence normalization, deduplication, data validation, the MCA-registry query, and the run file under `runs/<mandate_id>/orchestrator-run.json`.

The desk button **Run team** starts that pass on the saved buy box. Chat still works for a follow-up. Nothing is sent.

`dd-checklist`, `dd-meeting-prep`, `ic-memo`, `returns-analysis`, and `portfolio-monitoring` stay out of discovery. They run only after a buyer wants to go deeper on a shortlisted target.

## Scores stay separate

- Mandate fit — does the company match the buyer?
- Transaction status — PE-backed, marketed, acquired, fundraising, or no public process found?

## First working version

Enough to run the India auto-components mandate end to end:

- Tavily research (`tavily-search`, `tavily-extract`, `tavily-map`, `tavily-crawl`, `tavily-research`)
- Adapted `deal-sourcing` and `deal-screening`
- Five proprietary skills: `aveyroni-mandate`, `aveyroni-entity-resolver`, `aveyroni-ownership`, `aveyroni-transaction-status`, `aveyroni-evidence-auditor`
- The MCA registry pre-filter above, as a deterministic alternative to web discovery for India mandates

Also in this tree: `aveyroni-fit-score`, `aveyroni-relationship-map`, `aveyroni-target-monitor`, `comps-analysis`, `web-search`, `web-extract`, and `deep-research`. `ai-readiness` and `value-creation-plan` stay out of discovery.

## Demo

Two saved runs demonstrate the full pipeline end to end, on two different buy-box shapes, without any live model or search call:

- **`runs/india-auto-components/`** — the most recent orchestrator pass on the mandate below (`orchestrator-run.json`, `screening.jsonl`), plus **`runs/india-auto-components-001/`**, an earlier pass with the full deliverable set: `mandate-dashboard.md`, `market-map.md`, `weekly-signal-brief.md`, and per-company deep profiles in `profiles/` (Triton Valves, Kiswok Industries, Punch Ratna Fasteners) with real revenue, ownership, and export citations.
- **`runs/austin-housing/`** — the same orchestrator on a real-estate buy box (Austin, TX; multi-family and single-family; USD 2–30M; value-add), proving the engine is not hardcoded to one vertical.

Mandate: founder/family-owned Indian auto-component manufacturers, estimated ₹300–1,500 crore revenue, Tier-1/OEM supply, export capability, niche manufacturing, no known institutional PE ownership, room for operational and export value creation.

Funnel targets, not promised results: 150 discovered → 80 identity-verified → 45 mandate-fit → 20 high-fit → 10 priority → 5 deeply researched.

Portfolio artifacts: Mandate Dashboard, Market Map, Target Universe, Deep Target Profile, Weekly Signal Brief.

Example buy-box: `examples/india-auto-components/mandate.json`.

See **[`DEMO.md`](DEMO.md)** for the scripted client walkthrough of both runs and of a live pass.

## Skill manifest

| Capability | Skill | Source | Decision |
| --- | --- | --- | --- |
| Web search | tavily-search | Tavily | Reuse |
| Webpage extraction | tavily-extract | Tavily | Reuse |
| Website discovery | tavily-map | Tavily | Reuse |
| Website crawling | tavily-crawl | Tavily | Reuse |
| Deep research | tavily-research | Tavily | Reuse |
| Large-result filtering | tavily-dynamic-search | Tavily | Reuse |
| Deal sourcing | deal-sourcing | Anthropic Financial Services | Adapt |
| Deal screening | deal-screening | Anthropic Financial Services | Adapt |
| DD planning | dd-checklist | Anthropic Financial Services | Reuse later |
| DD meeting prep | dd-meeting-prep | Anthropic Financial Services | Reuse later |
| IC memo | ic-memo | Anthropic Financial Services | Reuse later |
| Returns | returns-analysis | Anthropic Financial Services | Reuse later |
| Portfolio monitoring | portfolio-monitoring | Anthropic Financial Services | Reuse later |
| AI value creation | ai-readiness | Anthropic Financial Services | Adapt later |
| Value creation plan | value-creation-plan | Anthropic Financial Services | Adapt later |
| Comparable companies | comps-analysis | Anthropic Financial Services | Adapt later |
| Mandate normalization | aveyroni-mandate | Aveyroni | Build |
| Entity resolution | aveyroni-entity-resolver | Aveyroni | Build |
| Ownership verification | aveyroni-ownership | Aveyroni | Build |
| Transaction status | aveyroni-transaction-status | Aveyroni | Build |
| Mandate fit | aveyroni-fit-score | Aveyroni | Build |
| Evidence audit | aveyroni-evidence-auditor | Aveyroni | Build |
| Relationship mapping | aveyroni-relationship-map | Aveyroni | Build |
| Origination monitoring | aveyroni-target-monitor | Aveyroni | Build |
| India company registry discovery | mca-registry (`orchestrator/mca_registry.py`) | data.gov.in via Syndiq's Supabase | Build |

Sources: [anthropics/financial-services](https://github.com/anthropics/financial-services), [tavily-ai/skills](https://github.com/tavily-ai/skills).

The adapted skills already have Hermes frontmatter. Link them with `sh scripts/install-hermes-skills.sh`. A Hermes session that is already open does not see new skills until it is restarted. The desk loads them on its own restart.

## Pipeline

```
mandate
  → aveyroni-mandate
  → deal-sourcing + Tavily   (or the MCA registry query, deterministic, for a configured India mandate)
  → candidates
  → aveyroni-entity-resolver
  → aveyroni-ownership
  → aveyroni-transaction-status
  → deal-screening
  → aveyroni-fit-score
  → company research + comps
  → aveyroni-evidence-auditor
  → red team
  → priority list
  → aveyroni-relationship-map
  → outreach brief
  → human review
  → aveyroni-target-monitor
```

Monitoring watches priority companies for director changes, fundraises, plant expansion, promoter changes, debt, succession, acquisitions, new geography, management hires, strategic reviews, and competitor transactions. A meaningful change re-scores the company and alerts the investor.

Project 01 (RFQ-to-order) is the value-creation playbook that can follow a shortlisted manufacturer. It has not been started yet.
