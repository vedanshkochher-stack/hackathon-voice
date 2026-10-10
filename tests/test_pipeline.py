from ctxlayer import privacy, reader
from ctxlayer.config import MAX_BYTES
from ctxlayer.util import iso, now


def test_files_for_3_buyers_and_3_sellers_within_budget(env):
    files = reader.read_all()
    assert sum(c.meta["role"] == "buyer" for c in files) >= 3
    assert sum(c.meta["role"] == "seller" for c in files) >= 3
    for c in files:
        assert len(c.raw.encode()) <= MAX_BYTES[c.meta["role"]], c.path
        for key in ("schema", "glid", "generated_at", "watermark", "known", "next", "never_ask"):
            assert key in c.meta, (c.path, key)


def test_no_pii_in_any_file(env):
    for c in reader.read_all():
        for name, pat in privacy._PATTERNS:
            assert not pat.search(c.raw), (c.path, name)
    # buyer names that sat inside seller lead payloads never reach seller.md
    assert "Lakshmi" not in reader.read("70221003", "seller").raw
    assert "Ramesh" not in reader.read("70221001", "seller").raw
    assert "packaged drinking water" not in reader.read("70221003", "seller").raw
    assert privacy.audit["field:buyer_name"] >= 1 and privacy.audit["field:mobile"] >= 1


def test_conflict_resolution_buyer_confirmed_city_wins(env):
    c = reader.read("50112002", "buyer")
    assert c.meta["known"]["city"] == "Hyderabad"
    assert any("Secunderabad" in line for line in c.sections["Data notes"])


def test_lookback_and_missing_source(env):
    om = reader.read("70221002", "seller").raw
    assert "L-690112" not in om  # 40-day-old lead is outside the 30-day lead window
    arjun = reader.read("50112003", "buyer")
    assert arjun.meta["kyc"] == "unavailable" and arjun.meta["sources_missing"] == ["kyc"]
    assert arjun.meta["intent"]["product"] == "Bubble Wrap Roll"


def test_event_driven_refresh_and_read_through(env):
    store, ref, _ = env
    before = reader.read("50112003", "buyer").meta["watermark"]
    rows = ref.ingest([{"glid": "50112003", "role": "buyer", "type": "kyc.update", "occurred_at": iso(now()),
                        "source": "test", "payload": {"gst_verified": True, "gstin": "24ABCDE1234F1Z5"}}])
    ref.ensure_fresh("50112003", "buyer")  # bot path: never stale, even before the worker runs
    c = reader.read("50112003", "buyer")
    assert c.meta["watermark"] == rows[0]["seq"] > before
    assert c.meta["kyc"] == {"gst": True} and "24ABCDE" not in c.raw


def test_cross_party_pns_event_updates_both_files(env):
    store, ref, _ = env
    ts = iso(now())
    ref.ingest([
        {"glid": "50112002", "role": "buyer", "type": "pns.call", "occurred_at": ts, "source": "test", "counterparty": "70221002",
         "payload": {"seller_glid": "70221002", "seller_name": "Om Packaging", "seller_city": "Ahmedabad", "product": "Bubble Wrap Roll", "answered": False}},
        {"glid": "70221002", "role": "seller", "type": "pns.call", "occurred_at": ts, "source": "test", "counterparty": "50112002",
         "payload": {"buyer_city": "Hyderabad", "product": "Bubble Wrap Roll", "answered": False}}])
    assert ref.wait_idle(5)
    assert "Om Packaging" in reader.read("50112002", "buyer").raw
    s = reader.read("70221002", "seller")
    assert "Hyderabad buyer" in s.raw and "Lakshmi" not in s.raw

