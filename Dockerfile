# syntax=docker/dockerfile:1
# DigitalFly in a container: the hashed Python locks, the built interface, and Mesa for headless
# rendering (EGL, with OSMesa as the fallback). See docs/INSTALL.md.
#
#   docker build -t digitalfly .
#   docker run --rm --init -p 127.0.0.1:8000:8000 -v digitalfly_runs:/app/runs -v digitalfly_cache:/app/.cache \
#     -v digitalfly_presets:/app/configs/local digitalfly
#
# then open http://localhost:8000. Build arguments:
#   EXTRAS=flyvis,builder,recording  optional parts, as for ./scripts/setup.sh --with (flyvis: CPU-only PyTorch)
#   UID=1000                         the container user's id, to match the owner of bind-mounted folders
#   APT_MIRROR=https://...           another Ubuntu archive (needs an https mirror behind an https-only proxy)
# Behind a TLS-intercepting proxy, pass its CA certificate for the build only, with
#   --secret id=ca,src=/path/to/ca.crt --build-arg HTTPS_PROXY=...
# Neither the certificate nor the proxy settings are stored in the image.
# The "dev" target (Node 24, Xvfb, git; no application) is the VS Code dev container in .devcontainer/.

ARG BASE_IMAGE=ubuntu:24.04
ARG NODE_IMAGE=node:24-slim

FROM ${NODE_IMAGE} AS node

# The interface, built from frontend/package-lock.json exactly as setup.sh does.
FROM node AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# Ubuntu 24.04: the validated Linux stack (its Python 3.12 and Mesa), with long-term security updates.
# EGL renders on the CPU through Mesa's llvmpipe without a display or /dev/dri; OSMesa is the fallback.
# System packages are not pinned: the archive keeps only current versions, which carry security fixes.
# Python packages are pinned and hashed by the locks.
FROM ${BASE_IMAGE} AS base
ARG APT_MIRROR=""
ARG DEBIAN_FRONTEND=noninteractive
# hadolint ignore=DL3008
RUN --mount=type=secret,id=ca,mode=0444,required=false \
    set -eu; \
    ca=""; if [ -s /run/secrets/ca ]; then ca=/run/secrets/ca; fi; \
    if [ -n "$APT_MIRROR" ]; then \
      sed -i -E "s#http://(archive|security)\.ubuntu\.com/ubuntu/?#${APT_MIRROR%/}/#" /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    apt-get ${ca:+-o Acquire::https::CAInfo=$ca} update; \
    apt-get ${ca:+-o Acquire::https::CAInfo=$ca} install -y --no-install-recommends \
      ca-certificates python3.12 python3.12-venv \
      libegl1 libegl-mesa0 libgl1 libglx-mesa0 libgl1-mesa-dri libosmesa6; \
    rm -rf /var/lib/apt/lists/*

# Development container: the workspace is mounted, and postCreate runs ./scripts/setup.sh in it.
FROM base AS dev
ARG DEBIAN_FRONTEND=noninteractive
# hadolint ignore=DL3008
RUN --mount=type=secret,id=ca,mode=0444,required=false \
    set -eu; \
    ca=""; if [ -s /run/secrets/ca ]; then ca=/run/secrets/ca; fi; \
    apt-get ${ca:+-o Acquire::https::CAInfo=$ca} update; \
    apt-get ${ca:+-o Acquire::https::CAInfo=$ca} install -y --no-install-recommends \
      git openssh-client less sudo xvfb xauth \
      libx11-6 libxrandr2 libxinerama1 libxcursor1 libxi6 libxxf86vm1 libxkbcommon0; \
    rm -rf /var/lib/apt/lists/*; \
    echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu; chmod 0440 /etc/sudoers.d/ubuntu
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version
# The image's own "ubuntu" user (uid 1000), which the dev container runs as.
USER 1000

# The application. Code and environment belong to root; the app writes only to its data folders.
FROM base AS runtime
WORKDIR /app
# The hashed installs, as in setup.sh: pip and its tools from their lock first, then the runtime lock.
# A layer of their own, so that only a lock change downloads them again.
COPY backend/requirements-tools.lock backend/requirements.lock backend/
RUN --mount=type=secret,id=ca,required=false \
    set -eu; \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    python3.12 -m venv backend/.venv; \
    backend/.venv/bin/python -m pip install --no-cache-dir --disable-pip-version-check --require-hashes -r backend/requirements-tools.lock; \
    backend/.venv/bin/python -m pip install --no-cache-dir --disable-pip-version-check --require-hashes -r backend/requirements.lock
COPY LICENSE NOTICE README.md CITATION.cff ./
COPY backend/ backend/
COPY scripts/ scripts/
COPY configs/ configs/
COPY data/ data/
COPY docs/ docs/
COPY frontend/package.json frontend/
COPY --from=frontend /src/frontend/dist frontend/dist
# setup.sh itself then finds the locks satisfied, installs the package, prepares the first-run caches
# and adds the optional EXTRAS.
ARG EXTRAS=""
RUN --mount=type=secret,id=ca,required=false \
    set -eu; \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca SSL_CERT_FILE=/run/secrets/ca; fi; \
    ./scripts/setup.sh --backend-only ${EXTRAS:+--with "$EXTRAS"}; \
    rm -rf .cache/pip .cache/pip-tools
ARG UID=1000
RUN set -eu; \
    userdel --remove ubuntu 2>/dev/null || true; \
    useradd --uid "$UID" --create-home --shell /usr/sbin/nologin digitalfly; \
    mkdir -p runs configs/local data/circuits/local data/connectivity data/flygym-assets; \
    chown -R digitalfly:digitalfly runs .cache configs/local data/circuits/local data/connectivity data/flygym-assets
ARG REVISION=""
LABEL org.opencontainers.image.title="DigitalFly" \
      org.opencontainers.image.description="Closed-loop fruit-fly sensorimotor workbench (FlyGym/MuJoCo, FlyWire circuits)" \
      org.opencontainers.image.source="https://github.com/Jeevash23/frankenfly" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.version=""
# DIGITALFLY_HOST makes the server listen on the container's network interface, which a published
# port needs. DIGITALFLY_ALLOW_NETWORK_BIND=1 acknowledges that there is no login: publish the port
# to 127.0.0.1 only (-p 127.0.0.1:8000:8000). Host and Origin checks stay on; for another host port,
# add it with DIGITALFLY_ALLOWED_ORIGINS=http://localhost:PORT.
ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DIGITALFLY_CONTAINER=image \
    DIGITALFLY_HOST=0.0.0.0 \
    DIGITALFLY_ALLOW_NETWORK_BIND=1
USER ${UID}
# Saved runs, caches and presets saved in the app. A new volume starts with the image's folder, owned by its user.
VOLUME ["/app/runs", "/app/.cache", "/app/configs/local"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request as u; r = u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:8000/api/health', timeout=4); assert json.load(r)['worker_alive']"]
CMD ["./scripts/start.sh"]
