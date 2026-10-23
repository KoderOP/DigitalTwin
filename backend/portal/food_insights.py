"""Daily consumption pattern + personal food-impact detection ("which foods push *my* sugar up?").

For every logged meal in the twin's 14-day diary we measure this patient's own glucose response from the
CGM: baseline at the meal, peak in the next 150 min, rise, minutes above the target, time to peak. Meals
followed by another meal within 90 min are kept in the diary but excluded from the statistics (their
responses overlap). We then:

* aggregate the response per food item (n, mean rise / peak, share of meals going above target), and flag
  items as **watch** when the pattern is consistent (n >= 2 and >= 2/3 of meals above target, or a mean
  peak >= target + 40) **and** the food is clearly worse than this patient's usual meal (mean rise >= 1.2x
  their median rise, or mean peak >= their median peak + 20 mg/dL). For a poorly controlled patient whose
  every meal goes high, this singles out the foods that are worse than usual. Confidence comes from n;
* compare patterns: late dinners (>= 21:00) vs earlier dinners, and rice meals vs roti/millet meals;
* link **symptoms** the patient reported (Quick Log) to foods eaten in the 4 h before, together with the
  glucose at the time of the symptom;
* produce a gentle **warning** when a flagged food is logged again.

This is transparent per-patient statistics on the twin's own data, not a black box. With few meals it says
so (confidence low / medium). It never gives medication advice. ASSUMPTION: only *logged* meals are
analysed. Unlogged meals are invisible, as in real life.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.portal.i18n import t
from data_gen.meals import MEAL_BY_NAME

PRESETS = ("idli_sambar", "dal_chawal", "roti_sabzi", "poha", "biryani")
SWEETS = {"gulab_jamun", "jalebi", "chai_biscuits"}
POST_MIN = 150
CONFOUND_MIN = 90
SYMPTOM_LOOKBACK_MIN = 240


def food_key(name: str | None) -> str:
    n = (name or "other").lower()
    if n.endswith("_d"):
        n = n[:-2]
    if "biryani" in n:
        return "biryani"
    return n


def food_label(key: str, label: str | None, lang: str) -> str:
    if key in PRESETS:
        return t(lang, f"food.{key}")
    lbl = (label or key).replace(" (logged in app)", "").replace(" (injected)", "")
    return lbl


def _staple(key: str) -> str | None:
    m = MEAL_BY_NAME.get(key) or MEAL_BY_NAME.get(key + "_d") or MEAL_BY_NAME.get("chicken_" + key)
    return m.staple if m else None


def meal_responses(events: list[dict], cgm_hist: list[tuple], high: int = 180) -> list[dict]:
    """One row per logged meal with the measured post-meal response (or None if not measurable)."""
    s = pd.Series({pd.Timestamp(ts): g for ts, g in cgm_hist}, dtype=float).sort_index().dropna()
    meals = sorted((e for e in events if e.get("type") == "meal"), key=lambda e: e["ts"])
    out = []
    times = [pd.Timestamp(m["ts"]) for m in meals]
    for k, m in enumerate(meals):
        ts = times[k]
        key = food_key(m.get("name"))
        row = {"ts": ts, "key": key, "label": m.get("label"), "carbs": float(m.get("amount") or 0), "measured": False,
               "confounded": any(ts < t2 <= ts + pd.Timedelta(minutes=CONFOUND_MIN) for t2 in times[k + 1:k + 4])}
        before = s[ts - pd.Timedelta(minutes=30):ts]
        post = s[ts + pd.Timedelta(minutes=5):ts + pd.Timedelta(minutes=POST_MIN)]
        if len(before) and len(post) >= 15:
            base = float(before.iloc[-1])
            peak = float(post.max())
            row.update(measured=True, base=base, peak=peak, rise=peak - base, above_min=int((post > high).sum() * 5),
                       went_above=bool(peak > high), time_to_peak=int((post.idxmax() - ts).total_seconds() // 60))
        out.append(row)
    return out


def analyse(events: list[dict], cgm_hist: list[tuple], symptom_logs: list[dict], now: pd.Timestamp,
            lang: str = "en", high: int = 180, days: int = 7) -> dict:
    rows = meal_responses(events, cgm_hist, high)
    stat = [r for r in rows if r["measured"] and not r["confounded"]]
    base_rise = float(np.median([r["rise"] for r in stat])) if stat else None
    base_peak = float(np.median([r["peak"] for r in stat])) if stat else None

    # ---- per food --------------------------------------------------------------------------
    foods = []
    for key in sorted({r["key"] for r in stat}):
        rs = [r for r in stat if r["key"] == key]
        n = len(rs)
        pct_above = sum(r["went_above"] for r in rs) / n
        mean_peak = float(np.mean([r["peak"] for r in rs]))
        mean_rise = float(np.mean([r["rise"] for r in rs]))
        # personal + relative: consistently above target AND clearly worse than this patient's usual meal
        worse_than_usual = (base_rise is not None and mean_rise >= 1.2 * max(base_rise, 1)) or \
                           (base_peak is not None and mean_peak >= base_peak + 20)
        watch = n >= 2 and (pct_above >= 2 / 3 or mean_peak >= high + 40) and worse_than_usual
        conf = "high" if n >= 4 else "medium" if n >= 2 else "low"
        lbl = food_label(key, rs[-1]["label"], lang)
        foods.append({
            "key": key, "label": lbl, "n": n, "mean_rise": round(mean_rise), "mean_peak": round(mean_peak),
            "pct_above": round(pct_above * 100), "mean_carbs": round(float(np.mean([r["carbs"] for r in rs]))),
            "minutes_above": round(float(np.mean([r["above_min"] for r in rs]))),
            "relative_to_usual": None if not base_rise else round(mean_rise / max(base_rise, 1), 2),
            "flag": "watch" if watch else "ok", "confidence": conf,
            "text": t(lang, "foodai.food_line", food=lbl, rise=round(mean_rise), peak=round(mean_peak), high=high, pct=round(pct_above * 100)),
            "based_on": t(lang, "foodai.based_on", n=n),
        })
    foods.sort(key=lambda f: (f["flag"] != "watch", -f["minutes_above"], -f["mean_rise"]))

    # ---- patterns ----------------------------------------------------------------------------
    patterns = []
    dinners = [r for r in stat if 18 <= r["ts"].hour <= 23 and r["carbs"] >= 40]
    late = [r["peak"] for r in dinners if r["ts"].hour >= 21]
    early = [r["peak"] for r in dinners if r["ts"].hour < 21]
    if len(late) >= 2 and len(early) >= 2 and np.mean(late) - np.mean(early) >= 15:
        patterns.append({"key": "late_dinner", "text": t(lang, "foodai.late_dinner", diff=round(np.mean(late) - np.mean(early))),
                         "n": len(late) + len(early)})
    rice = [r["rise"] for r in stat if _staple(r["key"]) == "rice" and r["carbs"] >= 40]
    other = [r["rise"] for r in stat if _staple(r["key"]) in ("wheat", "millet") and r["carbs"] >= 40]
    if len(rice) >= 2 and len(other) >= 2 and np.mean(rice) - np.mean(other) >= 15:
        patterns.append({"key": "rice_vs_roti", "text": t(lang, "foodai.rice_vs", diff=round(np.mean(rice) - np.mean(other))),
                         "n": len(rice) + len(other)})

    # ---- symptoms <-> foods ---------------------------------------------------------------
    s = pd.Series({pd.Timestamp(ts): g for ts, g in cgm_hist}, dtype=float).sort_index().dropna()
    links: dict[tuple[str, str], dict] = {}
    for lg in symptom_logs:
        st = pd.Timestamp(lg["ts_sim"])
        g_at = s[:st].iloc[-1] if len(s[:st]) else None
        prior = {r["key"]: r for r in rows if st - pd.Timedelta(minutes=SYMPTOM_LOOKBACK_MIN) <= r["ts"] <= st}
        for sym in lg["payload"].get("symptoms", []):
            for key, r in prior.items():
                d = links.setdefault((key, sym), {"food": key, "label": food_label(key, r["label"], lang), "symptom": sym, "n": 0, "glucose": []})
                d["n"] += 1
                if g_at is not None:
                    d["glucose"].append(float(g_at))
    symptom_links = []
    for d in sorted(links.values(), key=lambda x: -x["n"]):
        g = round(float(np.mean(d["glucose"]))) if d["glucose"] else None
        ctx = "" if g is None else " " + (t(lang, "foodai.sugar_high", g=g) if g > high else t(lang, "foodai.sugar_low", g=g) if g < 70 else t(lang, "foodai.sugar_in_range", g=g))
        symptom_links.append({**{k: d[k] for k in ("food", "label", "symptom", "n")}, "glucose_at_symptom": g,
                              "pattern": d["n"] >= 2,
                              "text": t(lang, "foodai.symptom_line", symptom=t(lang, f"symptoms.{d['symptom']}"), food=d["label"], n=d["n"]) + ctx})

    # ---- daily consumption diary (last `days` days) ----------------------------------------
    day0 = now.normalize() - pd.Timedelta(days=days - 1)
    diary = []
    watch_keys = {f["key"] for f in foods if f["flag"] == "watch"}
    for d in pd.date_range(day0, now.normalize(), freq="D"):
        items = [r for r in rows if d <= r["ts"] < d + pd.Timedelta(days=1)]
        diary.append({
            "date": str(d.date()), "total_carbs": round(sum(r["carbs"] for r in items)), "meals": len(items),
            "late_meals": sum(r["ts"].hour >= 21 for r in items), "sweets": sum(r["key"] in SWEETS for r in items),
            "spikes_after_meals": sum(bool(r.get("went_above")) for r in items),
            "items": [{"time": r["ts"].strftime("%H:%M"), "key": r["key"], "label": food_label(r["key"], r["label"], lang),
                       "carbs": round(r["carbs"]), "peak": None if not r["measured"] else round(r["peak"]),
                       "went_above": r.get("went_above"), "watch": r["key"] in watch_keys} for r in items],
        })
    return {"foods": foods, "patterns": patterns, "symptom_links": symptom_links, "diary": diary,
            "usual_rise": None if base_rise is None else round(base_rise), "meals_analysed": len(stat), "meals_logged": len(rows),
            "high": high, "tip": t(lang, "foodai.tip_watch"), "method": t(lang, "foodai.method")}


def warning_for(analysis: dict, key: str) -> dict | None:
    """Warning parameters if a just-logged food has a consistent spike pattern for this patient."""
    for f in analysis["foods"]:
        if f["key"] == key and f["flag"] == "watch":
            return {"food_key": key, "food": f["label"], "n": f["n"], "peak": f["mean_peak"], "high": analysis["high"], "pct": f["pct_above"]}
    return None
