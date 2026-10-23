"""Plain-language explanation service and next-action suggestions for the patient app.

Turns the model's grouped attribution factors (TreeSHAP / Integrated Gradients, see ml/explain.py)
into one short localised sentence, e.g. "A late, heavy dinner and short sleep last night are pushing
your sugar up." It never diagnoses and never mentions medication changes.
"""
from __future__ import annotations

import pandas as pd

from backend.portal.i18n import t

LONG_TERM = {"body_composition", "genetics_family", "diet_pattern", "comorbidity_duration"}
SKIP = {"data_quality"}


def _frag_key(factor: str, features: dict, now: pd.Timestamp, up: bool) -> str:
    if factor in LONG_TERM:
        return "long_term"
    if up and factor == "recent_meal":
        carbs = features.get("w_last_meal_carbs") or 0
        since = features.get("w_min_since_meal") or 720
        if carbs >= 60 and since < 240 and (now.hour >= 20 or now.hour < 2):
            return "late_heavy_dinner"
    return factor


def why(factors: list[dict] | None, features: dict, lang: str, now: pd.Timestamp) -> dict:
    """{'sentence': str, 'items': [{'text', 'direction'}]} from the twin's explanation factors."""
    factors = [f for f in (factors or []) if f["factor"] not in SKIP]
    ups = [f for f in factors if f["contribution"] > 0][:2]
    downs = [f for f in factors if f["contribution"] < 0][:1]
    items, parts = [], []
    up_txt = []
    for f in ups:
        k = _frag_key(f["factor"], features, now, True)
        txt = t(lang, f"why.frag_up.{k}")
        if txt not in up_txt:
            up_txt.append(txt)
            items.append({"text": txt, "direction": "up"})
    if len(up_txt) == 2:
        parts.append(t(lang, "why.up_two", a=up_txt[0], b=_lower_first(up_txt[1], lang)))
    elif len(up_txt) == 1:
        parts.append(t(lang, "why.up_one", a=up_txt[0]))
    for f in downs:
        txt = t(lang, f"why.frag_down.{_frag_key(f['factor'], features, now, False)}")
        items.append({"text": txt, "direction": "down"})
        parts.append(t(lang, "why.down_one", a=txt))
    return {"sentence": " ".join(parts) if parts else t(lang, "why.none"), "items": items}


def _lower_first(s: str, lang: str) -> str:
    return s[:1].lower() + s[1:] if lang == "en" else s


def next_action(pred: dict | None, cgm: float | None, features: dict, cfg: dict, lang: str, now: pd.Timestamp) -> dict:
    """One recommended lifestyle action. Hypoglycaemia first-aid takes priority. Never a medication change."""
    walk = cfg["care_plan"]["walk_minutes"]
    night = now.hour >= 22 or now.hour < 6 or (features.get("w_asleep_now") or 0) > 0
    if is_low(cgm, pred):
        return {"key": "eat_sugar", "icon": "candy", "text": t(lang, "actions.eat_sugar"), "safety": True}
    level = (pred or {}).get("level", "GREEN")
    since_meal = features.get("w_min_since_meal") or 720
    if level in ("RED", "AMBER", "HIGH") and not night:
        if since_meal < 120 or level == "HIGH":
            return {"key": "walk_now", "icon": "walk", "text": t(lang, "actions.walk_now", minutes=walk)}
        return {"key": "swap_rice", "icon": "plate", "text": t(lang, "actions.swap_rice")}
    if level in ("RED", "HIGH") and night:
        return {"key": "drink_water", "icon": "water", "text": t(lang, "actions.drink_water")}
    for r in cfg["care_plan"].get("medication_reminders", []):
        hh, mm = (int(x) for x in r["time"].split(":"))
        due = now.normalize() + pd.Timedelta(hours=hh, minutes=mm)
        if pd.Timedelta(0) <= due - now <= pd.Timedelta(minutes=30):
            return {"key": "med_reminder", "icon": "pill", "text": t(lang, "actions.med_reminder", label=r["label"])}
    if cfg["care_plan"].get("post_meal_walk") and since_meal < 60 and not night:
        return {"key": "walk_now", "icon": "walk", "text": t(lang, "actions.walk_now", minutes=walk)}
    return {"key": "keep_going", "icon": "star", "text": t(lang, "actions.keep_going")}


def is_low(cgm: float | None, pred: dict | None) -> bool:
    return cgm is not None and cgm == cgm and cgm < 70


def low_predicted(pred: dict | None) -> bool:
    if not pred:
        return False
    if (pred.get("hypo_risk") or 0) >= 0.25:
        return True
    return min(f["p50"] for f in pred["forecast"][:2]) < 72


def confidence(prob: float | None, lang: str) -> dict:
    """Calibrated probability -> plain confidence label."""
    if prob is None:
        return {"pct": None, "label": t(lang, "confidence.measured"), "key": "measured"}
    p = max(prob, 1 - prob)
    key = "high" if p >= 0.8 else "medium" if p >= 0.6 else "low"
    return {"pct": round(prob * 100), "label": t(lang, f"confidence.{key}"), "key": key}
