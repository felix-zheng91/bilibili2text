## bilibili-to-text Web UI

The Web UI consists of a FastAPI backend and a Vue/Vite frontend. See the root [README.md](../README.md) for the complete clone-to-run workflow.

### Directory Structure

- `backend/`: FastAPI API routes and task queue
- `frontend/`: Vue + Vite frontend, using Bun for dependency management

### Configuration

The Web UI uses the following files from the project root:

- `config.toml`
- `summary_presets.toml`
- `context.toml` (optional, used to inject author-specific stock/alias context into the summary prompt)

First, copy the configuration template in the project root:

```bash
cp config.toml.example config.toml
```

It is recommended to start with `Groq + local storage` to get the local workflow running. DashScope/Qwen ASR requires MinIO or Alibaba Cloud OSS to provide public temporary audio URLs.

### One-Click Start

Run the following in the project root:

```bash
just web on
```

Access by default at:

```text
http://127.0.0.1:6010
```

To stop:

```bash
just web off
```

### Manual Start

Backend:

```bash
uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd web-ui/frontend
bun install
bun run dev
```

If the backend port is not `8000`:

```bash
bun run dev --backend-port 8001
```

### Login Protection

The Web UI uses the paid ASR/LLM credentials from `config.toml`, so a public deployment must require authentication. Set the following environment variables for the backend process (or in the Docker Compose `.env`):

```bash
B2T_AUTH_ENABLED=1
B2T_AUTH_USERNAME=admin
B2T_AUTH_PASSWORD=<a long random password>
B2T_AUTH_SESSION_HOURS=168
```

When `B2T_AUTH_PASSWORD` is set, authentication is enabled even without `B2T_AUTH_ENABLED`. If authentication is enabled but no password or `B2T_AUTH_PASSWORD_HASH` is configured, the backend refuses to start. Sessions are stored in an HMAC-signed HttpOnly cookie, and changing the password invalidates all existing sessions.

To keep only a hash in the environment:

```bash
docker compose exec -w /app/web-ui backend uv run --no-sync python -m backend.auth hash
```

The signing secret is read from `B2T_AUTH_SECRET`; when unset, it is generated once and stored in `db_data/.auth_secret`. Login attempts are limited to 5 failures per IP per 5 minutes, followed by a 15 minute lockout.

For an additional edge layer, configure [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/applications/) for the public hostname and restrict it to your email address.

### Open-Public Mode

```bash
just web-open-public on
```

This mode disables history deletion and local project API Keys, and requires users to enter their own DashScope API Key on the page. User audio/video uploads are handled as ephemeral transcriptions: they are not added to shared history and are deleted 2 hours after completion. Since this mode uses Qwen ASR, the local `config.toml` still requires a working MinIO or Alibaba Cloud OSS configuration.

### Host Backend + Nginx Container

Run the following in the project root:

```bash
uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port 8000
./scripts/serve_frontend_nginx.sh up
```

The script builds `web-ui/frontend/dist` and serves it with the official Nginx image. The backend remains on the host, and `/api/*` is proxied to `host.docker.internal:8000`.

For open-public mode:

```bash
B2T_WEB_UI_MODE=open-public uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port 8000
./scripts/serve_frontend_nginx.sh up
```
