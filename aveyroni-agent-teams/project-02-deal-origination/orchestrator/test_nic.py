"""NIC 2025 catalog is loaded from JSON, not hardcoded."""

from __future__ import annotations

import unittest

from orchestrator import nic


class NicCatalogTests(unittest.TestCase):
    def test_lists_come_from_json_files(self) -> None:
        self.assertTrue((nic.ROOT / "industries.json").exists())
        self.assertTrue((nic.ROOT / "sectors.json").exists())
        self.assertTrue((nic.ROOT / "niches.json").exists())
        self.assertEqual([row["id"] for row in nic.industries()], list("ABCDEFGHIJKLMNOPQRSTUV"))
        self.assertGreaterEqual(len(nic.sectors()), 80)
        self.assertGreaterEqual(len(nic.niches()), 200)

    def test_auto_components_cascade(self) -> None:
        resolved = nic.resolve({"industry_code": "C", "sector_code": "29", "niche_code": ""})
        self.assertEqual(resolved["industry_code"], "C")
        self.assertEqual(resolved["sector_code"], "29")
        self.assertEqual(resolved["niche_code"], "")
        self.assertEqual(resolved["sector_codes"], ["291", "292", "293"])
        self.assertEqual(resolved["sector"], ["Manufacture of motor vehicles, trailers and semi-trailers"])

    def test_niche_narrows_to_one_group(self) -> None:
        resolved = nic.resolve({"industry_code": "C", "sector_code": "29", "niche_code": "293"})
        self.assertEqual(resolved["sector_codes"], ["293"])
        self.assertIn("parts and accessories", resolved["sector"][0].lower())

    def test_infer_from_legacy_group_codes(self) -> None:
        inferred = nic.infer_selection(["291", "292", "293"])
        self.assertEqual(inferred, {"industry_code": "C", "sector_code": "29", "niche_code": ""})

    def test_alias_file_maps_auto_components(self) -> None:
        self.assertEqual(nic.prefixes_from_labels(["auto components"]), ["291", "292", "293"])


if __name__ == "__main__":
    unittest.main()
