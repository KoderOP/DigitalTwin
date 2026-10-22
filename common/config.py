"""Configuration loading (YAML + env overrides), path resolution, logging and seeding."""
from __future__ import annotations

import copy
import logging
import os
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "default.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _coerce(value: str) -> Any:
    """Parse an env-var string with YAML rules so numbers/bools/lists work."""
    try:
        return yaml.safe_load(value)
    except yaml.YAMLError:
        return value


def _apply_env_overrides(cfg: dict) -> dict:
    for key, raw in os.environ.items():
        if not key.startswith("DT__"):
            continue
        parts = [p.lower() for p in key[4:].split("__")]
        node = cfg
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = _coerce(raw)
    return cfg


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Return the merged configuration (default YAML, optional DT_CONFIG file, DT__* env vars)."""
    with open(DEFAULT_CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    extra = os.environ.get("DT_CONFIG")
    if extra:
        with open(extra, encoding="utf-8") as f:
            cfg = _deep_merge(cfg, yaml.safe_load(f) or {})
    return _apply_env_overrides(cfg)


def path_of(key: str) -> Path:
    """Resolve a configured path (``paths.<key>``) relative to the repo root and create its parent."""
    p = Path(get_config()["paths"][key])
    if not p.is_absolute():
        p = ROOT / p
    (p if p.suffix == "" else p.parent).mkdir(parents=True, exist_ok=True)
    return p


def seed_everything(seed: int | None = None) -> int:
    """Seed python, numpy and (if available) torch for reproducibility."""
    seed = get_config()["seed"] if seed is None else seed
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
    except ImportError:  # torch is optional for data generation
        pass
    return seed


def get_logger(name: str) -> logging.Logger:
    """Return a module logger with a consistent format."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=os.environ.get("DT_LOG_LEVEL", "INFO"),
            format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    return logging.getLogger(name)
