"""Lift measurement: same buyer/seller, same simulated answers, cold start vs context file.

A scripted user answers whatever the bot asks from a ground-truth profile (SYNTHETIC). We count
questions the bot asked, re-asks of facts the context file already held, user turns to reach the
goal, and estimated voice seconds. Sessions run with persist=False so the store is untouched.
"""
from __future__ import annotations

TRUTH = {  # SYNTHETIC ground truth for the simulated users
    "50112001": {"product": "PVC pipe", "quantity": "500 piece", "Size": "4 inch", "Pressure Rating": "6 kg",
                 "name": "Ramesh", "city": "Indore", "state": "Madhya Pradesh", "call_product": "PVC Pipe"},
    "50112002": {"product": "RO plant", "quantity": "1 unit", "Capacity": "2000 LPH", "Body Material": "SS 304",
                 "name": "Lakshmi", "city": "Hyderabad", "state": "Telangana", "call_product": "Industrial RO Plant"},
    "50112003": {"product": "bubble wrap", "quantity": "500 roll", "Width": "1 meter", "Thickness": "70 micron",
                 "name": "Arjun", "city": "Ahmedabad", "state": "Gujarat", "call_product": None},
    "70221001": {"lead": "haan baat hui, quotation bhej diya", "pref_min_qty": "100 piece", "pref_regions": "Maharashtra, MP, Gujarat"},
    "70221002": {"lead": "haan, order mil gaya", "pref_min_qty": "100 roll", "pref_regions": "Gujarat, Maharashtra"},
    "70221003": {"lead": "nahi abhi call nahi kiya", "resend": "haan bhej do", "pref_min_qty": "1 unit", "pref_regions": "Telangana, Andhra Pradesh"},
}
SECONDS_PER_TURN = 9  # avg voice turn: ~5 s bot speech + ~4 s buyer reply (VANI call samples)


def _answer(truth: dict, expect: str | None, role: str) -> str:
    if role == "seller":
        if expect and expect.startswith("lead_followup"):
            return truth["lead"]
        if expect and expect.startswith("lead_outcome"):
            return "quotation bhej diya"
        if expect == "resend":
            return truth.get("resend", "haan")
        if expect in truth:
            return truth[expect]
        return "haan"
    if expect == "product":
        return truth["product"]
    if expect in ("product_confirm", "transfer", "transfer_feedback"):
        return "haan"
    return truth.get(expect, "haan")


def run_one(engine, glid: str, role: str, warm: bool, channel: str = "voice", max_turns: int = 14) -> dict:
    truth = TRUTH[glid]
    r = engine.start(glid, role, channel, warm=warm, persist=False, reply_mode="template",
                     call_product=truth.get("call_product") if role == "buyer" else None)
    s = engine.sessions[r["session_id"]]
    turns = 0
    while not s.ended and turns < max_turns:
        engine.message(s.id, _answer(truth, s.expect, role))
        turns += 1
    if not s.ended:
        engine.end(s.id)
    return {"glid": glid, "role": role, "mode": "warm" if warm else "cold", "opening": r["opening"],
            "scenario": r["scenario"], "facts_in_opening": len(r["facts"]), "questions": s.metrics["questions"],
            "reasks_of_known": s.metrics["reasks_of_known"], "user_turns": turns, "outcome": s.outcome,
            "goal_met": (s.outcome in ("transferred", "no_live_seller")) if role == "buyer"
            else any(k.startswith("lead_") for k in s.captured_session),
            "est_seconds": (turns + 1) * SECONDS_PER_TURN}


def lift_report(engine) -> dict:
    rows = []
    for glid, truth in TRUTH.items():
        role = "seller" if glid.startswith("7") else "buyer"
        cold = run_one(engine, glid, role, warm=False)
        warm = run_one(engine, glid, role, warm=True)
        rows.append({"glid": glid, "role": role, "cold": cold, "warm": warm,
                     "questions_saved": cold["questions"] - warm["questions"],
                     "turns_saved": cold["user_turns"] - warm["user_turns"],
                     "seconds_saved": cold["est_seconds"] - warm["est_seconds"]})
    tot = lambda k, m: sum(r[m][k] for r in rows)  # noqa: E731
    summary = {"cold_questions": tot("questions", "cold"), "warm_questions": tot("questions", "warm"),
               "cold_reasks": tot("reasks_of_known", "cold"), "warm_reasks": tot("reasks_of_known", "warm"),
               "cold_turns": tot("user_turns", "cold"), "warm_turns": tot("user_turns", "warm"),
               "cold_seconds": tot("est_seconds", "cold"), "warm_seconds": tot("est_seconds", "warm"),
               "personalised_openings": sum(1 for r in rows if r["warm"]["facts_in_opening"] > 0),
               "cold_goals": sum(1 for r in rows if r["cold"]["goal_met"]), "warm_goals": sum(1 for r in rows if r["warm"]["goal_met"])}
    return {"rows": rows, "summary": summary}
