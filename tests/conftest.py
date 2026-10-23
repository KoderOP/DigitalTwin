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
def client(tmp_path_factory):
    """One live API (engine + portal) for all API tests: 4 demo patients, 3 warm-up days, isolated DB."""
    import os

    os.environ["DT_WARMUP_DAYS"] = "3"
    os.environ["DT__SERVING__DEMO_PATIENTS"] = "4"
    os.environ["DT__PATHS__DB_PATH"] = str(tmp_path_factory.mktemp("db") / "test.sqlite3")
    os.environ["DT__PORTAL__DEMO_ACCOUNTS_ENABLED"] = "false"  # enabled explicitly in test_demo_accounts
    get_config.cache_clear()
    from fastapi.testclient import TestClient

    from backend.app import app

    with TestClient(app) as c:
        c.post("/api/sim/pause", json={"paused": True})
        yield c


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
