"""PortalService: doctor-initiated provisioning, consent gate, patient sessions and the two-way channel.

The twin (``Engine.twins``) is the single source of truth. This service only adds the patient-facing
lifecycle, access control and communication around it.
"""
from __future__ import annotations

import hmac
import json
import math
import os
import secrets
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import HTTPException

from backend.engine import Engine
from backend.portal import auth
from backend.portal.config_schema import TEMPLATES, PortalConfig, from_template
from backend.portal.food_insights import analyse, food_key, warning_for
from backend.portal.i18n import LANGS, t
from backend.portal.lifecycle import InvalidTransition, State, check_transition
from backend.portal.notify import Notifier
from backend.portal.store import PortalStore, now_iso
from backend.portal.views import build, care_plan_text, glucose, status
from common import get_config, get_logger

log = get_logger("backend.portal")
CONSENT_VERSION = "1.0"
TRYIT = ("walk15", "roti_rice", "early_dinner")
FOODS = {"idli_sambar": "idli_sambar", "dal_chawal": "dal_chawal", "roti_sabzi": "roti_sabzi", "poha": "poha", "biryani": "chicken_biryani"}
SYMPTOMS = ("dizziness", "thirst", "fatigue", "sweating")


class PortalService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.cfg = get_config()["portal"]
        self.store = PortalStore(engine.audit)
        self.notifier = Notifier(self.store)
        self.doctors = {d["id"]: d for d in self.cfg["doctors"]}
        self.open_limiter = auth.RateLimiter(20, 60)
        self.otp_limiter = auth.RateLimiter(8, 60)
        self.sockets: dict[str, set] = defaultdict(set)  # pid -> patient/preview websockets
        self.to_disconnect: set[str] = set()
        self._invite_tokens: dict[str, str] = {}  # jti -> signed token, so the doctor can re-show the QR
        self._meal_seen: dict[str, str] = {}  # pid -> timestamp of the last meal already checked for food warnings
        self._restore_extra_patients()
        self._assign_defaults()
        self.seed_demo_accounts()
        engine.post_tick_hooks.append(self.after_tick)

    # ------------------------------------------------------------------------------------------
    # setup / helpers
    # ------------------------------------------------------------------------------------------
    def _assign_defaults(self) -> None:
        """Split the demo patients between the fictional doctors (first half / second half)."""
        ids = sorted(self.engine.base_ids)
        docs = list(self.doctors)
        half = math.ceil(len(ids) / len(docs))
        for k, pid in enumerate(ids):
            self.store.ensure_patient(pid, docs[min(k // half, len(docs) - 1)])

    def _restore_extra_patients(self) -> None:
        for r in self.store.q("SELECT * FROM extra_patients"):
            if r["pid"] not in self.engine.twins:
                ehr = pd.read_json(r["ehr"], orient="split")
                lat = pd.read_json(r["latent"], orient="split")
                ehr.index.name = lat.index.name = "patient_id"
                self.engine.add_patient(ehr, lat)

    def doctor(self, doctor_id: str) -> dict:
        d = self.doctors.get(doctor_id, {"id": doctor_id, "name": doctor_id, "title": doctor_id})
        return {"id": d["id"], "name": d["name"], "title": d.get("title", d["name"])}

    def _audit(self, actor: str, action: str, pid: str | None = None, detail: dict | None = None) -> None:
        self.engine.audit.log(actor, action, pid, detail or {}, ts_sim=self.engine.clock())

    def record(self, pid: str) -> dict:
        r = self.store.patient(pid)
        if not r or pid not in self.engine.twins:
            raise HTTPException(404, "unknown patient")
        return r

    def assigned(self, claims: dict, pid: str) -> dict:
        r = self.record(pid)
        if r["doctor_id"] != claims["sub"]:
            raise HTTPException(403, "this patient is not assigned to you")
        return r

    def transition(self, pid: str, to: State, actor: str, reason: str = "", **fields) -> None:
        r = self.record(pid)
        try:
            frm, to = check_transition(r["state"], to)
        except InvalidTransition as e:
            raise HTTPException(409, str(e)) from None
        self.store.update_patient(pid, state=to.value, **fields)
        self._audit(actor, "state_change", pid, {"from": frm.value, "to": to.value, "reason": reason})
        if to in (State.REVOKED, State.PAUSED):
            self.to_disconnect.add(pid)

    # ------------------------------------------------------------------------------------------
    # doctor auth
    # ------------------------------------------------------------------------------------------
    def login(self, doctor_id: str, password: str) -> dict:
        expected = os.environ.get("DT_DEMO_PASSWORD", "demo")
        if doctor_id not in self.doctors or not hmac.compare_digest(password, expected):
            self._audit(doctor_id or "unknown", "login_failed")
            raise HTTPException(401, "invalid credentials")
        self._audit(doctor_id, "login")
        token = auth.issue({"typ": "access", "role": "doctor", "sub": doctor_id}, 12 * 3600)
        return {"token": token, "doctor": self.doctor(doctor_id)}

    # ------------------------------------------------------------------------------------------
    # enrol / configure
    # ------------------------------------------------------------------------------------------
    def create_patient(self, claims: dict) -> str:
        """Create a brand-new synthetic patient (never seen by the models) and add it to the live engine."""
        from data_gen.ehr_generator import generate_ehr
        from data_gen.physiology import params_from_ehr
        from data_gen.world import calibrate_basal

        gc = get_config()
        rng = np.random.default_rng(int(time.time() * 1000) % 2**32)
        ehr, lat = generate_ehr(1, rng, gc["cohort"]["urban_fraction"])
        params = params_from_ehr(ehr, lat, rng)
        params = calibrate_basal(ehr, lat, params, pd.Timestamp(gc["cohort"]["start_date"]), 7, gc["simulation"]["sensor"], days=2, iters=2)
        lat = lat.join(params.to_frame(lat.index))
        pid = self.engine.add_patient(ehr, lat)
        self.store.x("INSERT OR REPLACE INTO extra_patients (pid, doctor_id, ehr, latent) VALUES (?,?,?,?)",
                     (pid, claims["sub"], ehr.to_json(orient="split"), lat.to_json(orient="split")))
        self.store.ensure_patient(pid, claims["sub"])
        self._audit(claims["sub"], "patient_created", pid, {"synthetic": True})
        return pid

    def enroll(self, claims: dict, pid: str, template: str = "standard") -> dict:
        r = self.assigned(claims, pid)
        if template not in TEMPLATES:
            raise HTTPException(400, f"unknown template; choose from {list(TEMPLATES)}")
        if not r["config"]:
            cfg = from_template(template, self.engine._ehr_raw(pid))
            self.store.update_patient(pid, config=cfg.model_dump())
        self._audit(claims["sub"], "enroll", pid, {"template": template})
        return self.manager(claims, pid)

    def configure(self, claims: dict, pid: str, cfg: PortalConfig) -> dict:
        r = self.assigned(claims, pid)
        old = r["config"] or {}
        new = cfg.model_dump()
        changed = sorted(k for k in new if old.get(k) != new.get(k))
        self.store.update_patient(pid, config=new)
        self._audit(claims["sub"], "config_update", pid, {"changed": changed, "template": new["template"]})
        if r["state"] == State.ACTIVE.value and "care_plan" in changed:
            self.push_card(claims, pid, "care_plan_update", t(new["language"], "notify.card_title", doctor=self.doctor(claims["sub"])["title"]),
                           " · ".join(i["text"] for i in care_plan_text(new, new["language"])["items"][:3]))
        return self.manager(claims, pid)

    # ------------------------------------------------------------------------------------------
    # invites
    # ------------------------------------------------------------------------------------------
    def _active_invite(self, pid: str) -> dict | None:
        r = self.store.q("SELECT * FROM invites WHERE pid=? AND status='active' ORDER BY created DESC LIMIT 1", (pid,))
        return r[0] if r else None

    def launch(self, claims: dict, pid: str, base_url: str) -> dict:
        """Create a fresh single-use invite (also used for 'regenerate'); supersedes any older invite."""
        r = self.assigned(claims, pid)
        if not r["config"]:
            raise HTTPException(400, "configure the patient interface first")
        try:
            check_transition(r["state"], State.INVITED)
        except InvalidTransition as e:
            raise HTTPException(409, str(e)) from None
        self.store.x("UPDATE invites SET status='superseded' WHERE pid=? AND status IN ('active','locked')", (pid,))
        jti = uuid.uuid4().hex
        ttl = int(self.cfg["invite_ttl_hours"] * 3600)
        token = auth.issue({"typ": "invite", "pid": pid, "jti": jti}, ttl)
        self.store.x("INSERT INTO invites (jti, pid, created, expires_ts, status, sends) VALUES (?,?,?,?,?,1)",
                     (jti, pid, now_iso(), time.time() + ttl, "active"))
        self._invite_tokens[jti] = token
        self.transition(pid, State.INVITED, claims["sub"], "invite_created" if r["state"] != "INVITED" else "invite_regenerated",
                        session_id=None, device_hash=None)
        link = self._link(base_url, token)
        self.store.send(pid, "sms", f"patient {pid} (mock)", f"[Demo SMS] {self.doctor(claims['sub'])['title']} invited you to your "
                                                             f"diabetes twin app: {link}")
        self._audit(claims["sub"], "invite_created", pid, {"jti": jti[:8], "expires_in_h": self.cfg["invite_ttl_hours"]})
        return self.invite_info(pid, base_url)

    def _link(self, base_url: str, token: str) -> str:
        base = (self.cfg.get("public_base_url") or base_url).rstrip("/")
        return f"{base}/patient/?invite={token}"

    def invite_info(self, pid: str, base_url: str) -> dict | None:
        inv = self._active_invite(pid) or (self.store.q("SELECT * FROM invites WHERE pid=? ORDER BY created DESC LIMIT 1", (pid,)) or [None])[0]
        if not inv:
            return None
        token = self._invite_tokens.get(inv["jti"])
        if token is None and inv["status"] == "active":  # server restarted: re-sign the same invite (same jti/expiry)
            token = auth.issue({"typ": "invite", "pid": pid, "jti": inv["jti"]}, max(int(inv["expires_ts"] - time.time()), 1))
            self._invite_tokens[inv["jti"]] = token
        return {"status": inv["status"], "expires_at": datetime.fromtimestamp(inv["expires_ts"], timezone.utc).isoformat(timespec="seconds"),
                "seconds_left": max(int(inv["expires_ts"] - time.time()), 0), "sends": inv["sends"], "attempts": inv["attempts"],
                "link": self._link(base_url, token) if token and inv["status"] == "active" else None}

    def resend(self, claims: dict, pid: str, base_url: str) -> dict:
        self.assigned(claims, pid)
        inv = self._active_invite(pid)
        if not inv or inv["expires_ts"] < time.time():
            raise HTTPException(409, "no active invite; regenerate one")
        if inv["sends"] >= 5:
            raise HTTPException(429, "resend limit reached; regenerate the invite")
        self.store.x("UPDATE invites SET sends=sends+1 WHERE jti=?", (inv["jti"],))
        info = self.invite_info(pid, base_url)
        self.store.send(pid, "sms", f"patient {pid} (mock)", f"[Demo SMS] Reminder: open your diabetes twin app: {info['link']}")
        self._audit(claims["sub"], "invite_resent", pid, {"jti": inv["jti"][:8]})
        return info

    # ------------------------------------------------------------------------------------------
    # patient activation: open invite -> OTP -> consent
    # ------------------------------------------------------------------------------------------
    def _invite_from_token(self, token: str) -> tuple[dict, dict]:
        c = auth.decode(token, "invite")
        rows = self.store.q("SELECT * FROM invites WHERE jti=?", (c["jti"],))
        if not rows:
            raise HTTPException(401, "invalid invite")
        inv = rows[0]
        if inv["status"] == "used":
            raise HTTPException(410, "this invite has already been used")
        if inv["status"] != "active":
            raise HTTPException(410, f"this invite is no longer valid ({inv['status']}); ask your doctor for a new one")
        if inv["expires_ts"] < time.time():
            raise HTTPException(410, "this invite has expired; ask your doctor for a new one")
        return c, inv

    def open_invite(self, token: str, device_id: str, client: str) -> dict:
        self.open_limiter.check(client)
        c, inv = self._invite_from_token(token)
        r = self.record(c["pid"])
        if r["state"] not in (State.INVITED.value,):
            raise HTTPException(409, "invite cannot be used in the current state")
        otp = f"{secrets.randbelow(10**6):06d}"
        self.store.x("UPDATE invites SET otp_hash=?, otp_expires_ts=? WHERE jti=?",
                     (auth.hash_secret(otp + inv["jti"]), time.time() + 60 * self.cfg["otp_ttl_min"], inv["jti"]))
        self.store.send(c["pid"], "sms", f"patient {c['pid']} (mock)",
                        f"[Demo SMS] Your diabetes twin code is {otp}. It is valid for {self.cfg['otp_ttl_min']} minutes.")
        self._audit("patient", "otp_sent", c["pid"], {"channel": "mock_sms"})
        cfg = r["config"] or {}
        return {"otp_sent": True, "doctor": self.doctor(r["doctor_id"]), "language": cfg.get("language", "en"),
                "dev_mode": bool(self.cfg.get("dev_show_otp")), "otp_ttl_min": self.cfg["otp_ttl_min"]}

    def dev_otp(self, token: str) -> dict:
        """DEMO ONLY: read the mock SMS so the demo works without a phone. Disabled unless portal.dev_show_otp."""
        if not self.cfg.get("dev_show_otp"):
            raise HTTPException(404, "not available")
        c, _ = self._invite_from_token(token)
        msgs = [m for m in self.store.outbox(10, c["pid"]) if "code is" in m["body"]]
        return {"message": msgs[0]["body"] if msgs else None}

    def verify_otp(self, token: str, otp: str, device_id: str, client: str) -> dict:
        c, inv = self._invite_from_token(token)
        self.otp_limiter.check(client + "|" + inv["jti"])
        if not inv["otp_hash"] or (inv["otp_expires_ts"] or 0) < time.time():
            raise HTTPException(401, "code expired; request a new one")
        if not hmac.compare_digest(auth.hash_secret(otp.strip() + inv["jti"]), inv["otp_hash"]):
            attempts = inv["attempts"] + 1
            locked = attempts >= self.cfg["otp_max_attempts"]
            self.store.x("UPDATE invites SET attempts=?, status=? WHERE jti=?", (attempts, "locked" if locked else "active", inv["jti"]))
            self._audit("patient", "otp_failed", c["pid"], {"attempts": attempts, "locked": locked})
            raise HTTPException(403 if locked else 401, "too many wrong codes; ask your doctor for a new invite" if locked
                                else f"wrong code ({self.cfg['otp_max_attempts'] - attempts} tries left)")
        sid = uuid.uuid4().hex
        dev = auth.hash_secret(device_id)
        self.store.x("UPDATE invites SET status='used' WHERE jti=?", (inv["jti"],))  # single use
        self.transition(c["pid"], State.CONSENT_PENDING, "patient", "otp_verified", session_id=sid, device_hash=dev,
                        last_activity=now_iso())
        tok = auth.issue({"typ": "access", "role": "patient", "sub": c["pid"], "sid": sid}, self.cfg["patient_token_days"] * 86400)
        r = self.record(c["pid"])
        return {"token": tok, "state": State.CONSENT_PENDING.value, "doctor": self.doctor(r["doctor_id"]),
                "language": (r["config"] or {}).get("language", "en"), "consent_version": CONSENT_VERSION}

    # ------------------------------------------------------------------------------------------
    # sessions (consent gate) and patient-side actions
    # ------------------------------------------------------------------------------------------
    def session(self, token: str, device_id: str | None, allow: tuple[State, ...] = (State.ACTIVE,)) -> dict:
        """Validate a patient / preview / caregiver token. Patients must use their bound device and current session."""
        c = auth.decode(token, "access")
        role = c.get("role")
        pid = c.get("sub")
        r = self.record(pid)
        if role == "patient":
            if r["session_id"] != c.get("sid"):
                raise HTTPException(401, "session ended")
            if not device_id or not hmac.compare_digest(auth.hash_secret(device_id), r["device_hash"] or ""):
                raise HTTPException(401, "this app is linked to another device")
            if State(r["state"]) not in allow:
                raise HTTPException(403, f"state {r['state']}")
            self.store.update_patient(pid, last_activity=now_iso())
        elif role == "preview":
            if r["doctor_id"] != c.get("doc"):
                raise HTTPException(403, "not your patient")
        elif role == "caregiver":
            if not self.store.q("SELECT 1 FROM caregiver_links WHERE jti=? AND revoked=0", (c["jti"],)) or r["state"] != State.ACTIVE.value:
                raise HTTPException(403, "caregiver access is not active")
        else:
            raise HTTPException(403, "role not allowed")
        return {"claims": c, "role": role, "pid": pid, "rec": r}

    def me(self, s: dict) -> dict:
        """What the app should render now. No twin data unless ACTIVE (or a doctor preview)."""
        r, pid = s["rec"], s["pid"]
        cfg = r["config"] or from_template("standard").model_dump()
        lang = cfg["language"]
        doc = self.doctor(r["doctor_id"])
        state = r["state"]
        if s["role"] == "caregiver":
            return self.caregiver_view(pid, cfg, doc)
        if s["role"] == "patient" and state == State.CONSENT_PENDING.value:
            return {"state": state, "language": lang, "doctor": doc, "consent_version": CONSENT_VERSION,
                    "features": cfg["features"], "caregiver_allowed": cfg["features"]["caregiver"]}
        if s["role"] == "patient" and state == State.PAUSED.value:
            return {"state": state, "language": lang, "doctor": doc, "message": t(lang, "status.PAUSED")}
        if s["role"] == "preview":
            self._audit(s["claims"]["doc"], "preview_as_patient", pid)
        return self.view(pid, cfg, doc, state if s["role"] == "patient" else f"PREVIEW:{state}")

    def view(self, pid: str, cfg: dict, doc: dict, state: str) -> dict:
        lang = cfg["language"]
        tw = self.engine.twins[pid]
        notes = [self.notifier.render(n, lang, doc["title"]) for n in
                 self.store.q("SELECT * FROM notifications WHERE pid=? AND delivered=1 ORDER BY priority ASC, id DESC LIMIT 30", (pid,))]
        notes.sort(key=lambda n: (n["seen"], n["priority"], -n["id"]))
        cards = self.store.q("SELECT id, ts_sim, source, kind, title, body, status FROM cards WHERE pid=? ORDER BY status DESC, id DESC LIMIT 20", (pid,))
        msgs = self.store.q("SELECT id, ts_sim, sender, author, body, read_at FROM messages WHERE pid=? ORDER BY id DESC LIMIT 20", (pid,))
        logs = [{**lg, "payload": json.loads(lg["payload"])} for lg in
                self.store.q("SELECT ts_sim, kind, payload FROM patient_logs WHERE pid=? ORDER BY id DESC LIMIT 200", (pid,))]
        with self.engine.lock:
            out = build(tw, cfg, lang, doc, notes, cards, msgs, logs, state)
            out["food"] = self.food(pid, lang, cfg["target"]["high"], logs)
            return out

    # ------------------------------------------------------------------------------------------
    # daily consumption pattern + personal food-impact insights
    # ------------------------------------------------------------------------------------------
    def food(self, pid: str, lang: str = "en", high: int = 180, logs: list[dict] | None = None) -> dict:
        tw = self.engine.twins[pid]
        if logs is None:
            logs = [{**lg, "payload": json.loads(lg["payload"])} for lg in
                    self.store.q("SELECT ts_sim, kind, payload FROM patient_logs WHERE pid=? ORDER BY id DESC LIMIT 200", (pid,))]
        now = self.engine.clock()
        # ignore logs "from the future" (possible after a server restart re-simulates the same clock; reset-portal for clean demos)
        symptoms = [lg for lg in logs if lg["kind"] == "symptom" and lg["ts_sim"] <= now]
        with self.engine.lock:
            return analyse(list(tw.events), list(tw.cgm_hist), symptoms, tw.now, lang, high)

    def accept_consent(self, s: dict, choices: dict, language: str) -> dict:
        pid, r = s["pid"], s["rec"]
        if not choices.get("twin_view"):
            raise HTTPException(400, "the core consent (use my data to show me my twin) is required to continue")
        if language not in LANGS:
            raise HTTPException(400, "unsupported language")
        cfg = r["config"]
        cfg["language"] = language
        consent = {"version": CONSENT_VERSION, "accepted_at": now_iso(), "accepted_at_sim": self.engine.clock(),
                   "choices": {k: bool(choices.get(k)) for k in ("twin_view", "share_logs", "caregiver")}}
        self.transition(pid, State.ACTIVE, "patient", "consent_accepted", config=cfg, consent=consent)
        self._audit("patient", "consent_accepted", pid, consent)
        self._on_activated(pid, cfg, language, self.doctor(r["doctor_id"]))
        return {"state": State.ACTIVE.value}

    def _on_activated(self, pid: str, cfg: dict, language: str, doc: dict) -> None:
        """Seed the care-plan cards and the doctor's welcome message when an app becomes ACTIVE."""
        for item in care_plan_text(cfg, language)["items"]:
            self.store.x("INSERT INTO cards (pid, ts_sim, source, kind, title, body) VALUES (?,?,?,?,?,?)",
                         (pid, self.engine.clock(), "care_plan", item["kind"], item["text"], ""))
        self.store.x("INSERT INTO messages (pid, ts_sim, sender, author, body) VALUES (?,?,?,?,?)",
                     (pid, self.engine.clock(), "doctor", doc["title"], {"en": "Welcome! I will see your sugar trends here. Message me if anything worries you.",
                                                                          "hi": "स्वागत है! मैं यहाँ आपकी शुगर देखूँगा/देखूँगी। कोई चिंता हो तो संदेश भेजें।",
                                                                          "ta": "வரவேற்கிறோம்! உங்கள் சர்க்கரை நிலையை இங்கே பார்ப்பேன். கவலை இருந்தால் செய்தி அனுப்புங்கள்."}[language]))

    # ------------------------------------------------------------------------------------------
    # DEMO patient accounts (pre-activated, one-tap login). Disabled unless portal.demo_accounts_enabled.
    # ------------------------------------------------------------------------------------------
    def _demo_pid(self, acc: dict) -> str | None:
        mine = sorted(r["pid"] for r in self.store.all_patients() if r["doctor_id"] == acc["doctor"] and r["pid"] in self.engine.base_ids)
        return mine[-acc["pick"]] if len(mine) >= acc["pick"] else None

    def _activate_demo(self, acc: dict, pid: str) -> None:
        """Walk a demo patient through the real lifecycle (audited as 'demo-seed'): enrol -> invite -> consent -> ACTIVE."""
        cfg = from_template(acc["template"], self.engine._ehr_raw(pid)).model_dump()
        cfg["language"] = acc["language"]
        if acc.get("caregiver"):
            cfg["features"]["caregiver"] = True
        self.store.update_patient(pid, config=cfg)
        self._audit("demo-seed", "enroll", pid, {"template": acc["template"], "demo_account": acc["id"]})
        jti = uuid.uuid4().hex
        self.store.x("INSERT INTO invites (jti, pid, created, expires_ts, status, sends) VALUES (?,?,?,?,?,0)",
                     (jti, pid, now_iso(), time.time(), "used"))
        self.transition(pid, State.INVITED, "demo-seed", "demo_account")
        self.transition(pid, State.CONSENT_PENDING, "demo-seed", "demo_account")
        consent = {"version": CONSENT_VERSION, "accepted_at": now_iso(), "accepted_at_sim": self.engine.clock(), "simulated_demo_account": True,
                   "choices": {"twin_view": True, "share_logs": True, "caregiver": bool(acc.get("caregiver"))}}
        self.transition(pid, State.ACTIVE, "demo-seed", "demo_account", consent=consent)
        self._on_activated(pid, cfg, acc["language"], self.doctor(acc["doctor"]))

    def seed_demo_accounts(self) -> None:
        if not self.cfg.get("demo_accounts_enabled"):
            return
        for acc in self.cfg.get("demo_accounts", []):
            pid = self._demo_pid(acc)
            if pid and self.store.patient(pid)["state"] in (State.NOT_ENROLLED.value, State.REVOKED.value):
                self._activate_demo(acc, pid)

    def demo_accounts(self) -> list[dict]:
        if not self.cfg.get("demo_accounts_enabled"):
            return []
        out = []
        for acc in self.cfg.get("demo_accounts", []):
            pid = self._demo_pid(acc)
            if pid:
                out.append({"id": acc["id"], "label": acc["label"], "language": acc["language"], "patient_id": pid,
                            "doctor": self.doctor(acc["doctor"])["name"], "state": self.store.patient(pid)["state"]})
        return out

    def demo_login(self, account: str, device_id: str, client: str) -> dict:
        """DEMO ONLY: start a patient session for a demo account on this device (re-activates it if revoked)."""
        if not self.cfg.get("demo_accounts_enabled"):
            raise HTTPException(404, "demo accounts are disabled")
        self.open_limiter.check(client + "|demo")
        acc = next((a for a in self.cfg.get("demo_accounts", []) if a["id"] == account), None)
        pid = self._demo_pid(acc) if acc else None
        if not pid:
            raise HTTPException(404, "unknown demo account")
        if self.store.patient(pid)["state"] in (State.NOT_ENROLLED.value, State.REVOKED.value):
            self._activate_demo(acc, pid)
        sid = uuid.uuid4().hex
        self.store.update_patient(pid, session_id=sid, device_hash=auth.hash_secret(device_id), last_activity=now_iso())
        self._audit("patient", "demo_login", pid, {"account": account})
        tok = auth.issue({"typ": "access", "role": "patient", "sub": pid, "sid": sid}, self.cfg["patient_token_days"] * 86400)
        return {"token": tok, "patient_id": pid, "language": acc["language"]}

    def withdraw(self, s: dict) -> dict:
        pid, r = s["pid"], s["rec"]
        consent = r["consent"] or {}
        consent["withdrawn_at"] = now_iso()
        self.store.x("UPDATE caregiver_links SET revoked=1 WHERE pid=?", (pid,))
        self.transition(pid, State.REVOKED, "patient", "consent_withdrawn", session_id=None, device_hash=None, consent=consent)
        self._audit("patient", "consent_withdrawn", pid)
        return {"state": State.REVOKED.value}

    def set_language(self, s: dict, language: str) -> dict:
        if language not in LANGS:
            raise HTTPException(400, "unsupported language")
        cfg = s["rec"]["config"]
        cfg["language"] = language
        self.store.update_patient(s["pid"], config=cfg)
        self._audit("patient", "language_changed", s["pid"], {"language": language})
        return {"language": language}

    def quick_log(self, s: dict, payload: dict) -> dict:
        pid, cfg = s["pid"], s["rec"]["config"]
        if not cfg["features"]["quick_log"]:
            raise HTTPException(403, "Quick Log is not enabled for you")
        kind = payload.get("kind")
        action: dict
        if kind == "meal":
            if payload.get("food") not in FOODS or payload.get("portion", "regular") not in ("small", "regular", "large"):
                raise HTTPException(400, "unknown food or portion")
            action = {"kind": "meal", "meal": FOODS[payload["food"]], "portion": payload.get("portion", "regular")}
        elif kind == "exercise":
            mins = int(payload.get("minutes", 15))
            if not 5 <= mins <= 120:
                raise HTTPException(400, "minutes must be 5-120")
            action = {"kind": "exercise", "minutes": mins, "intensity": payload.get("intensity", "moderate")}
        elif kind == "med":
            if payload.get("status") not in ("taken", "missed"):
                raise HTTPException(400, "status must be taken or missed")
            action = {"kind": "med", "status": payload["status"]}
        elif kind == "symptom":
            syms = [x for x in payload.get("symptoms", []) if x in SYMPTOMS]
            if not syms:
                raise HTTPException(400, "pick at least one symptom")
            action = {"kind": "symptom", "symptoms": syms}
        else:
            raise HTTPException(400, "unknown log kind")
        effect = self.engine.perform(pid, action)
        dur = int(payload.get("duration_ms") or 0)
        self.store.x("INSERT INTO patient_logs (pid, ts_sim, kind, payload, duration_ms) VALUES (?,?,?,?,?)",
                     (pid, self.engine.clock(), kind, json.dumps({**action, **effect}), dur))
        share = (s["rec"]["consent"] or {}).get("choices", {}).get("share_logs", True)
        self._audit("patient", "patient_log", pid, {"kind": kind, "shared_with_doctor": share, "duration_ms": dur})
        resp = {"ok": True, "kind": kind, "effect": effect}
        if kind == "symptom" and {"dizziness", "sweating"} & set(action["symptoms"]):
            lang = cfg["language"]
            resp["safety"] = {"first_aid": t(lang, "first_aid"), "note": t(lang, "notify.safety_note")}
        return resp

    def try_it(self, s: dict, preset: str) -> dict:
        pid, cfg = s["pid"], s["rec"]["config"]
        if not cfg["features"]["try_it"]:
            raise HTTPException(403, "Try-It is not enabled for you")
        if preset not in TRYIT:
            raise HTTPException(400, f"preset must be one of {TRYIT}")
        lang = cfg["language"]
        tw = self.engine.twins[pid]
        if preset == "walk15":
            sc = [{"name": "walk", "interventions": [{"type": "exercise", "minutes": 15, "intensity": "moderate", "in_min": 0}]}]
        elif preset == "roti_rice":
            sc = [{"name": "rice", "interventions": [{"type": "meal", "carbs": 80, "gi": "high", "in_min": 0}]},
                  {"name": "roti", "interventions": [{"type": "meal", "carbs": 60, "gi": "medium", "in_min": 0}]}]
        else:
            sc = [{"name": "late", "interventions": [{"type": "meal", "carbs": 70, "gi": "medium", "at": "21:30"}]},
                  {"name": "early", "interventions": [{"type": "meal", "carbs": 70, "gi": "medium", "at": "19:30"}]}]
        with self.engine.lock:
            res = tw.what_if(sc)
        if preset == "walk15":
            before, after = res["baseline"]["trajectory"], res["scenarios"][0]["trajectory"]
        else:
            before, after = res["scenarios"][0]["trajectory"], res["scenarios"][1]["trajectory"]
        n = min(len(before), 48 if preset != "early_dinner" else len(before))
        delta = round(max(before[:n]) - max(after[:n]))
        key = "tryit.better" if delta >= 5 else "tryit.worse" if delta <= -5 else "tryit.same"
        self._audit("patient", "try_it", pid, {"preset": preset, "delta_peak": delta})
        return {"preset": preset, "question": t(lang, f"tryit.{preset}"), "times": res["times"][:n],
                "before": before[:n], "after": after[:n], "delta_peak": delta, "result": t(lang, key, delta=abs(delta)),
                "note": t(lang, "tryit.note"), "target": cfg["target"]}

    def ack_alert(self, s: dict, nid: int, understood: bool | None) -> dict:
        self.store.x("UPDATE notifications SET seen_at=COALESCE(seen_at, ?), understood=COALESCE(?, understood) WHERE id=? AND pid=?",
                     (now_iso(), None if understood is None else int(understood), nid, s["pid"]))
        self._audit("patient", "alert_seen", s["pid"], {"id": nid, "understood": understood})
        return {"ok": True}

    def card_done(self, s: dict, cid: int) -> dict:
        self.store.x("UPDATE cards SET status='done', done_at=? WHERE id=? AND pid=?", (self.engine.clock(), cid, s["pid"]))
        self._audit("patient", "card_done", s["pid"], {"id": cid})
        return {"ok": True}

    def message_read(self, s: dict, mid: int) -> dict:
        self.store.x("UPDATE messages SET read_at=COALESCE(read_at, ?) WHERE id=? AND pid=?", (now_iso(), mid, s["pid"]))
        return {"ok": True}

    def access_log(self, s: dict) -> list[dict]:
        """Who viewed or changed my data (patient's right to access), newest first."""
        rows = self.engine.audit.recent(100, s["pid"])
        keep = {"view_patient", "preview_as_patient", "config_update", "state_change", "invite_created", "message_sent",
                "card_pushed", "consent_accepted", "consent_withdrawn", "acknowledge_alert", "add_note", "suggest_intervention",
                "caregiver_link_created", "what_if"}
        out = []
        for r in rows:
            if r["action"] in keep:
                who = self.doctor(r["actor"])["name"] if r["actor"] in self.doctors else r["actor"]
                out.append({"ts": r["ts_sim"] or r["ts_wall"], "who": who, "action": r["action"]})
        return out

    # ------------------------------------------------------------------------------------------
    # caregiver (optional, consented, read-only)
    # ------------------------------------------------------------------------------------------
    def caregiver_link(self, s: dict, base_url: str) -> dict:
        r = s["rec"]
        if not r["config"]["features"]["caregiver"] or not (r["consent"] or {}).get("choices", {}).get("caregiver"):
            raise HTTPException(403, "caregiver sharing needs your consent and your doctor's approval")
        jti = uuid.uuid4().hex
        tok = auth.issue({"typ": "access", "role": "caregiver", "sub": s["pid"], "jti": jti}, self.cfg["caregiver_token_days"] * 86400)
        self.store.x("INSERT INTO caregiver_links (jti, pid, created) VALUES (?,?,?)", (jti, s["pid"], now_iso()))
        self._audit("patient", "caregiver_link_created", s["pid"])
        base = (self.cfg.get("public_base_url") or base_url).rstrip("/")
        return {"link": f"{base}/patient/?caregiver={tok}"}

    def caregiver_view(self, pid: str, cfg: dict, doc: dict) -> dict:
        lang = cfg["language"]
        tw = self.engine.twins[pid]
        with self.engine.lock:
            st, g = status(tw, lang), glucose(tw, lang)
        safety = [self.notifier.render(n, lang, doc["title"]) for n in
                  self.store.q("SELECT * FROM notifications WHERE pid=? AND safety=1 AND delivered=1 ORDER BY id DESC LIMIT 5", (pid,))]
        self._audit("caregiver", "caregiver_view", pid)
        return {"state": "CAREGIVER", "language": lang, "doctor": doc, "status": st,
                "glucose": {k: g[k] for k in ("value", "trend", "trend_icon", "trend_text", "unit", "ts")},
                "alerts": safety, "disclaimer": t(lang, "notify.disclaimer")}

    # ------------------------------------------------------------------------------------------
    # doctor-side control and two-way channel
    # ------------------------------------------------------------------------------------------
    def pause(self, claims: dict, pid: str) -> dict:
        self.assigned(claims, pid)
        self.transition(pid, State.PAUSED, claims["sub"], "doctor_paused")
        return self.manager(claims, pid)

    def resume(self, claims: dict, pid: str) -> dict:
        self.assigned(claims, pid)
        self.transition(pid, State.ACTIVE, claims["sub"], "doctor_resumed")
        return self.manager(claims, pid)

    def revoke(self, claims: dict, pid: str) -> dict:
        self.assigned(claims, pid)
        self.store.x("UPDATE invites SET status='revoked' WHERE pid=? AND status='active'", (pid,))
        self.store.x("UPDATE caregiver_links SET revoked=1 WHERE pid=?", (pid,))
        self.transition(pid, State.REVOKED, claims["sub"], "doctor_revoked", session_id=None, device_hash=None)
        return self.manager(claims, pid)

    def preview_token(self, claims: dict, pid: str) -> dict:
        self.assigned(claims, pid)
        tok = auth.issue({"typ": "access", "role": "preview", "sub": pid, "doc": claims["sub"]}, self.cfg["preview_token_min"] * 60)
        return {"token": tok, "path": f"/patient/?preview={tok}"}

    def send_message(self, claims: dict, pid: str, body: str) -> dict:
        r = self.assigned(claims, pid)
        doc = self.doctor(claims["sub"])
        mid = self.store.x("INSERT INTO messages (pid, ts_sim, sender, author, body) VALUES (?,?,?,?,?)",
                           (pid, self.engine.clock(), "doctor", doc["title"], body))
        if r["state"] == State.ACTIVE.value:
            self.notifier.emit(pid, pd.Timestamp(self.engine.clock()), "message", 1, False, "INFO", "notify.message_title",
                               "notify.open_care", {}, None, r["config"])
        self._audit(claims["sub"], "message_sent", pid, {"id": mid})
        return {"id": mid}

    def push_card(self, claims: dict, pid: str, kind: str, title: str, body: str) -> dict:
        r = self.record(pid)
        cid = self.store.x("INSERT INTO cards (pid, ts_sim, source, kind, title, body) VALUES (?,?,?,?,?,?)",
                           (pid, self.engine.clock(), "doctor", kind, title, body))
        if r["state"] == State.ACTIVE.value and r["config"]:
            self.notifier.emit(pid, pd.Timestamp(self.engine.clock()), "card", 1, False, "INFO", "notify.card_title",
                               "notify.open_care", {}, None, r["config"])
        self._audit(claims["sub"], "card_pushed", pid, {"id": cid, "kind": kind})
        return {"id": cid}

    def engagement(self, pid: str) -> dict:
        q = self.store.q
        n = q("SELECT COUNT(*) AS n, SUM(seen_at IS NOT NULL) AS seen, SUM(understood=1) AS und, SUM(understood IS NOT NULL) AS asked, "
              "SUM(safety) AS safety, SUM(escalated) AS esc FROM notifications WHERE pid=? AND delivered=1", (pid,))[0]
        sup = q("SELECT COUNT(*) AS n FROM notifications WHERE pid=? AND delivered=0", (pid,))[0]["n"]
        logs = q("SELECT kind, COUNT(*) AS n, AVG(duration_ms) AS ms FROM patient_logs WHERE pid=? GROUP BY kind", (pid,))
        last_logs = q("SELECT ts_sim, kind, payload FROM patient_logs WHERE pid=? ORDER BY id DESC LIMIT 8", (pid,))
        msgs = q("SELECT COUNT(*) AS n, SUM(read_at IS NOT NULL) AS read FROM messages WHERE pid=? AND sender='doctor'", (pid,))[0]
        cards = q("SELECT COUNT(*) AS n, SUM(status='done') AS done FROM cards WHERE pid=?", (pid,))[0]
        first = q("SELECT MIN(ts_sim) AS a, MAX(ts_sim) AS b FROM notifications WHERE pid=?", (pid,))[0]
        days = max((pd.Timestamp(first["b"]) - pd.Timestamp(first["a"])).total_seconds() / 86400, 1 / 24) if first["a"] else None
        return {
            "alerts_delivered": n["n"] or 0, "alerts_seen": n["seen"] or 0, "safety_alerts": n["safety"] or 0,
            "alerts_suppressed_by_cap": sup, "escalations": n["esc"] or 0,
            "alert_comprehension": (n["und"] or 0) / n["asked"] if n["asked"] else None,
            "alerts_per_day": round((n["n"] or 0) / days, 2) if days else None,
            "logs": {r["kind"]: r["n"] for r in logs},
            "median_time_to_log_s": round(np.median([r["ms"] for r in logs if r["ms"]]) / 1000, 1) if any(r["ms"] for r in logs) else None,
            "recent_logs": [{**r, "payload": json.loads(r["payload"])} for r in last_logs],
            "messages_sent": msgs["n"] or 0, "messages_read": msgs["read"] or 0,
            "cards_total": cards["n"] or 0, "cards_done": cards["done"] or 0,
        }

    def manager(self, claims: dict | None, pid: str, base_url: str = "") -> dict:
        """Everything the doctor's Patient Interface Manager panel shows."""
        r = self.record(pid)
        return {"patient_id": pid, "state": r["state"], "doctor": self.doctor(r["doctor_id"]),
                "assigned_to_me": claims is not None and r["doctor_id"] == claims.get("sub"),
                "config": r["config"], "consent": r["consent"], "last_activity": r["last_activity"],
                "invite": self.invite_info(pid, base_url), "engagement": self.engagement(pid),
                "outbox": self.store.outbox(6, pid)}

    def statuses(self, claims: dict | None) -> list[dict]:
        return [{"patient_id": r["pid"], "state": r["state"], "doctor_id": r["doctor_id"],
                 "assigned_to_me": claims is not None and r["doctor_id"] == claims.get("sub"),
                 "configured": bool(self.store.patient(r["pid"])["config"]), "last_activity": r["last_activity"]}
                for r in self.store.all_patients() if r["pid"] in self.engine.twins]

    def bulk_invite(self, claims: dict, pids: list[str], template: str, base_url: str) -> list[dict]:
        out = []
        for pid in pids:
            try:
                r = self.assigned(claims, pid)
                if r["state"] not in (State.NOT_ENROLLED.value, State.REVOKED.value):
                    out.append({"patient_id": pid, "ok": False, "error": f"state {r['state']}"})
                    continue
                self.enroll(claims, pid, template)
                inv = self.launch(claims, pid, base_url)
                out.append({"patient_id": pid, "ok": True, "link": inv["link"]})
            except HTTPException as e:
                out.append({"patient_id": pid, "ok": False, "error": e.detail})
        self._audit(claims["sub"], "bulk_invite", None, {"count": len(pids), "ok": sum(o["ok"] for o in out)})
        return out

    def usage_metrics(self) -> dict:
        """In-app usability metrics across all patients (for docs/USABILITY.md)."""
        q = self.store.q
        logs = q("SELECT duration_ms FROM patient_logs WHERE kind='meal' AND duration_ms>0")
        n = q("SELECT pid, COUNT(*) AS n, MIN(ts_sim) AS a, MAX(ts_sim) AS b FROM notifications WHERE delivered=1 GROUP BY pid")
        per_day = [r["n"] / max((pd.Timestamp(r["b"]) - pd.Timestamp(r["a"])).total_seconds() / 86400, 1 / 24) for r in n]
        und = q("SELECT AVG(understood) AS u, COUNT(understood) AS k FROM notifications WHERE understood IS NOT NULL")[0]
        return {"meal_logs": len(logs),
                "median_time_to_log_meal_s": round(float(np.median([r["duration_ms"] for r in logs])) / 1000, 1) if logs else None,
                "alerts_per_patient_day": round(float(np.mean(per_day)), 2) if per_day else None,
                "alert_comprehension": round(und["u"], 2) if und["k"] else None, "comprehension_answers": und["k"]}

    # ------------------------------------------------------------------------------------------
    # engine hook: runs inside Engine.tick (under the engine lock)
    # ------------------------------------------------------------------------------------------
    def after_tick(self) -> None:
        now = pd.Timestamp(self.engine.clock())
        for r in self.store.q("SELECT pid, doctor_id, config FROM portal_patient WHERE state='ACTIVE'"):
            pid = r["pid"]
            if pid not in self.engine.twins:
                continue
            cfg = json.loads(r["config"])
            tw = self.engine.twins[pid]
            cgm = tw.rows[-1]["cgm"] if tw.rows else None
            self.notifier.process(pid, now, tw.prediction, cgm, cfg)
            self.notifier.escalate(pid, now, cfg, self.doctor(r["doctor_id"])["name"])
            self._food_warnings(pid, tw, cfg, now)

    def _food_warnings(self, pid: str, tw, cfg: dict, now: pd.Timestamp) -> None:
        """When a meal is logged, warn gently if this food has a consistent spike pattern for this patient."""
        last = self._meal_seen.get(pid)
        meals = [e for e in tw.events if e.get("type") == "meal"]
        if not meals:
            return
        self._meal_seen[pid] = meals[-1]["ts"]
        if last is None:  # first tick after activation: don't warn about history
            return
        new = [e for e in meals if e["ts"] > last]
        if not new:
            return
        analysis = analyse(list(tw.events), list(tw.cgm_hist), [], now, "en", cfg["target"]["high"])
        for e in new:
            w = warning_for(analysis, food_key(e.get("name")))
            if w:
                self.notifier.emit(pid, now, "food_warning", 2, False, "AMBER", "foodai.warn_title", "foodai.warn_body",
                                   {**w, "minutes": cfg["care_plan"]["walk_minutes"]}, None, cfg)
                self._audit("twin-engine", "food_warning", pid, {"food": w["food_key"], "n": w["n"], "mean_peak": w["peak"]})
