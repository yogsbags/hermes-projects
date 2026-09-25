"""Mandate-scoped outreach with explicit human approval.

Contact lookup may discover emails and the desk may prepare copy, but no
provider action is allowed until a user approves the exact draft. Gmail
sends only after a second explicit action. Instantly campaigns are created
inactive.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from orchestrator.deterministic import listing_gate_passes


RUNS_ROOT = Path(__file__).resolve().parents[1] / "runs"
LEGACY_ENV_FILES = (
    Path.home() / "Downloads" / "Marqq-test" / ".env",
    Path.home() / "Downloads" / "Marqq-test" / ".env.marqq-live",
)
COMPOSIO_BASE = "https://backend.composio.dev/api/v3"
APOLLO_BASE = "https://api.apollo.io/api/v1"
APIFY_BASE = "https://api.apify.com/v2"
APIFY_CONTACT_ACTOR = "code_crafter~leads-finder"
DECISION_MAKER_TITLES = [
    "Founder", "Co-Founder", "CEO", "Chief Executive Officer",
    "Managing Director", "Whole-time Director", "Director",
    "Designated Partner", "Partner", "Promoter",
    "Chairman", "Executive Chairman", "Chairperson",
    "Owner", "President", "CFO",
]
_NAME_SPLIT = re.compile(r"\s+[—–-]\s+")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env() -> None:
    configured = os.environ.get("AVEYRONI_OUTREACH_ENV_FILE", "").strip()
    paths = (Path(configured).expanduser(),) if configured else LEGACY_ENV_FILES
    for path in paths:
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if value and not os.environ.get(key):
                os.environ[key] = value


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _read_json(path: Path, default):
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default
    return value


def _draft_path(mandate_id: str, runs_root: Path = RUNS_ROOT) -> Path:
    return Path(runs_root) / mandate_id / "outreach-drafts.json"


def _suppression_path(mandate_id: str, runs_root: Path = RUNS_ROOT) -> Path:
    return Path(runs_root) / mandate_id / "outreach-suppressions.json"


def _run_path(mandate_id: str, runs_root: Path = RUNS_ROOT) -> Path:
    return Path(runs_root) / mandate_id / "orchestrator-run.json"


def readiness() -> dict:
    _load_env()
    missing = []
    if not os.environ.get("COMPOSIO_API_KEY"):
        missing.append("Composio API key")
    return {"ready": not missing, "missing": missing}


class ComposioClient:
    def __init__(self, api_key: str | None = None, user_id: str | None = None):
        _load_env()
        self.api_key = api_key or os.environ.get("COMPOSIO_API_KEY", "")
        self.user_id = user_id or os.environ.get("AVEYRONI_COMPOSIO_USER_ID", "marqq-ws-1")
        if not self.api_key:
            raise ValueError("Outreach is not configured: COMPOSIO_API_KEY is missing.")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        request = Request(
            f"{COMPOSIO_BASE}{path}",
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS host
                payload = json.loads(response.read().decode() or "{}")
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise RuntimeError(f"Composio returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"Composio could not be reached: {exc}") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload

    def connected_account(self, toolkit: str) -> str:
        query = urlencode({"user_id": self.user_id, "limit": 100})
        payload = self._request("GET", f"/connected_accounts?{query}")
        rows = payload.get("items") or payload.get("data") or payload.get("connected_accounts") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or []
        toolkit = toolkit.lower()
        for row in rows:
            label = str(
                row.get("toolkit", {}).get("slug")
                if isinstance(row.get("toolkit"), dict)
                else row.get("toolkit") or row.get("appName") or row.get("app_name") or ""
            ).lower()
            status = str(row.get("status") or "active").lower()
            if toolkit in label and status not in {"expired", "failed", "inactive"}:
                account_id = row.get("id") or row.get("connected_account_id")
                if account_id:
                    return str(account_id)
        raise RuntimeError(f"No active {toolkit.title()} account is connected for outreach.")

    def execute(self, action: str, arguments: dict, toolkit: str) -> dict:
        payload = self._request(
            "POST",
            f"/tools/execute/{action}",
            {
                "user_id": self.user_id,
                "arguments": arguments,
                "connected_account_id": self.connected_account(toolkit),
            },
        )
        return payload.get("data") if isinstance(payload.get("data"), dict) else payload

    def proxy(self, endpoint: str, body: dict, toolkit: str, method: str = "POST") -> dict:
        payload = self._request(
            "POST",
            "/tools/execute/proxy",
            {
                "connected_account_id": self.connected_account(toolkit),
                "endpoint": endpoint,
                "method": method.upper(),
                "parameters": [],
                "body": body,
            },
        )
        result = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(result, dict) and result.get("message") and len(result) == 1:
            raise RuntimeError(str(result["message"]))
        return result


def _apollo_direct(path: str, body: dict) -> dict:
    _load_env()
    api_key = os.environ.get("APOLLO_API_KEY", "")
    if not api_key:
        raise RuntimeError("Contact lookup is not configured.")
    request = Request(
        f"{APOLLO_BASE}/{path.lstrip('/')}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS host
            return json.loads(response.read().decode() or "{}")
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Contact lookup returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Contact lookup could not be reached.") from exc


def _apify_contacts(domain: str, geography: list[str]) -> list[dict]:
    _load_env()
    token = os.environ.get("APIFY_TOKEN", "")
    if not token or not domain:
        return []
    request = Request(
        f"{APIFY_BASE}/acts/{APIFY_CONTACT_ACTOR}/run-sync-get-dataset-items"
        "?timeout=120&memory=256&clean=true",
        data=json.dumps({
            "fetch_count": 5,
            "file_name": f"Aveyroni contact lookup — {domain}",
            "company_domain": [domain],
            "contact_job_title": DECISION_MAKER_TITLES,
            "seniority_level": ["founder", "owner", "c_suite", "director", "partner"],
            "contact_location": [str(item).lower() for item in geography],
            "email_status": ["validated"],
        }).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=150) as response:  # noqa: S310 - fixed HTTPS host
            rows = json.loads(response.read().decode() or "[]")
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Contact lookup returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Contact lookup could not be reached.") from exc
    if not isinstance(rows, list):
        return []
    contacts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        email = str(row.get("email") or "").strip().lower()
        result_domain = str(row.get("company_domain") or "").strip().lower()
        if not EMAIL_RE.match(email) or result_domain.removeprefix("www.") != domain.removeprefix("www."):
            continue
        contacts.append({
            "apollo_id": "",
            "first_name": str(row.get("first_name") or ""),
            "last_name": str(row.get("last_name") or ""),
            "name": str(row.get("full_name") or "").strip(),
            "title": str(row.get("job_title") or ""),
            "email": email,
            "email_status": "validated",
            "company": str(row.get("company_name") or ""),
            "source": "apify",
        })
    return contacts


def _walk_lists(value):
    if isinstance(value, list):
        yield value
        for item in value:
            yield from _walk_lists(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_lists(item)


def _people_from_response(payload: dict) -> list[dict]:
    candidates = []
    for rows in _walk_lists(payload):
        for row in rows:
            if not isinstance(row, dict):
                continue
            email = str(row.get("email") or row.get("email_address") or "").strip()
            person_id = row.get("id") or row.get("person_id")
            name = row.get("name") or row.get("full_name")
            if person_id or email or name:
                candidates.append(row)
    seen = set()
    unique = []
    for row in candidates:
        key = str(row.get("id") or row.get("person_id") or row.get("email") or row.get("name"))
        if key and key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _contact(row: dict, company: str) -> dict:
    name = str(row.get("name") or row.get("full_name") or "").strip()
    first = str(row.get("first_name") or (name.split()[0] if name else "")).strip()
    last = str(row.get("last_name") or (" ".join(name.split()[1:]) if name else "")).strip()
    org = row.get("organization") if isinstance(row.get("organization"), dict) else {}
    return {
        "apollo_id": str(row.get("id") or row.get("person_id") or ""),
        "first_name": first,
        "last_name": last,
        "name": name or " ".join(part for part in (first, last) if part),
        "title": str(row.get("title") or row.get("job_title") or ""),
        "email": str(row.get("email") or row.get("email_address") or "").strip().lower(),
        "email_status": str(row.get("email_status") or row.get("status") or ""),
        "company": str(org.get("name") or row.get("organization_name") or company),
    }


def _relationship_names(entity: dict) -> list[str]:
    names = []
    for claim in entity.get("claims") or []:
        if claim.get("field") != "relationship":
            continue
        text = " ".join(str(claim.get("value") or "").split())
        if not text:
            continue
        person = _NAME_SPLIT.split(text, 1)[0].strip()
        if person and person not in names:
            names.append(person)
    return names[:4]


def _people_search(arguments: dict, client: ComposioClient, failures: list[str]) -> dict:
    response = {}
    if os.environ.get("APOLLO_API_KEY"):
        try:
            response = _apollo_direct("mixed_people/api_search", arguments)
        except RuntimeError as exc:
            failures.append(str(exc))
    if not _people_from_response(response):
        try:
            response = client.proxy(
                "https://api.apollo.io/api/v1/mixed_people/api_search",
                arguments,
                "apollo",
            )
        except RuntimeError as exc:
            failures.append(str(exc))
    if not _people_from_response(response):
        try:
            response = client.execute("APOLLO_PEOPLE_SEARCH", arguments, "apollo")
        except RuntimeError as exc:
            failures.append(str(exc))
    return response


def _contacts_from_people(people: list[dict], company: str, client: ComposioClient) -> list[dict]:
    contacts = []
    for person in people:
        if person.get("id") or person.get("person_id"):
            try:
                person_id = person.get("id") or person.get("person_id")
                if os.environ.get("APOLLO_API_KEY"):
                    enriched = _apollo_direct(
                        "people/match",
                        {"id": person_id, "reveal_personal_emails": True},
                    )
                else:
                    enriched = client.execute(
                        "APOLLO_PEOPLE_ENRICHMENT",
                        {"id": person_id},
                        "apollo",
                    )
                enriched_people = _people_from_response(enriched)
                if enriched_people:
                    person = {**person, **enriched_people[0]}
            except RuntimeError:
                pass
        item = _contact(person, company)
        item["source"] = "apollo"
        if EMAIL_RE.match(item["email"]):
            contacts.append(item)
    return contacts


def find_contacts(
    company: str,
    geography: list[str],
    client: ComposioClient,
    domain: str = "",
    names: list[str] | None = None,
) -> list[dict]:
    arguments = {
        "page": 1,
        "per_page": 10,
        "q_organization_name": company,
        "person_titles": DECISION_MAKER_TITLES,
        "person_locations": geography,
        "contact_email_status": ["verified", "likely to engage"],
    }
    failures = []
    _load_env()
    response = _people_search(arguments, client, failures)
    if not _people_from_response(response):
        broad = dict(arguments)
        broad.pop("contact_email_status", None)
        response = _people_search(broad, client, failures)
    contacts = _contacts_from_people(_people_from_response(response), company, client)
    if not contacts:
        for name in names or []:
            named = {
                "page": 1,
                "per_page": 5,
                "q_organization_name": company,
                "q_keywords": name,
                "person_locations": geography,
            }
            named_response = _people_search(named, client, failures)
            contacts = _contacts_from_people(_people_from_response(named_response), company, client)
            if contacts:
                break
    if contacts:
        return contacts
    try:
        return _apify_contacts(domain, geography)
    except RuntimeError as exc:
        failures.append(str(exc))
    if any("payment" in message.lower() for message in failures):
        raise RuntimeError("Contact lookup is unavailable until billing is updated.")
    return []


def _fit_entity(mandate_id: str, entity_id: str, runs_root: Path) -> tuple[dict, dict]:
    package = _read_json(_run_path(mandate_id, runs_root), {})
    for entity in package.get("entities") or []:
        if entity.get("entity_id") == entity_id:
            if (entity.get("screening") or {}).get("fit_label") != "MANDATE_FIT":
                raise ValueError("Outreach is restricted to companies that fit the buy box.")
            if (package.get("mandate") or {}).get("focus") != "real-estate" and not listing_gate_passes(entity):
                raise ValueError("Outreach requires sourced proof that the company is unlisted.")
            return package.get("mandate") or {}, entity
    raise ValueError("That company is not in the active mandate's screened results.")


def list_drafts(mandate_id: str, runs_root: Path = RUNS_ROOT) -> list[dict]:
    value = _read_json(_draft_path(mandate_id, runs_root), [])
    return value if isinstance(value, list) else []


def list_suppressions(mandate_id: str, runs_root: Path = RUNS_ROOT) -> list[dict]:
    value = _read_json(_suppression_path(mandate_id, runs_root), [])
    return value if isinstance(value, list) else []


def _suppressed(mandate_id: str, entity_id: str, email: str, runs_root: Path) -> bool:
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    for row in list_suppressions(mandate_id, runs_root):
        if row.get("entity_id") == entity_id:
            return True
        if email and str(row.get("email") or "").lower() == email.lower():
            return True
        if domain and str(row.get("domain") or "").lower() == domain:
            return True
    return False


def _facts(entity: dict) -> list[str]:
    facts = []
    for claim in entity.get("claims") or []:
        if claim.get("field") in {"sector", "geography", "ownership", "business_model"} and claim.get("value"):
            facts.append(f"{claim['field'].replace('_', ' ')}: {claim['value']}")
    return facts[:3]


def _company_domain(entity: dict) -> str:
    third_party = {
        "bseindia.com", "careratings.com", "icra.in", "thecompanycheck.com",
        "dbonline.in", "nsrpartners.com", "zaubacorp.com", "tofler.in",
    }
    for claim in entity.get("claims") or []:
        host = urlparse(str(claim.get("source_url") or "")).netloc.lower().removeprefix("www.")
        if host and not any(host == item or host.endswith("." + item) for item in third_party):
            return host
    return ""


def default_copy(contact: dict, entity: dict, mandate: dict) -> dict:
    sender = os.environ.get("OUTREACH_SENDER_NAME", "Yogesh").strip() or "Yogesh"
    first = contact.get("first_name") or "there"
    company = entity.get("name") or contact.get("company") or "your company"
    sectors = ", ".join(mandate.get("sector") or [])
    geography = ", ".join(mandate.get("geography") or [])
    focus = " in ".join(value for value in (sectors, geography) if value)
    context = f" in {focus}" if focus else ""
    return {
        "subject": f"Exploring a partnership with {company}"[:50],
        "body": (
            f"Hi {first},\n\n"
            f"I'm reaching out because we are evaluating established, privately held businesses{context}, "
            f"and {company} appears relevant to our investment focus.\n\n"
            "Would you be open to a short, confidential introduction to see whether our long-term approach "
            "could be useful to you? No assumption that you are seeking a transaction.\n\n"
            f"Best,\n{sender}"
        ),
    }


def prepare(
    mandate_id: str,
    entity_id: str,
    *,
    runs_root: Path = RUNS_ROOT,
    client=None,
    contact_finder: Callable | None = None,
    copy_writer: Callable | None = None,
) -> dict:
    mandate, entity = _fit_entity(mandate_id, entity_id, runs_root)
    if _suppressed(mandate_id, entity_id, "", runs_root):
        raise ValueError("This company is on the mandate's do-not-contact list.")
    existing = next(
        (
            row for row in reversed(list_drafts(mandate_id, runs_root))
            if row.get("entity_id") == entity_id
            and row.get("status") in {"pending_approval", "approved"}
        ),
        None,
    )
    if existing:
        return existing
    finder = contact_finder or find_contacts
    contacts = finder(
        entity.get("name") or "",
        mandate.get("geography") or [],
        client or ComposioClient(),
        _company_domain(entity),
        _relationship_names(entity),
    )
    if not contacts:
        raise ValueError("No usable email was found for a founder, director, or other decision-maker at this company.")
    contact = contacts[0]
    if _suppressed(mandate_id, entity_id, contact["email"], runs_root):
        raise ValueError("This contact is on the mandate's do-not-contact list.")
    writer = copy_writer or default_copy
    copy = writer(contact, entity, mandate)
    subject = str(copy.get("subject") or "").strip()
    body = str(copy.get("body") or "").strip()
    if not subject or not body:
        raise ValueError("The outreach writer returned an empty subject or body.")
    draft = {
        "draft_id": "outreach-" + uuid.uuid4().hex[:12],
        "mandate_id": mandate_id,
        "entity_id": entity_id,
        "company": entity.get("name") or "",
        "contact": contact,
        "fit_facts": _facts(entity),
        "subject": subject[:120],
        "body": body[:4000],
        "status": "pending_approval",
        "provider": None,
        "created_at": _now(),
        "updated_at": _now(),
        "approved_at": None,
        "sent_at": None,
        "provider_receipt": None,
        "error": None,
    }
    with LOCK:
        drafts = list_drafts(mandate_id, runs_root)
        drafts.append(draft)
        _atomic_json(_draft_path(mandate_id, runs_root), drafts)
    return draft


def _update_draft(mandate_id: str, draft_id: str, updater, runs_root: Path) -> dict:
    with LOCK:
        drafts = list_drafts(mandate_id, runs_root)
        for index, draft in enumerate(drafts):
            if draft.get("draft_id") == draft_id:
                drafts[index] = updater(dict(draft))
                drafts[index]["updated_at"] = _now()
                _atomic_json(_draft_path(mandate_id, runs_root), drafts)
                return drafts[index]
    raise ValueError("Outreach draft not found for this mandate.")


def approve(mandate_id: str, draft_id: str, subject: str, body: str, runs_root: Path = RUNS_ROOT) -> dict:
    subject, body = subject.strip(), body.strip()
    if not subject or not body:
        raise ValueError("Subject and body are required.")

    def update(draft):
        if draft.get("status") not in {"pending_approval", "approved"}:
            raise ValueError("Only a pending draft can be approved.")
        draft.update({"subject": subject[:120], "body": body[:4000], "status": "approved", "approved_at": _now()})
        return draft

    return _update_draft(mandate_id, draft_id, update, runs_root)


def reject(mandate_id: str, draft_id: str, runs_root: Path = RUNS_ROOT) -> dict:
    def update(draft):
        if draft.get("status") in {"sent", "provider_draft"}:
            raise ValueError("A provider-processed draft cannot be rejected.")
        draft["status"] = "rejected"
        return draft

    return _update_draft(mandate_id, draft_id, update, runs_root)


def _receipt(payload: dict) -> dict:
    result = payload.get("response_data") if isinstance(payload.get("response_data"), dict) else payload
    return {
        key: result.get(key)
        for key in ("id", "draft_id", "message_id", "campaign_id", "thread_id")
        if result.get(key) is not None
    }


def deliver(
    mandate_id: str,
    draft_id: str,
    provider: str,
    *,
    runs_root: Path = RUNS_ROOT,
    client=None,
) -> dict:
    drafts = list_drafts(mandate_id, runs_root)
    draft = next((row for row in drafts if row.get("draft_id") == draft_id), None)
    if not draft:
        raise ValueError("Outreach draft not found for this mandate.")
    if draft.get("status") != "approved":
        raise ValueError("Approve the exact draft before using an email provider.")
    email = str((draft.get("contact") or {}).get("email") or "")
    if _suppressed(mandate_id, draft.get("entity_id") or "", email, runs_root):
        raise ValueError("This company or contact is on the mandate's do-not-contact list.")
    api = client or ComposioClient()
    provider = provider.lower()
    if provider == "gmail":
        payload = api.execute(
            "GMAIL_SEND_EMAIL",
            {
                "recipient_email": email,
                "to": email,
                "subject": draft["subject"],
                "body": draft["body"],
                "message_body": draft["body"],
            },
            "gmail",
        )
        status = "sent"
    elif provider == "instantly":
        payload = api.execute(
            "INSTANTLY_CREATE_CAMPAIGN",
            {
                "name": f"{draft['company']} — {draft['draft_id']}"[:100],
                "sequences": [{
                    "steps": [{
                        "type": "email",
                        "delay": 0,
                        "variants": [{"subject": draft["subject"], "body": draft["body"]}],
                    }]
                }],
                "daily_limit": 1,
                "stop_on_reply": True,
                "open_tracking": True,
                "link_tracking": True,
            },
            "instantly",
        )
        campaign_id = (
            payload.get("id") or payload.get("campaign_id")
            or (payload.get("response_data") or {}).get("id")
        )
        if campaign_id:
            api.execute(
                "INSTANTLY_ADD_LEADS_BULK",
                {
                    "campaign_id": campaign_id,
                    "leads": [{
                        "email": email,
                        "first_name": draft["contact"].get("first_name", ""),
                        "last_name": draft["contact"].get("last_name", ""),
                        "company_name": draft["company"],
                    }],
                    "skip_if_in_campaign": True,
                    "skip_if_in_workspace": False,
                    "verify": False,
                },
                "instantly",
            )
        status = "provider_draft"
    else:
        raise ValueError("Provider must be gmail or instantly.")

    def update(row):
        if row.get("status") != "approved":
            raise ValueError("Draft status changed before delivery.")
        row.update({
            "status": status,
            "provider": provider,
            "sent_at": _now() if status == "sent" else None,
            "provider_receipt": _receipt(payload),
            "error": None,
        })
        return row

    return _update_draft(mandate_id, draft_id, update, runs_root)


def suppress(
    mandate_id: str,
    *,
    entity_id: str = "",
    email: str = "",
    domain: str = "",
    reason: str = "user_request",
    runs_root: Path = RUNS_ROOT,
) -> dict:
    if not any((entity_id, email, domain)):
        raise ValueError("Choose a company, email, or domain to suppress.")
    row = {
        "suppression_id": "suppress-" + uuid.uuid4().hex[:12],
        "entity_id": entity_id,
        "email": email.strip().lower(),
        "domain": domain.strip().lower(),
        "reason": reason,
        "created_at": _now(),
    }
    with LOCK:
        rows = list_suppressions(mandate_id, runs_root)
        rows.append(row)
        _atomic_json(_suppression_path(mandate_id, runs_root), rows)
    return row
