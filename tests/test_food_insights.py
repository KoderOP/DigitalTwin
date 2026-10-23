"""Personal food-impact detection and daily consumption pattern."""
import numpy as np
import pandas as pd

from backend.portal.food_insights import analyse, food_key, meal_responses, warning_for


def _world(days=6):
    """Synthetic CGM where biryani and dal-chawal spike high, roti-sabzi stays moderate; one confounded meal."""
    t0 = pd.Timestamp("2026-02-10 00:00")
    ts = pd.date_range(t0, periods=days * 288, freq="5min")
    g = np.full(len(ts), 120.0)
    events = []

    def meal(day, hh, name, carbs, rise):
        at = t0 + pd.Timedelta(days=day, hours=hh)
        events.append({"ts": at.isoformat(), "type": "meal", "name": name, "label": name, "amount": carbs})
        k = ts.get_loc(at)
        bump = rise * np.exp(-0.5 * ((np.arange(36) - 14) / 6.0) ** 2)  # peak ~70 min after the meal
        seg = g[k:k + 36]
        seg += bump[:len(seg)]

    for d in range(days):
        meal(d, 13, "roti_sabzi", 65, 40)
        meal(d, 21.5 if d % 2 == 0 else 19.5, "chicken_biryani" if d % 2 == 0 else "roti_sabzi_d", 95 if d % 2 == 0 else 60,
             150 if d % 2 == 0 else 45)
    if days > 4:
        meal(1, 8, "dal_chawal", 85, 110)
        meal(3, 8, "dal_chawal", 85, 115)
        meal(4, 8, "poha", 45, 30)
        meal(4, 9, "jalebi", 40, 90)  # within 90 min of poha -> poha is confounded
    cgm = list(zip(ts, g))
    return events, cgm, ts[-1]


def test_detects_spiking_foods_and_patterns():
    events, cgm, now = _world()
    symptoms = [{"ts_sim": (pd.Timestamp(e["ts"]) + pd.Timedelta(minutes=90)).isoformat(), "kind": "symptom", "payload": {"symptoms": ["thirst"]}}
                for e in events if e["name"] == "chicken_biryani"][:2]
    a = analyse(events, cgm, symptoms, now, "en", 180, days=7)
    by = {f["key"]: f for f in a["foods"]}
    assert by["biryani"]["flag"] == "watch" and by["biryani"]["pct_above"] == 100 and by["biryani"]["n"] == 3
    assert by["dal_chawal"]["flag"] == "watch" and by["dal_chawal"]["confidence"] == "medium"
    assert by["roti_sabzi"]["flag"] == "ok" and by["roti_sabzi"]["n"] >= 6
    assert a["foods"][0]["flag"] == "watch"  # watch items first
    assert "poha" not in by  # confounded by the jalebi 60 min later -> excluded from the statistics
    assert any(p["key"] == "late_dinner" for p in a["patterns"])  # late biryani dinners vs earlier roti dinners
    link = next(s for s in a["symptom_links"] if s["food"] == "biryani" and s["symptom"] == "thirst")
    assert link["n"] == 2 and link["pattern"] and link["glucose_at_symptom"] > 180
    assert len(a["diary"]) == 7 and a["diary"][-1]["meals"] >= 2
    w = warning_for(a, food_key("chicken_biryani"))
    assert w and w["n"] == 3 and w["peak"] > 250
    assert warning_for(a, "roti_sabzi") is None


def test_localised_and_honest_with_little_data():
    events, cgm, now = _world(days=1)
    a = analyse(events, cgm, [], now, "hi", 180)
    assert all(f["flag"] == "ok" for f in a["foods"])  # one meal per food is never enough to flag
    assert "आधारित" in a["foods"][0]["based_on"]
    rows = meal_responses(events, cgm)
    assert all(r["measured"] for r in rows if not r["confounded"])
