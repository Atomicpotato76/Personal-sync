# PBL Router HTTP Server

`router_v4.py` is kept unchanged. `router_server.py` wraps its existing routing logic with FastAPI so other Python programs can call the router over HTTP.

## Files

- `router_server.py`: FastAPI server that reuses `smart_classify()` and `call_with_preset()`
- `client.py`: lightweight Python helper for external scripts
- `requirements.txt`: minimal dependencies for the HTTP server

## Install

```bash
python -m pip install -r requirements.txt
```

## Environment

Create or update `.env` in the project root:

```env
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
LM_STUDIO_URL=http://100.78.18.95:1234/v1/chat/completions
ROUTER_HOST=0.0.0.0
ROUTER_PORT=8000
```

`router_server.py` syncs those values into `router_v4` at startup so the server and CLI share the same backend logic.

## Run

```bash
python router_server.py
```

The server listens on `http://0.0.0.0:8000` by default.

## Auto-start on Windows

If you want the server to come up automatically after login, use `start_router_server.ps1` with Windows Task Scheduler.

- Script: `start_router_server.ps1`
- Logs: `logs/router_server.stdout.log`, `logs/router_server.stderr.log`
- The script skips launch if `router_server.py` is already running

## Endpoints

### `POST /chat`

Example request:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"안녕\",\"preset\":\"hermes\"}"
```

Behavior:

- `preset` provided: force that preset
- `preset` omitted: run `smart_classify()` from `router_v4`
- `profile`: restricts the active preset pool
- `history`: transient extra conversation context
- `session_id`: enables in-memory history persistence for that session

### `GET /presets`

Lists loaded presets with backend and JSON-schema availability.

### `GET /profiles`

Lists loaded profiles and their active presets.

### `GET /health`

Returns server status, LM Studio connectivity, API-key availability, and preset/profile counts.

### `DELETE /session/{session_id}`

Clears the in-memory history for the given session.

## Session behavior

- Session history is stored in memory only
- Each session keeps at most 40 messages (20 turns)
- If you want a new session from Python, `RouterClient` generates a UUID automatically when `use_session=True`

## Python client example

```python
from client import RouterClient

router = RouterClient("http://localhost:8000")
reply = router.chat("프롬프트 템플릿 설계 도와줘", preset="hermes", use_session=True)
follow_up = router.chat("위 템플릿을 RAG용으로 개선", use_session=True)
```

## Notes

- `router_v4.py` is not modified by this server wrapper
- CORS is open to all origins for local/Tailscale use
- Local backend failures return HTTP 503
- Missing Claude/OpenAI API keys return HTTP 400
