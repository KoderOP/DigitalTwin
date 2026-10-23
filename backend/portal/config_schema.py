"""Per-patient interface configuration with safe bounds, plus launch templates.

Safety rules are encoded in the schema itself:
* the target range can only be set within clinically conservative bounds;
* the AMBER (watch) sensitivity can be tuned, but the RED threshold is the validated model threshold
  and is not configurable;
* ``red_alerts`` and ``low_glucose_alerts`` are typed ``Literal[True]``, so no configuration (doctor
  or patient) can switch them off;
* medication items are *reminders of the existing prescription*. The app never changes a dose.
"""
from __future__ import annotations

import copy
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Language = Literal["en", "hi", "ta"]
DIET_ITEMS = ("swap_rice_millet", "half_plate_veg", "early_dinner", "limit_sweets", "less_sugar_chai", "protein_breakfast")


class TargetRange(BaseModel):
    low: int = Field(70, ge=70, le=100, description="mg/dL; cannot be set below 70 (hypoglycaemia)")
    high: int = Field(180, ge=140, le=200, description="mg/dL")

    @model_validator(mode="after")
    def _ordered(self) -> "TargetRange":
        if self.high - self.low < 60:
            raise ValueError("target range must span at least 60 mg/dL")
        return self


class Contact(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    relation: str = Field("family", max_length=30)
    channel: Literal["sms", "email"] = "sms"
    handle: str = Field(..., min_length=3, max_length=60, description="fictional demo contact only")


class AlertSettings(BaseModel):
    amber_threshold: float = Field(0.5, ge=0.25, le=0.9, description="probability for gentle 'watch' notifications")
    daily_cap: int = Field(4, ge=1, le=8, description="max non-safety notifications per day")
    min_gap_min: int = Field(90, ge=30, le=240, description="min minutes between non-safety notifications")
    escalate_after_min: int = Field(30, ge=10, le=120, description="unacknowledged safety alert -> escalation")
    escalation_contacts: list[Contact] = Field(default_factory=list, max_length=3)
    red_alerts: Literal[True] = True  # always on, not configurable
    low_glucose_alerts: Literal[True] = True  # always on, not configurable


class Features(BaseModel):
    quick_log: bool = True
    try_it: bool = True
    progress: bool = True
    caregiver: bool = False


class MedReminder(BaseModel):
    label: str = Field(..., min_length=1, max_length=60)
    time: str = Field(..., description="HH:MM")

    @field_validator("time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("time must be HH:MM")
        return v


class CarePlan(BaseModel):
    diet: list[str] = Field(default_factory=lambda: ["swap_rice_millet", "early_dinner"])
    steps_goal: int = Field(6000, ge=2000, le=15000)
    post_meal_walk: bool = True
    walk_minutes: int = Field(15, ge=5, le=60)
    medication_reminders: list[MedReminder] = Field(default_factory=list, max_length=6)

    @field_validator("diet")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        bad = [d for d in v if d not in DIET_ITEMS]
        if bad:
            raise ValueError(f"unknown diet items {bad}; allowed {DIET_ITEMS}")
        return v


class PortalConfig(BaseModel):
    template: str = "standard"
    language: Language = "en"
    target: TargetRange = Field(default_factory=TargetRange)
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    features: Features = Field(default_factory=Features)
    care_plan: CarePlan = Field(default_factory=CarePlan)


TEMPLATES: dict[str, dict] = {
    "standard": {"label": "Standard T2D follow-up"},
    "newly_diagnosed": {"label": "Newly diagnosed (more guidance)",
                        "alerts": {"amber_threshold": 0.45, "daily_cap": 5},
                        "care_plan": {"diet": ["swap_rice_millet", "half_plate_veg", "less_sugar_chai"], "steps_goal": 5000}},
    "insulin_user": {"label": "On insulin (hypo-aware)",
                     "target": {"low": 80, "high": 180},
                     "alerts": {"amber_threshold": 0.55, "escalate_after_min": 20}},
    "elderly_caregiver": {"label": "Older adult with caregiver",
                          "features": {"caregiver": True, "try_it": False},
                          "alerts": {"daily_cap": 3, "min_gap_min": 120},
                          "care_plan": {"steps_goal": 4000, "walk_minutes": 10}},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def from_template(name: str, ehr: dict | None = None, **overrides) -> PortalConfig:
    """Template defaults, personalised from the EHR (medication reminders for the existing prescription)."""
    if name not in TEMPLATES:
        raise ValueError(f"unknown template {name}")
    base = PortalConfig(template=name).model_dump()
    t = {k: v for k, v in TEMPLATES[name].items() if k != "label"}
    cfg = _merge(base, t)
    if ehr:
        rem = []
        if ehr.get("metformin_mg"):
            rem += [{"label": "Metformin (as prescribed)", "time": "08:30"}, {"label": "Metformin (as prescribed)", "time": "21:00"}]
        if ehr.get("insulin_type") and ehr["insulin_type"] != "none":
            rem.append({"label": "Insulin (as prescribed)", "time": "08:00" if ehr["insulin_type"] == "premix_30_70" else "22:00"})
        cfg["care_plan"]["medication_reminders"] = rem
    cfg = _merge(cfg, overrides)
    return PortalConfig.model_validate(cfg)
