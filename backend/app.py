"""FastAPI application: REST + WebSocket API for the clinician dashboard.

Run: ``python -m backend.app`` (or ``uvicorn backend.app:app``). Serves the built React dashboard
from ``frontend/dist`` at ``/`` when it exists.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.engine import INJECTIONS, SPEEDS, Engine
from backend.portal.routes import broadcast as portal_broadcast
from backend.portal.routes import router as portal_router
from backend.portal.service import PortalService
from common import ROOT, get_config, get_logger, path_of

log = get_logger("backend.app")
BANNER = "SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE"
DIST = ROOT / "frontend" / "dist"


# ---------------------------------------------------------------------------------------------
# request schemas
# ---------------------------------------------------------------------------------------------
class Intervention(BaseModel):
    type: Literal["meal", "exercise", "medication", "sleep"]
    carbs: float | None = Field(None, ge=0, le=300)
    gi: Literal["low", "medium", "high"] | None = None
    minutes: int | None = Field(None, ge=1, le=240)
    intensity: Literal["light", "moderate", "vigorous"] | None = None
    drug: Literal["metformin", "sulfonylurea", "rapid_insulin", "basal_insulin"] | None = None
    dose: float | None = Field(None, ge=0, le=3000)
    hours: float | None = Field(None, ge=2, le=12)
    at: str | None = Field(None, pattern=r"^\d{1,2}:\d{2}$")
    in_min: int | None = Field(None, ge=0, le=900)


class Scenario(BaseModel):
    name: str = Field(..., max_length=80)
    interventions: list[Intervention] = Field(..., max_length=6)


class WhatIfRequest(BaseModel):
    scenarios: list[Scenario] = Field(..., min_length=1, max_length=4)
    horizon_min: int | None = Field(None, ge=60, le=960)
    user: str = "dr.demo"


class UserAction(BaseModel):
    user: str = Field("dr.demo", max_length=40)


class NoteRequest(UserAction):
    text: str = Field(..., min_length=1, max_length=1000)


class InterventionRequest(UserAction):
    kind: Literal["diet_advice", "activity_advice", "medication_review", "teleconsult", "sensor_check", "other"]
    detail: str = Field("", max_length=500)


class SpeedRequest(BaseModel):
    speed: int


class PauseRequest(BaseModel):
    paused: bool


class InjectRequest(BaseModel):
    patient_id: str
    event: str


class IngestRequest(BaseModel):
    patient_id: str
    record: dict[str, Any]
    events: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------------------------
# app + background loop
# ---------------------------------------------------------------------------------------------
class Hub:
    """WebSocket fan-out."""

    def __init__(self) -> None:
        self.clients: dict[int, WebSocket] = {}

    async def send_all(self, engine: Engine, payload: dict) -> None:
        dead = []
        for cid, ws in list(self.clients.items()):
            try:
                await ws.send_text(json.dumps(payload, default=str))
                pid = engine.focus.get(cid)
                if pid:
                    detail = await asyncio.to_thread(engine.detail, pid)
                    await ws.send_text(json.dumps({"type": "patient", "data": detail}, default=str))
            except Exception:  # noqa: BLE001 - client went away
                dead.append(cid)
        for cid in dead:
            self.clients.pop(cid, None)
            engine.focus.pop(cid, None)


async def _loop(app: FastAPI) -> None:
    engine: Engine = app.state.engine
    hub: Hub = app.state.hub
    while True:
        started = asyncio.get_running_loop().time()
        if engine.mode == "internal" and not engine.paused:
            try:
                res = await asyncio.to_thread(engine.tick)
                await hub.send_all(engine, {"type": "tick", "state": engine.state(), "cohort": engine.cohort(),
                                            "new_alerts": res["new_alerts"]})
                await portal_broadcast(app.state.portal)
            except Exception:  # noqa: BLE001 - keep the demo alive, but log loudly
                log.exception("tick failed")
        interval = 300.0 / max(engine.speed, 1)
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(interval - elapsed, 0.02))


@asynccontextmanager
async def lifespan(app: FastAPI):
    mode = os.environ.get("DT_STREAM_MODE", "internal")
    warmup = int(os.environ.get("DT_WARMUP_DAYS", 14))
    app.state.engine = await asyncio.to_thread(Engine, None, warmup, os.environ.get("DT_START_CLOCK", "17:30"), mode)
    app.state.portal = await asyncio.to_thread(PortalService, app.state.engine)
    app.state.hub = Hub()
    task = asyncio.create_task(_loop(app))
    yield
    task.cancel()


app = FastAPI(title="T2D Digital Twin PoC", version="1.0.0", lifespan=lifespan,
              description=f"{BANNER}. Pseudonymous synthetic patients only.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(portal_router)


def _engine() -> Engine:
    return app.state.engine


def _twin_or_404(pid: str):
    e = _engine()
    if pid not in e.twins:
        raise HTTPException(404, "unknown patient")
    consent = e.audit.consent(pid)
    if not consent or consent["status"] != "granted":
        raise HTTPException(403, "no active consent for twin monitoring")
    return e.twins[pid]


# ---------------------------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "banner": BANNER}


@app.get("/api/meta")
def meta() -> dict:
    e = _engine()
    serving = json.loads((path_of("artifacts_dir") / "serving.json").read_text())
    metrics_p = path_of("reports_dir") / "metrics.json"
    headline = {}
    if metrics_p.exists():
        m = json.loads(metrics_p.read_text())
        r = m["results"][f"{serving['model']}_fused"]["test"]
        al = r.get("alerts_red") if serving.get("notify_level", "RED") == "RED" else r["alerts"]
        al = al or r["alerts"]
        headline = {"roc_auc": r["classification"]["roc_auc"], "pr_auc": r["classification"]["pr_auc"],
                    "mean_lead_min": al["mean_lead_min"], "false_alerts_per_patient_day": al["false_alerts_per_patient_day"],
                    "event_sensitivity": al["event_sensitivity"], "notify_level": serving.get("notify_level", "RED")}
    return {
        "banner": BANNER,
        "model": e.predictor.model_name, "thresholds": e.predictor.thresholds, "headline_test_metrics": headline,
        "provenance": {
            "ehr": "Custom synthetic Indian T2D EHR generator (data_gen/ehr_generator.py); FHIR R4 export available",
            "wearables": "Physiological world simulator: extended Bergman minimal model + lifestyle + sensor-artefact models",
            "synthea": "Optional adapter (data_gen/synthea/); not in use",
            "open_cgm": "Optional loaders for open CGM datasets (data_gen/open_cgm.py); not in use",
            "mimic": "Optional credentialed adapter (data_gen/mimic_adapter.py); not in use",
            "generator_version": e.manifest.get("generator_version"), "seed": e.manifest.get("seed"),
            "demo_patients_from": "held-out test split (never used in training)",
        },
        "compliance": [
            "No real persons: all patients are synthetic with pseudonymous random IDs (TWN-xxxxxx).",
            "Data minimisation: the API exposes only device fields and EHR items needed for care. Simulator ground truth is never served.",
            "Consent (simulated): every twin requires an active consent record; views are blocked otherwise.",
            "Audit: every view, alert, acknowledgement, note, intervention, what-if and demo control is logged.",
            "Not a medical device: outputs are research-prototype estimates without clinical validation.",
        ],
    }


@app.get("/api/sim/state")
def sim_state() -> dict:
    return _engine().state()


@app.post("/api/sim/speed")
def set_speed(req: SpeedRequest) -> dict:
    if req.speed not in SPEEDS:
        raise HTTPException(400, f"speed must be one of {SPEEDS}")
    e = _engine()
    e.speed = req.speed
    e.audit.log("demo-operator", "set_speed", detail={"speed": req.speed}, ts_sim=e.clock())
    return e.state()


@app.post("/api/sim/pause")
def pause(req: PauseRequest) -> dict:
    e = _engine()
    e.paused = req.paused
    e.audit.log("demo-operator", "pause" if req.paused else "resume", ts_sim=e.clock())
    return e.state()


@app.post("/api/sim/step")
async def step_once() -> dict:
    e = _engine()
    res = await asyncio.to_thread(e.tick)
    await app.state.hub.send_all(e, {"type": "tick", "state": e.state(), "cohort": e.cohort(), "new_alerts": res["new_alerts"]})
    await portal_broadcast(app.state.portal)
    return e.state()


@app.post("/api/sim/reset")
async def reset() -> dict:
    e = _engine()
    await asyncio.to_thread(e.reset)
    return e.state()


@app.post("/api/sim/inject")
def inject(req: InjectRequest) -> dict:
    _twin_or_404(req.patient_id)
    if req.event not in INJECTIONS:
        raise HTTPException(400, f"event must be one of {list(INJECTIONS)}")
    return _engine().inject(req.patient_id, req.event)


@app.post("/api/ingest")
def ingest(req: IngestRequest) -> dict:
    """External device-gateway ingestion (stream mode ``external``)."""
    e = _engine()
    if e.mode != "external":
        raise HTTPException(409, "backend runs the internal stream simulator (set DT_STREAM_MODE=external)")
    _twin_or_404(req.patient_id)
    with e.lock:
        e.ingest(req.patient_id, req.record, req.events)
    return {"ok": True}


@app.get("/api/patients")
def patients(search: str = "", level: str = "") -> list[dict]:
    rows = _engine().cohort()
    if search:
        rows = [r for r in rows if search.lower() in r["patient_id"].lower()]
    if level:
        rows = [r for r in rows if r["level"] == level.upper()]
    order = {"RED": 0, "HIGH": 1, "AMBER": 2, "GREEN": 3}
    return sorted(rows, key=lambda r: (order.get(r["level"], 4), -(r["risk"] or 0)))


@app.get("/api/patients/{pid}")
async def patient(pid: str, user: str = "dr.demo") -> dict:
    _twin_or_404(pid)
    e = _engine()
    e.audit.log(user, "view_patient", pid, ts_sim=e.clock())
    return await asyncio.to_thread(e.detail, pid)


@app.get("/api/patients/{pid}/food")
async def food_insights(pid: str, user: str = "dr.demo") -> dict:
    """Daily consumption pattern + personal food-impact / symptom insights for the doctor view."""
    _twin_or_404(pid)
    e = _engine()
    e.audit.log(user, "view_food_insights", pid, ts_sim=e.clock())
    return await asyncio.to_thread(app.state.portal.food, pid, "en", 180)


@app.post("/api/patients/{pid}/whatif")
async def what_if(pid: str, req: WhatIfRequest) -> dict:
    tw = _twin_or_404(pid)
    e = _engine()
    scenarios = [{"name": s.name, "interventions": [i.model_dump(exclude_none=True) for i in s.interventions]} for s in req.scenarios]

    def run() -> dict:
        with e.lock:
            return tw.what_if(scenarios, req.horizon_min)

    res = await asyncio.to_thread(run)
    e.audit.log(req.user, "what_if", pid, {"scenarios": [s["name"] for s in scenarios],
                                           "summary": [s["summary"] for s in res["scenarios"]]}, ts_sim=e.clock())
    return res


@app.post("/api/patients/{pid}/alerts/{aid}/ack")
def ack(pid: str, aid: int, req: UserAction) -> dict:
    tw = _twin_or_404(pid)
    e = _engine()
    with e.lock:
        a = tw.acknowledge(aid, req.user)
    if not a:
        raise HTTPException(404, "unknown alert")
    e.audit.log(req.user, "acknowledge_alert", pid, {"alert_id": aid, "level": a["level"]}, ts_sim=e.clock())
    return a


@app.post("/api/patients/{pid}/notes")
def add_note(pid: str, req: NoteRequest) -> dict:
    tw = _twin_or_404(pid)
    e = _engine()
    note = {"ts": e.clock(), "user": req.user, "text": req.text}
    with e.lock:
        tw.notes.append(note)
    e.audit.log(req.user, "add_note", pid, {"text": req.text}, ts_sim=e.clock())
    return note


@app.post("/api/patients/{pid}/interventions")
def suggest_intervention(pid: str, req: InterventionRequest) -> dict:
    tw = _twin_or_404(pid)
    e = _engine()
    item = {"ts": e.clock(), "user": req.user, "text": f"[Suggested intervention: {req.kind.replace('_', ' ')}] {req.detail}".strip()}
    with e.lock:
        tw.notes.append(item)
    e.audit.log(req.user, "suggest_intervention", pid, {"kind": req.kind, "detail": req.detail}, ts_sim=e.clock())
    # two-way channel: if the patient app is active, the suggestion becomes an actionable card for the patient
    portal = app.state.portal
    rec = portal.store.patient(pid)
    if rec and rec["state"] == "ACTIVE":
        portal.push_card({"sub": req.user}, pid, "intervention", req.kind.replace("_", " ").capitalize(), req.detail)
    return item


@app.get("/api/audit")
def audit(limit: int = 100, patient_id: str | None = None) -> list[dict]:
    return _engine().audit.recent(min(limit, 500), patient_id)


# ---------------------------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    e, hub = _engine(), app.state.hub
    cid = id(ws)
    hub.clients[cid] = ws
    await ws.send_text(json.dumps({"type": "tick", "state": e.state(), "cohort": e.cohort(), "new_alerts": []}, default=str))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "subscribe" and msg.get("patient_id") in e.twins:
                e.focus[cid] = msg["patient_id"]
                detail = await asyncio.to_thread(e.detail, msg["patient_id"])
                await ws.send_text(json.dumps({"type": "patient", "data": detail}, default=str))
            elif msg.get("type") == "unsubscribe":
                e.focus.pop(cid, None)
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.pop(cid, None)
        e.focus.pop(cid, None)


# ---------------------------------------------------------------------------------------------
# static dashboard
# ---------------------------------------------------------------------------------------------
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """Doctor dashboard at /, patient PWA at /patient/ (both from one Vite multi-page build)."""
    doctor_index, patient_index = DIST / "doctor" / "index.html", DIST / "patient" / "index.html"
    if doctor_index.exists():
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            resp = FileResponse(f)
            if f.name == "sw.js":
                resp.headers["Service-Worker-Allowed"] = "/patient/"
            return resp
        return FileResponse(patient_index if path.startswith("patient") else doctor_index)
    return HTMLResponse(f"<h2>{BANNER}</h2><p>Dashboard not built. Run <code>make build</code> (or "
                        "<code>python tasks.py build</code>), or start the dev server in <code>frontend/</code>. "
                        "The API is at <a href='/docs'>/docs</a>.</p>")


def main() -> None:
    import uvicorn

    s = get_config()["serving"]
    uvicorn.run("backend.app:app", host=os.environ.get("DT_HOST", s["host"]), port=int(os.environ.get("DT_PORT", s["port"])),
                log_level="info")


if __name__ == "__main__":
    main()
