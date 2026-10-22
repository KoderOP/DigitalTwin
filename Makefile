# Thin wrapper around tasks.py so the same commands work on Linux/macOS (make) and Windows (python tasks.py ...).
PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python)

.PHONY: setup data train evaluate build demo dev test clean all docker

setup:     ; $(PYTHON) tasks.py setup
data:      ; $(PYTHON) tasks.py data
train:     ; $(PYTHON) tasks.py train
evaluate:  ; $(PYTHON) tasks.py evaluate
build:     ; $(PYTHON) tasks.py build
demo:      ; $(PYTHON) tasks.py demo
dev:       ; $(PYTHON) tasks.py dev
test:      ; $(PYTHON) tasks.py test
clean:     ; $(PYTHON) tasks.py clean
all:       ; $(PYTHON) tasks.py all
docker:    ; docker compose up --build
