"""AnyControl web server launcher.

The implementation lives in backend/src/vision_input.  Keeping this entry
point preserves the project's original `python server.py` workflow.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    backend_python = root / "backend" / ".venv" / "bin" / "python"
    if not backend_python.is_file():
        raise SystemExit("backend/.venv is missing; see README.md for setup")
    env = os.environ.copy()
    paths = [root / "backend" / "src", root / "third_party" / "EfficientTAM"]
    env["PYTHONPATH"] = os.pathsep.join([*(str(p) for p in paths), env.get("PYTHONPATH", "")])
    os.execve(str(backend_python), [str(backend_python), "-m", "vision_input", "serve", *sys.argv[1:]], env)
