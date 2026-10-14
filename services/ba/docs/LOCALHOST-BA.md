# Chạy BA Agent trên localhost

Cách được hỗ trợ: **Docker Compose**. Stack gồm Web UI, FastAPI/ADK, PostgreSQL
(named volume) và wiki SQLite (named volume). API gọi trực tiếp company LLM
gate `https://llm-gate.imespro.ai/v1`. LiteLLM Proxy là **tùy chọn**
(`--profile litellm`) và không chặn `docker compose up` nếu image thiếu.

Uvicorn ad-hoc trên máy (venv + `/tmp/ba-demo-*.db`) chỉ còn là fallback khi
không chạy được Docker.

| Thành phần | Port host | Dữ liệu |
| --- | ---: | --- |
| Web UI | `5173` | Vite; proxy `/api` → container `api` |
| API | `8000` | FastAPI + ADK |
| PostgreSQL | `5432` | Named volume `pgdata` — `ba_packages` và ADK sessions |
| Wiki | (trong API) | Named volume `wiki-data` — `mvp/data/wiki.db` + blobs |
| LiteLLM | nội bộ `4000` | Chỉ khi `--profile litellm` |

## Yêu cầu và cấu hình

- Docker Desktop với Docker Compose v2.
- API key company gate trong `.env` (`LLM_GATE_API_KEY`).

Tạo `.env` nếu chưa có:

```bash
cp .env.example .env
```

Cấu hình tối thiểu:

```env
LLM_GATE_API_BASE_URL=https://llm-gate.imespro.ai/v1
LLM_GATE_API_KEY=<company-key>
LLM_GATE_MODEL_NAME=Qwen3.5-27B-AWQ

# Host checkout of Wiki Knowledge MVP (compose bind-mounts it)
WIKI_MVP_ROOT=/absolute/path/to/WikiFactoryAI/mvp
```

Mặc định Compose ghi đè `WIKI_MVP_ROOT` **trong container** thành
`/opt/wiki-mvp` và gắn named volume lên `/opt/wiki-mvp/data`. Đường dẫn host
chỉ dùng cho bind-mount.

## Khởi động (cách hỗ trợ)

Từ thư mục repo BA:

```bash
docker compose up -d --build
```

Hoặc `make docker-up`. Compose chờ PostgreSQL healthy và seed wiki volume
(nếu volume trống, copy `mvp/data` hiện có). Không chờ LiteLLM.

URL:

- UI (Document Manager): http://127.0.0.1:5173
- BA chat: http://127.0.0.1:5173/chat.html?session=<session_id>&title=<title>
- Validate Agent: http://127.0.0.1:5173/va.html?session=<session_id>&title=<title>
- Wiki import: http://127.0.0.1:5173/wiki.html
- Swagger: http://127.0.0.1:8000/docs
- Readiness: http://127.0.0.1:8000/api/health

Readiness bình thường (demo **không** 503 khi LLM gate lỗi):

```json
{
  "status": "ok",
  "app": "ba-agent",
  "adk_ready": true,
  "database_ready": true,
  "llm_proxy_ready": true,
  "llm_provider": "company-gate",
  "llm_endpoint": "https://llm-gate.imespro.ai/v1"
}
```

`llm_proxy_ready` có thể là `false` nếu company gate không trả `/v1/models`.
Manager, wiki upload và `/api/features` vẫn chạy. Chat cần gate.

## Fallback: uvicorn trên máy (không Docker)

Chỉ dùng khi Docker không chạy được. Cần PostgreSQL local (cùng `DB_*` trong
`.env`) — **không** dùng lại `/tmp/ba-demo-*.db`.

Host uvicorn uses **PATH Node** for BPMN ELK layout (`tools/bpmn_elk`). Install
once, then leave Node on PATH (or set `BA_NODE` / `BA_BPMN_NODE`):

```bash
cd tools/bpmn_elk && npm ci --omit=dev
.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

`deploy/host-up.sh` installs the ELK helper automatically when missing. If Node
or the package is absent, BPMN still generates with DIY DI (no failure).
`BA_BPMN_ELK_DISABLE=1` forces DIY. Docker API image already includes Node 20 +
`npm ci` for this helper.

Các file `/tmp/ba-demo-sync.db` và `/tmp/ba-demo-adk.db` (nếu còn) là archive
của harness cũ. Compose **không** migrate chúng sang Postgres.

## LiteLLM tùy chọn

```bash
USE_LITELLM_PROXY=true LITELLM_API_BASE_URL=http://litellm:4000/v1 \
  docker compose --profile litellm up -d --build
```

Cần image `docker.litellm.ai/...` pull được. Không bắt buộc cho demo local.

## Kiểm tra và test

```bash
docker compose ps
docker compose logs --tail 100 api web
curl -sS http://127.0.0.1:8000/api/health
curl -sS http://127.0.0.1:8000/api/features
```

Pytest **không** cần Docker (SQLite in-memory):

```bash
pytest tests/ -q
```

Pytest trong image (optional):

```bash
docker compose --profile test run --rm --build test
```

## Dừng và dữ liệu

Giữ Postgres + wiki:

```bash
docker compose down
```

Xóa named volumes (mất packages và wiki.db trong Docker):

```bash
docker compose down -v
```

**Clear wiki** trên UI chỉ xóa 3 bảng `wiki_*` trong volume wiki — không đụng
`ba_packages` / ADK sessions trên Postgres.

## Troubleshooting

### Cổng 5173 hoặc 8000 đã được dùng

Dừng Vite/uvicorn host cũ (`lsof -nP -iTCP:5173 -sTCP:LISTEN` và
`lsof -nP -iTCP:8000 -sTCP:LISTEN`) rồi `docker compose up -d`.

Harness ad-hoc `uvicorn` trên `127.0.0.1:8000` (kể cả `/tmp/ba-demo-*.db`)
chiếm IPv4 và làm `curl http://127.0.0.1:8000` không vào container. Tắt
process đó trước khi dùng Compose.

### Cổng 5432 đã được dùng

Dừng PostgreSQL/container khác hoặc đổi host mapping thành `5433:5432`. API
trong Compose vẫn kết nối `db:5432`.

### API báo `llm_proxy_ready=false`

Company gate `https://llm-gate.imespro.ai/v1/models` không trả 200. Kiểm tra
`LLM_GATE_API_KEY` trong `.env`. Demo vẫn `status=ok` nếu `database_ready`.

### Thay `.env`

```bash
docker compose up -d --force-recreate api
```

## Coder VPS

Frappe giữ cổng 8000 trên máy chủ. Overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.coder.yml up -d --build
```

API ra host **8010**, UI **5173**. Trên Compose 2.40 phải dùng `ports: !override` (không `!reset` rồi liệt kê — như vậy cổng bị xóa). Workspace hiện tại: user `ubuntu`, mã tại `/home/ubuntu/data/home/apps/` (`ba-factory`, `wiki-mvp`), symlink `~/apps`. `WIKI_MVP_ROOT` không được trỏ `/home/coder/apps/wiki-mvp`.

Demo khép kín: `make demo-all` (hoặc runner `--continue --turn-timeout 300`). Nếu glossary `PG-GLOSS-*` đụng seed cũ `PRJ-MES-01`: `POST /api/wiki/clear` (confirm `CLEAR`) rồi xóa feature lỗi và chạy lại — lệnh này không xóa Postgres.

Closed-cycle packs: [demo/README.md](../demo/README.md). Handoff: WikiFactoryAI `HANDOFF.md`.
