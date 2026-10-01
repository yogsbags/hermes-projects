"""Contract origination desk is JSON-driven and stays on sourced claims."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from orchestrator.contracts import build_desk, client_profile, store_desk
from orchestrator.deterministic import parse_mandate
from orchestrator.test_orchestrator import OPERATING, _claim


class ContractDeskTests(unittest.TestCase):
    def test_client_profile_comes_from_json(self) -> None:
        profile = client_profile()
        self.assertEqual(profile["id"], "aveyroni-industrial-automation")
        self.assertEqual(profile["contract_min_inr_cr"], 5)

    def test_desk_uses_sourced_signals_and_named_people_only(self) -> None:
        package = {
            "mandate": parse_mandate(OPERATING),
            "entities": [{
                "entity_id": "bhavani-industries-india",
                "name": "Bhavani Industries India LLP",
                "claims": [
                    _claim("listing_status", "unlisted", "The company is privately held and unlisted"),
                    _claim("geography", "India; Rajkot", "Plant at Rajkot, Gujarat, India"),
                    _claim("sector", "Automotive transmission components", "Gears and shafts"),
                    _claim("maa", "Acquired Kadvani Forge on 1 April 2018", "Acquired a forging plant on 01/04/2018"),
                    _claim("plant expansion", "Added two machines on 2026-07-15: Cone OD Grinding ECG-500", "adding two more machines on 2026-07-15"),
                    _claim("relationship", "Himanshubhai Dolatram Nandwana — Designated Partner", "Himanshubhai Dolatram Nandwana Designated Partner"),
                ],
                "screening": {
                    "fit_label": "MANDATE_FIT",
                    "fit_score": 70,
                    "mandatory": [{"check": "listing_status", "result": "pass"}],
                },
            }],
        }
        desk = build_desk(package, "bhavani-industries-india", today=date(2026, 9, 26))
        self.assertEqual(desk["account"]["name"], "Bhavani Industries India LLP")
        self.assertGreaterEqual(desk["funnel"]["signals"], 1)
        self.assertGreaterEqual(desk["funnel"]["qualified"], 1)
        self.assertEqual(len(desk["agents"]), 6)
        self.assertTrue(desk["hermes_layers"])
        self.assertIn("Himanshubhai", desk["people"][0]["name"])
        self.assertEqual(desk["funnel"]["potential"], 1)
        first = desk["opportunities"][0]
        self.assertIn("2026-07-15", first["title"] + first["trigger"])
        self.assertEqual(first["date_label"], "15 Jul 2026")
        stale = next(row for row in desk["signals"] if "2018" in (row.get("date_label") or ""))
        self.assertFalse(stale["fresh"])
        self.assertIn("Not sourced", first["procurement_chain"][1]["name"])
        self.assertIn("not sourced", first["fit"]["value_note"].lower())
        self.assertNotIn("@", json_blob := str(desk))
        self.assertNotIn("wants to sell", json_blob.lower())
        with tempfile.TemporaryDirectory() as folder:
            path = store_desk(Path(folder), "india-auto-components", desk)
            self.assertTrue(path.exists())

    def test_rejects_companies_not_on_the_board(self) -> None:
        package = {"mandate": parse_mandate(OPERATING), "entities": []}
        with self.assertRaises(ValueError):
            build_desk(package, "missing")


if __name__ == "__main__":
    unittest.main()
