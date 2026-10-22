"""Vectorised glucose-insulin dynamics (extended Bergman minimal model).

One integration step updates N patients at once, which makes it fast enough for batch generation
(150 patients x 30 days at 1-min resolution in seconds), the live demo stream, and the twin's
counterfactual (what-if) simulations.

State per patient
-----------------
G   plasma glucose (mg/dL)              Gi  interstitial glucose seen by the CGM (mg/dL)
X   remote insulin action (1/min)       I   plasma insulin above basal (uU/mL)
Qf1,Qf2 / Qs1,Qs2  fast / slow gut carbohydrate compartments (mg)
met, su, dpp4, sglt2  drug effect-site amounts      r1,r2 / n1,n2 / b  s.c. insulin depots (U)
ex  post-exercise insulin-sensitivity accumulator   sleep_mult  insulin-sensitivity factor from last night

Equations (dt = 1 min, explicit Euler)
---------------------------------------
Ra   = f * (kf*Qf2 + ks*Qs2) / Vg                                   meal glucose appearance
Gb_t = Gb * (1 + dawn_amp*dawn(t)) * (1 - E_met) * (1 + 0.10*stress) moving basal set-point
dG   = -p1 (G - Gb_t) - X G + Ra - e_ex*a*G - SGLT2 + counter-regulation
dX   = -p2 X + p2 * SI_t * I,  SI_t = SI * sleep_mult * (1 + 0.35 ex)
dI   = -n I + gamma_t * max(G - Gb_t, 0) + SU_basal + exogenous insulin appearance
dGi  = (G - Gi) / tau_sensor

ASSUMPTION: this is a teaching-grade model calibrated to give plausible T2D excursions. It is
**not** the validated UVA/Padova simulator and must not be used for dosing decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

import numpy as np
import pandas as pd

# Fixed population constants (ASSUMPTION, literature-order-of-magnitude)
P2 = 0.025  # 1/min, insulin action decay
N_CLEAR = 0.14  # 1/min, plasma insulin clearance
K_FAST = 0.030  # 1/min, fast gut absorption
K_SLOW = 0.011  # 1/min, slow gut absorption
F_BIO = 0.65  # effective systemic carbohydrate appearance (bioavailability x hepatic extraction)
VG_PER_KG = 1.9  # dL/kg glucose distribution volume
VI_ML_PER_KG = 120.0  # mL/kg insulin distribution volume
K_MET = np.log(2) / 300  # metformin half-life ~5 h
K_SU = np.log(2) / 540  # glimepiride ~9 h
K_DPP4 = np.log(2) / 720  # DPP-4 inhibitor ~12 h
K_SGLT2 = np.log(2) / 720  # SGLT2 inhibitor ~12 h
KA_RAPID = 0.022  # rapid-acting component of premix
KA_NPH = 0.0055  # intermediate (NPH) component of premix
KB_BASAL = 1 / 900  # glargine depot release
E_EX = 0.008  # insulin-independent uptake per unit activity
COUNTER_REG = 0.05  # counter-regulatory response below 70 mg/dL


@dataclass
class PhysioParams:
    """Per-patient model parameters (each field is an array of shape (N,))."""

    weight: np.ndarray
    Vg: np.ndarray
    VI_ml: np.ndarray
    p1: np.ndarray
    SI: np.ndarray
    gamma: np.ndarray
    Gb: np.ndarray
    dawn_amp: np.ndarray
    met_emax: np.ndarray
    su_gain: np.ndarray
    dpp4_gain: np.ndarray
    sglt2_k: np.ndarray
    sensor_lag: np.ndarray

    @property
    def n(self) -> int:
        return len(self.Gb)

    def subset(self, idx: np.ndarray | list[int]) -> "PhysioParams":
        return PhysioParams(**{f.name: np.asarray(getattr(self, f.name))[idx].copy() for f in fields(self)})

    def to_frame(self, index: pd.Index) -> pd.DataFrame:
        return pd.DataFrame({f.name: getattr(self, f.name) for f in fields(self)}, index=index)

    @classmethod
    def from_frame(cls, df: pd.DataFrame) -> "PhysioParams":
        return cls(**{f.name: df[f.name].to_numpy(dtype=float).copy() for f in fields(cls)})


def params_from_ehr(
    patients: pd.DataFrame,
    latent: pd.DataFrame | None = None,
    rng: np.random.Generator | None = None,
) -> PhysioParams:
    """Map EHR (and optionally hidden latent traits) to physiological parameters.

    * With ``latent`` + ``rng`` -> the **true** virtual-patient physiology (world simulator).
    * Without them -> an EHR-only **prior** (what a twin can infer from the record alone); the twin
      then personalises it online from CGM data.
    """
    n = len(patients)
    w = patients["weight_kg"].to_numpy(float)
    bmi = patients["bmi"].to_numpy(float)
    hba1c = patients["hba1c"].to_numpy(float)
    dur = patients["years_since_dx"].to_numpy(float)
    egfr = patients["egfr"].to_numpy(float)
    fpg = patients["fasting_glucose"].to_numpy(float)

    if latent is not None:
        ir = latent["ir_index"].to_numpy(float)
        beta = latent["beta_fn"].to_numpy(float)
    else:  # EHR-only proxies of the hidden traits (ASSUMPTION: crude regression-style priors)
        waist_excess = patients["waist_cm"].to_numpy(float) - np.where(patients["sex"] == "M", 90, 80)
        ir = 0.10 * (bmi - 25) + 0.03 * waist_excess + 0.25 * patients["prs"].to_numpy(float)
        beta = np.clip(1.0 - 0.025 * dur - 0.12 * (patients["snp_tcf7l2"].to_numpy(float) - 0.6)
                       - 0.10 * (hba1c - 8.3) / 1.5, 0.15, 1.2)

    noise = (lambda s: rng.lognormal(0, s, n)) if rng is not None else (lambda s: np.ones(n))
    SI = 2.4e-4 * np.exp(-0.45 * ir) * noise(0.15)
    gamma = 0.075 * beta * noise(0.10)
    p1 = 0.012 * noise(0.15)
    dawn_amp = np.clip(0.05 + 0.025 * (hba1c - 7), 0.03, 0.22) * noise(0.2)

    met_emax = np.where(patients["metformin_mg"].to_numpy() > 0, 0.22, 0.0)
    su_gain = np.where(patients["sulfonylurea_mg"].to_numpy() > 0, 1.0, 0.0)
    dpp4_gain = patients["dpp4"].to_numpy(float) * 0.5
    sglt2_k = patients["sglt2"].to_numpy(float) * 0.0025 * np.clip(egfr / 90, 0.3, 1.2)

    # Initial basal set-point: un-medicated fasting level implied by the lab FPG.
    # The world simulator later re-calibrates Gb so simulated mean glucose matches HbA1c (ADAG).
    Gb = np.clip(fpg / (1 - 0.6 * met_emax), 80, 320)

    return PhysioParams(
        weight=w,
        Vg=VG_PER_KG * w,
        VI_ml=VI_ML_PER_KG * w,
        p1=p1,
        SI=SI,
        gamma=gamma,
        Gb=Gb,
        dawn_amp=dawn_amp,
        met_emax=met_emax,
        su_gain=su_gain,
        dpp4_gain=dpp4_gain,
        sglt2_k=sglt2_k,
        sensor_lag=np.full(n, 8.0),
    )


@dataclass
class PhysioState:
    """Mutable model state for N patients."""

    G: np.ndarray
    Gi: np.ndarray
    X: np.ndarray
    I: np.ndarray
    Qf1: np.ndarray
    Qf2: np.ndarray
    Qs1: np.ndarray
    Qs2: np.ndarray
    met: np.ndarray
    su: np.ndarray
    dpp4: np.ndarray
    sglt2: np.ndarray
    r1: np.ndarray
    r2: np.ndarray
    n1: np.ndarray
    n2: np.ndarray
    b: np.ndarray
    ex: np.ndarray
    sleep_mult: np.ndarray = field(default=None)  # type: ignore[assignment]

    @classmethod
    def initial(cls, params: PhysioParams) -> "PhysioState":
        n = params.n
        z = lambda: np.zeros(n)  # noqa: E731
        return cls(G=params.Gb.copy(), Gi=params.Gb.copy(), X=z(), I=z(), Qf1=z(), Qf2=z(), Qs1=z(), Qs2=z(),
                   met=z(), su=z(), dpp4=z(), sglt2=z(), r1=z(), r2=z(), n1=z(), n2=z(), b=z(), ex=z(),
                   sleep_mult=np.ones(n))

    def copy(self) -> "PhysioState":
        return PhysioState(**{f.name: getattr(self, f.name).copy() for f in fields(self)})

    def subset(self, idx: np.ndarray | list[int]) -> "PhysioState":
        return PhysioState(**{f.name: getattr(self, f.name)[idx].copy() for f in fields(self)})

    def as_dict(self, i: int) -> dict[str, float]:
        return {f.name: float(getattr(self, f.name)[i]) for f in fields(self)}


@dataclass
class MinuteInputs:
    """Exogenous inputs applied during one minute (arrays of shape (N,); zeros = nothing)."""

    carb_fast: np.ndarray  # mg ingested into the fast compartment
    carb_slow: np.ndarray  # mg into the slow compartment
    activity: np.ndarray  # 0..1 intensity
    stress: np.ndarray  # 0..1
    met: np.ndarray  # g metformin taken
    su: np.ndarray  # mg glimepiride
    dpp4: np.ndarray  # tablets
    sglt2: np.ndarray  # tablets
    ins_rapid: np.ndarray  # U (rapid component)
    ins_nph: np.ndarray  # U (intermediate component)
    ins_basal: np.ndarray  # U (glargine)


def dawn_curve(minute_of_day: float | np.ndarray) -> np.ndarray:
    """Dawn-phenomenon bump centred around 06:30 (hepatic glucose output rises before waking)."""
    h = np.asarray(minute_of_day) / 60.0
    return np.exp(-0.5 * ((h - 6.5) / 1.3) ** 2)


def step(s: PhysioState, p: PhysioParams, u: MinuteInputs, minute_of_day: float) -> np.ndarray:
    """Advance the state by one minute in place. Returns the meal appearance rate Ra (mg/dL/min)."""
    # --- gut ---------------------------------------------------------------------------------
    s.Qf1 += u.carb_fast
    s.Qs1 += u.carb_slow
    ra_mg = F_BIO * (K_FAST * s.Qf2 + K_SLOW * s.Qs2)
    s.Qf2 += K_FAST * (s.Qf1 - s.Qf2)
    s.Qf1 -= K_FAST * s.Qf1
    s.Qs2 += K_SLOW * (s.Qs1 - s.Qs2)
    s.Qs1 -= K_SLOW * s.Qs1
    Ra = ra_mg / p.Vg

    # --- oral drugs (first-order elimination; effect via Emax) ---------------------------------
    s.met = s.met * (1 - K_MET) + u.met
    s.su = s.su * (1 - K_SU) + u.su
    s.dpp4 = s.dpp4 * (1 - K_DPP4) + u.dpp4
    s.sglt2 = s.sglt2 * (1 - K_SGLT2) + u.sglt2
    e_met = p.met_emax * s.met / (s.met + 0.5)
    e_su = p.su_gain * s.su / (s.su + 1.0)
    e_dpp4 = p.dpp4_gain * s.dpp4 / (s.dpp4 + 0.3)
    e_sglt2 = s.sglt2 / (s.sglt2 + 0.3)

    # --- subcutaneous insulin depots -----------------------------------------------------------
    s.r1 += u.ins_rapid
    s.n1 += u.ins_nph
    s.b += u.ins_basal
    app_u = KA_RAPID * s.r2 + KA_NPH * s.n2 + KB_BASAL * s.b  # U/min reaching plasma
    s.r2 += KA_RAPID * (s.r1 - s.r2)
    s.r1 -= KA_RAPID * s.r1
    s.n2 += KA_NPH * (s.n1 - s.n2)
    s.n1 -= KA_NPH * s.n1
    s.b -= KB_BASAL * s.b

    # --- exercise memory --------------------------------------------------------------------------
    s.ex = np.minimum(s.ex * (1 - 1 / 360) + 0.02 * u.activity, 1.5)

    # --- glucose / insulin ------------------------------------------------------------------------
    Gb_t = p.Gb * (1 + p.dawn_amp * dawn_curve(minute_of_day)) * (1 - e_met) * (1 + 0.10 * u.stress)
    SI_t = p.SI * s.sleep_mult * (1 + 0.35 * s.ex)
    gamma_t = p.gamma * (1 + 0.9 * e_su) * (1 + e_dpp4 * Ra / (Ra + 1.0))
    secretion = gamma_t * np.maximum(s.G - Gb_t, 0) + 0.7 * e_su
    exo = app_u * 1e6 / p.VI_ml

    dG = (
        -p.p1 * (s.G - Gb_t) - s.X * s.G + Ra
        - E_EX * u.activity * s.G
        - p.sglt2_k * e_sglt2 * np.maximum(s.G - 80, 0)
        + COUNTER_REG * np.maximum(70 - s.G, 0)
    )
    s.X += -P2 * s.X + P2 * SI_t * s.I
    s.I += -N_CLEAR * s.I + secretion + exo
    s.G = np.clip(s.G + dG, 30, 600)
    s.Gi += (s.G - s.Gi) / p.sensor_lag
    return Ra


def eag_from_hba1c(hba1c: np.ndarray) -> np.ndarray:
    """ADAG estimated average glucose (mg/dL) = 28.7 * HbA1c - 46.7."""
    return 28.7 * np.asarray(hba1c) - 46.7


def gmi_from_mean(mean_glucose: np.ndarray | float) -> np.ndarray:
    """Glucose Management Indicator (%) = 3.31 + 0.02392 * mean glucose (mg/dL)."""
    return 3.31 + 0.02392 * np.asarray(mean_glucose)
