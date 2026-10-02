from __future__ import annotations

"""
Root conftest.py — adds ``src/`` and ``scripts/`` to ``sys.path`` so that
pytest can import ``chainshield`` and the demo scripts without requiring an
editable install.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent
for _p in (_REPO_ROOT / "src", _REPO_ROOT / "scripts"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

# Preload ortools CP-SAT on Windows before third-party native libraries (DuckDB) initialize
try:
    from ortools.sat.python import cp_model as _preload_cp_model  # noqa: F401
except Exception:
    pass

