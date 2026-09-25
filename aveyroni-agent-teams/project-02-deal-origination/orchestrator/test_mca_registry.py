"""MCA registry discovery — deterministic, no network, no model call."""

from __future__ import annotations

import os
import unittest

from orchestrator import mca_registry

OPERATING_INDIA_AUTO = {
    "title": "India Auto Components",
    "focus": "operating-company",
    "geography": ["India"],
    "sector": ["auto components"],
    "ownership": ["founder", "family"],
    "exclude_ownership": ["private_equity"],
    "revenue_min_inr_cr": 300,
    "revenue_max_inr_cr": 1500,
}

ROW = {
    "cin": "U29211DL2005PTC142857",
    "company_name": "Sample Forge Components Private Limited",
    "company_state_code": "haryana",
    "nic_code": "29211",
    "industrial_classification": "Manufacturing (Machinery and Equipments)",
    "archetype": "manufacturing",
    "company_class": "Private",
    "company_status": "Active",
    "paidup_crores": 4.5,
    "company_age_years": 18,
    "registered_office_address": "Gurgaon, Haryana, India",
    "pe_tier": None,
    "operating_revenue_range": None,
}


def _with_env(**kv):
    def decorator(fn):
        def wrapper(self):
            saved = {k: os.environ.get(k) for k in kv}
            os.environ.update(kv)
            try:
                fn(self)
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        return wrapper
    return decorator


class ConfigTests(unittest.TestCase):
    @_with_env(AVEYRONI_MCA_SUPABASE_URL="", AVEYRONI_MCA_SUPABASE_KEY="")
    def test_not_configured_without_env(self) -> None:
        self.assertFalse(mca_registry.configured())
        self.assertFalse(mca_registry.applies(OPERATING_INDIA_AUTO))

    @_with_env(AVEYRONI_MCA_SUPABASE_URL="https://example.supabase.co", AVEYRONI_MCA_SUPABASE_KEY="secret")
    def test_applies_for_known_sector_and_india(self) -> None:
        self.assertTrue(mca_registry.applies(OPERATING_INDIA_AUTO))

    @_with_env(AVEYRONI_MCA_SUPABASE_URL="https://example.supabase.co", AVEYRONI_MCA_SUPABASE_KEY="secret")
    def test_does_not_apply_to_real_estate(self) -> None:
        mandate = {**OPERATING_INDIA_AUTO, "focus": "real-estate"}
        self.assertFalse(mca_registry.applies(mandate))

    @_with_env(AVEYRONI_MCA_SUPABASE_URL="https://example.supabase.co", AVEYRONI_MCA_SUPABASE_KEY="secret")
    def test_does_not_apply_to_unmapped_sector(self) -> None:
        mandate = {**OPERATING_INDIA_AUTO, "sector": ["artisanal soap"]}
        self.assertFalse(mca_registry.applies(mandate))

    @_with_env(AVEYRONI_MCA_SUPABASE_URL="https://example.supabase.co", AVEYRONI_MCA_SUPABASE_KEY="secret")
    def test_does_not_apply_outside_india(self) -> None:
        mandate = {**OPERATING_INDIA_AUTO, "geography": ["Vietnam"]}
        self.assertFalse(mca_registry.applies(mandate))

    @_with_env(AVEYRONI_MCA_SUPABASE_URL="https://example.supabase.co", AVEYRONI_MCA_SUPABASE_KEY="secret")
    def test_selected_nic_codes_support_multiple_sectors(self) -> None:
        mandate = {
            **OPERATING_INDIA_AUTO,
            "sector": ["packaging", "auto components"],
            "sector_codes": ["170", "222", "293"],
        }
        self.assertTrue(mca_registry.applies(mandate))
        self.assertEqual(mca_registry._nic_prefixes(mandate)[:3], ["170", "222", "293"])


class DiscoverTests(unittest.TestCase):
    def test_row_becomes_a_sourced_entity(self) -> None:
        captured = {}

        def fake_fetch(mandate, limit):
            captured["mandate"] = mandate
            captured["limit"] = limit
            return [ROW]

        result = mca_registry.discover(OPERATING_INDIA_AUTO, limit=30, fetch_fn=fake_fetch)
        self.assertEqual(result["worker"], "mca-registry")
        self.assertFalse(result["unparsed"])
        self.assertEqual(len(result["entities"]), 1)
        entity = result["entities"][0]
        self.assertEqual(entity["name"], "Sample Forge Components Private Limited")
        fields = {claim["field"] for claim in entity["claims"]}
        self.assertIn("geography", fields)
        self.assertIn("sector", fields)
        self.assertNotIn("revenue_inr_cr", fields)  # no enrichment band on this row
        for claim in entity["claims"]:
            self.assertTrue(claim["source_url"].startswith("https://"))
            self.assertTrue(claim["excerpt"])
            self.assertIn(ROW["cin"], claim["excerpt"])
        self.assertIn("business_model", entity["unknowns"])
        self.assertIn("revenue_inr_cr", entity["unknowns"])
        self.assertEqual(captured["mandate"], OPERATING_INDIA_AUTO)
        self.assertEqual(captured["limit"], 30)

    def test_revenue_band_becomes_a_claim_not_an_unknown(self) -> None:
        row = {**ROW, "operating_revenue_range": "INR 1 cr - 100 cr"}
        result = mca_registry.discover(OPERATING_INDIA_AUTO, fetch_fn=lambda m, n: [row])
        entity = result["entities"][0]
        fields = {claim["field"] for claim in entity["claims"]}
        self.assertIn("revenue_inr_cr", fields)
        self.assertNotIn("revenue_inr_cr", entity["unknowns"])

    def test_unnamed_row_is_dropped(self) -> None:
        row = {**ROW, "company_name": ""}
        result = mca_registry.discover(OPERATING_INDIA_AUTO, fetch_fn=lambda m, n: [row])
        self.assertEqual(result["entities"], [])
        self.assertTrue(result["unparsed"])

    def test_fetch_failure_degrades_without_raising(self) -> None:
        def boom(mandate, limit):
            raise RuntimeError("connection refused")

        result = mca_registry.discover(OPERATING_INDIA_AUTO, fetch_fn=boom)
        self.assertTrue(result["unparsed"])
        self.assertIn("connection refused", result["error"])
        self.assertEqual(result["entities"], [])

    def test_default_limit_is_conservative_for_a_live_demo(self) -> None:
        captured = {}
        mca_registry.discover(OPERATING_INDIA_AUTO, fetch_fn=lambda m, n: (captured.__setitem__("limit", n), [])[1])
        self.assertLessEqual(captured["limit"], 15)

    def test_excluded_company_is_not_returned_in_later_batch(self) -> None:
        result = mca_registry.discover(
            OPERATING_INDIA_AUTO,
            fetch_fn=lambda m, n: [ROW],
            exclude_names=["sample-forge-components"],
        )
        self.assertEqual(result["entities"], [])


class DefaultFetchQueryTests(unittest.TestCase):
    """Regression test for a real bug: sorting candidates by paid-up capital
    descending systematically surfaced MNC subsidiaries first (Parker
    Hannifin India, Vitesco Technologies India, Siemens Energy, ...) for a
    founder/family-owned mandate -- a real live run rejected 30/30 candidates
    on ownership because of it. This locks in the fix so it can't silently
    regress back to that sort."""

    @_with_env(AVEYRONI_MCA_SUPABASE_URL="https://example.supabase.co", AVEYRONI_MCA_SUPABASE_KEY="secret")
    def test_does_not_sort_by_paidup_capital(self) -> None:
        captured = {}

        def fake_postgrest_get(path, params, url, key):
            captured["params"] = dict(params)
            return []

        original = mca_registry._postgrest_get
        mca_registry._postgrest_get = fake_postgrest_get
        try:
            mca_registry._default_fetch(OPERATING_INDIA_AUTO, 12)
        finally:
            mca_registry._postgrest_get = original

        order = captured["params"].get("order", "")
        self.assertNotIn("paidup_crores", order, "must not sort by paid-up capital -- it front-loads MNC subsidiaries")
        self.assertIn("company_age_years", order)

    @_with_env(AVEYRONI_MCA_SUPABASE_URL="https://example.supabase.co", AVEYRONI_MCA_SUPABASE_KEY="secret")
    def test_later_batch_uses_postgrest_offset(self) -> None:
        captured = {}

        def fake_postgrest_get(path, params, url, key):
            captured["params"] = dict(params)
            return []

        original = mca_registry._postgrest_get
        mca_registry._postgrest_get = fake_postgrest_get
        try:
            mca_registry._default_fetch(OPERATING_INDIA_AUTO, 12, offset=24)
        finally:
            mca_registry._postgrest_get = original
        self.assertEqual(captured["params"]["offset"], "24")


if __name__ == "__main__":
    unittest.main()
