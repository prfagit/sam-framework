"""Helpers to locate and write .env files for SAM CLI.

Kept intentionally simple to avoid coupling with the CLI module.
"""

import os
from typing import Dict


def find_env_path() -> str:
    """Determine a stable .env file location.

    Prefers existing .env in CWD; else sam_framework/.env next to example; else CWD/.env
    """
    cwd_env = os.path.join(os.getcwd(), ".env")
    if os.path.exists(cwd_env):
        return cwd_env
    repo_env_example = os.path.join(os.getcwd(), "sam_framework", ".env.example")
    if os.path.exists(repo_env_example):
        return os.path.join(os.path.dirname(repo_env_example), ".env")
    return cwd_env


def write_env_file(path: str, values: Dict[str, str]) -> None:
    """Write or update key=value pairs in a .env file."""
    existing: Dict[str, str] = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.strip().split("=", 1)
                        existing[k] = v
        except Exception:
            pass
    existing.update(values)
    lines = ["# SAM Framework configuration", "# Managed by CLI", ""]
    for k, v in existing.items():
        lines.append(f"{k}={v}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
