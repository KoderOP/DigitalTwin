"""Patient interface: lifecycle, invites, OTP, consent gate, RBAC, config bounds, safety, caps, end-to-end."""
import time
import uuid

import pandas as pd
import pytest
from pydantic import ValidationError

from backend.portal.config_schema import PortalConfig, from_template
from backend.portal.lifecycle import InvalidTransition, State, check_transition
from conftest import needs_models

# ---------------------------------------------------------------------------------------------
# pure units (no engine)
# ---------------------------------------------------------------------------------------------
VALID = [("NOT_ENROLLED", "INVITED"), ("INVITED", "CONSENT_PENDING"), ("INVITED", "INVITED"), ("CONSENT_PENDING", "ACTIVE"),
         ("ACTIVE", "PAUSED"), ("PAUSED", "ACTIVE"), ("ACTIVE", "REVOKED"), ("PAUSED", "REVOKED"), ("REVOKED", "INVITED"),
         ("CONSENT_PENDING", "INVITED"), ("INVITED", "REVOKED")]
INVALID = [("NOT_ENROLLED", "ACTIVE"), ("NOT_ENROLLED", "CONSENT_PENDING"), ("INVITED", "ACTIVE"), ("ACTIVE", "INVITED"),
           ("REVOKED", "ACTIVE"), ("PAUSED", "CONSENT_PENDING"), ("ACTIVE", "NOT_ENROLLED"), ("REVOKED", "PAUSED")]


@pytest.mark.parametrize("frm,to", VALID)
def test_valid_transitions(frm, to):
    assert check_transition(frm, to) == (State(frm), State(to))


@pytest.mark.parametrize("frm,to", INVALID)
def test_invalid_transitions(frm, to):
    with pytest.raises(InvalidTransition):
        check_transition(frm, to)


@pytest.mark.parametrize("bad", [
    {"target": {"low": 60, "high": 180}},          # below hypoglycaemia threshold
    {"target": {"low": 70, "high": 250}},          # above allowed max
    {"target": {"low": 100, "high": 140}},         # range too narrow
    {"alerts": {"amber_threshold": 0.1}},
    {"alerts": {"daily_cap": 50}},
    {"alerts": {"red_alerts": False}},             # safety alerts cannot be disabled
    {"alerts": {"low_glucose_alerts": False}},
    {"care_plan": {"diet": ["eat_less_insulin"]}},
    {"care_plan": {"medication_reminders": [{"label": "x", "time": "25:00"}]}},
    {"language": "fr"},
])
def test_config_bounds_rejected(bad):
    base = PortalConfig().model_dump()
    for k, v in bad.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) else v
    with pytest.raises(ValidationError):
        PortalConfig.model_validate(base)


def test_templates_and_safe_defaults():
    c = PortalConfig()
    assert (c.target.low, c.target.high) == (70, 180) and c.alerts.red_alerts and c.alerts.low_glucose_alerts
    t = from_template("insulin_user", {"metformin_mg": 1000, "insulin_type": "premix_30_70"})
    assert t.target.low == 80 and len(t.care_plan.medication_reminders) == 3


def test_notifier_caps_and_safety_bypass(tmp_path):
    from backend.audit import AuditLog
    from backend.portal.notify import Notifier
    from backend.portal.store import PortalStore

    store = PortalStore(AuditLog(tmp_path / "n.sqlite3"))
    n = Notifier(store)
    cfg = PortalConfig(alerts={"daily_cap": 1, "min_gap_min": 60}).model_dump()
    t0 = pd.Timestamp("2026-02-20 08:00")
    amber = {"level": "AMBER", "risk": 0.7, "eligible": True, "minutes_to_spike": 40, "hypo_risk": 0.0,
             "forecast": [{"p50": 150, "p10": 120, "p90": 190, "minutes": m} for m in (30, 60, 90, 120)]}
    green = {**amber, "level": "GREEN", "risk": 0.05}
    out = []
    for k in range(6):  # alternate into / out of the watch zone -> 3 AMBER attempts
        out += n.process("P1", t0 + pd.Timedelta(minutes=5 * k), amber if k % 2 == 0 else green, 140.0, cfg)
    ambers = [o for o in out if o["kind"] == "amber"]
    assert len(ambers) == 3 and sum(o["delivered"] for o in ambers) == 1  # capped
    assert {o["suppressed"] for o in ambers if not o["delivered"]} <= {"daily_cap", "min_gap"}
    # safety: detected low and RED are delivered even though the cap is exhausted
    red = {**amber, "level": "RED", "risk": 0.97}
    got = n.process("P1", t0 + pd.Timedelta(minutes=40), red, 62.0, cfg)
    kinds = {o["kind"]: o for o in got}
    assert kinds["hypo_detected"]["delivered"] and kinds["hypo_detected"]["safety"]
    assert kinds["red"]["delivered"] and kinds["red"]["safety"]
    # de-duplicated per episode, but not suppressed by the cap
    again = n.process("P1", t0 + pd.Timedelta(minutes=45), red, 60.0, cfg)
    assert not [o for o in again if o["kind"] in ("red", "hypo_detected")]


# ---------------------------------------------------------------------------------------------
# API (live engine)
# ---------------------------------------------------------------------------------------------
def _doctor(client, doc_id="dr.mehta"):
    tok = client.post("/api/auth/login", json={"doctor_id": doc_id, "password": "demo"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _mine(client, h, states=("NOT_ENROLLED", "REVOKED")):
    """Assigned patients that can be (re-)launched (REVOKED -> INVITED is allowed)."""
    rows = client.get("/api/portal/status", headers=h).json()
    return [r["patient_id"] for r in rows if r["assigned_to_me"] and r["state"] in states]


def _activate(client, h, pid, lang="en"):
    client.post(f"/api/portal/patients/{pid}/enroll", json={"template": "standard"}, headers=h)
    inv = client.post(f"/api/portal/patients/{pid}/launch", headers=h).json()
    token = inv["link"].split("invite=")[1]
    dev = "dev-" + uuid.uuid4().hex[:12]
    assert client.post("/api/portal/invite/open", json={"token": token, "device_id": dev}).status_code == 200
    otp = client.get("/api/portal/dev/otp", params={"token": token}).json()["message"].split("code is ")[1][:6]
    r = client.post("/api/portal/invite/verify", json={"token": token, "otp": otp, "device_id": dev})
    assert r.status_code == 200, r.text
    ph = {"Authorization": f"Bearer {r.json()['token']}", "X-Device-Id": dev}
    return token, dev, ph


@needs_models
def test_login_and_rbac(client):
    assert client.post("/api/auth/login", json={"doctor_id": "dr.mehta", "password": "nope"}).status_code == 401
    assert client.get("/api/portal/status").status_code == 401
    ha, hb = _doctor(client), _doctor(client, "dr.rao")
    a_pid = _mine(client, ha)[0]
    # doctor B cannot provision or preview doctor A's patient
    assert client.post(f"/api/portal/patients/{a_pid}/enroll", json={"template": "standard"}, headers=hb).status_code == 403
    assert client.post(f"/api/portal/patients/{a_pid}/launch", headers=hb).status_code == 403
    assert client.post(f"/api/portal/patients/{a_pid}/preview-token", headers=hb).status_code == 403


@needs_models
def test_invite_otp_single_use_expiry_and_lock(client):
    h = _doctor(client)
    pid = _mine(client, h)[0]
    assert client.post(f"/api/portal/patients/{pid}/launch", headers=h).status_code == 400  # not configured yet
    client.post(f"/api/portal/patients/{pid}/enroll", json={"template": "standard"}, headers=h)
    old = client.post(f"/api/portal/patients/{pid}/launch", headers=h).json()["link"].split("invite=")[1]
    new = client.post(f"/api/portal/patients/{pid}/regenerate", headers=h).json()["link"].split("invite=")[1]
    assert client.post("/api/portal/invite/open", json={"token": old, "device_id": "device-0001"}).status_code == 410  # superseded
    assert client.post("/api/portal/invite/open", json={"token": new, "device_id": "device-0001"}).status_code == 200
    r = client.post("/api/portal/invite/verify", json={"token": new, "otp": "000000", "device_id": "device-0001"})
    assert r.status_code in (401, 403) and "tries left" in r.text or r.status_code == 403
    for _ in range(5):
        r = client.post("/api/portal/invite/verify", json={"token": new, "otp": "000001", "device_id": "device-0001"})
    assert r.status_code in (403, 410, 429)  # locked after max attempts (or rate-limited)
    assert client.post("/api/portal/invite/open", json={"token": new, "device_id": "device-0001"}).status_code == 410
    # expiry: a fresh invite whose record has expired is refused
    fresh = client.post(f"/api/portal/patients/{pid}/regenerate", headers=h).json()["link"].split("invite=")[1]
    portal = client.app.state.portal
    portal.store.x("UPDATE invites SET expires_ts=? WHERE pid=? AND status='active'", (time.time() - 1, pid))
    r = client.post("/api/portal/invite/open", json={"token": fresh, "device_id": "device-0001"})
    assert r.status_code == 410 and "expired" in r.text
    # single use: after a successful verification the same invite cannot be used again
    token, dev, _ = _activate(client, h, pid)
    assert client.post("/api/portal/invite/open", json={"token": token, "device_id": dev}).status_code == 410
    assert client.post(f"/api/portal/patients/{pid}/revoke", headers=h).status_code == 200


@needs_models
def test_consent_gate_device_binding_and_withdrawal(client):
    h = _doctor(client)
    pid = _mine(client, h)[0]
    _, dev, ph = _activate(client, h, pid)
    me = client.get("/api/portal/me", headers=ph).json()
    assert me["state"] == "CONSENT_PENDING" and "glucose" not in me and "status" not in me  # no twin data before consent
    assert client.post("/api/portal/me/logs", json={"kind": "exercise", "minutes": 15}, headers=ph).status_code == 403
    bad_dev = {**ph, "X-Device-Id": "another-device-123"}
    assert client.get("/api/portal/me", headers=bad_dev).status_code == 401  # device binding
    assert client.post("/api/portal/me/consent", json={"accept": True, "language": "hi", "choices": {"share_logs": True}},
                       headers=ph).json()["state"] == "ACTIVE"
    me = client.get("/api/portal/me", headers=ph).json()
    assert me["state"] == "ACTIVE" and me["glucose"] and me["language"] == "hi"
    assert any("डॉक्टर" in m["body"] or "स्वागत" in m["body"] for m in me["messages"])  # localised welcome
    assert client.post("/api/portal/me/withdraw", headers=ph).json()["state"] == "REVOKED"
    r = client.get("/api/portal/me", headers=ph)
    assert r.status_code == 401  # session killed: no data after withdrawal
    assert client.post("/api/portal/me/logs", json={"kind": "exercise", "minutes": 15}, headers=ph).status_code == 401
    log = client.get(f"/api/audit?patient_id={pid}&limit=50").json()
    assert {"consent_accepted", "consent_withdrawn", "state_change", "otp_sent", "invite_created"} <= {a["action"] for a in log}


@needs_models
def test_patient_cannot_see_other_patient(client):
    h = _doctor(client)
    p1, p2 = _mine(client, h)[:2]
    _, _, ph1 = _activate(client, h, p1)
    client.post("/api/portal/me/consent", json={"accept": True, "language": "en"}, headers=ph1)
    me = client.get("/api/portal/me", headers=ph1).json()
    assert me["patient_id"] == p1
    # there is no endpoint taking another patient id; the doctor-side endpoints reject patient tokens
    assert client.get(f"/api/portal/patients/{p2}", headers=ph1).status_code == 403
    assert client.get("/api/portal/status", headers=ph1).status_code == 403
    client.post(f"/api/portal/patients/{p1}/revoke", headers=h)


@needs_models
def test_new_patient_bulk_invite_pause_and_caregiver(client):
    h = _doctor(client)
    new = client.post("/api/portal/patients/new", json={"template": "elderly_caregiver"}, headers=h).json()
    pid = new["patient_id"]
    assert new["assigned_to_me"] and new["config"]["features"]["caregiver"]
    assert pid in client.app.state.engine.twins  # twin instantiated from a fresh synthetic EHR
    res = client.post("/api/portal/bulk-invite", json={"patient_ids": [pid], "template": "elderly_caregiver"}, headers=h).json()
    assert res[0]["ok"] and "invite=" in res[0]["link"]
    # activate with caregiver consent
    token = res[0]["link"].split("invite=")[1]
    dev = "dev-" + uuid.uuid4().hex[:12]
    client.post("/api/portal/invite/open", json={"token": token, "device_id": dev})
    otp = client.get("/api/portal/dev/otp", params={"token": token}).json()["message"].split("code is ")[1][:6]
    ph = {"Authorization": "Bearer " + client.post("/api/portal/invite/verify", json={"token": token, "otp": otp, "device_id": dev}).json()["token"],
          "X-Device-Id": dev}
    client.post("/api/portal/me/consent", json={"accept": True, "language": "ta", "choices": {"caregiver": True}}, headers=ph)
    link = client.post("/api/portal/me/caregiver-link", headers=ph).json()["link"]
    cg = {"Authorization": "Bearer " + link.split("caregiver=")[1]}
    view = client.get("/api/portal/me", headers=cg).json()
    assert view["state"] == "CAREGIVER" and "status" in view and "my_day" not in view and "messages" not in view
    assert client.post("/api/portal/me/logs", json={"kind": "exercise", "minutes": 15}, headers=cg).status_code == 403
    # pause: no twin data, no logs; resume restores
    client.post(f"/api/portal/patients/{pid}/pause", headers=h)
    paused = client.get("/api/portal/me", headers=ph).json()
    assert paused["state"] == "PAUSED" and "glucose" not in paused
    assert client.post("/api/portal/me/logs", json={"kind": "exercise", "minutes": 15}, headers=ph).status_code == 403
    assert client.get("/api/portal/me", headers=cg).status_code == 403  # caregiver blocked while paused
    client.post(f"/api/portal/patients/{pid}/resume", headers=h)
    assert client.get("/api/portal/me", headers=ph).json()["state"] == "ACTIVE"
    # withdrawal revokes caregiver access too
    client.post("/api/portal/me/withdraw", headers=ph)
    assert client.get("/api/portal/me", headers=cg).status_code == 403


@needs_models
def test_food_insights_in_views(client):
    h = _doctor(client)
    pid = _mine(client, h)[0]
    food = client.get(f"/api/patients/{pid}/food").json()
    assert {"foods", "patterns", "symptom_links", "diary"} <= set(food) and food["meals_logged"] > 0
    assert len(food["diary"]) == 7


@needs_models
def test_end_to_end_patient_journey(client):
    """enroll -> configure -> invite -> OTP -> consent -> live alert -> patient log -> forecast update -> revoke."""
    h = _doctor(client, "dr.rao")
    pid = _mine(client, h)[0]
    client.post(f"/api/portal/patients/{pid}/enroll", json={"template": "standard"}, headers=h)
    cfg = client.post(f"/api/portal/patients/{pid}/template-config", json={"template": "newly_diagnosed"}, headers=h).json()
    cfg["language"] = "ta"
    cfg["alerts"]["escalation_contacts"] = [{"name": "Demo Family", "relation": "son", "channel": "sms", "handle": "+91-00000-00000"}]
    assert client.put(f"/api/portal/patients/{pid}/config", json=cfg, headers=h).status_code == 200
    bad = {**cfg, "alerts": {**cfg["alerts"], "red_alerts": False}}
    assert client.put(f"/api/portal/patients/{pid}/config", json=bad, headers=h).status_code == 422
    _, dev, ph = _activate(client, h, pid)
    client.post("/api/portal/me/consent", json={"accept": True, "language": "en", "choices": {"share_logs": True}}, headers=ph)
    assert client.get(f"/api/portal/patients/{pid}", headers=h).json()["state"] == "ACTIVE"
    # live alert: inject a heavy meal and step the clock
    client.post("/api/sim/inject", json={"patient_id": pid, "event": "heavy_meal"})
    for _ in range(3):
        client.post("/api/sim/step")
    me = client.get("/api/portal/me", headers=ph).json()
    assert me["status"]["level"] in ("AMBER", "RED", "HIGH")
    assert any(a["kind"] in ("red", "amber") for a in me["alerts"]) or me["status"]["level"] == "HIGH"
    for a in me["alerts"]:
        assert a["disclaimer"] and ("confidence" in a)
    before_ts = me["now"]
    # patient logs a 15-minute walk -> event reaches the twin -> next forecast is computed with it
    r = client.post("/api/portal/me/logs", json={"kind": "exercise", "minutes": 15, "duration_ms": 4200}, headers=ph)
    assert r.status_code == 200
    for _ in range(2):
        client.post("/api/sim/step")
    me2 = client.get("/api/portal/me", headers=ph).json()
    assert me2["now"] > before_ts and me2["glucose"]["forecast"]
    assert any(i["kind"] == "walk" for i in me2["my_day"])
    tri = client.post("/api/portal/me/tryit", json={"preset": "walk15"}, headers=ph).json()
    assert tri["before"] and tri["after"] and tri["note"]
    # doctor sees the response in the engagement panel
    eng = client.get(f"/api/portal/patients/{pid}", headers=h).json()["engagement"]
    assert eng["logs"].get("exercise") == 1 and eng["median_time_to_log_s"] == 4.2
    # revoke: data flow stops
    client.post(f"/api/portal/patients/{pid}/revoke", headers=h)
    assert client.get("/api/portal/me", headers=ph).status_code == 401
    assert client.get(f"/api/portal/patients/{pid}", headers=h).json()["state"] == "REVOKED"
