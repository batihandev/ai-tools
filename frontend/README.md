# ai-scripts frontend

React (Vite) UI for the local **ai-scripts** server.

Currently includes:

- **Voice**: microphone capture with silence detection → `/api/voice/transcribe`
- **Teacher session**: queued transcripts → `/api/english/teach` with session persistence
- **History**: transcript history + teacher reply history

## Run

From repo root:

```bash
make frontend-dev
```

Vite runs on `http://127.0.0.1:5173`.

In another terminal, run the backend:

```bash
make server
```

Backend runs on `http://127.0.0.1:8008`.

## Notes

- The teacher chat is persisted by `chat_key` and restores the last session on load.
