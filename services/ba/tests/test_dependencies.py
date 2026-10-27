"""The image has exactly the pinned dependencies and they are consistent.

Catches the class of failure where a fresh build pulls a newer library that needs a package
nobody declared (litellm needing mcp 2.x broke every chat turn): the build is pinned by
constraints.txt, and this test fails if the installed set drifts from it or is inconsistent.
"""

import subprocess
import sys
from importlib import metadata
from pathlib import Path

CONSTRAINTS = Path(__file__).resolve().parents[1] / "constraints.txt"


def _pins() -> dict[str, str]:
    pins = {}
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


def test_pip_check_is_clean():
    result = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_installed_versions_match_constraints():
    drift = {}
    for name, version in _pins().items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue  # dev-only extras are not installed in every image
        if installed != version:
            drift[name] = (installed, version)
    assert not drift, f"installed vs pinned: {drift}"


def test_llm_tool_call_dependencies_import():
    """litellm imports mcp on tool calls; import it here so a missing/old mcp fails the tests."""
    import litellm  # noqa: F401
    from mcp.types import CacheableResult  # noqa: F401
