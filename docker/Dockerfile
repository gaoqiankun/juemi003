ARG TRELLIS2_IMAGE=cubie3d/trellis2:latest
ARG NODE_IMAGE=node:24-bookworm-slim
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/

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
    UV_NO_CACHE=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

COPY pyproject.toml uv.lock ./

ARG PIP_INDEX_URL
RUN apt-get update && \
    apt-get install -y --no-install-recommends libegl1-mesa && \
    rm -rf /var/lib/apt/lists/* && \
    pip install uv --index-url ${PIP_INDEX_URL} && \
    uv export --group worker --no-dev --frozen --no-emit-project -o /tmp/requirements.txt && \
    uv pip install --system --index-url ${PIP_INDEX_URL} -r /tmp/requirements.txt

# Project source lives under /app/cubie.
COPY . /app/cubie
COPY --from=web-builder /web/dist /app/cubie/web/dist

RUN chmod +x /app/cubie/scripts/download_models.sh

WORKDIR /app/cubie

ENV PROVIDER_MODE=real \
    ARTIFACT_STORE_MODE=local \
    DATABASE_PATH=/data/app.sqlite3 \
    ARTIFACTS_DIR=/data/artifacts

EXPOSE 18001

CMD ["python", "-m", "cubie.serve"]
