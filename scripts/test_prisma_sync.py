"""Validate the shipped entrypoint's flags against the installed Prisma CLI."""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = [
    shlex.split(line)
    for line in (ROOT / "scripts/ci/prisma-sync.sh").read_text().splitlines()
    if line.startswith("bunx prisma db migrate")
]


@pytest.mark.parametrize("command", COMMANDS)
def test_migration_entrypoint_uses_supported_cli_flags(command: list[str]) -> None:
    # Preview the same command without connecting to a database or applying DDL.
    # In particular, db migrate does not support db sign's --no-advance-ref flag.
    args = [*command]
    if "--show" not in args:
        args.append("--show")
    args += ["--from", "@empty", "--to", "@contract"]
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    result = subprocess.run(
        args, cwd=ROOT / "packages/db", env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
