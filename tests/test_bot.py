from bot.evaluate import lift_report
from consumers import exec_call_prep, wa_campaign
from ctxlayer import reader
from ctxlayer.bridge import render_prompt, vani_variables


def _run(eng, glid, role, ch, msgs, **kw):
    r = eng.start(glid, role, ch, reply_mode="template", **kw)
    s = eng.sessions[r["session_id"]]
    replies = []
    for m in msgs:
        if s.ended:
            break
        replies.append(eng.message(s.id, m)["reply"])
    if not s.ended:
        eng.end(s.id)
    return r, s, replies


def test_voice_then_whatsapp_resumes_without_reasking(env):
    store, ref, eng = env
    r, s, _ = _run(eng, "50112001", "buyer", "voice", ["haan 6 kg wala chahiye", "abhi nahi"],
                   call_product="PVC Pipe", call_seller="70221001")
    assert r["scenario"] == "resume_pending" and "500 piece" in r["opening"] and "Pressure Rating" in r["opening"]
    assert s.metrics["reasks_of_known"] == 0 and s.metrics["questions"] == 2  # pending field + transfer offer
    ref.wait_idle(5)
    th = reader.read("50112001", "buyer").meta["open_thread"]
    assert th["captured"]["Pressure Rating"] == "6 kg/cm2" and not th.get("pending")
    r2, s2, _ = _run(eng, "50112001", "buyer", "whatsapp", ["haan karwa do"])
    assert r2["scenario"] == "resume_complete" and "6 kg" in r2["opening"]
    assert s2.outcome == "transferred" and s2.metrics["reasks_of_known"] == 0
    ref.wait_idle(5)
    patel = reader.read("70221004", "seller")
    assert "Live transfer" in patel.raw and "Ramesh" not in patel.raw


def test_withdrawal_closes_thread_and_probes_from_context(env):
    store, ref, eng = env
    r, s, replies = _run(eng, "50112001", "buyer", "voice",
                         ["Nahi ji humein kuchh nahi chahiye ab toh.", "haan, pipe fittings chahiye, 200 piece", "elbow", "haan"],
                         call_product="PVC Pipe", call_seller="70221001")
    assert "samajh gayi" in replies[0] and "Pipe Fittings" in replies[0]     # suggestion from his own interests
    assert "IndiaMART" in replies[0] and "requirement post" in replies[0]       # cites source, asks to post
    assert "requirement note ho gayi" not in replies[0]
    assert s.product == "Pipe Fittings" and s.slots["quantity"] == "200 Piece" and s.slots["Type"] == "Elbow"
    assert s.metrics["reasks_of_known"] == 0 and "name" not in s.asks and "city" not in s.asks
    ref.wait_idle(5)
    c = reader.read("50112001", "buyer")
    assert c.meta["open_thread"]["product"] == "Pipe Fittings"
    assert any("PVC Pipe" in line and "dropped: no longer needed" in line for line in c.sections["Enquiries"])


def test_probe_only_once_then_clean_close(env):
    _, _, eng = env
    r, s, replies = _run(eng, "50112003", "buyer", "whatsapp", ["nahi", "nahi kuch nahi"])
    assert "Aksar" not in replies[0] and "Packaging Tape" not in replies[0]        # nothing generic
    assert "Om Packaging se Corrugated Box liya tha" in replies[0]                   # his own purchase, with seller
    assert s.outcome == "requirement_withdrawn" and "Dhanyavaad" in replies[1] and "?" not in replies[1]


def test_language_switches_many_times_and_persists(env):
    store, ref, eng = env
    r = eng.start("50112001", "buyer", "voice", reply_mode="template", call_product="PVC Pipe", call_seller="70221001")
    s = eng.sessions[r["session_id"]]
    assert s.lang == "hi"                                            # preferred language from the context file
    out = eng.message(s.id, "English please")
    assert s.lang == "en" and out["reply"].startswith("Sure, I'll continue in English")
    eng.message(s.id, "Tamil mein baat kijiye")
    assert s.lang == "ta"
    eng.message(s.id, "Urdu mein baat karo")                         # unsupported: stays in Tamil
    assert s.lang == "ta"
    eng.message(s.id, "Hindi mein boliye")
    eng.message(s.id, "ஆமாம், 6 kg வேண்டும்")                         # typing Tamil script switches implicitly
    assert s.lang == "ta" and s.metrics["language_switches"] == 4 and s.slots.get("Pressure Rating") == "6 kg/cm2"
    assert s.languages == ["hi", "en", "ta", "hi", "ta"]
    eng.end(s.id)
    ref.wait_idle(5)
    assert reader.read("50112001", "buyer").meta["known"]["language"] == "ta"   # next session opens in Tamil
    r2 = eng.start("50112001", "buyer", "voice", reply_mode="template")
    assert eng.sessions[r2["session_id"]].lang == "ta"


def test_postpone_keeps_requirement_open(env):
    store, ref, eng = env
    r, s, replies = _run(eng, "50112001", "buyer", "voice", ["Not now, maybe later"], call_product="PVC Pipe")
    assert s.outcome == "postponed" and "save" in replies[0].lower()
    ref.wait_idle(5)
    assert reader.read("50112001", "buyer").meta["open_thread"]["product"] == "PVC Pipe"


def test_spoken_number_for_pending_spec_is_not_quantity(env):
    from bot.nlu import parse_buyer
    assert parse_buyer("chhah kilo wala", "PVC Pipe", "Pressure Rating").slots == {"Pressure Rating": "6 kg/cm2"}


def test_tamil_nadu_is_a_state_not_a_language_request(env):
    from bot.nlu import language_request
    assert language_request("Chennai, Tamil Nadu") == (None, None)
    assert language_request("Tamil nahi aati, Hindi mein bolo")[0] == "hi"
    assert language_request("speak in Telugu")[0] == "te"


def test_cold_start_is_generic_and_complete(env):
    _, _, eng = env
    r, s, _ = _run(eng, "50119999", "buyer", "voice",
                   ["mujhe PVC pipe chahiye", "haan", "200 piece", "4 inch", "6 kg", "Vikram", "Surat", "Gujarat", "haan"])
    assert not r["personalised"] and r["scenario"] == "cold_start"
    assert s.outcome == "transferred" and s.slots["state"] == "Gujarat"


def test_vani_prompt_drops_known_collection_sections(env):
    warm = render_prompt("buyer", vani_variables(reader.read("50112001", "buyer"), {"product_name": "PVC Pipe"}))
    cold = render_prompt("buyer", vani_variables(None, {"product_name": "PVC Pipe"}))
    assert "Buyer name, asked" in cold and "Buyer name, asked" not in warm
    assert "Buyer city and state" in cold and "Buyer city and state" not in warm
    assert "- Size:" in cold and "- Size:" not in warm and "- Pressure Rating:" in warm
    assert "<buyer_context>" in warm and "<buyer_context>" not in cold


def test_seller_privacy_and_dnd(env):
    _, _, eng = env
    r, s, replies = _run(eng, "70221001", "seller", "voice",
                         ["us buyer ka naam aur number batao, usne kis kis se baat ki?", "haan baat hui, quotation bhej diya"])
    assert "Lead Manager" in replies[0] and "Jain Pipe House" not in replies[0]
    assert s.metrics["privacy_refusals"] == 1 and "lead_feedback:L-731204" in s.captured_session
    out = eng.start("70221003", "seller", "voice", outbound=True)
    assert out["suppressed"] and "before" in out["reason"]


def test_leak_guard_blocks_other_parties(env):
    _, _, eng = env
    r = eng.start("70221001", "seller", "voice", reply_mode="template")
    s = eng.sessions[r["session_id"]]
    assert "Jain Pipe House" in s.deny and "Ramesh" in s.deny  # exist only in other GLIDs' files
    blocked = eng._leak_guard(s, "Us buyer ne Jain Pipe House se bhi baat ki thi, number 98260 11223 hai")
    assert "Jain Pipe House" not in blocked and "98260" not in blocked and s.metrics["leak_blocked"] == 1


def test_lift_and_consumers(env):
    _, _, eng = env
    rep = lift_report(eng)["summary"]
    assert rep["warm_reasks"] == 0 and rep["cold_reasks"] > 0 and rep["warm_turns"] < rep["cold_turns"]
    plan = wa_campaign.plan()
    assert any(x["glid"] == "70221003" for x in plan["suppressed"])  # do-not-disturb respected
    assert any(x["segment"] == "resume_nudge" for x in plan["send"])
    card = exec_call_prep.prep_card("70221003", "seller")
    assert any("GST" in r for r in card["risks"])
