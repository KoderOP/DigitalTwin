"""Backend content localisation (English, Hindi, Tamil). Hindi/Tamil are machine-drafted: needs native review."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

LANGS = ("en", "hi", "ta")
DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def bundle(lang: str) -> dict:
    with open(DIR / f"{lang if lang in LANGS else 'en'}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get(d: dict, key: str):
    for part in key.split("."):
        if not isinstance(d, dict) or part not in d:
            return None
        d = d[part]
    return d


def t(lang: str, key: str, **kw) -> str | list:
    """Localised text for ``key`` (dotted path), falling back to English, formatted with ``kw``."""
    v = _get(bundle(lang), key)
    if v is None:
        v = _get(bundle("en"), key)
    if v is None:
        return key
    if isinstance(v, str):
        try:
            return v.format(**kw)
        except (KeyError, IndexError):
            return v
    return v
