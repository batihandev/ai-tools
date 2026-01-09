# ai-scripts

```bash
bin/explain --diff
python scripts/explain.py --diff
```

- smart_parse

```bash
bin/smart_parse broken.json
python scripts/smart_parse.py broken.json
```

- runi

```bash
bin/runi pytest
python scripts/runi.py pytest
```

- screen_explain

```bash
bin/screen_explain
python scripts/screen_explain.py
```

- english-teacher

```bash
bin/english-teacher --mode coach "hello i am fine"
python -m scripts.english_teacher --mode coach "hello i am fine"
```

## Server + UI

- Backend (FastAPI):

```bash
make server
```

Runs on `http://127.0.0.1:8008`.

- Frontend (Vite):

```bash
make frontend-dev
```

Runs on `http://127.0.0.1:5173`.

## PATH setup (optional)

To run the tools directly without typing `bin/`, add the repo’s `bin/` directory to your PATH:

```bash
export PATH="$HOME/personal/ai-scripts/bin:$PATH"
```

After that, you can run:

```bash
ai_commit
investigate
explain --diff
smart_parse broken.json
runi pytest
english-teacher --mode coach "hello i am fine"
```

Add the export line to your shell config (`~/.bashrc`, `~/.zshrc`, etc.) to make it permanent.

## Config

Main env vars (see `.env.example`):

- `OLLAMA_URL`
- `OLLAMA_SKIP_WSL_IP_DETECT`
- `INVESTIGATE_MODEL` (default: `llama3.1:8b`)
- `AI_COMMIT_MODEL`
- `SMART_PARSE_MODEL`
- `LLM_SOFT_CONTEXT_LIMIT`
- `SCREENSHOT_DIR`
- `VLM_MODEL`
- `VLM_DEBUG`

English teacher:

- `ENGLISH_TEACHER_MODEL`
- `ENGLISH_TEACHER_NUM_CTX`
- `ENGLISH_TEACHER_TIMEOUT`
- `ENGLISH_TEACHER_MODE`

## Notes

- Runs fully local
- Linux / WSL only (no native Windows)
- Built for daily personal use
