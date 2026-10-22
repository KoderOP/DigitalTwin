# Multi-stage build: React dashboard -> Python runtime that trains (if needed) and serves the demo.
FROM node:20.18-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app DT_HOST=0.0.0.0 DT_PORT=8000 DT_NO_BROWSER=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt
COPY common/ common/
COPY config/ config/
COPY data_gen/ data_gen/
COPY ml/ ml/
COPY twin/ twin/
COPY backend/ backend/
COPY tests/ tests/
COPY tasks.py pytest.ini ./
COPY --from=web /app/frontend/dist frontend/dist
# data/, artifacts/ and reports/ are volumes. On first start the entrypoint generates data and trains (~15 min on CPU).
EXPOSE 8000
CMD ["sh", "-c", "[ -f data/ehr/patients.csv ] || python -m data_gen.generate; [ -f artifacts/serving.json ] || python -W ignore -m ml.train; python -m backend.app"]
