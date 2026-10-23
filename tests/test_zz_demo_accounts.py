"""Demo patient accounts (runs last: it re-activates patients that other API tests used)."""
from conftest import needs_models


@needs_models
def test_demo_accounts(client):
    portal = client.app.state.portal
    portal.cfg["demo_accounts_enabled"] = True
    try:
        accts = client.get("/api/portal/demo/accounts").json()
        assert [a["id"] for a in accts] == ["demo1", "demo2", "demo3"]
        assert len({a["patient_id"] for a in accts}) == 3
        r = client.post("/api/portal/demo/login", json={"account": "demo2", "device_id": "demo-device-123"}).json()
        ph = {"Authorization": f"Bearer {r['token']}", "X-Device-Id": "demo-device-123"}
        me = client.get("/api/portal/me", headers=ph).json()
        assert me["state"] == "ACTIVE" and me["language"] == "hi" and "food" in me and me["cards"]
        # the activation went through the audited lifecycle
        actions = [a["action"] for a in client.get(f"/api/audit?patient_id={r['patient_id']}&limit=50").json()]
        assert "demo_login" in actions and actions.count("state_change") >= 3
        # a second device takes over the session (device binding)
        r2 = client.post("/api/portal/demo/login", json={"account": "demo2", "device_id": "other-device-456"}).json()
        assert client.get("/api/portal/me", headers=ph).status_code == 401
        assert client.get("/api/portal/me", headers={"Authorization": f"Bearer {r2['token']}", "X-Device-Id": "other-device-456"}).status_code == 200
    finally:
        portal.cfg["demo_accounts_enabled"] = False
    assert client.get("/api/portal/demo/accounts").json() == []
    assert client.post("/api/portal/demo/login", json={"account": "demo1", "device_id": "demo-device-123"}).status_code == 404
