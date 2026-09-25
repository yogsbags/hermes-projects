"""Pure-function tests for chat/server.py's tool-result formatting.

Regression test for a real client-visible bug: the regular chat turn's
`_result_detail()` was json.dumps()-ing any structured tool result
straight into the live "Agent trace" card -- a user saw raw payloads like
`{"success": true, "name": "aveyroni-mandate", "description": ...}` for
skill_view and `{"total_count": 50, "files": [...]}` for search_files.

This module does not import chat/server.py directly, because the module
has import-time side effects (sys.path mutation, os.chdir, a hard-coded
~/.hermes/hermes-agent path) that assume a full Hermes install. The
functions under test are pure (no I/O, no Hermes dependency), so this
extracts just their source and execs it in an isolated namespace --
avoiding a fragile, heavy conftest just to reach two small functions.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

_SOURCE = (Path(__file__).resolve().parent / "server.py").read_text()


def _load_pure_functions() -> dict:
    start = _SOURCE.index("def _clip(")
    end = _SOURCE.index("def _words(")
    assert start < end, "chat/server.py layout changed -- update the slice markers"
    namespace: dict = {"json": json}
    exec(_SOURCE[start:end], namespace)  # noqa: S102 -- trusted, local source slice
    return namespace


_NS = _load_pure_functions()
_result_detail = _NS["_result_detail"]
_tool_detail = _NS["_tool_detail"]


class ResultDetailTests(unittest.TestCase):
    def test_json_string_is_reduced_not_shown_raw(self) -> None:
        raw = json.dumps({
            "success": True,
            "name": "aveyroni-mandate",
            "description": "Use when turning a buy-side thesis into a buy-box.",
        })
        detail = _result_detail(raw)
        self.assertEqual(detail, "Use when turning a buy-side thesis into a buy-box.")
        self.assertNotIn("{", detail)

    def test_plain_string_result_passes_through(self) -> None:
        self.assertEqual(_result_detail("already a clean summary"), "already a clean summary")

    def test_skill_view_shows_description_not_raw_json(self) -> None:
        # The exact real payload shape reported by a live client screenshot.
        result = {
            "success": True,
            "name": "aveyroni-mandate",
            "description": "Use when turning a buy-side thesis into a buy-box.",
            "tags": ["mandate", "buy-box", "screening-rules"],
        }
        detail = _result_detail(result)
        self.assertEqual(detail, "Use when turning a buy-side thesis into a buy-box.")
        self.assertNotIn("{", detail)
        self.assertNotIn("success", detail)

    def test_search_files_shows_a_count_not_raw_json(self) -> None:
        result = {"total_count": 50, "files": ["./DEMO.md", "./chat/index.html"]}
        detail = _result_detail(result)
        self.assertEqual(detail, "50 files")
        self.assertNotIn("{", detail)

    def test_name_plus_success_without_a_text_field(self) -> None:
        self.assertEqual(_result_detail({"success": True, "name": "aveyroni-relationship-map"}), "aveyroni-relationship-map — ok")
        self.assertEqual(_result_detail({"success": False, "name": "some-tool"}), "some-tool — failed")

    def test_bare_success_flag_with_no_name(self) -> None:
        self.assertEqual(_result_detail({"success": False}), "Failed.")
        self.assertEqual(_result_detail({"success": True}), "Done.")

    def test_unrecognized_dict_shape_never_dumps_raw_json(self) -> None:
        detail = _result_detail({"nested": {"a": 1, "b": [1, 2, 3]}, "weird_key": True})
        self.assertNotIn("{", detail)
        self.assertNotIn("nested", detail)

    def test_list_result_shows_a_count(self) -> None:
        self.assertEqual(_result_detail(["a", "b", "c"]), "3 results")
        self.assertEqual(_result_detail(["a"]), "1 result")

    def test_no_result_shape_ever_looks_like_json(self) -> None:
        # Broad sweep: whatever the shape, the output must never contain
        # raw-JSON punctuation a business user shouldn't see.
        samples = [
            {"success": True, "name": "x", "tags": ["a", "b"], "extra": {"nested": 1}},
            {"count": 0, "files": []},
            {"random_field": "value", "another": 123},
            None,
            42,
            True,
        ]
        for sample in samples:
            detail = _result_detail(sample)
            self.assertNotRegex(detail, r'[{}\[\]"]', msg=f"leaked structure for {sample!r}: {detail!r}")


class ToolDetailTests(unittest.TestCase):
    def test_delegate_task_summarizes_parallel_goals(self) -> None:
        args = {"tasks": [{"goal": "Research A"}, {"goal": "Research B"}]}
        self.assertEqual(_tool_detail("delegate_task", args), "parallel · Research A · Research B")

    def test_skill_view_shows_the_skill_name_from_args(self) -> None:
        self.assertEqual(_tool_detail("skill_view", {"skill": "aveyroni-mandate"}), "aveyroni-mandate")

    def test_non_dict_args_are_empty(self) -> None:
        self.assertEqual(_tool_detail("anything", None), "")
        self.assertEqual(_tool_detail("anything", "not a dict"), "")


class ChatScopeGuardrailTests(unittest.TestCase):
    """Regression test for a real incident: a free-text chat message ("look
    into food processing companies...") led the agent to interpret the
    preloaded origination-controller skill literally -- running its own
    scripts and writing mandate.json/target-universe.jsonl/etc. straight to
    an invented runs/india-food-processing-001/ folder, never registered,
    never reachable from the UI. Nothing was fabricated (every field was
    honestly "not_scored"), but the scope was wrong -- chat is for
    follow-up questions, "Run team" is for actual research passes."""

    def setUp(self) -> None:
        from chat import server

        self.server = server

    def test_guardrail_is_present_for_operating_company(self) -> None:
        config = self.server._default_config()
        text = self.server.buy_box_text(config)
        self.assertIn(self.server.CHAT_SCOPE_GUARDRAIL, text)
        self.assertIn("Run team", text)
        self.assertIn("do not write mandate/target files or run scripts", text)

    def test_guardrail_is_present_for_real_estate(self) -> None:
        config = self.server._default_config()
        config["focus"] = "real-estate"
        config["asset_types"] = ["multi-family"]
        text = self.server.buy_box_text(config)
        self.assertIn(self.server.CHAT_SCOPE_GUARDRAIL, text)


class MandateRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        from chat import server

        self.server = server
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {
            "ROOT": server.ROOT,
            "CONFIG_PATH": server.CONFIG_PATH,
            "MANDATES_PATH": server.MANDATES_PATH,
            "REGISTRY_PATH": server.REGISTRY_PATH,
            "DESKS": server.DESKS,
            "public_targets": server.public_targets,
        }
        server.ROOT = self.root
        server.CONFIG_PATH = self.root / "desk-config.json"
        server.MANDATES_PATH = self.root / "mandates"
        server.REGISTRY_PATH = server.MANDATES_PATH / "registry.json"
        server.DESKS = {}

    def tearDown(self) -> None:
        for key, value in self.originals.items():
            setattr(self.server, key, value)
        self.temp.cleanup()

    def test_single_config_migrates_without_changing_legacy_run_id(self) -> None:
        config = self.server._default_config()
        config["title"] = "Renamed India Mandate"
        self.server.CONFIG_PATH.write_text(json.dumps(config))

        registry = self.server._load_registry()

        self.assertEqual(registry["active_mandate_id"], "india-auto-components")
        loaded = self.server.load_desk_config("india-auto-components")
        self.assertEqual(loaded["mandate_id"], "india-auto-components")
        self.assertEqual(loaded["title"], "Renamed India Mandate")

    def test_histories_are_isolated_by_mandate(self) -> None:
        self.server._load_registry()
        second = "mandate-second"
        registry = self.server._load_registry()
        config = {**self.server._default_config(), "mandate_id": second, "title": "Second"}
        registry["mandates"][second] = {
            "mandate_id": second, "title": "Second",
            "created_at": self.server._now(), "updated_at": self.server._now(),
            "targets_available": False,
        }
        self.server._write_json(self.server._config_path(second), config)
        self.server._save_registry(registry)

        self.server.save_history("india-auto-components", [{"role": "user", "content": "India"}], "a")
        self.server.save_history(second, [{"role": "user", "content": "Second"}], "b")

        self.assertEqual(self.server.load_history("india-auto-components")["messages"][0]["content"], "India")
        self.assertEqual(self.server.load_history(second)["messages"][0]["content"], "Second")

    def test_target_lookup_uses_stable_id_and_stale_flag(self) -> None:
        registry = self.server._load_registry()
        run = self.root / "runs" / "india-auto-components" / "orchestrator-run.json"
        run.parent.mkdir(parents=True)
        run.write_text(json.dumps({"marker": "correct mandate"}))
        self.server.public_targets = lambda package: [package["marker"]]

        registry["mandates"]["india-auto-components"]["targets_available"] = True
        self.server._save_registry(registry)
        self.assertEqual(self.server.latest_targets("india-auto-components"), ["correct mandate"])

        registry["mandates"]["india-auto-components"]["targets_available"] = False
        self.server._save_registry(registry)
        self.assertEqual(self.server.latest_targets("india-auto-components"), [])

    def test_explicit_id_survives_title_rename(self) -> None:
        from orchestrator.deterministic import parse_mandate

        config = self.server._default_config()
        config.update({"mandate_id": "mandate-fixed", "title": "New Display Name"})
        self.assertEqual(parse_mandate(config)["mandate_id"], "mandate-fixed")

    def test_non_india_operating_config_uses_selected_revenue_currency(self) -> None:
        config = self.server.normalize_config({
            **self.server._default_config(),
            "title": "Vietnam Auto Components",
            "geography": "Vietnam",
            "currency": "USD",
            "revenue_min": 50,
            "revenue_max": 200,
            "revenue_scale": "million",
        })
        self.assertEqual(config["currency"], "USD")
        self.assertEqual(config["revenue_min"], 50)
        self.assertEqual(config["revenue_max"], 200)
        self.assertEqual(config["revenue_scale"], "million")
        self.assertIsNone(config["revenue_min_inr_cr"])


if __name__ == "__main__":
    unittest.main()
