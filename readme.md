# ai-scripts

## Description

Personal CLI toolbox built around **Ollama** for working with logs, diffs, code, and text using a local LLM.
Opinionated, lightweight, and designed for **Linux** and **Windows via WSL2**.

Runs fully local. No cloud services.

## Tools

- **ai-commit** – Generate structured git commit messages from diffs
- **investigate** – Analyze logs (debug / summary / blame)
- **explain** – Explain diffs, code, configs, docs, or logs
- **smart-parse** – Repair malformed JSON / code / text
- **runi** – Run a command, capture logs, investigate on failure
- **screen-explain** – Analyze screenshots / UI states using a local vision-capable model

## Install

```bash
make install
cp .env.example .env   # optional
```

Requires Python 3.12+, `make`, and Ollama running locally.

## Usage

One example per tool (bin wrapper and direct Python):

- ai-commit

  ```bash
  bin/ai-commit
  python scripts/ai-commit.py
  ```

- investigate

  ```bash
  bin/investigate logs/app.log
  python scripts/investigate.py logs/app.log
  ```

- explain

  ```bash
  bin/explain --diff
  python scripts/explain.py --diff
  ```

- smart-parse

  ```bash
  bin/smart-parse broken.json
  python scripts/smart-parse.py broken.json
  ```

- runi

  ```bash
  bin/runi pytest
  python scripts/runi.py pytest
  ```

- screen-explain

  ```bash
  bin/screen-explain
  python scripts/screen-explain.py
  ```

## PATH setup (optional)

To run the tools directly without typing `bin/`, add the repo’s `bin/` directory to your PATH:

```
export PATH="$HOME/personal/ai-scripts/bin:$PATH"
```

After that, you can run:

```
ai-commit
investigate
explain --diff
smart-parse broken.json
runi pytest
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

## Notes

- Runs fully local
- Linux / WSL only (no native Windows)
- Built for daily personal use
