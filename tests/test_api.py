"""End-to-end API test: engine warm-up, cohort, twin view, what-if, injection, alerts, audit, consent."""
from conftest import needs_models

pytestmark = needs_models


def test_health_and_meta(client):
    assert client.get("/api/health").json()["banner"].startswith("SYNTHETIC DATA ONLY")
    m = client.get("/api/meta").json()
    assert "provenance" in m and m["compliance"]


def test_cohort_and_detail(client):
    rows = client.get("/api/patients").json()
    assert len(rows) == 4 and {"risk", "level", "patient_id"} <= set(rows[0])
    pid = rows[0]["patient_id"]
    d = client.get(f"/api/patients/{pid}").json()
    assert d["header"]["patient_id"] == pid and d["prediction"]["explanation"]
    assert len(d["series"]) > 100 and d["consent"]["status"] == "granted"


def test_step_inject_whatif_and_audit(client):
    pid = client.get("/api/patients").json()[0]["patient_id"]
    assert client.post("/api/sim/inject", json={"patient_id": pid, "event": "heavy_meal"}).status_code == 200
    before = client.get("/api/sim/state").json()["clock"]
    for _ in range(3):
        client.post("/api/sim/step")
    assert client.get("/api/sim/state").json()["clock"] > before
    d = client.get(f"/api/patients/{pid}").json()
    assert any(e["injected"] for e in d["events"])
    r = client.post(f"/api/patients/{pid}/whatif", json={"scenarios": [
        {"name": "walk", "interventions": [{"type": "exercise", "minutes": 20, "intensity": "moderate"}]}]})
    assert r.status_code == 200 and r.json()["scenarios"][0]["trajectory"]
    assert client.post(f"/api/patients/{pid}/notes", json={"text": "test note"}).status_code == 200
    actions = {a["action"] for a in client.get(f"/api/audit?patient_id={pid}").json()}
    assert {"inject_event", "view_patient", "what_if", "add_note"} <= actions


def test_validation_and_consent(client):
    assert client.post("/api/sim/speed", json={"speed": 7}).status_code == 400
    assert client.get("/api/patients/TWN-NOPE").status_code == 404
    from backend.app import app

    e = app.state.engine
    pid = e.ids[-1]
    with e.audit._lock:
        e.audit._conn.execute("UPDATE consent SET status='withdrawn' WHERE patient_id=?", (pid,))
    assert client.get(f"/api/patients/{pid}").status_code == 403
    with e.audit._lock:
        e.audit._conn.execute("UPDATE consent SET status='granted' WHERE patient_id=?", (pid,))
