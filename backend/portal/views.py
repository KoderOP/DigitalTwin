"""Patient-facing projection of the twin: minimised, translated, plain language.

Only what the patient app needs is included (data minimisation): no EHR internals, no model
features, no other patients. The doctor's "view as patient" preview renders exactly this payload.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.portal.explain_text import confidence, is_low, next_action, why
from backend.portal.i18n import t
from common.glycemic import summary_metrics
from twin.twin import DigitalTwin

FOOD_PRESETS = ("idli_sambar", "dal_chawal", "roti_sabzi", "poha", "biryani")
TREND_ICON = {"up_fast": "⇈", "up": "↑", "flat": "→", "down": "↓", "down_fast": "⇊"}


def _trend(features: dict) -> str:
    s = features.get("w_slope_15m") or 0
    return "up_fast" if s > 2 else "up" if s > 1 else "down_fast" if s < -2 else "down" if s < -1 else "flat"


def status(tw: DigitalTwin, lang: str) -> dict:
    p = tw.prediction or {}
    cgm = tw.rows[-1]["cgm"] if tw.rows else None
    level = p.get("level", "GREEN")
    mins = p.get("minutes_to_spike")
    if is_low(cgm, p):
        level, key = "LOW", "status.LOW"
    elif level == "HIGH":
        key = "status.HIGH"
    elif level in ("RED", "AMBER"):
        key = f"status.{level}" if mins else f"status.{level}_nominutes"
    else:
        key = "status.GREEN"
    icon = {"GREEN": "smile", "AMBER": "alert", "RED": "alert-octagon", "HIGH": "arrow-up", "LOW": "alert-octagon"}[level]
    return {"level": level, "icon": icon, "sentence": t(lang, key, minutes=mins),
            "sub": t(lang, "status.GREEN_sub") if level == "GREEN" else None,
            "minutes_to_spike": mins if level in ("AMBER", "RED") else None,
            "confidence": confidence(None if level in ("LOW", "HIGH") else p.get("risk"), lang)}


def glucose(tw: DigitalTwin, lang: str) -> dict:
    p = tw.prediction or {}
    f = p.get("features", {})
    last = tw.rows[-1] if tw.rows else {}
    cgm = last.get("cgm")
    tr = _trend(f)
    hist = [{"ts": r["ts"].isoformat(), "g": None if np.isnan(r["cgm"]) else round(r["cgm"])} for r in list(tw.rows)[-24:]]
    fc = [{"minutes": 0, "low": p.get("g_now"), "mid": p.get("g_now"), "high": p.get("g_now")}] + [
        {"minutes": x["minutes"], "low": round(x["p10"]), "mid": round(x["p50"]), "high": round(x["p90"])} for x in p.get("forecast", [])]
    dq = tw.data_quality()
    return {"value": None if cgm is None or np.isnan(cgm) else round(cgm), "estimated": p.get("g_now"),
            "trend": tr, "trend_icon": TREND_ICON[tr], "trend_text": t(lang, f"trend.{tr}"), "unit": "mg/dL",
            "ts": last.get("ts").isoformat() if last else None, "history": hist, "forecast": fc,
            "sensor_ok": dq["status"] == "good", "imputing": dq["imputing"]}


def my_day(tw: DigitalTwin, cfg: dict, lang: str, logs: list[dict], notes: list[dict]) -> list[dict]:
    if not tw.rows:
        return []
    now = tw.now
    day0 = now.normalize()
    rows = [r for r in tw.rows if r["ts"] >= day0 - pd.Timedelta(hours=6)]
    items: list[dict] = []
    # sleep: one entry at the final morning wake-up (brief night awakenings are not separate wake-ups)
    wakes = [b["ts"] for a, b in zip(rows, rows[1:])
             if a["sleep_stage"] > 0 and b["sleep_stage"] == 0 and day0 <= b["ts"] < day0 + pd.Timedelta(hours=12)]
    if wakes and tw.last_sleep_h:
        items.append({"ts": wakes[-1].isoformat(), "kind": "sleep", "icon": "moon", "text": t(lang, "timeline.sleep", hours=round(tw.last_sleep_h, 1))})
    today = [r for r in rows if r["ts"] >= day0]
    # walks: >= 10 min of moderate activity
    run = []
    for r in today + [{"activity": 0, "ts": now}]:
        if (r.get("activity") or 0) >= 0.3:
            run.append(r)
        else:
            if len(run) >= 2:
                items.append({"ts": run[0]["ts"].isoformat(), "kind": "walk", "icon": "walk",
                              "text": t(lang, "timeline.walk", minutes=len(run) * 5)})
            run = []
    # highs / lows (first crossing of each episode)
    hi = cfg["target"]["high"]
    prev = None
    for r in today:
        g = r["cgm"]
        if np.isnan(g):
            continue
        if g > hi and (prev is None or prev <= hi):
            items.append({"ts": r["ts"].isoformat(), "kind": "high", "icon": "arrow-up", "text": t(lang, "timeline.high", high=hi)})
        if g < 70 and (prev is None or prev >= 70):
            items.append({"ts": r["ts"].isoformat(), "kind": "low", "icon": "arrow-down", "text": t(lang, "timeline.low")})
        prev = g
    for e in tw.events:
        ts = pd.Timestamp(e["ts"])
        if ts < day0:
            continue
        if e["type"] == "meal":
            key = next((k for k in FOOD_PRESETS if k in (e.get("name") or "")), None)
            food = t(lang, f"food.{key}") if key else (e.get("label") or t(lang, "food.other")).replace(" (logged in app)", "")
            items.append({"ts": ts.isoformat(), "kind": "meal", "icon": "plate", "text": t(lang, "timeline.meal", food=food, carbs=round(e.get("amount") or 0))})
        elif e["type"] == "med":
            items.append({"ts": ts.isoformat(), "kind": "med", "icon": "pill", "text": t(lang, "timeline.med", label=e.get("label") or "")})
    for lg in logs:
        if lg["kind"] == "symptom" and pd.Timestamp(lg["ts_sim"]) >= day0:
            names = ", ".join(t(lang, f"symptoms.{s}") for s in lg["payload"].get("symptoms", []))
            items.append({"ts": lg["ts_sim"], "kind": "symptom", "icon": "note", "text": t(lang, "timeline.symptom", symptoms=names)})
        if lg["kind"] == "med" and lg["payload"].get("status") == "missed" and pd.Timestamp(lg["ts_sim"]) >= day0:
            items.append({"ts": lg["ts_sim"], "kind": "med", "icon": "pill", "text": t(lang, "timeline.med_missed")})
    for n in notes:
        if pd.Timestamp(n["ts"]) >= day0 and n.get("delivered", True):
            items.append({"ts": n["ts"], "kind": "alert", "icon": "bell", "text": n["title"]})
    return sorted(items, key=lambda x: x["ts"])


def progress(tw: DigitalTwin, cfg: dict, lang: str, log_dates: set[str]) -> dict:
    lo, hi = cfg["target"]["low"], cfg["target"]["high"]
    hist = pd.DataFrame(list(tw.cgm_hist), columns=["ts", "g"]).dropna()
    if hist.empty:
        return {}
    hist["date"] = pd.to_datetime(hist["ts"]).dt.date
    days = []
    for d, grp in hist.groupby("date"):
        tir = float(((grp.g >= lo) & (grp.g <= hi)).mean() * 100)
        days.append({"date": str(d), "tir": round(tir), "mean": round(float(grp.g.mean()))})
    days = days[-7:]
    today = days[-1]["tir"] if days else 0
    week = round(float(np.mean([d["tir"] for d in days]))) if days else 0
    msg = "progress.good" if today >= 70 else "progress.mid" if today >= 40 else "progress.low"
    streak, d = 0, tw.now.normalize()
    while str(d.date()) in log_dates:
        streak += 1
        d -= pd.Timedelta(days=1)
    m24 = summary_metrics(hist.g.tail(288))
    return {"today_tir": today, "week_tir": week, "message": t(lang, msg, tir=today), "week_text": t(lang, "progress.week", tir=week),
            "streak": streak, "streak_text": t(lang, "progress.streak", n=streak) if streak else None, "days": days,
            "target": {"low": lo, "high": hi}, "good_days": sum(x["tir"] >= 70 for x in days), "cv": m24["cv"]}


def build(tw: DigitalTwin, cfg: dict, lang: str, doctor: dict, notifications: list[dict], cards: list[dict],
          messages: list[dict], logs: list[dict], state: str) -> dict:
    """Full patient payload (state ACTIVE only; the caller enforces the consent gate)."""
    p = tw.prediction or {}
    f = p.get("features", {})
    cgm = tw.rows[-1]["cgm"] if tw.rows else None
    now = tw.now
    log_dates = {str(pd.Timestamp(lg["ts_sim"]).date()) for lg in logs}
    st = status(tw, lang)
    return {
        "state": state, "language": lang, "now": now.isoformat(), "patient_id": tw.pid,
        "doctor": doctor, "features": cfg["features"], "target": cfg["target"],
        "status": st, "glucose": glucose(tw, lang),
        "next_action": next_action(p, cgm, f, cfg, lang, now),
        "why": why(p.get("explanation"), f, lang, now),
        "safety": {"low_now": st["level"] == "LOW", "first_aid": t(lang, "first_aid") if st["level"] == "LOW" else None,
                   "note": t(lang, "notify.safety_note")},
        "my_day": my_day(tw, cfg, lang, logs, notifications),
        "progress": progress(tw, cfg, lang, log_dates) if cfg["features"]["progress"] else None,
        "alerts": notifications[:20], "cards": cards, "messages": messages,
        "care_plan": care_plan_text(cfg, lang),
        "disclaimer": t(lang, "notify.disclaimer"),
    }


def care_plan_text(cfg: dict, lang: str) -> dict:
    cp = cfg["care_plan"]
    items = [{"kind": "diet", "text": t(lang, f"diet.{d}")} for d in cp["diet"]]
    items.append({"kind": "exercise", "text": t(lang, "care.steps_goal", steps=cp["steps_goal"])})
    if cp["post_meal_walk"]:
        items.append({"kind": "exercise", "text": t(lang, "care.post_meal_walk", minutes=cp["walk_minutes"])})
    for r in cp["medication_reminders"]:
        items.append({"kind": "med", "text": t(lang, "care.med", label=r["label"], time=r["time"])})
    return {"items": items, "med_note": t(lang, "care.med_note")}
