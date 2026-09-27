# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""What `.claude/settings.json` lets a Claude Code session run without asking.

The file is a standing grant to every session opened on this repository, so
the list is pinned here whole: adding to it has to be argued in the same
commit, not appended. Three commands are on it, the ones a contributor runs
before pushing, each in the narrowest form that still covers that:

- `pytest`, exactly. A prefix rule would pre-approve every argument list, and
  pytest has options that write or delete wherever they are pointed:
  `--junitxml` writes a file, `--basetemp` empties the directory it is given
  before a run, `-p` loads a plugin by name.
- `ruff check --no-cache --select F,B tests`, exactly: what the **Ruff** check
  runs. `--fix` rewrites files and `--output-file` writes one.
- `shellcheck`, with any arguments. It only reads the files it is given and
  prints to standard output; no option of it names a file to write.

`git`, `docker` and `gh` are deliberately absent.

Like `test_ruleset.py` this reads a file and starts nothing, so it is part of
the half of the suite that needs no docker daemon.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

ALLOWED = [
    "Bash(pytest)",
    "Bash(ruff check --no-cache --select F,B tests)",
    "Bash(shellcheck:*)",
]


def settings():
    return json.loads(SETTINGS.read_text())


def test_the_pre_approved_commands_are_exactly_the_argued_ones():
    allowed = settings().get("permissions", {}).get("allow", [])
    assert allowed == ALLOWED, (
        f"{SETTINGS.name} pre-approves {allowed}; changing that list is a "
        "decision to argue in this module's docstring, not a line to append"
    )


def test_nothing_is_pre_denied_or_asked_instead():
    """Only `allow` is used. A `deny` or `ask` list would be a second place
    the grant is decided, and nothing here would pin it."""
    assert set(settings().get("permissions", {})) <= {"allow"}


def test_the_session_start_hook_is_registered():
    """The hook sets the sign-off identity and starts docker; a settings file
    rewritten for the permissions must not lose it."""
    commands = [
        hook["command"]
        for group in settings()["hooks"]["SessionStart"]
        for hook in group["hooks"]
    ]
    assert commands == ["$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh"]
