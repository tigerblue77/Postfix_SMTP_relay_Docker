# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""Which shell scripts the ShellCheck gate reads.

`.github/workflows/lint.yml` names its scripts one by one instead of globbing,
because the tree has no directory that holds only them: `run` and `healthcheck`
sit at the root next to everything else. That makes the list something a new
script has to be added to by hand, and a script missing from it is analysed by
nothing at all while **ShellCheck** stays green. So the list is compared here
with what the tree actually holds, in both directions: every tracked file with a
shell shebang is named, and every name is a file.

Like `test_ruleset.py` this reads files and starts nothing, so it is part of the
half of the suite that needs no docker daemon.
"""

import re
import shlex
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LINT = REPO_ROOT / ".github" / "workflows" / "lint.yml"

SHELL_SHEBANG = re.compile(r"^#!\s*(/usr/bin/env\s+)?(/bin/|/usr/bin/)?(ba|da|k|z)?sh\b")


def shell_scripts():
    """Every tracked file whose first line is a shell shebang, by path from
    the repository root. Tracked rather than present, so a virtualenv or a
    scratch file in the checkout does not count."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.split("\0")
    scripts = set()
    for name in filter(None, tracked):
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        with path.open("rb") as f:
            first = f.readline(256)
        if SHELL_SHEBANG.match(first.decode("utf-8", "replace")):
            scripts.add(name)
    return scripts


def linted():
    """The files the ShellCheck job's shellcheck invocation names."""
    steps = yaml.safe_load(LINT.read_text())["jobs"]["shellcheck"]["steps"]
    commands = [
        line for step in steps for line in step.get("run", "").splitlines()
        if line.strip().startswith("shellcheck ") and "--version" not in line
    ]
    assert len(commands) == 1, (
        f"expected one shellcheck invocation in {LINT.name}, found {commands}"
    )
    words = shlex.split(commands[0])[1:]
    files, skip = set(), False
    for word in words:
        if skip:
            skip = False
        elif word in ("-S", "--severity", "-s", "--shell", "-e", "--exclude"):
            skip = True
        elif not word.startswith("-"):
            files.add(word)
    return files


def test_every_shell_script_is_linted():
    missing = shell_scripts() - linted()
    assert not missing, (
        f"{sorted(missing)} carry a shell shebang and {LINT.name} does not "
        "name them, so nothing lints them: add them to the ShellCheck step"
    )


def test_every_linted_name_is_a_shell_script():
    stale = linted() - shell_scripts()
    assert not stale, (
        f"{LINT.name} names {sorted(stale)}, which are not tracked shell "
        "scripts: a renamed or removed script leaves the gate pointing at "
        "nothing"
    )


def test_the_tree_has_the_scripts_this_is_about():
    """Guards the two tests above against passing on an empty set, which is
    what they would do if `git ls-files` stopped seeing the tree."""
    assert {"run", "healthcheck"} <= shell_scripts()
