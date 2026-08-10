"""
Runs the browser-side suite as part of `uv run pytest`.

The calendar's logic is JavaScript, and until now none of it was tested. Giving
it a second command to remember is how a suite stops being run, so it is
attached to the one that already exists rather than left beside it.

Node's own test runner is used, so no package.json and no npm dependency tree
enter a Python project. Where node is absent the suite skips rather than fails:
the JS is served as static files and needs no build, so a contributor without
node can still run everything else.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Node treats a bare directory as a module to require, so the tests are named
#: by glob instead.
TEST_GLOB = "tests/js/**/*.test.js"


def test_the_javascript_suite_passes():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --test` to cover the browser code")

    result = subprocess.run(
        [node, "--test", TEST_GLOB],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # The runner's own output is the failure report, so it is passed through
    # rather than summarised into "exit code 1".
    assert result.returncode == 0, "\n" + result.stdout + result.stderr
