# Build context: platform root (docker build -f services/ba/Dockerfile .)
FROM python:3.12-slim-bookworm

# Slow mirrors: retry instead of failing the build.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5

WORKDIR /app

# Every pip install is pinned to the versions of a known-good build (see constraints.txt).
COPY services/ba/constraints.txt /opt/constraints.txt
ENV PIP_CONSTRAINT=/opt/constraints.txt

# Node 20 for API-side BPMN ELK layout (tools/bpmn_elk). Copied from official
# Node image — no full frontend toolchain.
COPY --from=node:20-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:20-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node -v && npm -v

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY services/ba/pyproject.toml services/ba/README.md ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[dev]"

# Shared platform library (auth, project access) and wiki package
# (factory_wiki adds the wiki to sys.path via WIKI_MVP_ROOT).
COPY packages/platform_core /opt/platform/packages/platform_core
RUN pip install --no-cache-dir /opt/platform/packages/platform_core
COPY packages/wiki /opt/platform/packages/wiki

COPY services/ba/ .

# Install after copying the source: .dockerignore intentionally excludes
# node_modules, so installing before COPY . would remove the helper again.
# The official npm tarball currently returns 404; the mirror serves the
# pinned 1.4.0 artifact.
RUN cd tools/bpmn_elk && npm ci --omit=dev --registry=https://registry.npmmirror.com

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
