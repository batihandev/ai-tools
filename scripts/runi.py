#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path
from .helper.env import load_repo_dotenv
from .helper.colors import Colors
load_repo_dotenv()


def main() -> None:
    if not sys.argv[1:]:
        print(f"Usage: {Colors.bold('runi')} <command ...>", file=sys.stderr)
        sys.exit(1)

    base_dir = Path(__file__).resolve().parents[1]
    log_dir = base_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    log_path = log_dir / "investigate-last.log"

    # Environment for child
    env = os.environ.copy()
    env["INVESTIGATE_LOG"] = str(log_path)
    # Help Python-based tools flush more frequently
    env.setdefault("PYTHONUNBUFFERED", "1")

    cmd = sys.argv[1:]
    print(f"{Colors.c('[runi]')} executing: {' '.join(cmd)}")

    with log_path.open("w", encoding="utf-8", errors="ignore") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered on our side
            env=env,
        )

        assert proc.stdout is not None

        try:
            for line in proc.stdout:
                # live output
                sys.stdout.write(line)
                sys.stdout.flush()
                # log everything
                log_file.write(line)
                log_file.flush()
        except KeyboardInterrupt:
            # Forward Ctrl+C to the child
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        finally:
            try:
                proc.wait()
            except KeyboardInterrupt:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    code = proc.returncode

    if code != 0:
        try:
            answer = input(
                f"\n{Colors.c('[runi]')} command exited with {Colors.r(str(code))}. "
                "Run investigate on this log? [y/N] "
            ).strip().lower()
        except EOFError:
            answer = ""

        if answer in ("y", "yes"):
            investigate_py = base_dir / "scripts" / "investigate.py"
            subprocess.call([sys.executable, str(investigate_py)])

    sys.exit(code)


if __name__ == "__main__":
    main()
