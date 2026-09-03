"""Tests for minisweagent.__init__."""

import os
import subprocess
import sys
from pathlib import Path

import minisweagent


def test_root_dir_is_repository_root():
    """root_dir must point to the repository root (the parent of the package's parent)."""
    assert isinstance(minisweagent.root_dir, Path)
    assert minisweagent.root_dir == minisweagent.package_dir.parent.parent
    # The repo root should contain the src directory and pyproject.toml
    assert (minisweagent.root_dir / "src").is_dir()
    assert (minisweagent.root_dir / "pyproject.toml").is_file()


def test_startup_banner_survives_non_utf8_stdout(tmp_path):
    """Importing the package must not crash when stdout can't encode the startup banner (e.g. Windows cp1252)."""
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "MSWEA_SILENT_STARTUP": "",
        "MSWEA_GLOBAL_CONFIG_DIR": str(tmp_path),
    }
    result = subprocess.run([sys.executable, "-c", "import minisweagent"], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
