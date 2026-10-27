# Build context: platform root (docker build -f services/designer/Dockerfile .)
FROM python:3.12-slim-bookworm

# Service root = /app (data/, logs/ live beside app/).
# Slow mirrors: retry instead of failing the build.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5

WORKDIR /app

# Every pip install is pinned to the versions of a known-good build (see constraints.txt).
COPY services/designer/constraints.txt /opt/constraints.txt
ENV PIP_CONSTRAINT=/opt/constraints.txt

COPY packages/platform_core /opt/platform/packages/platform_core
RUN pip install --no-cache-dir /opt/platform/packages/platform_core

# Headless Chromium for rendering screens (shell build only), before the other dependencies
# so changing requirements.txt does not download the browser again.
RUN pip install --no-cache-dir playwright==1.60.0     && playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*

COPY services/designer/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY services/designer/ ./

EXPOSE 8282

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8282"]
