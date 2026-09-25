# Client demo script

A 10–15 minute walkthrough of the Aveyroni origination desk. Two paths: **live** (the team actually researches, costs a few minutes and some API spend) and **replay** (walk through a saved run, zero cost, zero risk of a flaky search call mid-meeting). Default to replay for a first client meeting; offer live once they ask "is this really searching right now?"

## 0. Before the call

```sh
cd aveyroni-agent-teams/project-02-deal-origination
python3 evals/check.py                                                    # sanity: skill contracts are intact
python3 -m unittest orchestrator.test_orchestrator orchestrator.test_mca_registry   # sanity: 31/31 pass
python3 -m unittest chat.test_server                                      # sanity: 17/17 pass
sh scripts/install-hermes-skills.sh                  # link skills into ~/.hermes/skills
PORT=8791 ~/.hermes/hermes-agent/.venv/bin/python chat/server.py   # start the desk -- use the Hermes venv's python, not a bare python3 (needs pyyaml + the Hermes CLI deps)
```

Open `http://127.0.0.1:8791`. The desk boots with the India auto-components mandate already saved (`chat/desk-config.json`) — geography, sector, revenue band, ownership all visible in the workspace panel — but the **Companies** section and the chat thread are deliberately empty (*"None yet. A company appears here after the team finds it in a public source."*), and the left rail shows only Mandates, nothing else. This is intentional: the desk never auto-loads a prior run or a static agent roster into the live UI, specifically so a viewer sees nothing until they click **Run team** and watch the real multi-agent trace, the live per-worker tool-call streaming, and the company results all arrive for the first time, in front of them. (The real last run's data still exists — `runs/india-auto-components/orchestrator-run.json`, or `curl localhost:8791/api/targets` — for the replay path in §5, or to prove none of this is a mockup if someone asks.)

Haven't got the desk running yet, or just want to see it first? `docs/screenshots/` has real screenshots of every state below (clean idle state, the "How the team works" card, a live run's parallel worker batch mid-flight, and a completed run) — captured from this exact page, not mockups.

## 1. Frame the problem (2 min, no screen needed)

Say this before touching the keyboard:

> A buy-side mandate says: founder-owned Indian auto-component manufacturers, ₹300–1,500 crore revenue, Tier-1/OEM supply, exports, no institutional PE already in the cap table. A junior analyst spends two weeks on this. The two failure modes are (1) missing real targets, and (2) quietly overclaiming — turning "no news of a sale" into "this is off-market and available," or "the founder is 70" into "the founder wants to sell." Both failure modes get an associate fired. This system is built to make both structurally hard to do by accident.

## 2. Show the mandate (workspace panel, right side)

Point at the **Workspace** panel: geography, sector, revenue band, ownership filter. Click **Edit** to show it's a real form, not a static card, then **Cancel** to leave the saved mandate untouched.

If someone asks "who's actually going to do this?" before you click anything, click **How the team works** in the composer toolbar — a card lists all 12 agents with the same color legend the live trace uses (brass = Hermes model turn, blue = delegated worker, teal = the MCA registry, gray = deterministic code with no model call). Otherwise skip it — letting the live trace introduce each agent as it actually runs is the stronger moment; don't spend it early.

## 3. Run the team (live path)

Click **Run team** → **Approve**. The **Agent trace** card streams the whole story in the center thread, live:

1. A color legend at the top, then one row per deterministic/orchestrator step, and — for a parallel batch — a grouped row ("Research Coordinator — dispatching 3 workers in parallel") with each worker as its own chip. Watch "Ownership Researcher," "Financial Researcher," and "Transaction Researcher" run **simultaneously** — the clearest "this is not one model talking to itself" moment in the demo.
2. **Inside each worker's chip, live tool calls stream in as they happen** — real lines like "Execute code: from hermes_tools import web_search…" and "Skill view: aveyroni-ownership" appear under the worker's name while it's running, then the feed collapses to a clean `Ownership Researcher · 30` the moment that worker reports back. This is the same live tool-call visibility Claude Code shows for delegated sub-agents — it's real: `orchestrator/service.py` bridges Hermes' `delegate_task` progress callback (`tools/delegate_tool.py`) straight into the SSE stream, so nothing here is simulated.
3. **Every step and every parallel batch shows how long it actually took** — "Fit Scorer — Judged the excerpts · 8s", "Research Coordinator — 3 workers reported back · 41s" — timed client-side from the real start/done events as they stream in, the same "10 seconds," "3 seconds" labels Claude's own UI shows per action.
4. **The whole trace card auto-collapses to one terse line the moment the run finishes** — "▸ Agent trace · 14 steps · 5 workers delegated · Registry-backed discovery · 4m 12s" (now including the total run time) — the same pattern Claude's own tool-use UI uses: expanded and detailed while it's live and worth watching, collapsed once it's not, so the actual answer below it (the company report) reads as the prominent result instead of competing with a permanently-open technical log. Click the chevron any time to re-expand and review exactly what happened, including every step's timing.

If a company name appears in two separate batches in one run (e.g. Ownership Researcher gets a fill pass, then later a gap-fill pass for the same field on a different name), the live feed correctly follows the *currently running* instance of that worker, not a stale finished one from earlier in the run.

Narrate the trace as it streams:

| Trace row | What's actually happening | Why it matters to a buyer |
|---|---|---|
| Origination Controller | One Hermes turn, tools off, reads the buy box | Frames the constraint before any search starts |
| MCA Registry query *(if configured)* / Company Researcher (delegate) | A deterministic SQL pre-filter against India's 852K-row MCA company registry — geography, NIC-derived sector, legal class, active status — or, if not configured, a spawned worker doing `web_search`/`web_extract` discovery | Either way, isolated from the buy box's other fields — it only names candidates. The registry path is faster, more complete for India, and free of search-ranking bias; it still can't tell you what a company makes today or who really owns it |
| Ownership / Financial / Transaction researchers | Up to 3 parallel workers, one field each, researching **only** the names the previous step surfaced | No single agent both finds a company and decides it's a fit — true whether discovery came from the registry or the web |
| Entity normalize / Deduplication | Deterministic code, zero model calls | Same company found two different ways doesn't become two rows |
| Fit Scorer | One Hermes turn, judges pre-collected excerpts only | Cannot search — it can only say pass/fail/unknown on evidence already gathered |
| Data validation | Deterministic code | Physically cannot let a company score `MANDATE_FIT` while a mandatory check is unknown — see `validate_screening()` |
| Evidence Reviewer | Red-teams the finished package | Cannot change the score — can only flag what's weak |

When it finishes, click into a company card. Point out the separate **fit** and **transaction status** lines, including the off-market caveat.

If someone asks "where did that name come from?" on a registry-sourced company, open its claims: the source is `api.data.gov.in`, the excerpt is the literal MCA registration facts (status, class, NIC code, CIN), and it explicitly says the NIC classification is self-declared, not verified. That transparency — showing exactly which fields came from a government registry versus a web page versus nothing yet — is the point.

## 4. Replay path (if not running live)

Open `runs/india-auto-components-001/profiles/triton-valves.md` and read the **Transaction status** section aloud — real citations, real caveats, and a red-team note about verifying current shareholding before prioritization. This is the deep-dive artifact a shortlisted target gets.

Also open `runs/austin-housing/mandate-dashboard.md` to show the same engine running a completely different asset class — real estate, not operating companies — off the same orchestrator, same evidence discipline, different buy-box schema. This is the strongest "this generalizes" moment in the demo.

## 5. Switch verticals live (optional, 3 min)

Click **+ New mandate** → **Edit** → set **Buy box** to *Real estate*, market `Austin, Texas`, asset types `Multi-family` + `Single-family`, price `2,000,000`–`30,000,000` USD, strategy `value-add`. Save. Point out the workspace panel now shows *how the team screens* per asset type — units/occupancy/rent for multifamily, beds/baths/yield for single-family — pulled straight from the buy-box config, not hardcoded per vertical. (The MCA registry pre-filter is India-and-operating-company only — a real-estate mandate always uses web discovery, which is correct and expected.)

## 6. Close

> Everything you saw enforces two rules in code, not in a prompt: a claim without a source and an excerpt is dropped before scoring, and a company can't be marked a fit while a mandatory check is unknown. That's what makes this usable for outreach decisions instead of just another AI summary.

## If something breaks mid-demo

- A worker returns nothing usable → the trace row still shows `done` with a short note; the run continues with fewer names, doesn't crash. Say so and move on.
- Network/API hiccup → fall back to the replay path (§4) without missing a beat.
- MCA registry unreachable → the trace row says so and the run automatically falls back to web discovery for that pass — no crash, no manual intervention needed.
- Someone asks to see the code enforcing a claim → open `orchestrator/deterministic.py`, function `validate_screening`.
