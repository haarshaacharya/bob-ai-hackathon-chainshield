from __future__ import annotations

"""
Standalone runner for ChainShield end-to-end integration tests.

Executes every test class in tests/integration/test_e2e_scenario.py and
prints PASS / FAIL.  Does not require pytest to be installed — a minimal
shim for pytest.approx is injected before the test module is imported.

Usage
-----
    python run_integration_tests.py
"""

import importlib
import inspect
import sys
import traceback
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
for p in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

# ---------------------------------------------------------------------------
# Minimal pytest shim  (only approx is needed by the tests)
# ---------------------------------------------------------------------------

try:
    import pytest
except ImportError:
    class _Approx:
        def __init__(self, expected: float, rel: float = 1e-6) -> None:
            self.expected = expected
            self.rel = rel

        def __eq__(self, actual: object) -> bool:
            if not isinstance(actual, (int, float)):
                return False
            if self.expected == 0:
                return abs(actual) < self.rel  # type: ignore[operator]
            return abs(actual - self.expected) / abs(self.expected) < self.rel  # type: ignore[operator]

        def __repr__(self) -> str:
            return f"≈{self.expected}"

    def _fixture(*args, **kwargs):
        def decorator(fn):
            return fn
        if args and callable(args[0]):
            return args[0]
        return decorator

    _pytest_shim = types.ModuleType("pytest")
    _pytest_shim.approx = _Approx  # type: ignore[attr-defined]
    _pytest_shim.fixture = _fixture  # type: ignore[attr-defined]
    sys.modules.setdefault("pytest", _pytest_shim)

# ---------------------------------------------------------------------------
# Import the integration test module (after shim is registered)
# ---------------------------------------------------------------------------

import tests.integration.test_e2e_scenario as test_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Pre-build all module-scoped fixtures once
# ---------------------------------------------------------------------------

from demo_scenario import _build_scenario_data, _build_scenario_graph, run_demo_scenario  # noqa: E402
from generate_synthetic_data import generate_scenario  # noqa: E402

print("Building scenario fixtures (this may take a moment)...")
_scenario_result = run_demo_scenario()
_bundle = generate_scenario(seed=42)
_graph = _build_scenario_graph()
_scenario_data = _build_scenario_data()
print("Fixtures ready.\n")

FIXTURES: dict[str, object] = {
    "scenario_result": _scenario_result,
    "bundle": _bundle,
    "graph": _graph,
    "scenario_data": _scenario_data,
}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def _call_test(instance: object, method_name: str) -> None:
    """Call a test method, injecting fixtures for any named parameters."""
    method = getattr(instance, method_name)
    sig = inspect.signature(method)
    # Bound methods: sig.parameters does NOT include 'self'
    params = list(sig.parameters.keys())
    args = []
    for p in params:
        if p not in FIXTURES:
            raise ValueError(
                f"Test {method_name!r} requests unknown fixture {p!r}. "
                f"Available: {list(FIXTURES)}"
            )
        args.append(FIXTURES[p])
    method(*args)


def run_all() -> int:
    total = passed = failed = 0
    failures: list[str] = []

    for class_name, cls in sorted(
        inspect.getmembers(test_mod, inspect.isclass),
        key=lambda x: x[0],
    ):
        if not class_name.startswith("Test"):
            continue
        instance = cls()
        for method_name, _ in sorted(inspect.getmembers(instance, inspect.ismethod)):
            if not method_name.startswith("test_"):
                continue
            total += 1
            label = f"{class_name}.{method_name}"
            try:
                _call_test(instance, method_name)
                print(f"  PASS  {label}")
                passed += 1
            except Exception:
                failed += 1
                tb = traceback.format_exc()
                print(f"  FAIL  {label}")
                # Indent the traceback for readability
                indented = "\n        ".join(tb.splitlines())
                print(f"        {indented}")
                failures.append(label)

    print()
    print("=" * 72)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failures:
        print("\nFailed tests:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("All integration tests passed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
