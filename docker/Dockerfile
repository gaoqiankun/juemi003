ARG TRELLIS2_IMAGE=cubify3d/trellis2:latest
ARG NODE_IMAGE=node:24-bookworm-slim

FROM ${NODE_IMAGE} AS web-builder

WORKDIR /web

COPY web/package.json web/package-lock.json ./

RUN npm ci

COPY web/index.html ./
COPY web/postcss.config.js ./
COPY web/tailwind.config.ts ./
COPY web/tsconfig.json ./
COPY web/vite.config.ts ./
COPY web/public ./public
COPY web/src ./src

RUN npm run build

FROM ${TRELLIS2_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-worker.txt ./

RUN apt-get update && \
    apt-get install -y --no-install-recommends libegl1-mesa && \
    rm -rf /var/lib/apt/lists/* && \
    python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install -r requirements-worker.txt

# Keep the checkout under /app/gen3d so `python serve.py` sees the same
# package layout as a normal repo checkout (`<parent>/gen3d/...`).
COPY . /app/gen3d
COPY --from=web-builder /web/dist /app/gen3d/web/dist

RUN chmod +x /app/gen3d/scripts/download_models.sh

WORKDIR /app/gen3d

ENV PYTHONPATH=/opt/TRELLIS.2 \
    PROVIDER_MODE=real \
    MODEL_PROVIDER=trellis2 \
    MODEL_PATH=/models/trellis2 \
    ARTIFACT_STORE_MODE=local \
    DATABASE_PATH=/data/cubify3d.sqlite3 \
    ARTIFACTS_DIR=/data/artifacts

EXPOSE 18001

CMD ["python", "serve.py"]
