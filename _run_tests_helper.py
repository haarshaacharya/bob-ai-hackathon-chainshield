from __future__ import annotations

"""Helper: run the integration test runner and print results."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

result = subprocess.run(
    [sys.executable, "run_integration_tests.py"],
    cwd=str(ROOT),
    capture_output=True,
    text=True,
    timeout=120,
)
print("STDOUT:")
print(result.stdout)
if result.stderr:
    print("STDERR:")
    print(result.stderr)
print(f"\nExit code: {result.returncode}")
