"""Indian meal library with approximate carbohydrate content and absorption speed.

``fast_frac`` is the share of carbohydrate that goes through the fast-absorbing gut compartment.
High-GI, low-fat meals (idli, poha, white rice) have a high fast_frac. Fat/protein/fibre-rich meals
(biryani, millet, dal-heavy) have a low one, which flattens and lengthens the glucose excursion.

ASSUMPTION: carb grams are typical home portions estimated from public Indian food-composition
tables (IFCT-style values), rounded. GI is approximated through fast_frac, not taken from a
validated table. Portions vary by patient (``portion`` trait) and by day (log-normal jitter).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Meal:
    name: str
    label: str
    carbs: float  # grams for a standard portion
    fast_frac: float  # 0..1 share absorbed through the fast compartment (GI proxy)
    slot: str  # breakfast | lunch | snack | dinner | sweet
    veg: bool
    staple: str  # rice | wheat | millet | any


MEALS: list[Meal] = [
    # breakfast
    Meal("poha", "Poha", 45, 0.75, "breakfast", True, "any"),
    Meal("idli_sambar", "Idli-sambar", 55, 0.80, "breakfast", True, "rice"),
    Meal("dosa_chutney", "Dosa-chutney", 50, 0.75, "breakfast", True, "rice"),
    Meal("upma", "Upma", 45, 0.70, "breakfast", True, "wheat"),
    Meal("aloo_paratha", "Aloo paratha", 55, 0.55, "breakfast", True, "wheat"),
    Meal("oats", "Oats porridge", 35, 0.40, "breakfast", True, "any"),
    Meal("ragi_dosa", "Ragi dosa", 40, 0.45, "breakfast", True, "millet"),
    Meal("egg_toast", "Egg bhurji + toast", 30, 0.60, "breakfast", False, "wheat"),
    # lunch
    Meal("dal_chawal", "Dal-chawal", 85, 0.75, "lunch", True, "rice"),
    Meal("sambar_rice", "Sambar rice", 85, 0.75, "lunch", True, "rice"),
    Meal("curd_rice", "Curd rice", 70, 0.70, "lunch", True, "rice"),
    Meal("rajma_chawal", "Rajma-chawal", 90, 0.60, "lunch", True, "rice"),
    Meal("roti_sabzi", "Roti-sabzi", 65, 0.50, "lunch", True, "wheat"),
    Meal("roti_dal", "Roti-dal", 60, 0.45, "lunch", True, "wheat"),
    Meal("bajra_roti_dal", "Bajra roti + dal", 60, 0.35, "lunch", True, "millet"),
    Meal("chicken_rice", "Chicken curry + rice", 80, 0.65, "lunch", False, "rice"),
    Meal("chicken_roti", "Chicken curry + roti", 55, 0.45, "lunch", False, "wheat"),
    # evening snack
    Meal("chai_biscuits", "Chai (sugar) + biscuits", 25, 0.85, "snack", True, "any"),
    Meal("samosa_chai", "Samosa + chai", 40, 0.70, "snack", True, "any"),
    Meal("fruit", "Fruit (banana)", 22, 0.55, "snack", True, "any"),
    Meal("roasted_chana", "Roasted chana", 15, 0.30, "snack", True, "any"),
    # dinner
    Meal("roti_sabzi_d", "Roti-sabzi", 65, 0.50, "dinner", True, "wheat"),
    Meal("dal_chawal_d", "Dal-chawal", 85, 0.75, "dinner", True, "rice"),
    Meal("khichdi", "Khichdi", 60, 0.60, "dinner", True, "rice"),
    Meal("veg_biryani", "Veg biryani", 95, 0.50, "dinner", True, "rice"),
    Meal("chicken_biryani", "Chicken biryani", 95, 0.45, "dinner", False, "rice"),
    Meal("fish_curry_rice", "Fish curry + rice", 80, 0.65, "dinner", False, "rice"),
    Meal("millet_khichdi", "Millet khichdi", 55, 0.35, "dinner", True, "millet"),
    Meal("roti_dal_d", "Roti-dal", 60, 0.45, "dinner", True, "wheat"),
    # occasional sweets
    Meal("gulab_jamun", "Gulab jamun", 35, 0.90, "sweet", True, "any"),
    Meal("jalebi", "Jalebi", 40, 0.95, "sweet", True, "any"),
]

MEAL_BY_NAME = {m.name: m for m in MEALS}
MEAL_INDEX = {m.name: i for i, m in enumerate(MEALS)}


def candidates(slot: str, veg: bool, staple: str) -> tuple[list[Meal], list[float]]:
    """Meals for a slot compatible with diet, weighted towards the patient's staple."""
    opts = [m for m in MEALS if m.slot == slot and (m.veg or not veg)]
    weights = [3.0 if m.staple == staple else (1.0 if m.staple == "any" else 0.6) for m in opts]
    total = sum(weights)
    return opts, [w / total for w in weights]


def heavy_carb_meal() -> Meal:
    """Meal used by the 'inject heavy carb meal' demo control."""
    return Meal("injected_heavy", "Heavy carb meal (injected)", 120, 0.75, "dinner", True, "any")
