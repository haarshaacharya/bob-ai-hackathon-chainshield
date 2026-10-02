from __future__ import annotations

"""Standalone test runner — no pytest required.  Executes every test class
in tests/unit/test_fallback.py and prints a concise PASS/FAIL report."""

import importlib
import inspect
import sys
import traceback
from pathlib import Path

# Make sure src/ is importable
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Import the test module
import tests.unit.test_fallback as test_mod


def run_all() -> int:
    total = passed = failed = 0
    failures: list[str] = []

    for class_name, cls in inspect.getmembers(test_mod, inspect.isclass):
        if not class_name.startswith("Test"):
            continue
        instance = cls()
        for method_name, method in inspect.getmembers(instance, inspect.ismethod):
            if not method_name.startswith("test_"):
                continue
            total += 1
            label = f"{class_name}.{method_name}"
            try:
                method()
                print(f"  PASS  {label}")
                passed += 1
            except Exception:
                failed += 1
                tb = traceback.format_exc()
                print(f"  FAIL  {label}")
                print("        " + tb.replace("\n", "\n        ").strip())
                failures.append(label)

    print()
    print(f"{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failures:
        print("Failed tests:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("All tests passed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
