"""Iter26 Phase 1 — AI Business Assistant + Trip Templates + Duplicate Trip.

Covers:
 1. Templates CRUD + company scoping
 2. Duplicate trip resets variable fields but preserves rate/route
 3. from-template returns prefill payload
 4. AI chat streams SSE + session persistence
 5. AI chat session history endpoints
 6. AI multi-company scoping (no cross leak)
"""
import json
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _api(path):
    return f"{BASE_URL}/api{path}"


def _hdr(cid=None):
    h = dict(HDR)
    if cid:
        h["X-Company-Id"] = cid
    return h


# Shared state across tests
S = {}


TAG = f"IT26_{uuid.uuid4().hex[:6]}"


# ================== Fixture: two companies + customer ==================
@pytest.fixture(scope="module", autouse=True)
def _setup_companies():
    cA = requests.post(_api("/companies"), headers=HDR, json={
        "name": f"TEST_{TAG}_CompA", "state": "Andhra Pradesh",
        "gstin": "37ZZZZZ9999Z1Z5", "pan": "ZZZZZ9999Z",
        "address": "AP addr", "invoice_prefix": "AI26A",
    })
    assert cA.status_code == 200, cA.text
    S["cA"] = cA.json()["id"]

    cB = requests.post(_api("/companies"), headers=HDR, json={
        "name": f"TEST_{TAG}_CompB", "state": "Telangana",
        "gstin": "36YYYYY8888Y1Z5", "pan": "YYYYY8888Y",
        "address": "TG addr", "invoice_prefix": "AI26B",
    })
    assert cB.status_code == 200, cB.text
    S["cB"] = cB.json()["id"]

    # A customer in each company
    r = requests.post(_api("/customers"), headers=_hdr(S["cA"]), json={
        "name": f"TEST_{TAG}_CustA", "state": "Andhra Pradesh"
    })
    assert r.status_code == 200
    S["custA"] = r.json()["id"]

    r = requests.post(_api("/customers"), headers=_hdr(S["cB"]), json={
        "name": f"TEST_{TAG}_CustB", "state": "Telangana"
    })
    assert r.status_code == 200
    S["custB"] = r.json()["id"]

    yield

    # ---- Teardown: best-effort cleanup ----
    # Delete templates
    for cid in (S.get("cA"), S.get("cB")):
        if not cid: continue
        try:
            tpls = requests.get(_api("/templates"), headers=_hdr(cid)).json()
            for t in tpls:
                if TAG in t.get("name", ""):
                    requests.delete(_api(f"/templates/{t['id']}"), headers=_hdr(cid))
        except Exception:
            pass
    # Delete chat sessions
    try:
        sess = requests.get(_api("/ai/sessions"), headers=_hdr(S.get("cA") or "")).json()
        for s in sess:
            requests.delete(_api(f"/ai/sessions/{s['id']}"), headers=_hdr(S["cA"]))
    except Exception:
        pass
    try:
        sess = requests.get(_api("/ai/sessions"), headers=_hdr(S.get("cB") or "")).json()
        for s in sess:
            requests.delete(_api(f"/ai/sessions/{s['id']}"), headers=_hdr(S["cB"]))
    except Exception:
        pass


# ================== 1. Templates CRUD ==================
class TestTemplatesCRUD:
    def test_create_template(self):
        r = requests.post(_api("/templates"), headers=_hdr(S["cA"]), json={
            "name": f"TEST_{TAG}_TPL_A",
            "customer_id": S["custA"],
            "from_location": "Vizag",
            "to_location": "Hyderabad",
            "load_details": "Bitumen VG 40",
            "freight_mode": "per_ton",
            "rate_per_ton": 1500,
            "hsn_sac": "996791",
            "halting_rate_per_day": 500,
            "remarks": "Test remarks",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == f"TEST_{TAG}_TPL_A"
        assert data["rate_per_ton"] == 1500
        assert data["from_location"] == "Vizag"
        assert data["to_location"] == "Hyderabad"
        assert "id" in data
        S["tpl_a"] = data["id"]

    def test_list_includes(self):
        r = requests.get(_api("/templates"), headers=_hdr(S["cA"]))
        assert r.status_code == 200
        docs = r.json()
        assert any(t["id"] == S["tpl_a"] for t in docs)

    def test_update_template(self):
        r = requests.put(_api(f"/templates/{S['tpl_a']}"), headers=_hdr(S["cA"]), json={
            "name": f"TEST_{TAG}_TPL_A",
            "customer_id": S["custA"],
            "from_location": "Vizag",
            "to_location": "Hyderabad",
            "freight_mode": "per_ton",
            "rate_per_ton": 1600,
            "hsn_sac": "996791",
            "halting_rate_per_day": 500,
            "remarks": "Updated remarks",
        })
        assert r.status_code == 200, r.text
        assert r.json()["rate_per_ton"] == 1600
        # Verify persisted
        g = requests.get(_api(f"/templates/{S['tpl_a']}"), headers=_hdr(S["cA"]))
        assert g.status_code == 200
        assert g.json()["rate_per_ton"] == 1600
        assert g.json()["remarks"] == "Updated remarks"

    def test_company_scoping(self):
        # Create template under B
        r = requests.post(_api("/templates"), headers=_hdr(S["cB"]), json={
            "name": f"TEST_{TAG}_TPL_B",
            "customer_id": S["custB"],
            "from_location": "Hyd",
            "to_location": "Warangal",
            "freight_mode": "per_ton",
            "rate_per_ton": 2000,
        })
        assert r.status_code == 200, r.text
        S["tpl_b"] = r.json()["id"]

        # A's list should NOT have B's template
        listA = requests.get(_api("/templates"), headers=_hdr(S["cA"])).json()
        assert not any(t["id"] == S["tpl_b"] for t in listA), "Template leaked from B to A"
        listB = requests.get(_api("/templates"), headers=_hdr(S["cB"])).json()
        assert any(t["id"] == S["tpl_b"] for t in listB)
        # A's template not in B
        assert not any(t["id"] == S["tpl_a"] for t in listB), "Template leaked from A to B"

    def test_delete_template(self):
        # Create a throwaway to delete
        r = requests.post(_api("/templates"), headers=_hdr(S["cA"]), json={
            "name": f"TEST_{TAG}_TPL_DEL", "freight_mode": "per_ton"
        })
        tid = r.json()["id"]
        d = requests.delete(_api(f"/templates/{tid}"), headers=_hdr(S["cA"]))
        assert d.status_code == 200
        g = requests.get(_api(f"/templates/{tid}"), headers=_hdr(S["cA"]))
        assert g.status_code == 404


# ================== 2. Duplicate Trip ==================
class TestDuplicateTrip:
    def test_create_and_duplicate(self):
        r = requests.post(_api("/trips"), headers=_hdr(S["cA"]), json={
            "customer_id": S["custA"],
            "date": "2026-01-05",
            "vehicle_number": f"AP99{TAG[-4:]}",
            "tons": 20,
            "from_location": "Vizag",
            "to_location": "Hyd",
            "freight_mode": "per_ton",
            "rate_per_ton": 1500,
            "expenses": {"diesel": 5000, "diesel_from_customer_amount": 9000},
        })
        assert r.status_code == 200, r.text
        src = r.json()
        assert src["freight_amount"] == 30000  # 20 * 1500
        S["trip_src"] = src["id"]

        d = requests.post(_api(f"/trips/{src['id']}/duplicate"), headers=_hdr(S["cA"]))
        assert d.status_code == 200, d.text
        dup = d.json()
        assert dup["id"] != src["id"], "Duplicate must have new id"
        assert dup["vehicle_number"] == src["vehicle_number"]
        assert dup["customer_id"] == src["customer_id"]
        assert dup["from_location"] == "Vizag"
        assert dup["to_location"] == "Hyd"
        assert dup["rate_per_ton"] == 1500
        # Reset fields
        assert dup["tons"] == 0
        assert dup["freight_amount"] == 0
        assert dup["status"] == "pending"
        assert not dup.get("invoice_id"), f"invoice_id should be cleared, got {dup.get('invoice_id')}"
        assert dup.get("lr_number", "") in ("", None)
        assert dup["expenses"]["diesel_from_customer_amount"] == 0
        # date should be today
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        assert dup["date"] == today

        S["trip_dup"] = dup["id"]


# ================== 3. From-Template Endpoint ==================
class TestFromTemplate:
    def test_from_template_prefill(self):
        r = requests.post(_api(f"/trips/from-template/{S['tpl_a']}"), headers=_hdr(S["cA"]))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["customer_id"] == S["custA"]
        assert data["from_location"] == "Vizag"
        assert data["to_location"] == "Hyderabad"
        assert data["freight_mode"] == "per_ton"
        assert data["rate_per_ton"] == 1600  # after update
        assert data["hsn_sac"] == "996791"
        assert data["halting_rate_per_day"] == 500
        assert data["notes"] == "Updated remarks"
        from datetime import datetime, timezone
        assert data["date"] == datetime.now(timezone.utc).date().isoformat()

    def test_from_template_not_found(self):
        r = requests.post(_api("/trips/from-template/tpl_nonexistent"), headers=_hdr(S["cA"]))
        assert r.status_code == 404


# ================== 4. AI Chat SSE ==================
def _parse_sse(response, timeout=25):
    """Parse SSE stream, return list of events (dicts)."""
    events = []
    start = time.time()
    for raw in response.iter_lines(decode_unicode=True):
        if time.time() - start > timeout:
            break
        if not raw:
            continue
        if raw.startswith("data: "):
            try:
                events.append(json.loads(raw[6:]))
            except Exception:
                pass
        if events and events[-1].get("type") in ("done", "error"):
            break
    return events


class TestAIChat:
    def test_chat_stream_and_session(self):
        r = requests.post(_api("/ai/chat"), headers=_hdr(S["cA"]),
                          json={"message": "What is my total revenue?"},
                          stream=True, timeout=30)
        assert r.status_code == 200, r.text
        assert "text/event-stream" in r.headers.get("Content-Type", "")
        events = _parse_sse(r, timeout=25)
        assert events, "No SSE events received"
        text_events = [e for e in events if e.get("type") == "text"]
        done_events = [e for e in events if e.get("type") == "done"]
        err_events = [e for e in events if e.get("type") == "error"]
        assert not err_events, f"AI stream returned error: {err_events}"
        assert len(text_events) >= 1, f"No text events: {events}"
        assert done_events, f"No done event: {events}"
        sid = done_events[-1].get("session_id")
        assert sid and sid.startswith("chat_"), f"Bad session_id: {sid}"
        S["sid_a"] = sid

    def test_chat_reuses_session(self):
        prev_sid = S.get("sid_a")
        assert prev_sid
        r = requests.post(_api("/ai/chat"), headers=_hdr(S["cA"]),
                          json={"message": "Any overdue invoices?", "session_id": prev_sid},
                          stream=True, timeout=30)
        assert r.status_code == 200
        events = _parse_sse(r, timeout=25)
        done = [e for e in events if e.get("type") == "done"]
        assert done and done[-1].get("session_id") == prev_sid, \
            f"Session id changed: expected {prev_sid} got {done}"


# ================== 5. Session History ==================
class TestSessionHistory:
    def test_list_sessions(self):
        r = requests.get(_api("/ai/sessions"), headers=_hdr(S["cA"]))
        assert r.status_code == 200
        sessions = r.json()
        assert any(s["id"] == S["sid_a"] for s in sessions), \
            f"Session {S['sid_a']} not in list"

    def test_get_messages(self):
        r = requests.get(_api(f"/ai/sessions/{S['sid_a']}/messages"), headers=_hdr(S["cA"]))
        assert r.status_code == 200
        msgs = r.json()
        roles = [m["role"] for m in msgs]
        assert "user" in roles, f"No user msg: {roles}"
        assert "assistant" in roles, f"No assistant msg persisted: {roles}"


# ================== 6. Multi-Company AI Scoping ==================
class TestMultiCompanyScoping:
    def test_company_isolation_in_ai_tool(self):
        """Direct tool call: dashboard for A must not include B's trips.
        We validate the underlying isolation by seeding trips and checking
        dashboard/trips endpoints (the same source AI's tool uses)."""
        # Trip in A worth 10000
        rA = requests.post(_api("/trips"), headers=_hdr(S["cA"]), json={
            "customer_id": S["custA"], "date": "2026-01-05",
            "vehicle_number": f"AP01{TAG[-4:]}", "tons": 10,
            "from_location": "V", "to_location": "H",
            "freight_mode": "per_ton", "rate_per_ton": 1000,
        })
        assert rA.status_code == 200
        # Trip in B worth 50000
        rB = requests.post(_api("/trips"), headers=_hdr(S["cB"]), json={
            "customer_id": S["custB"], "date": "2026-01-05",
            "vehicle_number": f"TS01{TAG[-4:]}", "tons": 25,
            "from_location": "H", "to_location": "W",
            "freight_mode": "per_ton", "rate_per_ton": 2000,
        })
        assert rB.status_code == 200

        # Dashboard should be scoped
        tripsA = requests.get(_api("/trips"), headers=_hdr(S["cA"])).json()
        tripsB = requests.get(_api("/trips"), headers=_hdr(S["cB"])).json()
        a_freight = sum(float(t.get("freight_amount", 0)) for t in tripsA)
        b_freight = sum(float(t.get("freight_amount", 0)) for t in tripsB)
        assert a_freight < b_freight, "Company A should have less freight than B"
        # Ensure no cross-leak of ids
        a_ids = {t["id"] for t in tripsA}
        b_ids = {t["id"] for t in tripsB}
        assert not (a_ids & b_ids), "Trip ids leaked between companies"

    def test_ai_chat_scoping(self):
        """Chat under A: ask total revenue. Under B: same. Sessions must be per-company."""
        rA = requests.post(_api("/ai/chat"), headers=_hdr(S["cA"]),
                           json={"message": "What is my total revenue in rupees? Give me only the number."},
                           stream=True, timeout=30)
        assert rA.status_code == 200
        evA = _parse_sse(rA, timeout=25)
        txtA = "".join(e.get("delta", "") for e in evA if e.get("type") == "text")
        sidA = next((e["session_id"] for e in evA if e.get("type") == "done"), None)
        assert sidA

        rB = requests.post(_api("/ai/chat"), headers=_hdr(S["cB"]),
                           json={"message": "What is my total revenue in rupees? Give me only the number."},
                           stream=True, timeout=30)
        assert rB.status_code == 200
        evB = _parse_sse(rB, timeout=25)
        txtB = "".join(e.get("delta", "") for e in evB if e.get("type") == "text")
        sidB = next((e["session_id"] for e in evB if e.get("type") == "done"), None)
        assert sidB
        assert sidA != sidB, "Sessions must be distinct per company"

        # Sessions listing must be scoped
        sessA = requests.get(_api("/ai/sessions"), headers=_hdr(S["cA"])).json()
        sessB = requests.get(_api("/ai/sessions"), headers=_hdr(S["cB"])).json()
        assert any(s["id"] == sidA for s in sessA)
        assert not any(s["id"] == sidA for s in sessB), "Session A leaked into B's list"
        assert any(s["id"] == sidB for s in sessB)
        assert not any(s["id"] == sidB for s in sessA), "Session B leaked into A's list"

        # Log responses for manual inspection (soft check on figures)
        print(f"\n[SCOPING] A response: {txtA[:200]}")
        print(f"[SCOPING] B response: {txtB[:200]}")
