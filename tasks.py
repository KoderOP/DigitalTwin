"""Cross-platform task runner (the Makefile delegates here; Windows has no `make` by default).

    python tasks.py setup      # venv + Python deps (CPU torch) + frontend deps
    python tasks.py data       # generate the synthetic cohort
    python tasks.py train      # train all models + evaluation report (~15 min on a laptop CPU)
    python tasks.py build      # build the React dashboard
    python tasks.py demo       # run whatever is missing above, then serve http://127.0.0.1:8000
    python tasks.py dev        # backend + Vite dev server with hot reload
    python tasks.py test       # pytest + frontend tests
    python tasks.py all        # setup -> data -> train -> build -> test
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
FRONT = ROOT / "frontend"
NPM = shutil.which("npm") or "npm"


def py() -> str:
    return str(VPY) if VPY.exists() else sys.executable


def run(cmd: list[str], cwd: Path = ROOT, env: dict | None = None) -> None:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    e = {**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}
    subprocess.run(cmd, cwd=cwd, env=e, check=True)


def setup() -> None:
    uv = shutil.which("uv")
    if not VPY.exists():
        if uv:
            run([uv, "venv", str(VENV), "--python", "3.12"])
        else:
            run([sys.executable, "-m", "venv", str(VENV)])
    if uv:
        run([uv, "pip", "install", "--python", str(VPY), "torch", "--index-url", "https://download.pytorch.org/whl/cpu"])
        run([uv, "pip", "install", "--python", str(VPY), "-r", "requirements.txt"])
    else:
        run([str(VPY), "-m", "pip", "install", "--upgrade", "pip"])
        run([str(VPY), "-m", "pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/cpu"])
        run([str(VPY), "-m", "pip", "install", "-r", "requirements.txt"])
    run([NPM, "install", "--no-audit", "--no-fund"], cwd=FRONT)


def data() -> None:
    run([py(), "-m", "data_gen.generate"])


def train() -> None:
    run([py(), "-W", "ignore", "-m", "ml.train"])


def evaluate() -> None:
    run([py(), "-W", "ignore", "-m", "ml.evaluate"])


def build() -> None:
    if not (FRONT / "node_modules").exists():
        run([NPM, "install", "--no-audit", "--no-fund"], cwd=FRONT)
    run([NPM, "run", "build"], cwd=FRONT)


def demo() -> None:
    if not (ROOT / "data" / "ehr" / "patients.csv").exists():
        data()
    if not (ROOT / "artifacts" / "serving.json").exists():
        train()
    if not (FRONT / "dist" / "index.html").exists():
        build()
    url = "http://127.0.0.1:8000"
    print(f"\nStarting the Digital Twin demo at {url}. The engine warms up in about 30 s. Ctrl+C to stop.\n", flush=True)
    if not os.environ.get("DT_NO_BROWSER"):
        threading_open(url)
    run([py(), "-m", "backend.app"])


def threading_open(url: str) -> None:
    import threading

    def _open() -> None:
        time.sleep(35)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def dev() -> None:
    back = subprocess.Popen([py(), "-m", "backend.app"], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
    try:
        run([NPM, "run", "dev"], cwd=FRONT)
    finally:
        back.terminate()


def test() -> None:
    run([py(), "-m", "pytest", "-q", "tests"])
    run([NPM, "test"], cwd=FRONT)


def clean() -> None:
    for p in ("artifacts", "reports/figures", "frontend/dist"):
        shutil.rmtree(ROOT / p, ignore_errors=True)


TASKS = {"setup": setup, "data": data, "train": train, "evaluate": evaluate, "build": build, "demo": demo, "dev": dev,
         "test": test, "clean": clean, "all": lambda: [f() for f in (setup, data, train, build, test)]}

if __name__ == "__main__":
    names = sys.argv[1:] or ["demo"]
    for n in names:
        if n not in TASKS:
            sys.exit(f"unknown task {n!r}; choose from {', '.join(TASKS)}")
        TASKS[n]()
