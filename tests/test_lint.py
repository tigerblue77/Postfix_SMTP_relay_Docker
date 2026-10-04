# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""Which shell scripts the ShellCheck gate reads, and what the workflow
linters are allowed to let through.

`.github/workflows/lint.yml` names its scripts one by one instead of globbing,
because the tree has no directory that holds only them: `run` and `healthcheck`
sit at the root next to everything else. That makes the list something a new
script has to be added to by hand, and a script missing from it is analysed by
nothing at all while **ShellCheck** stays green. So the list is compared here
with what the tree actually holds, in both directions: every tracked file with a
shell shebang is named, and every name is a file.

The second half is about `.github/workflows/lint-workflows.yml`, which lints the
workflows themselves with actionlint and zizmor. A linter is only worth its
check while it is pinned, and while what it has been told to let through stays
the short list somebody argued for: a suppression is a decision to defend, and
a pull request that appends one to turn its own check green is the case this is
for. So the versions, the hashes and the offline flag are pinned here, and the
suppressions are compared with the list below, which is where a new one has to
be argued.

Like `test_ruleset.py` this reads files and starts nothing, so it is part of the
half of the suite that needs no docker daemon.
"""

import re
import shlex
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB = REPO_ROOT / ".github"
LINT = GITHUB / "workflows" / "lint.yml"
LINT_WORKFLOWS = GITHUB / "workflows" / "lint-workflows.yml"
ACTIONLINT_CONFIG = GITHUB / "actionlint.yaml"
ZIZMOR_CONFIG = GITHUB / "zizmor.yml"
DEPENDABOT = GITHUB / "dependabot.yml"

# Everything the two workflow linters are told to let through. Adding to either
# list means editing it here, in the same change as the file it describes, with
# the reason where the suppression is written.
#
# actionlint, by file: the messages it may not report there. Both are one stale
# table entry -- its copy of actions/create-github-app-token@v3 predates the
# action's client-id input.
ACTIONLINT_IGNORES = {
    ".github/workflows/auto_update_pull_request_branches.yml": [
        'missing input "app-id" which is required by action "actions/create-github-app-token@v3"',
        'input "client-id" is not defined in action "actions/create-github-app-token@v3"',
    ],
}
# zizmor, by file and audit: the inline "# zizmor: ignore[...]" comments. The
# one is the workflow_run trigger of test-results.yml, whose header argues it.
ZIZMOR_IGNORES = {("test-results.yml", "dangerous-triggers")}

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


def lint_workflows():
    return yaml.safe_load(LINT_WORKFLOWS.read_text())["jobs"]


def run_lines(job):
    """Every line of every `run:` step of a job, with the backslash
    continuations joined, so a command wrapped over two lines is one."""
    text = "\n".join(step.get("run", "") for step in job["steps"])
    return text.replace("\\\n", " ").splitlines()


def test_actionlint_is_pinned_and_run_without_the_integrations():
    """`go install` names the version, and the version is a release and not
    `latest`: an unpinned linter fails somebody's unrelated pull request on the
    day it ships a new check. The command is the one CLAUDE.md documents, with
    shellcheck and pyflakes off -- both only run if the runner image has them,
    so on it the verdict would depend on the image, and the shell in a `run:`
    block is not what the ShellCheck gate reads.
    """
    job = lint_workflows()["actionlint"]
    version = job["env"]["ACTIONLINT_VERSION"]
    assert re.fullmatch(r"v\d+\.\d+\.\d+", version), f"actionlint is not pinned to a release: {version!r}"
    lines = run_lines(job)
    installs = [line for line in lines if "go install" in line]
    assert len(installs) == 1 and installs[0].endswith(
        "github.com/rhysd/actionlint/cmd/actionlint@${ACTIONLINT_VERSION}\""
    ), f"actionlint is not installed at the pinned version: {installs}"
    checks = [line.strip() for line in lines if line.strip().startswith("actionlint ")]
    assert "actionlint -shellcheck= -pyflakes=" in checks, (
        f"the actionlint command changed from the documented one: {checks}"
    )
    assert not any("-ignore" in line for line in lines), (
        "a suppression written on the actionlint command line; they belong in "
        ".github/actionlint.yaml, where this test compares them"
    )


def test_zizmor_is_pinned_by_hash_and_runs_offline():
    """The wheel is installed with `--require-hashes`, from the hash in the
    job's environment, so pip refuses any other file under the same name. And
    the audit is `--offline`: the online audits ask advisory databases whose
    content changes daily, which would turn a required check red for reasons
    that are in no pull request.
    """
    job = lint_workflows()["zizmor"]
    env = job["env"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", env["ZIZMOR_VERSION"]), env["ZIZMOR_VERSION"]
    assert re.fullmatch(r"[0-9a-f]{64}", env["ZIZMOR_WHEEL_SHA256"]), env["ZIZMOR_WHEEL_SHA256"]
    lines = run_lines(job)
    installs = [line for line in lines if "bin/pip" in line and " install " in line]
    assert len(installs) == 1, f"expected one pip install, got {installs}"
    assert "--require-hashes" in installs[0] and "--only-binary :all:" in installs[0], installs[0]
    assert any("--hash=sha256:%s" in line and "ZIZMOR_WHEEL_SHA256" in line for line in lines), (
        "the requirements line the install reads no longer carries the wheel's hash"
    )
    audits = [line.strip() for line in lines if line.strip().startswith("zizmor ") and "--version" not in line]
    assert len(audits) == 1 and "--offline" in audits[0], f"the audit does not run offline: {audits}"


def test_the_workflow_linters_let_through_only_what_is_argued_for():
    """The suppressions are compared with the lists at the top of this file,
    so that adding one is a change here, with its reason, rather than a line
    that makes a check green. What each is for is written beside it: the
    actionlint ones in `.github/actionlint.yaml`, the zizmor one in the header
    of the workflow it sits in.

    zizmor's two configured audits are checked too, because they can be turned
    into suppressions without anyone adding an `ignore`: a `*` policy of `any`
    would stop `unpinned-uses` finding anything, and a cooldown threshold under
    what `dependabot.yml` configures would stop `dependabot-cooldown` from
    noticing that file go soft.
    """
    actionlint = yaml.safe_load(ACTIONLINT_CONFIG.read_text())
    assert set(actionlint) == {"paths"}, f"actionlint.yaml has more than paths: {sorted(actionlint)}"
    assert {path: body["ignore"] for path, body in actionlint["paths"].items()} == ACTIONLINT_IGNORES

    found = set()
    for path in sorted(list(GITHUB.glob("**/*.yml")) + list(GITHUB.glob("**/*.yaml"))):
        for comment in re.findall(r"#\s*zizmor:\s*ignore\S*", path.read_text()):
            audit = re.fullmatch(r"#\s*zizmor:\s*ignore\[([\w-]+)\]", comment)
            assert audit, f"{path.name}: {comment!r} is a blanket zizmor ignore; name the audit"
            found.add((path.name, audit.group(1)))
    assert found == ZIZMOR_IGNORES, (
        f"zizmor suppressions found {sorted(found)}, argued for {sorted(ZIZMOR_IGNORES)}"
    )

    rules = yaml.safe_load(ZIZMOR_CONFIG.read_text())["rules"]
    assert set(rules) == {"unpinned-uses", "dependabot-cooldown"}, sorted(rules)
    assert not [r for r, body in rules.items() if "ignore" in body], "zizmor.yml ignores something"
    assert rules["unpinned-uses"]["config"]["policies"] == {"*": "ref-pin"}, (
        "unpinned-uses is configured for something other than 'a ref is enough, "
        "for every action': a hash pin would fail the whole tree, and any would "
        "let an action with no ref through"
    )
    cooldowns = [
        update["cooldown"]["default-days"]
        for update in yaml.safe_load(DEPENDABOT.read_text())["updates"]
        if "cooldown" in update
    ]
    assert rules["dependabot-cooldown"]["config"]["days"] == min(cooldowns), (
        "zizmor's cooldown threshold is not the shortest default-days of dependabot.yml"
    )
