#!/usr/bin/env python3
"""
smart_parse – repair malformed JSON / code / text using local LLM.

USAGE EXAMPLES
--------------

# 1) Paste content manually (stdin)
smart_parse
<paste here>
CTRL+D
# → writes into ai-scripts/parsed/smart_parse-YYYYMMDD-HHMMSS.xxx
# → prints "code <path>" to open output file

# 2) Paste content, choose output directory
smart_parse ./outdir
<paste>
CTRL+D
# → writes ./outdir/smart_parse-YYYYMMDD-HHMMSS.xxx

# 3) Parse broken file automatically
smart_parse ./data/broken.json
# → writes ./data/broken.parsed.json

# 4) Parse file, write into a different directory
smart_parse ./data/broken.json ./repaired
# → writes ./repaired/broken.parsed.json

# 5) Parse file, explicit output file
smart_parse ./data/broken.json ./repaired/fixed.json

# 6) Pipe output of another command
cat broken.js | smart_parse
# → auto-named file under parsed/

cat broken.js | smart_parse ./outdir
# → auto-named file under ./outdir
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from textwrap import dedent
import threading
import time

import requests
from .helper.ollama_utils import resolve_ollama_url
from .helper.env import load_repo_dotenv
from .helper.colors import Colors
load_repo_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
PARSED_DIR = BASE_DIR / "parsed"
PARSED_DIR.mkdir(exist_ok=True)





# ---------------------------------------------------------------------------

def _looks_like_json(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if s[0] not in "{[":
        return False
    return ":" in s and '"' in s


def _looks_like_markdown(s: str) -> bool:
    lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return False
    for ln in lines[:5]:
        if ln.startswith(("#", "-", "*", ">")):
            return True
        if ln.startswith("|") and "|" in ln[1:]:
            return True
    return False


def _looks_like_python_code(s: str) -> bool:
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return False

    first = lines[0]
    if first.startswith("#!/usr/bin/env python"):
        return True

    score = 0
    for ln in lines[:25]:
        if ln.startswith(("def ", "class ", "from ", "import ")):
            score += 1
        if ln.endswith(":") and ("def " in ln or "class " in ln):
            score += 1
    return score >= 2


def _guess_ext(content: str) -> str:
    # order matters: code > json > markdown > txt
    if _looks_like_python_code(content):
        return ".py"
    if _looks_like_json(content):
        return ".json"
    if _looks_like_markdown(content):
        return ".md"
    return ".txt"


def read_source() -> tuple[str, Path | None, Path | None]:
    """
    Determine input source + optional explicit output path / directory.

    Signature:
      smart_parse
      smart_parse <out_path_or_dir>
      smart_parse <input_file>
      smart_parse <input_file> <out_path_or_dir>

    Resolution rules:
      - If stdin has data → stdin is the source (args only used for output).
      - Else, if first arg is a file → use that file as input.
      - Second arg (if any) is treated as output path or directory.
      - If only one arg and it's not a file → treated as output path/dir, input = stdin.
    """
    argv = sys.argv[1:]

    # 1) stdin wins if it has data
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        src_path = None
        out_arg = Path(argv[0]).expanduser() if argv else None
        return data, src_path, out_arg

    # 2) interactive stdin, decide by args
    src_path: Path | None = None
    out_arg: Path | None = None

    if not argv:
        print(
            f"{Colors.c('[smart_parse]')} {Colors.m('Paste content, then press Ctrl+D.')}",
            file=sys.stderr,
        )
        data = sys.stdin.read()
        return data, None, None

    first = Path(argv[0]).expanduser()

    if first.exists() and first.is_file():
        # smart_parse input_file [out]
        src_path = first
        data = first.read_text(encoding="utf-8", errors="ignore")
        if len(argv) > 1:
            out_arg = Path(argv[1]).expanduser()
    else:
        # smart_parse out_path_or_dir  (input from stdin)
        out_arg = first
        print(
            f"{Colors.c('[smart_parse]')} {Colors.m('Paste content, then press Ctrl+D.')}",
            file=sys.stderr,
        )
        data = sys.stdin.read()

    return data, src_path, out_arg


def compute_output_path(
    src_path: Path | None,
    out_arg: Path | None,
    fixed: str,
) -> Path:
    """
    Decide final output path.

    Cases:
      - If out_arg is a file path (not an existing dir): use it as-is.
      - If out_arg is an existing dir: write under that dir.
      - If src_path exists and no explicit file: src_dir / name.parsed.ext
      - Else: ai-scripts/parsed/smart_parse-<timestamp>.ext
    """
    # explicit out_arg
    if out_arg is not None:
        if out_arg.is_dir():
            if src_path:
                base = src_path.stem
                ext = src_path.suffix or _guess_ext(fixed)
                return (out_arg / f"{base}.parsed{ext}").resolve()
            else:
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                ext = _guess_ext(fixed)
                return (out_arg / f"smart_parse-{ts}{ext}").resolve()
        else:
            parent = out_arg.parent
            parent.mkdir(parents=True, exist_ok=True)
            return out_arg.resolve()

    # no out_arg
    if src_path is not None:
        base = src_path.stem
        ext = src_path.suffix or _guess_ext(fixed)
        return src_path.with_name(f"{base}.parsed{ext}").resolve()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = _guess_ext(fixed)
    return (PARSED_DIR / f"smart_parse-{ts}{ext}").resolve()


def call_model(snippet: str) -> str:
    """
    Ask the local model to minimally repair the snippet,
    but keep the same format. Shows a spinner while waiting.
    """
    ollama_url = resolve_ollama_url("http://localhost:11434")
    model = os.getenv("SMART_PARSE_MODEL", os.getenv("INVESTIGATE_MODEL", "llama3.1:8b"))

    system_prompt = dedent(
        """
        You repair arbitrary text with minimal changes.

        Input may be:
          - code (any language),
          - JSON / arrays / objects,
          - configs (YAML, TOML, INI),
          - Markdown, tables, comments, logs, etc.

        Your job:
          - Fix obvious syntax / structural problems:
              - close brackets / braces / quotes
              - fix clearly invalid trailing commas
              - balance parentheses
              - complete obviously truncated structures
          - Preserve the existing format and language.
            Do NOT convert plain text into JSON or YAML.
            Do NOT wrap the content inside new containers.
            Do NOT add metadata or commentary.

        Output:
          - Return ONLY the fixed content.
          - No explanations, no markdown fences, no backticks.
        """
    ).strip()

    user_prompt = f"Repair this snippet while preserving its format:\n\n{snippet}"

    payload = {
        "model": model,
        "num_ctx": 16000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    stop_flag = {"stop": False}

    def spinner():
        symbols = "|/-\\"
        idx = 0
        while not stop_flag["stop"]:
            sys.stderr.write(f"\r{Colors.c('[smart_parse]')} processing " + symbols[idx % 4])
            sys.stderr.flush()
            idx += 1
            time.sleep(0.1)
        sys.stderr.write(f"\r{Colors.c('[smart_parse]')} processing done   \n")
        sys.stderr.flush()

    thread = threading.Thread(target=spinner, daemon=True)
    thread.start()

    try:
        resp = requests.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except Exception as e:
        print(f"{Colors.c('[smart_parse]')} {Colors.r(f'Error calling Ollama: {e}')}", file=sys.stderr)
        sys.exit(1)
    finally:
        stop_flag["stop"] = True
        thread.join()


def main() -> None:
    raw, src_path, out_arg = read_source()

    if not raw.strip():
        print(f"{Colors.c('[smart_parse]')} {Colors.r('No input detected.')}", file=sys.stderr)
        sys.exit(1)

    fixed = call_model(raw)

    final_out = compute_output_path(src_path, out_arg, fixed)
    final_out.parent.mkdir(parents=True, exist_ok=True)
    final_out.write_text(fixed, encoding="utf-8")

    print(f"-> wrote fixed content to {Colors.g(str(final_out))}")
    print(f"-> open parsed version in editor:")
    print(f"   {Colors.b(f'code {final_out}')}")


if __name__ == "__main__":
    main()
