"""Safety and state-transition tests for mandate-scoped outreach."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.outreach import (
    DECISION_MAKER_TITLES,
    _company_domain,
    _relationship_names,
    approve,
    deliver,
    list_drafts,
    prepare,
    suppress,
)


MANDATE = {
    "mandate_id": "test-mandate",
    "title": "Test mandate",
    "focus": "operating-company",
    "geography": ["India"],
    "sector": ["auto components"],
}


def _package(label: str = "MANDATE_FIT") -> dict:
    return {
        "mandate": MANDATE,
        "entities": [{
            "entity_id": "company-1",
            "name": "Example Components",
            "claims": [{
                "field": "ownership",
                "value": "founder-owned",
                "source_url": "https://example.com/about",
            }, {
                "field": "listing_status",
                "value": "unlisted",
                "source_url": "https://example.com/about",
                "excerpt": "Example Components is privately held and unlisted.",
            }],
            "screening": {
                "fit_label": label,
                "mandatory": [{"check": "listing_status", "result": "pass"}],
            },
        }],
    }


def _finder(_company, _geography, _client, _domain, _names=None):
    return [{
        "apollo_id": "person-1",
        "first_name": "Anita",
        "last_name": "Shah",
        "name": "Anita Shah",
        "title": "Managing Director",
        "email": "anita@example.com",
        "email_status": "verified",
        "company": "Example Components",
    }]


class FakeComposio:
    def __init__(self):
        self.calls = []

    def execute(self, action, arguments, toolkit):
        self.calls.append((action, arguments, toolkit))
        return {"message_id": "msg-1", "id": "provider-1"}


class OutreachTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        folder = self.root / MANDATE["mandate_id"]
        folder.mkdir(parents=True)
        (folder / "orchestrator-run.json").write_text(json.dumps(_package()))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _prepare(self):
        return prepare(
            MANDATE["mandate_id"],
            "company-1",
            runs_root=self.root,
            client=object(),
            contact_finder=_finder,
        )

    def test_prepare_only_accepts_mandate_fit_entity(self) -> None:
        run = self.root / MANDATE["mandate_id"] / "orchestrator-run.json"
        run.write_text(json.dumps(_package("INSUFFICIENT_EVIDENCE")))
        with self.assertRaisesRegex(ValueError, "fit the buy box"):
            self._prepare()
        self.assertEqual(list_drafts(MANDATE["mandate_id"], self.root), [])

    def test_prepare_rejects_fit_label_without_unlisted_gate(self) -> None:
        package = _package()
        package["entities"][0]["screening"]["mandatory"] = []
        run = self.root / MANDATE["mandate_id"] / "orchestrator-run.json"
        run.write_text(json.dumps(package))
        with self.assertRaisesRegex(ValueError, "proof that the company is unlisted"):
            self._prepare()

    def test_prepare_creates_pending_draft_without_provider_call(self) -> None:
        draft = self._prepare()
        self.assertEqual(draft["status"], "pending_approval")
        self.assertEqual(draft["contact"]["email"], "anita@example.com")
        self.assertIn("No assumption", draft["body"])

    def test_prepare_reuses_existing_open_draft(self) -> None:
        first = self._prepare()
        second = self._prepare()
        self.assertEqual(second["draft_id"], first["draft_id"])
        self.assertEqual(len(list_drafts(MANDATE["mandate_id"], self.root)), 1)

    def test_company_domain_prefers_first_party_source(self) -> None:
        entity = _package()["entities"][0]
        entity["claims"].insert(0, {
            "field": "revenue",
            "value": "100",
            "source_url": "https://www.careratings.com/report.pdf",
        })
        self.assertEqual(_company_domain(entity), "example.com")

    def test_relationship_names_split_director_and_partner(self) -> None:
        names = _relationship_names({
            "claims": [
                {"field": "relationship", "value": "Himanshubhai Dolatram Nandwana — Designated Partner"},
                {"field": "relationship", "value": "Sureshbhai Dolatram Nandwana - Designated Partner"},
                {"field": "ownership", "value": "family"},
            ]
        })
        self.assertEqual(names, [
            "Himanshubhai Dolatram Nandwana",
            "Sureshbhai Dolatram Nandwana",
        ])

    def test_decision_maker_titles_cover_owner_leadership(self) -> None:
        for title in (
            "Founder", "CEO", "Managing Director", "Director",
            "Designated Partner", "Chairman", "Chairperson",
        ):
            self.assertIn(title, DECISION_MAKER_TITLES)

    def test_delivery_requires_approval(self) -> None:
        draft = self._prepare()
        api = FakeComposio()
        with self.assertRaisesRegex(ValueError, "Approve"):
            deliver(MANDATE["mandate_id"], draft["draft_id"], "gmail", runs_root=self.root, client=api)
        self.assertEqual(api.calls, [])

    def test_approved_gmail_draft_sends_only_on_explicit_delivery(self) -> None:
        draft = self._prepare()
        approved = approve(
            MANDATE["mandate_id"],
            draft["draft_id"],
            "Edited subject",
            "Edited body",
            self.root,
        )
        self.assertEqual(approved["status"], "approved")
        api = FakeComposio()
        sent = deliver(MANDATE["mandate_id"], draft["draft_id"], "gmail", runs_root=self.root, client=api)
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(api.calls[0][0], "GMAIL_SEND_EMAIL")
        self.assertEqual(api.calls[0][1]["body"], "Edited body")

    def test_instantly_is_created_inactive(self) -> None:
        draft = self._prepare()
        approve(MANDATE["mandate_id"], draft["draft_id"], draft["subject"], draft["body"], self.root)
        api = FakeComposio()
        result = deliver(MANDATE["mandate_id"], draft["draft_id"], "instantly", runs_root=self.root, client=api)
        self.assertEqual(result["status"], "provider_draft")
        self.assertEqual([call[0] for call in api.calls], [
            "INSTANTLY_CREATE_CAMPAIGN",
            "INSTANTLY_ADD_LEADS_BULK",
        ])
        self.assertNotIn("INSTANTLY_ACTIVATE_CAMPAIGN", [call[0] for call in api.calls])

    def test_suppression_is_rechecked_before_delivery(self) -> None:
        draft = self._prepare()
        approve(MANDATE["mandate_id"], draft["draft_id"], draft["subject"], draft["body"], self.root)
        suppress(MANDATE["mandate_id"], email="anita@example.com", runs_root=self.root)
        api = FakeComposio()
        with self.assertRaisesRegex(ValueError, "do-not-contact"):
            deliver(MANDATE["mandate_id"], draft["draft_id"], "gmail", runs_root=self.root, client=api)
        self.assertEqual(api.calls, [])

    def test_credentials_never_enter_persisted_draft(self) -> None:
        draft = self._prepare()
        serialized = json.dumps(draft)
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("connected_account", serialized.lower())


if __name__ == "__main__":
    unittest.main()
