"""HTTP + WebSocket routes for provisioning (doctor) and the patient app."""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.portal import auth
from backend.portal.config_schema import TEMPLATES, PortalConfig
from backend.portal.lifecycle import State
from backend.portal.service import PortalService

router = APIRouter()


def svc(request: Request) -> PortalService:
    return request.app.state.portal


def base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------------------------
class Login(BaseModel):
    doctor_id: str
    password: str


class TemplateReq(BaseModel):
    template: str = "standard"


class BulkReq(BaseModel):
    patient_ids: list[str] = Field(..., min_length=1, max_length=50)
    template: str = "standard"


class MessageReq(BaseModel):
    body: str = Field(..., min_length=1, max_length=1000)


class CardReq(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field("", max_length=500)
    kind: str = "intervention"


class OpenReq(BaseModel):
    token: str
    device_id: str = Field(..., min_length=8, max_length=80)


class VerifyReq(OpenReq):
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class ConsentReq(BaseModel):
    accept: bool
    choices: dict[str, bool] = {}
    language: Literal["en", "hi", "ta"] = "en"


class LangReq(BaseModel):
    language: Literal["en", "hi", "ta"]


class LogReq(BaseModel):
    kind: Literal["meal", "exercise", "med", "symptom"]
    food: str | None = None
    portion: Literal["small", "regular", "large"] = "regular"
    minutes: int | None = None
    intensity: Literal["light", "moderate", "brisk"] = "moderate"
    status: Literal["taken", "missed"] | None = None
    symptoms: list[str] = []
    duration_ms: int | None = Field(None, ge=0, le=600000)


class TryReq(BaseModel):
    preset: Literal["walk15", "roti_rice", "early_dinner"]


class AckReq(BaseModel):
    understood: bool | None = None


# ---------------------------------------------------------------------------------------------
# doctor side
# ---------------------------------------------------------------------------------------------
@router.post("/api/auth/login")
def login(req: Login, request: Request) -> dict:
    return svc(request).login(req.doctor_id, req.password)


@router.get("/api/portal/doctors")
def doctors(request: Request) -> list[dict]:
    return [svc(request).doctor(d) for d in svc(request).doctors]


@router.get("/api/portal/templates")
def templates() -> dict:
    return {k: {"label": v["label"]} for k, v in TEMPLATES.items()}


@router.get("/api/portal/status")
def statuses(request: Request, claims: dict = Depends(auth.doctor_claims)) -> list[dict]:
    return svc(request).statuses(claims)


@router.get("/api/portal/patients/{pid}")
def manager(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).manager(claims, pid, base(request))


@router.post("/api/portal/patients/new")
def new_patient(req: TemplateReq, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    s = svc(request)
    pid = s.create_patient(claims)
    return s.enroll(claims, pid, req.template)


@router.post("/api/portal/patients/{pid}/enroll")
def enroll(pid: str, req: TemplateReq, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).enroll(claims, pid, req.template)


@router.put("/api/portal/patients/{pid}/config")
def configure(pid: str, cfg: PortalConfig, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).configure(claims, pid, cfg)


@router.post("/api/portal/patients/{pid}/template-config")
def template_config(pid: str, req: TemplateReq, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    """Template defaults personalised from the EHR (the wizard starts from this)."""
    from backend.portal.config_schema import from_template

    s = svc(request)
    s.assigned(claims, pid)
    return from_template(req.template, s.engine._ehr_raw(pid)).model_dump()


@router.post("/api/portal/patients/{pid}/launch")
def launch(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).launch(claims, pid, base(request))


@router.post("/api/portal/patients/{pid}/regenerate")
def regenerate(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).launch(claims, pid, base(request))


@router.post("/api/portal/patients/{pid}/resend")
def resend(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).resend(claims, pid, base(request))


@router.post("/api/portal/patients/{pid}/pause")
async def pause(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    out = svc(request).pause(claims, pid)
    await disconnect(svc(request))
    return out


@router.post("/api/portal/patients/{pid}/resume")
def resume(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).resume(claims, pid)


@router.post("/api/portal/patients/{pid}/revoke")
async def revoke(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    out = svc(request).revoke(claims, pid)
    await disconnect(svc(request))
    return out


@router.post("/api/portal/patients/{pid}/preview-token")
def preview_token(pid: str, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).preview_token(claims, pid)


@router.post("/api/portal/patients/{pid}/messages")
def message(pid: str, req: MessageReq, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).send_message(claims, pid, req.body)


@router.post("/api/portal/patients/{pid}/cards")
def card(pid: str, req: CardReq, request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    svc(request).assigned(claims, pid)
    return svc(request).push_card(claims, pid, req.kind, req.title, req.body)


@router.post("/api/portal/bulk-invite")
def bulk(req: BulkReq, request: Request, claims: dict = Depends(auth.doctor_claims)) -> list[dict]:
    return svc(request).bulk_invite(claims, req.patient_ids, req.template, base(request))


@router.get("/api/portal/outbox")
def outbox(request: Request, claims: dict = Depends(auth.doctor_claims)) -> list[dict]:
    """Mock SMS / email delivery log (dev console). Demo only."""
    return svc(request).store.outbox(30)


@router.get("/api/portal/metrics")
def metrics(request: Request, claims: dict = Depends(auth.doctor_claims)) -> dict:
    return svc(request).usage_metrics()


# ---------------------------------------------------------------------------------------------
# patient side
# ---------------------------------------------------------------------------------------------
def patient_session(request: Request, authorization: str | None = Header(None), x_device_id: str | None = Header(None)) -> dict:
    """ACTIVE sessions only (the consent gate for every data-bearing patient endpoint)."""
    return svc(request).session(auth.bearer(authorization), x_device_id, (State.ACTIVE,))


def any_session(request: Request, authorization: str | None = Header(None), x_device_id: str | None = Header(None)) -> dict:
    return svc(request).session(auth.bearer(authorization), x_device_id,
                                (State.ACTIVE, State.CONSENT_PENDING, State.PAUSED))


class DemoLoginReq(BaseModel):
    account: str = Field(..., max_length=20)
    device_id: str = Field(..., min_length=8, max_length=80)


@router.get("/api/portal/demo/accounts")
def demo_accounts(request: Request) -> list[dict]:
    """DEMO ONLY: the pre-activated synthetic patient accounts (empty when disabled)."""
    return svc(request).demo_accounts()


@router.post("/api/portal/demo/login")
def demo_login(req: DemoLoginReq, request: Request) -> dict:
    return svc(request).demo_login(req.account, req.device_id, auth.client_key(request))


@router.post("/api/portal/invite/open")
def open_invite(req: OpenReq, request: Request) -> dict:
    return svc(request).open_invite(req.token, req.device_id, auth.client_key(request))


@router.get("/api/portal/dev/otp")
def dev_otp(token: str, request: Request) -> dict:
    return svc(request).dev_otp(token)


@router.post("/api/portal/invite/verify")
def verify(req: VerifyReq, request: Request) -> dict:
    return svc(request).verify_otp(req.token, req.otp, req.device_id, auth.client_key(request))


@router.get("/api/portal/me")
def me(request: Request, s: dict = Depends(any_session)) -> dict:
    return svc(request).me(s)


@router.post("/api/portal/me/consent")
def consent(req: ConsentReq, request: Request, authorization: str | None = Header(None),
            x_device_id: str | None = Header(None)) -> dict:
    s = svc(request).session(auth.bearer(authorization), x_device_id, (State.CONSENT_PENDING,))
    if s["role"] != "patient":
        raise HTTPException(403, "only the patient can consent")
    if not req.accept:
        return {"state": State.CONSENT_PENDING.value, "accepted": False}
    return svc(request).accept_consent(s, {**req.choices, "twin_view": True}, req.language)


@router.post("/api/portal/me/withdraw")
async def withdraw(request: Request, s: dict = Depends(any_session)) -> dict:
    if s["role"] != "patient":
        raise HTTPException(403, "only the patient can withdraw consent")
    out = svc(request).withdraw(s)
    await disconnect(svc(request))
    return out


def _patient_only(s: dict) -> dict:
    if s["role"] != "patient":
        raise HTTPException(403, "read-only preview")
    return s


@router.post("/api/portal/me/language")
def language(req: LangReq, request: Request, s: dict = Depends(any_session)) -> dict:
    return svc(request).set_language(_patient_only(s), req.language)


@router.post("/api/portal/me/logs")
def quick_log(req: LogReq, request: Request, s: dict = Depends(patient_session)) -> dict:
    return svc(request).quick_log(_patient_only(s), req.model_dump(exclude_none=True))


@router.post("/api/portal/me/tryit")
def try_it(req: TryReq, request: Request, s: dict = Depends(patient_session)) -> dict:
    return svc(request).try_it(s, req.preset)


@router.post("/api/portal/me/alerts/{nid}/ack")
def ack(nid: int, req: AckReq, request: Request, s: dict = Depends(patient_session)) -> dict:
    return svc(request).ack_alert(_patient_only(s), nid, req.understood)


@router.post("/api/portal/me/cards/{cid}/done")
def card_done(cid: int, request: Request, s: dict = Depends(patient_session)) -> dict:
    return svc(request).card_done(_patient_only(s), cid)


@router.post("/api/portal/me/messages/{mid}/read")
def msg_read(mid: int, request: Request, s: dict = Depends(patient_session)) -> dict:
    return svc(request).message_read(_patient_only(s), mid)


@router.get("/api/portal/me/access-log")
def access_log(request: Request, s: dict = Depends(any_session)) -> list[dict]:
    return svc(request).access_log(s)


@router.post("/api/portal/me/caregiver-link")
def caregiver_link(request: Request, s: dict = Depends(patient_session)) -> dict:
    return svc(request).caregiver_link(_patient_only(s), base(request))


# ---------------------------------------------------------------------------------------------
# patient WebSocket (role-scoped push)
# ---------------------------------------------------------------------------------------------
@router.websocket("/ws/patient")
async def ws_patient(ws: WebSocket, token: str, device: str = "") -> None:
    s_: PortalService = ws.app.state.portal
    try:
        sess = s_.session(token, device, (State.ACTIVE,))
    except HTTPException as e:
        await ws.close(code=4401, reason=str(e.detail))
        return
    await ws.accept()
    pid = sess["pid"]
    s_.sockets[pid].add(ws)
    try:
        await ws.send_text(json.dumps({"type": "view", "data": await asyncio.to_thread(s_.me, sess)}, default=str))
        while True:
            await ws.receive_text()  # keep-alive / ignore client messages
    except WebSocketDisconnect:
        pass
    finally:
        s_.sockets[pid].discard(ws)


async def broadcast(s_: PortalService) -> None:
    """Push the fresh patient view to every connected patient (called after each engine tick)."""
    await disconnect(s_)
    for pid, socks in list(s_.sockets.items()):
        if not socks:
            continue
        r = s_.store.patient(pid)
        if r["state"] != State.ACTIVE.value:
            continue
        view = await asyncio.to_thread(s_.view, pid, r["config"], s_.doctor(r["doctor_id"]), r["state"])
        msg = json.dumps({"type": "view", "data": view}, default=str)
        for ws in list(socks):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001 - client went away
                socks.discard(ws)


async def disconnect(s_: PortalService) -> None:
    """Immediately close patient sockets after pause / revoke / withdrawal (data flow stops)."""
    while s_.to_disconnect:
        pid = s_.to_disconnect.pop()
        state = s_.store.patient(pid)["state"]
        for ws in list(s_.sockets.get(pid, ())):
            try:
                await ws.send_text(json.dumps({"type": "state", "state": state}))
                await ws.close(code=4403)
            except Exception:  # noqa: BLE001
                pass
        s_.sockets.pop(pid, None)
