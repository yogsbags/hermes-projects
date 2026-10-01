"""MCA browser filters and public rows — no live network."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator import mca_browse


FOXLABS_ROW = {
    "cin": "U18109DL2022PTC397831",
    "name": "Sample Textiles Private Limited",
    "status": "Active",
    "companyClass": "Private",
    "operatingRevenueRange": "INR 100 cr - 500 cr",
    "paidUpCapital": "1.2 cr",
    "authorisedCapital": "2.0 cr",
    "incorporationDate": "12 May 2022",
    "registeredAddress": "New Delhi",
    "email": "secretarial@example.com",
    "matched": True,
    "source": "tofler",
    "chargesCount": 1,
    "directorsCount": 1,
    "directors": [{"name": "Ada Founder", "din": "01234567", "designation": "Director", "tenure": "2 years"}],
    "charges": [{"date": "29 May, 2025", "amount": "25.0 cr", "holder": "Yes Bank Limited"}],
    "locations": [{"type": "Registered Office", "address": "New Delhi", "state": "Delhi", "pincode": "110001"}],
    "subsidiaries": [{"name": "Sample Textiles Retail", "cin": "U18109DL2023PTC000001", "status": "Active"}],
    "lastAgmDate": "30 Sep 2025",
    "ageYears": 4,
}


class FilterTests(unittest.TestCase):
    def test_parse_filters_defaults_and_plc(self) -> None:
        filters = mca_browse.parse_filters({"plc": "true", "page": "2", "page_size": "10", "q": "bhavani"})
        self.assertTrue(filters["plc"])
        self.assertEqual(filters["page"], 2)
        self.assertEqual(filters["page_size"], 10)
        self.assertEqual(filters["q"], "bhavani")

    def test_query_params_plc_and_listing(self) -> None:
        filters = mca_browse.parse_filters({
            "plc": True,
            "listing_status": "Unlisted",
            "company_status": "Active",
            "company_class": "Public",
        })
        params = dict(mca_browse.query_params(filters))
        self.assertEqual(params["cin"], "like.*PLC*")
        self.assertEqual(params["listing_status"], "eq.Unlisted")
        self.assertEqual(params["company_status"], "eq.Active")
        self.assertEqual(params["company_class"], "eq.Public")
        self.assertEqual(params["limit"], "25")
        self.assertEqual(params["offset"], "0")

    def test_exact_cin_does_not_add_plc_like(self) -> None:
        filters = mca_browse.parse_filters({"cin": "L17110MH1973PLC019786", "plc": True})
        values = [value for key, value in mca_browse.query_params(filters) if key == "cin"]
        self.assertEqual(values, ["eq.L17110MH1973PLC019786"])

    def test_sql_query_plc_and_listing(self) -> None:
        filters = mca_browse.parse_filters({
            "plc": True,
            "listing_status": "Unlisted",
            "company_status": "Active",
            "company_class": "Public",
            "page_size": "10",
        })
        select, select_args, count, count_args = mca_browse.sql_query(filters)
        self.assertIn("cin LIKE ?", select)
        self.assertIn("%PLC%", select_args)
        self.assertEqual(select_args[-2:], [10, 0])
        self.assertEqual(count_args, ["%PLC%", "Public", "Unlisted", "Active"])

    def test_sql_query_search_matches_name_or_cin(self) -> None:
        filters = mca_browse.parse_filters({"search": "bhavani", "plc": False})
        select, select_args, _count, count_args = mca_browse.sql_query(filters)
        self.assertIn("(company_name LIKE ? OR cin LIKE ?)", select)
        self.assertEqual(count_args[:2], ["%bhavani%", "%bhavani%"])
        exact = mca_browse.parse_filters({"search": "L17110MH1973PLC019786"})
        _select, args, _c, _ca = mca_browse.sql_query(exact)
        self.assertIn("L17110MH1973PLC019786", args)

    def test_sql_query_roc_capital_and_origin(self) -> None:
        filters = mca_browse.parse_filters({
            "roc": "ROC Mumbai",
            "origin": "india",
            "paidup_min_cr": "5",
            "registered_from": "2018",
        })
        select, select_args, _count, count_args = mca_browse.sql_query(filters)
        self.assertIn("company_roc_code = ?", select)
        self.assertIn("company_origin IN ('India', '91')", select)
        self.assertIn("paidup_capital >= ?", select)
        self.assertIn("registration_date >= ?", select)
        self.assertIn("ROC Mumbai", select_args)
        self.assertIn(50_000_000.0, select_args)
        self.assertIn("2018-01-01", count_args)


class PublicShapeTests(unittest.TestCase):
    def test_public_company_marks_plc(self) -> None:
        row = mca_browse.public_company({
            "cin": "u12345mh2010plc000001",
            "company_name": "Acme Public Limited",
            "company_class": "Public",
            "listing_status": "Unlisted",
            "company_status": "Active",
            "company_state_code": "maharashtra",
            "nic_code": "29301",
            "industrial_classification": "Manufacture of motor vehicles",
            "company_category": "Company limited by shares",
            "company_sub_category": "Non-government company",
            "company_origin": "India",
            "company_roc_code": "ROC Mumbai",
            "authorized_capital": 100_000_000,
            "paidup_capital": 50_000_000,
            "registration_date": "2010-01-15",
            "source": "data.gov.in",
        })
        self.assertTrue(row["plc"])
        self.assertEqual(row["cin"], "U12345MH2010PLC000001")
        self.assertEqual(row["paidup"], "₹5.00 cr")
        self.assertEqual(row["authorized"], "₹10.00 cr")
        self.assertEqual(row["category"], "Company limited by shares")
        self.assertEqual(row["roc"], "ROC Mumbai")

    def test_public_enrichment_keeps_sourced_tables_only(self) -> None:
        public = mca_browse.public_enrichment(FOXLABS_ROW)
        self.assertEqual(public["charges"][0]["holder"], "Yes Bank Limited")
        self.assertEqual(public["directors"][0]["din"], "01234567")
        self.assertEqual(public["email"], "secretarial@example.com")
        self.assertEqual(public["revenue"], "INR 100 cr - 500 cr")
        self.assertEqual(public["locations"][0]["state"], "Delhi")
        self.assertEqual(public["subsidiaries"][0]["name"], "Sample Textiles Retail")
        self.assertEqual(public["last_agm_date"], "30 Sep 2025")
        self.assertTrue(public["matched"])


class SearchAndCacheTests(unittest.TestCase):
    def test_search_uses_injected_fetch(self) -> None:
        def fake_fetch(table, params):
            self.assertEqual(table, "mca_companies")
            return ([{
                "cin": "U29211DL2005PLC142857",
                "company_name": "Sample Forge Limited",
                "company_class": "Public",
                "listing_status": "Unlisted",
                "company_status": "Active",
                "company_state_code": "delhi",
                "nic_code": "29211",
                "paidup_capital": 1000,
            }], 1)

        result = mca_browse.search({"q": "forge"}, fetch=fake_fetch)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["name"], "Sample Forge Limited")
        self.assertEqual(result["source"], "mca_companies")

    def test_enrich_reads_cache_without_actor(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = mca_browse.cache_path(FOXLABS_ROW["cin"], Path(folder))
            path.parent.mkdir(parents=True)
            path.write_text(__import__("json").dumps(FOXLABS_ROW))

            def boom(_cin):
                raise AssertionError("actor should not run when cache exists")

            public = mca_browse.enrich(
                FOXLABS_ROW["cin"],
                runs_root=Path(folder),
                fetch_existing=lambda *_a, **_k: None,
                run_actor=boom,
            )
            self.assertTrue(public["cached"])
            self.assertEqual(public["charges"][0]["amount"], "25.0 cr")

    def test_enrich_rejects_short_cin(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                mca_browse.enrich("PLC", runs_root=Path(folder))


if __name__ == "__main__":
    unittest.main()
