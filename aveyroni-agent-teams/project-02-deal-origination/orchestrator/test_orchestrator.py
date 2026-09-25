"""Orchestrator rules that must hold without a model call."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.deterministic import (
    dedupe_entities,
    entity_key,
    normalize_name,
    parse_mandate,
    parse_worker_summary,
    public_targets,
    render_report,
    screen_entities,
)
from orchestrator.roles import WORKERS, gap_plan
from orchestrator.service import Orchestrator

OPERATING = {
    "title": "India Auto Components",
    "focus": "operating-company",
    "geography": ["India"],
    "sector": ["auto components"],
    "ownership": ["founder", "family"],
    "exclude_ownership": ["private_equity"],
    "revenue_min_inr_cr": 300,
    "revenue_max_inr_cr": 1500,
    "asset_types": [],
    "exclude_assets": [],
    "units_min": None,
    "units_max": None,
    "price_min": None,
    "price_max": None,
    "currency": "INR",
    "strategy": "",
}

HOUSING = {
    "title": "Austin Housing",
    "focus": "real-estate",
    "geography": ["Austin"],
    "sector": [],
    "ownership": [],
    "exclude_ownership": [],
    "revenue_min_inr_cr": None,
    "revenue_max_inr_cr": None,
    "asset_types": ["multi-family", "single-family"],
    "exclude_assets": ["office"],
    "units_min": 10,
    "units_max": 80,
    "price_min": None,
    "price_max": None,
    "currency": "USD",
    "strategy": "value-add",
}

VIETNAM_OPERATING = {
    "mandate_id": "vietnam-auto-components",
    "title": "Vietnam Auto Components",
    "focus": "operating-company",
    "geography": ["Vietnam"],
    "sector": ["auto components"],
    "ownership": ["founder", "family"],
    "exclude_ownership": ["private_equity"],
    "revenue_min": 50,
    "revenue_max": 200,
    "revenue_scale": "million",
    "currency": "USD",
}


def _entity(name: str, claims: list[dict], worker: str = "company-researcher") -> dict:
    payload = json.dumps({"entities": [{"name": name, "claims": claims, "unknowns": []}]})
    return parse_worker_summary(payload, worker)["entities"][0]


def _claim(field: str, value, excerpt: str, url: str = "https://example.com/filing") -> dict:
    return {"field": field, "value": value, "source_url": url, "excerpt": excerpt}


def _judgment(entity: dict, results: dict[str, str]) -> dict:
    return {
        entity["entity_id"]: {
            "entity_id": entity["entity_id"],
            "mandatory": [{"check": name, "result": result, "reason": result} for name, result in results.items()],
        }
    }


def _screen(entity: dict, mandate: dict, results: dict[str, str]) -> dict:
    return screen_entities([entity], mandate, _judgment(entity, results))[0]["screening"]


class DeterministicTests(unittest.TestCase):
    def test_non_india_mandate_keeps_its_currency_and_scale(self) -> None:
        mandate = parse_mandate(VIETNAM_OPERATING)
        self.assertEqual(mandate["mandate_id"], "vietnam-auto-components")
        self.assertEqual(mandate["geography"], ["Vietnam"])
        self.assertEqual(mandate["revenue"], {
            "min": 50, "max": 200, "currency": "USD", "scale": "million",
        })

    def test_public_output_only_shows_mandate_fits(self) -> None:
        package = {
            "mandate": parse_mandate(OPERATING),
            "entities": [
                {"name": "Fit Co", "claims": [], "screening": {"fit_label": "MANDATE_FIT", "fit_score": 70, "mandatory": [{"check": "listing_status", "result": "pass"}]}},
                {"name": "Thin Co", "claims": [], "screening": {"fit_label": "INSUFFICIENT_EVIDENCE", "fit_score": None, "mandatory": []}},
                {"name": "Fail Co", "claims": [], "screening": {"fit_label": "FAILS_MANDATORY", "fit_score": None, "mandatory": []}},
            ],
        }
        self.assertEqual([card["name"] for card in public_targets(package)], ["Fit Co"])
        report = render_report(package)
        self.assertIn("Fit Co", report)
        self.assertNotIn("Thin Co", report)
        self.assertNotIn("Fail Co", report)
        self.assertIn("2 other candidates", report)
        self.assertIn("Why it fits", report)
        self.assertIn("Market thesis", report)
        self.assertIn("Seller interest", report)

    def test_public_output_explains_fit_seller_signals_and_thesis(self) -> None:
        entity = {
            "entity_id": "fit-co",
            "name": "Fit Co",
            "claims": [
                _claim("geography", "India; Rajkot, Gujarat", "Plant at Rajkot, Gujarat, India"),
                _claim("sector", "auto components", "Makes auto components"),
                _claim("business_model", "forging for OEMs", "OEM forging plant"),
                _claim("ownership", "family", "A family holds the shares"),
                _claim("listing_status", "unlisted", "The company is privately held and unlisted"),
                _claim("revenue", "₹500–₹1,000 Cr", "Revenue between 500 and 1,000 crore"),
                _claim("signal", "next-generation managing director", "The founder's son is managing director"),
            ],
            "screening": {
                "fit_label": "MANDATE_FIT",
                "fit_score": 70,
                "transaction_status": "NO_PUBLIC_PROCESS_FOUND",
                "mandatory": [
                    {"check": "geography", "result": "pass", "reason": "The excerpt states that the company operates at Rajkot, Gujarat, India."},
                    {"check": "sector", "result": "pass", "reason": "The excerpt supports auto components."},
                    {"check": "ownership", "result": "pass", "reason": "The excerpt describes a family-owned group."},
                    {"check": "listing_status", "result": "pass", "reason": "A sourced claim confirms the company is unlisted or privately held."},
                    {"check": "size", "result": "pass", "reason": "The excerpt reports revenue inside the buy box."},
                    {"check": "business_model", "result": "pass", "reason": "The excerpt supports forging for OEMs."},
                ],
            },
        }
        package = {"mandate": parse_mandate(OPERATING), "entities": [entity]}
        card = public_targets(package)[0]
        report = render_report(package)
        self.assertTrue(card["why"].startswith("Why it fits:"))
        self.assertIn("Rajkot, Gujarat", card["why"])
        self.assertIn("family-owned", card["why"])
        self.assertIn("unlisted", card["why"])
        self.assertTrue(card["thesis"].startswith("Market thesis:"))
        self.assertIn("auto components", card["thesis"])
        self.assertIn("control market", card["thesis"])
        self.assertNotIn("It is forging", card["thesis"])
        self.assertTrue(card["seller"].startswith("Seller interest (signals only):"))
        self.assertIn("next-generation", card["seller"])
        self.assertIn("not proof the owner wants to sell", card["seller"])
        self.assertIn("Rajkot, Gujarat", report)
        self.assertIn("control market", report)
        self.assertIn("next-generation", report)
        self.assertIn("Market thesis", report)
        self.assertNotIn("seller_interest", entity["screening"])

    def test_name_strips_legal_suffix(self) -> None:
        self.assertEqual(normalize_name("Punch Ratna Fasteners Pvt Ltd"), "punch ratna fasteners")
        self.assertEqual(
            entity_key("Punch Ratna Fasteners Pvt Ltd"),
            entity_key("Punch Ratna Fasteners"),
        )

    def test_duplicate_names_merge_claims(self) -> None:
        first = _entity("Punch Ratna Fasteners Pvt Ltd", [_claim("geography", "Pune, India", "Plant in Pune, India")])
        second = _entity(
            "Punch Ratna Fasteners",
            [_claim("ownership", "family", "The Kejriwal family holds the company", "https://example.com/rating")],
            worker="ownership-researcher",
        )
        merged = dedupe_entities([first, second])
        self.assertEqual(len(merged), 1)
        fields = {claim["field"] for claim in merged[0]["claims"]}
        self.assertEqual(fields, {"geography", "ownership"})

    def test_claim_without_excerpt_is_dropped(self) -> None:
        entity = _entity("Example Works", [{"field": "geography", "value": "India", "source_url": "https://example.com/a", "excerpt": ""}])
        merged = dedupe_entities([entity])
        self.assertEqual(merged[0]["claims"], [])

    def test_missing_revenue_leaves_fit_blank(self) -> None:
        entity = dedupe_entities([_entity("Example Works", [
            _claim("geography", "India", "Registered office in India"),
            _claim("sector", "auto components", "Makes auto components"),
            _claim("ownership", "family", "A family holds the shares"),
            _claim("business_model", "manufacturing for OEM", "OEM manufacturing plant"),
        ])])[0]
        screening = _screen(entity, parse_mandate(OPERATING), {
            "geography": "pass",
            "sector": "pass",
            "ownership": "pass",
            "size": "unknown",
            "business_model": "pass",
        })
        self.assertEqual(screening["fit_label"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(screening["fit_score"])
        self.assertTrue(screening["financial_confirmation_required"])

    def test_revenue_outside_band_fails(self) -> None:
        entity = dedupe_entities([_entity("Example Works", [
            _claim("geography", "India", "Registered office in India"),
            _claim("sector", "auto components", "Makes auto components"),
            _claim("ownership", "family", "A family holds the shares"),
            _claim("business_model", "manufacturing for OEM", "OEM manufacturing plant"),
            _claim("revenue_inr_cr", 40, "Revenue was 40 crore"),
        ])])[0]
        screening = _screen(entity, parse_mandate(OPERATING), {
            "geography": "pass",
            "sector": "pass",
            "ownership": "pass",
            "size": "fail",
            "business_model": "pass",
        })
        self.assertEqual(screening["fit_label"], "FAILS_MANDATORY")
        self.assertIsNone(screening["fit_score"])

    def test_complete_operating_company_scores_fit_only(self) -> None:
        entity = dedupe_entities([_entity("Example Works", [
            _claim("geography", "India", "Registered office in India"),
            _claim("sector", "auto components", "Makes auto components"),
            _claim("ownership", "family", "A family holds the shares"),
            _claim("listing_status", "unlisted", "The company is unlisted and privately held"),
            _claim("business_model", "Operating manufacturer supplying OEMs", "GNA caters to major OEMs"),
            _claim("revenue_inr_cr", 548, "Operating income was 548 crore"),
        ])])[0]
        screening = _screen(entity, parse_mandate(OPERATING), {
            "geography": "pass",
            "sector": "pass",
            "ownership": "pass",
            "size": "pass",
            "business_model": "pass",
        })
        self.assertEqual(screening["fit_label"], "MANDATE_FIT")
        self.assertEqual(screening["fit_score"], 70)
        self.assertIn("not proof", screening["transaction_status_note"])
        self.assertIn("off-market", screening["transaction_status_note"])

    def test_publicly_listed_company_fails_even_when_scorer_passes_it(self) -> None:
        entity = dedupe_entities([_entity("Listed Family Co", [
            _claim("listing_status", "listed", "The equity shares are listed on NSE and BSE"),
        ])])[0]
        screening = _screen(entity, parse_mandate(OPERATING), {
            "geography": "pass", "sector": "pass", "ownership": "pass",
            "listing_status": "pass", "size": "pass", "business_model": "pass",
        })
        listing = next(row for row in screening["mandatory"] if row["check"] == "listing_status")
        self.assertEqual(listing["result"], "fail")
        self.assertEqual(screening["fit_label"], "FAILS_MANDATORY")

    def test_private_equity_owner_fails(self) -> None:
        entity = dedupe_entities([_entity("Example Works", [
            _claim("ownership", "private equity", "A private equity fund controls the company"),
        ])])[0]
        row = next(item for item in _screen(entity, parse_mandate(OPERATING), {"ownership": "fail"})["mandatory"] if item["check"] == "ownership")
        self.assertEqual(row["result"], "fail")

    def test_listing_sets_active_transaction_status(self) -> None:
        entity = dedupe_entities([_entity("4314 Gillis", [
            _claim("geography", "Austin", "The property is in Austin"),
            _claim("asset_type", "multi-family", "24-unit multi-family community"),
            _claim("units", 24, "24 units"),
            _claim("transaction_status", "active listing", "Active listing"),
        ])])[0]
        screening = _screen(entity, parse_mandate(HOUSING), {
            "market": "pass",
            "asset_type": "pass",
            "size_units": "pass",
        })
        self.assertEqual(screening["transaction_status"], "ACTIVE_SALE_PROCESS")
        self.assertEqual(screening["fit_label"], "MANDATE_FIT")

    def test_office_asset_fails_housing_box(self) -> None:
        entity = dedupe_entities([_entity("Downtown Tower", [
            _claim("asset_type", "office", "A downtown office tower"),
        ])])[0]
        row = next(item for item in _screen(entity, parse_mandate(HOUSING), {"asset_type": "fail"})["mandatory"] if item["check"] == "asset_type")
        self.assertEqual(row["result"], "fail")

    def test_real_estate_requires_an_asset_type(self) -> None:
        broken = dict(HOUSING)
        broken["asset_types"] = []
        with self.assertRaises(ValueError):
            parse_mandate(broken)


class ServiceTests(unittest.TestCase):
    def test_service_delegates_every_worker_and_ignores_reviewer_overrides(self) -> None:
        calls = []
        order = []

        def complete(role, message):
            order.append(role)
            if role == "controller":
                return json.dumps({"focus_notes": "Stay inside the revenue band."})
            if role == "fit-scorer":
                self.assertIn("manufacturer", message)
                self.assertIn("OEMs", message)
                return json.dumps({"scores": [{
                    "entity_id": "example-works",
                    "mandatory": [
                        {"check": name, "result": "pass", "reason": "The excerpt supports the buy box."}
                        for name in ("geography", "sector", "ownership", "size", "business_model")
                    ],
                }]})
            return "Do not alter deterministic screening fields."

        def delegate(tasks, _agent):
            calls.append(tasks)
            order.append(tasks[0]["goal"].split(".", 1)[0])
            summaries = []
            for task in tasks:
                goal = task["goal"]
                if goal.startswith("Company Researcher"):
                    summaries.append(json.dumps({"entities": [{
                        "name": "Example Works Pvt Ltd",
                        "claims": [
                            _claim("geography", "India", "Registered office in India"),
                            _claim("sector", "auto components", "Makes auto components"),
                            _claim("business_model", "manufacturing for OEM", "OEM manufacturing plant"),
                        ],
                        "unknowns": [],
                    }]}))
                elif goal.startswith("Ownership Researcher"):
                    summaries.append(json.dumps({"entities": [{
                        "name": "Example Works",
                        "claims": [
                            _claim("ownership", "family", "A family holds the shares"),
                            _claim("listing_status", "unlisted", "The company is privately held and unlisted"),
                        ],
                        "unknowns": [],
                    }]}))
                elif goal.startswith("Financial Researcher"):
                    summaries.append(json.dumps({"entities": [{
                        "name": "Example Works Limited",
                        "claims": [_claim("revenue_inr_cr", 548, "Operating income was 548 crore")],
                        "unknowns": [],
                    }]}))
                elif goal.startswith("Transaction Researcher"):
                    summaries.append(json.dumps({"entities": [{
                        "name": "Example Works",
                        "claims": [_claim("transaction_status", "active listing", "Active listing on the broker page")],
                        "unknowns": [],
                    }]}))
                else:
                    summaries.append(json.dumps({"entities": []}))
            return json.dumps({
                "results": [{"task_index": index, "summary": text} for index, text in enumerate(summaries)]
            })

        with tempfile.TemporaryDirectory() as folder:
            events = []
            report = Orchestrator(
                agent=object(),
                on_event=events.append,
                runs_root=Path(folder),
                complete_fn=complete,
                delegate_fn=delegate,
            ).run(OPERATING)
            saved = json.loads((Path(folder) / "india-auto-components" / "orchestrator-run.json").read_text())

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(calls[0]), 1)
        self.assertTrue(calls[0][0]["goal"].startswith("Company Researcher"))
        self.assertIn("web_search and web_extract", calls[0][0]["goal"])
        self.assertIn("Do not call Apify", calls[0][0]["goal"])
        self.assertEqual(len(calls[1]), 3)
        self.assertIn("Example Works", calls[1][0]["context"])
        self.assertIn("Do not add a company", calls[1][0]["context"])
        self.assertEqual([task["goal"].split(".", 1)[0] for task in calls[1]], [
            "Ownership Researcher",
            "Financial Researcher",
            "Transaction Researcher",
        ])
        self.assertEqual(len(calls[2]), 1)
        self.assertIn("Relationship Researcher", calls[2][0]["goal"])
        self.assertIn("do not web_extract", calls[2][0]["context"])
        self.assertIn("Do not write an outreach brief", calls[2][0]["context"])
        self.assertLess(order.index("fit-scorer"), order.index("Relationship Researcher"))
        self.assertIn("A public sale process is underway.", report)
        self.assertNotIn("MANDATE_FIT", report)
        self.assertNotIn("ACTIVE_SALE_PROCESS", report)
        names = [event["tool"]["name"] for event in events if event.get("tool", {}).get("phase") == "start"]
        self.assertIn("delegate_task", names)
        self.assertIn("origination_controller", names)
        self.assertIn("fit_scorer", names)
        self.assertIn("evidence_reviewer", names)
        self.assertEqual({worker["id"] for worker in WORKERS}, {
            "company-researcher",
            "ownership-researcher",
            "financial-researcher",
            "transaction-researcher",
            "relationship-researcher",
        })
        self.assertNotIn("seller_interest", saved["entities"][0]["screening"])
        self.assertEqual(saved["entities"][0]["screening"]["fit_score"], 70)
        self.assertEqual(len(dedupe_entities(screen_entities([], parse_mandate(OPERATING)))), 0)

    def test_gap_plan_skips_a_field_already_listed_unknown(self) -> None:
        entity = _entity("Example Works", [_claim("geography", "India", "Registered office in India")])
        entity["unknowns"] = ["revenue_inr_cr"]
        plan = gap_plan([entity], parse_mandate(OPERATING))
        self.assertEqual(plan["company-researcher"], [("Example Works", ["sector", "business_model"])])
        self.assertEqual(plan["ownership-researcher"], [("Example Works", ["ownership", "listing_status"])])
        self.assertNotIn("financial-researcher", plan)

    def test_thin_discovery_triggers_a_gap_pass_and_drops_extra_names(self) -> None:
        calls = []

        def complete(role, _message):
            if role == "controller":
                return json.dumps({"focus_notes": "Stay inside the revenue band."})
            if role == "fit-scorer":
                return json.dumps({"scores": [{
                    "entity_id": "example-works",
                    "mandatory": [
                        {"check": name, "result": "pass", "reason": "The excerpt supports the buy box."}
                        for name in ("geography", "sector", "ownership", "size", "business_model")
                    ],
                }]})
            return "Do not alter deterministic screening fields."

        def delegate(tasks, _agent):
            calls.append(tasks)
            summaries = []
            for task in tasks:
                goal = task["goal"]
                gap = "Gap pass" in task["context"]
                if goal.startswith("Company Researcher") and gap:
                    summaries.append(json.dumps({"entities": [{
                        "name": "Example Works",
                        "claims": [
                            _claim("sector", "auto components", "Makes auto components"),
                            _claim("business_model", "manufacturing for OEM", "OEM manufacturing plant"),
                        ],
                        "unknowns": [],
                    }]}))
                elif goal.startswith("Company Researcher"):
                    summaries.append(json.dumps({"entities": [{
                        "name": "Example Works Pvt Ltd",
                        "claims": [_claim("geography", "India", "Registered office in India")],
                        "unknowns": [],
                    }]}))
                elif goal.startswith("Ownership Researcher"):
                    summaries.append(json.dumps({"entities": [
                        {
                            "name": "Example Works",
                            "claims": [
                                _claim("ownership", "family", "A family holds the shares"),
                                _claim("listing_status", "unlisted", "The company is privately held and unlisted"),
                            ],
                            "unknowns": [],
                        },
                        {
                            "name": "Not On The List",
                            "claims": [
                                _claim("ownership", "family", "A family holds the shares"),
                                _claim("listing_status", "unlisted", "The company is privately held and unlisted"),
                            ],
                            "unknowns": [],
                        },
                    ]}))
                elif goal.startswith("Financial Researcher") and gap:
                    summaries.append(json.dumps({"entities": [{
                        "name": "Example Works",
                        "claims": [_claim("revenue_inr_cr", 548, "Operating income was 548 crore")],
                        "unknowns": [],
                    }]}))
                else:
                    summaries.append(json.dumps({"entities": []}))
            return json.dumps({
                "results": [{"task_index": index, "summary": text} for index, text in enumerate(summaries)]
            })

        with tempfile.TemporaryDirectory() as folder:
            report = Orchestrator(
                agent=object(),
                on_event=lambda _event: None,
                runs_root=Path(folder),
                complete_fn=complete,
                delegate_fn=delegate,
            ).run(OPERATING)
            saved = json.loads((Path(folder) / "india-auto-components" / "orchestrator-run.json").read_text())

        self.assertEqual(len(calls), 4)
        self.assertEqual(len(calls[0]), 1)
        self.assertIn("Relationship Researcher", calls[3][0]["goal"])
        self.assertIn("do not web_extract", calls[3][0]["context"])
        gap = calls[2]
        self.assertEqual(len(gap), 2)
        self.assertIn("Gap pass", gap[0]["context"])
        self.assertIn("Example Works Pvt Ltd: sector, business_model", gap[0]["context"])
        self.assertIn("Example Works Pvt Ltd: revenue", gap[1]["context"])
        self.assertNotIn("Not On The List", gap[0]["context"])
        self.assertIn("Do not add a company", gap[0]["context"])
        names = [entity["name"] for entity in saved["entities"]]
        self.assertEqual(names, ["Example Works Pvt Ltd"])
        self.assertNotIn("Not On The List", report)
        self.assertEqual(saved["entities"][0]["screening"]["fit_score"], 70)


class MutableAgent:
    """A fake agent that (unlike a bare object()) supports attribute
    assignment, so tests can observe tool_progress_callback being wired
    and restored around a run -- the same thing a real AIAgent supports."""

    session_id = "test-session"
    tools = []


class SubagentProgressTests(unittest.TestCase):
    def test_extracts_worker_name_from_the_goal_and_filters_to_known_phases(self) -> None:
        events: list[dict] = []
        orch = Orchestrator(agent=MutableAgent(), on_event=events.append, runs_root=Path("/tmp"))

        orch._on_subagent_progress(
            "subagent.tool", "web_search", "Triton Valves ownership", None,
            goal="Ownership Researcher. Follow aveyroni-ownership. Sources who owns...",
        )
        orch._on_subagent_progress("subagent.start", preview="ignored", goal="Financial Researcher. Follow deal-screening.")
        orch._on_subagent_progress("subagent.complete", preview="done", goal="Financial Researcher. Follow deal-screening.")
        # Types the bridge deliberately does not forward (reasoning noise,
        # the batched digest, streamed child text) must not reach the UI.
        orch._on_subagent_progress("subagent.thinking", preview="reasoning...", goal="Ownership Researcher. x")
        orch._on_subagent_progress("subagent.progress", preview="batched digest", goal="Ownership Researcher. x")
        orch._on_subagent_progress("subagent.text", preview="chatter", goal="Ownership Researcher. x")

        self.assertEqual(len(events), 3)
        tool_event = events[0]["subagent"]
        self.assertEqual(tool_event["phase"], "tool")
        self.assertEqual(tool_event["worker"], "Ownership Researcher")
        self.assertEqual(tool_event["tool_name"], "web_search")
        self.assertEqual(tool_event["preview"], "Triton Valves ownership")
        orch._on_subagent_progress(
            "subagent.tool", "skill_view",
            '{"success": true, "name": "aveyroni-mandate", "description": "Use when."}',
            None, goal="Company Researcher. Find names.",
        )
        orch._on_subagent_progress(
            "subagent.tool", "execute_code",
            "from hermes_tools import web_search",
            None, goal="Company Researcher. Find names.",
        )
        self.assertEqual(events[-2]["subagent"]["preview"], "")
        self.assertEqual(events[-1]["subagent"]["preview"], "")
        self.assertEqual(events[1]["subagent"]["phase"], "start")
        self.assertEqual(events[1]["subagent"]["worker"], "Financial Researcher")
        self.assertEqual(events[2]["subagent"]["phase"], "complete")

    def test_missing_or_malformed_goal_does_not_raise(self) -> None:
        events: list[dict] = []
        orch = Orchestrator(agent=MutableAgent(), on_event=events.append, runs_root=Path("/tmp"))
        orch._on_subagent_progress("subagent.tool", "web_search", "x", None)  # no goal kwarg at all
        orch._on_subagent_progress("subagent.tool", "web_search", "x", None, goal="")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["subagent"]["worker"], "")
        self.assertEqual(events[1]["subagent"]["worker"], "")

    def test_run_wires_the_callback_during_delegation_and_restores_it_after(self) -> None:
        agent = MutableAgent()
        agent.tool_progress_callback = "sentinel-from-before"
        seen_during_delegate = []

        def delegate(tasks, parent_agent):
            seen_during_delegate.append(parent_agent.tool_progress_callback)
            return json.dumps({"results": [{"task_index": i, "summary": json.dumps({"entities": []})} for i in range(len(tasks))]})

        def complete(role, _message):
            if role == "controller":
                return json.dumps({"focus_notes": "x"})
            if role == "fit-scorer":
                return json.dumps({"scores": []})
            return "review complete"

        with tempfile.TemporaryDirectory() as folder:
            orch = Orchestrator(
                agent=agent, on_event=lambda _e: None, runs_root=Path(folder),
                delegate_fn=delegate, complete_fn=complete,
            )
            orch.run(OPERATING)

        # Wired to the bridge method (bound to this orchestrator instance)
        # for the whole duration of every delegate_task call in the run...
        self.assertTrue(seen_during_delegate)
        self.assertTrue(all(cb == orch._on_subagent_progress for cb in seen_during_delegate))
        # ...and restored to whatever was there before, once the run ends.
        self.assertEqual(agent.tool_progress_callback, "sentinel-from-before")

    def test_run_tolerates_an_agent_that_cannot_hold_new_attributes(self) -> None:
        # A bare object() has no __dict__ -- attribute assignment raises.
        # This must degrade to "no live subagent stream" quietly, never
        # break the run, matching pre-feature behavior exactly.
        def delegate(tasks, _agent):
            return json.dumps({"results": [{"task_index": i, "summary": json.dumps({"entities": []})} for i in range(len(tasks))]})

        def complete(role, _message):
            if role == "controller":
                return json.dumps({"focus_notes": "x"})
            if role == "fit-scorer":
                return json.dumps({"scores": []})
            return "review complete"

        with tempfile.TemporaryDirectory() as folder:
            report = Orchestrator(
                agent=object(), on_event=lambda _e: None, runs_root=Path(folder),
                delegate_fn=delegate, complete_fn=complete,
            ).run(OPERATING)
        self.assertIn("Nothing was sent.", report)


if __name__ == "__main__":
    unittest.main()
