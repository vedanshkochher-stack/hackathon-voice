"""Adapters for IndiaMART systems (the organisers' starter API list).

Each adapter only knows two things: how to fetch rows for a GLID since a timestamp, and how to map
one row to a normalised event. Endpoints/credentials come from env vars so the same code runs
against staging and prod. They are inactive until IM_<NAME>_URL is set; the pipeline then simply
has fewer sources (graceful degradation), and the synthetic source fills gaps for the demo.

Mapping table (source -> event type -> file section):
  Enquiry / BuyLead API    -> enquiry.created / .update / .status -> buyer.md "Enquiries"
  BL purchase / Lead API   -> lead.received / lead.response        -> seller.md "Leads", "Responses"
  PNS call logs            -> pns.call (fanned out to both GLIDs)  -> buyer "Sellers contacted", seller "Missed calls"
                              (also queryable via the Call Insights connector: run_pns_query on pns_insight)
  Search logs              -> search                               -> buyer.md "Categories searched"
  KYC API                  -> kyc.update                           -> both "KYC"
  User / seller profile    -> profile.update                       -> frontmatter "known"
  Bot platforms (VANI, WA) -> conversation.update / .ended         -> "Conversations", open_thread
  Engagement / app events  -> engagement                           -> "Engagement"
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx

from ..util import iso
from .base import Source, SourceUnavailable


class HttpSource(Source):
    env_key = ""
    event_type = ""
    role = "buyer"

    def __init__(self):
        self.url = os.environ.get(f"IM_{self.env_key}_URL", "")
        self.token = os.environ.get("IM_API_TOKEN", "")

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _fetch(self, glid: str | None, since: datetime | None) -> list[dict]:
        try:
            r = httpx.get(self.url, params={"glid": glid, "since": iso(since) if since else None},
                          headers={"Authorization": f"Bearer {self.token}"}, timeout=5)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"{self.name}: {e}") from e
        return r.json().get("data", [])

    def pull(self, glid: str | None, since: datetime | None) -> list[dict]:
        if not self.enabled:
            return []
        return [self.normalize(glid, row) for row in self._fetch(glid, since)]

    def normalize(self, glid: str, row: dict) -> dict:  # override per API
        raise NotImplementedError


class EnquiryAPI(HttpSource):
    name, env_key, role = "enquiry_api", "ENQUIRY", "buyer"

    def normalize(self, glid, row):
        return {"event_id": f"enq-{row['ENQ_ID']}-{row.get('STATUS', 'new')}", "glid": glid, "role": "buyer",
                "type": "enquiry.created" if row.get("STATUS") in (None, "NEW") else "enquiry.status",
                "occurred_at": row["MODIFIED_DATE"], "source": self.name,
                "payload": {"enq_id": row["ENQ_ID"], "product": row.get("PRODUCT_NAME"),
                            "quantity": row.get("QTY"), "unit": row.get("QTY_UNIT"),
                            "specs": row.get("ISQ", {}), "city": row.get("CITY"),
                            "status": (row.get("STATUS") or "open").lower()}}


class LeadAPI(HttpSource):
    name, env_key, role = "lead_api", "LEADS", "seller"

    def normalize(self, glid, row):
        return {"event_id": f"lead-{row['OFR_ID']}-{glid}", "glid": glid, "role": "seller",
                "type": "lead.received", "occurred_at": row["PURCHASE_DATE"], "source": self.name,
                "counterparty": str(row.get("BUYER_GLID")),
                "payload": {"lead_id": f"L-{row['OFR_ID']}", "product": row.get("PRODUCT_NAME"),
                            "quantity": row.get("QTY"), "unit": row.get("QTY_UNIT"),
                            "specs": row.get("ISQ", {}), "buyer_city": row.get("BUYER_CITY"),
                            "buyer_state": row.get("BUYER_STATE"), "via": "BL purchase"}}


class PNSCalls(HttpSource):
    """One PNS row becomes TWO events (buyer + seller views), each with only its own fields."""
    name, env_key = "pns_api", "PNS"

    def pull(self, glid, since):
        if not self.enabled:
            return []
        return [ev for row in self._fetch(glid, since) for ev in self.fanout(row)]

    @staticmethod
    def fanout(row: dict) -> list[dict]:
        base = {"occurred_at": row["CALL_TIME"], "source": "pns_api"}
        answered = row.get("CALL_STATUS") == "ANSWERED"
        return [
            {**base, "event_id": f"pns-{row['CALL_ID']}-b", "glid": str(row["CALLER_GLID"]), "role": "buyer",
             "type": "pns.call", "counterparty": str(row["RECEIVER_GLID"]),
             "payload": {"seller_glid": str(row["RECEIVER_GLID"]), "seller_name": row.get("RECEIVER_COMPANY"),
                         "seller_city": row.get("RECEIVER_CITY"), "product": row.get("MCAT_NAME"),
                         "answered": answered, "duration_s": row.get("DURATION", 0)}},
            {**base, "event_id": f"pns-{row['CALL_ID']}-s", "glid": str(row["RECEIVER_GLID"]), "role": "seller",
             "type": "pns.call", "counterparty": str(row["CALLER_GLID"]),
             "payload": {"buyer_city": row.get("CALLER_CITY"), "buyer_state": row.get("CALLER_STATE"),
                         "product": row.get("MCAT_NAME"), "answered": answered}},
        ]


class KYCAPI(HttpSource):
    name, env_key = "kyc_api", "KYC"

    def normalize(self, glid, row):
        return {"event_id": f"kyc-{glid}-{row['UPDATED_AT']}", "glid": glid, "role": row.get("ROLE", "buyer"),
                "type": "kyc.update", "occurred_at": row["UPDATED_AT"], "source": self.name,
                "payload": {"mobile_verified": row.get("MOBILE_VERIFIED") == "Y",
                            "email_verified": row.get("EMAIL_VERIFIED") == "Y",
                            "gst_verified": row.get("GST_VERIFIED") == "Y"}}


INDIAMART_SOURCES = [EnquiryAPI(), LeadAPI(), PNSCalls(), KYCAPI()]
