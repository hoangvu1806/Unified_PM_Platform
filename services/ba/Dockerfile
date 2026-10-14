FROM python:3.12-slim-bookworm

WORKDIR /app

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

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[dev]"

COPY . .

# Install after copying the source: .dockerignore intentionally excludes
# node_modules, so installing before COPY . would remove the helper again.
# The official npm tarball currently returns 404; the mirror serves the
# pinned 1.4.0 artifact.
RUN cd tools/bpmn_elk && npm ci --omit=dev --registry=https://registry.npmmirror.com

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
