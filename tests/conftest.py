import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common import get_config  # noqa: E402
from data_gen.ehr_generator import generate_ehr  # noqa: E402
from data_gen.physiology import params_from_ehr  # noqa: E402

HAS_DATA = (ROOT / "data" / "ehr" / "patients.csv").exists()
HAS_MODELS = (ROOT / "artifacts" / "serving.json").exists() and (ROOT / "artifacts" / "deep_fused.pt").exists()
needs_models = pytest.mark.skipif(not (HAS_DATA and HAS_MODELS), reason="run `make data train` first")


@pytest.fixture(scope="session")
def small_cohort():
    rng = np.random.default_rng(123)
    patients, latent = generate_ehr(12, rng)
    params = params_from_ehr(patients, latent, np.random.default_rng(5))
    return patients, latent, params


@pytest.fixture(scope="session")
def sensor_cfg():
    return get_config()["simulation"]["sensor"]


@pytest.fixture(scope="session")
def start():
    return pd.Timestamp(get_config()["cohort"]["start_date"])
