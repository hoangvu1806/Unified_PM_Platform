# Build context: platform root (docker build -f services/core/Dockerfile .)
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY packages/platform_core /opt/platform/packages/platform_core
RUN pip install --no-cache-dir /opt/platform/packages/platform_core

COPY services/core/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY services/core/ ./

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
