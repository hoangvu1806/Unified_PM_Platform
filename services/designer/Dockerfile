# Build context: platform root (docker build -f services/designer/Dockerfile .)
# Requires the openpencil:local image (see services/designer/infra/README.md).
FROM openpencil:local AS openpencil-runtime

FROM python:3.12-slim-bookworm

# The component pipeline uses OpenPencil's local CLI to inspect .fig sources.
# Reuse the exact CLI/dependency tree already built for the OpenPencil image so
# the backend and the running editor stay on the same version.
COPY --from=openpencil-runtime /app /opt/openpencil
COPY --from=openpencil-runtime /usr/local/bin/bun /usr/local/bin/bun
COPY --from=openpencil-runtime /lib/ld-musl-x86_64.so.1 /lib/ld-musl-x86_64.so.1
COPY --from=openpencil-runtime /usr/lib/libgcc_s.so.1 /usr/lib/libgcc_s.so.1
COPY --from=openpencil-runtime /usr/lib/libstdc++.so.6.0.33 /usr/lib/libstdc++.so.6.0.33
RUN ln -s /usr/lib/libstdc++.so.6.0.33 /usr/lib/libstdc++.so.6
COPY services/designer/openpencil-cli /usr/local/bin/openpencil
RUN chmod +x /usr/local/bin/openpencil

# Service root = /app (docs/, data/, logs/ live beside app/).
WORKDIR /app

COPY packages/platform_core /opt/platform/packages/platform_core
RUN pip install --no-cache-dir /opt/platform/packages/platform_core

COPY services/designer/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY services/designer/ ./

EXPOSE 8282

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8282"]
