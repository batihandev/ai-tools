# ai-scripts

## Description

Personal CLI toolbox built around **Ollama** for working with logs, diffs, code, and text using a local LLM.
Opinionated, lightweight, and designed for **Linux** and **Windows via WSL2**.

## Tools

- **ai-commit** – Generate structured git commit messages from diffs
- **investigate** – Analyze logs (debug / summary / blame)
- **explain** – Explain diffs, code, configs, docs, or logs
- **smart-parse** – Repair malformed JSON / code / text
- **runi** – Run a command, capture logs, investigate on failure

## Install

```bash
make install
cp .env.example .env   # optional
```

Requires Python 3.12+, `make`, and Ollama running locally.

## Usage

Recommended (via generated wrappers):

    bin/ai-commit
    bin/investigate
    bin/explain --diff
    bin/smart-parse broken.json
    bin/runi pytest

You can also run the scripts directly with Python:

    python scripts/ai-commit.py
    python scripts/investigate.py
    python scripts/explain.py --diff
    python scripts/smart-parse.py broken.json
    python scripts/runi.py pytest

## PATH setup (optional)

To run the tools directly without typing `bin/`, add the repo’s `bin/` directory to your PATH:

    export PATH="$HOME/personal/ai-scripts/bin:$PATH"

After that, you can run:

    ai-commit
    investigate
    explain --diff
    smart-parse broken.json
    runi pytest

Add the export line to your shell config (`~/.bashrc`, `~/.zshrc`, etc.) to make it permanent.

## Config

Main env vars (see `.env.example`):

- `OLLAMA_URL`
- `INVESTIGATE_MODEL` (default: `llama3.1:8b`)
- `AI_COMMIT_MODEL`
- `SMART_PARSE_MODEL`
- `LLM_SOFT_CONTEXT_LIMIT`

## Notes

- Runs fully local
- Linux / WSL only (no native Windows)
- Built for daily personal use
