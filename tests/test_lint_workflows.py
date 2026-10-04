# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""What `lint-workflows.yml` gates, and what its two linters may let through.

That workflow lints the workflows themselves with actionlint and zizmor, and
both of its jobs are required checks. A linter is only worth its check while it
is pinned, while it reads every file it is meant to, and while what it has been
told to let through stays the short list somebody argued for: a suppression is a
decision to defend, and a pull request that appends one to turn its own check
green is the case this is for. So the versions, the hashes and the flags are
pinned here, the suppressions are compared with the lists below, which is where
a new one has to be argued, and the two jobs are held to the ruleset: required,
and reporting on every pull request.

Like `test_ruleset.py` these read files and start nothing, so they are part of
the small half of the suite that needs no docker daemon.
"""

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB = REPO_ROOT / ".github"
LINT_WORKFLOWS = GITHUB / "workflows" / "lint-workflows.yml"
TEST_RESULTS = GITHUB / "workflows" / "test-results.yml"
RULESET = GITHUB / "rulesets" / "master.json"
ACTIONLINT_CONFIG = GITHUB / "actionlint.yaml"
ZIZMOR_CONFIG = GITHUB / "zizmor.yml"

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
# zizmor, by file and audit: the inline "# zizmor: ignore[...]" comments, each
# with the text the line carrying it has to contain, so that the comment cannot
# outlive the thing it is about. The one is the workflow_run trigger of
# test-results.yml, whose header argues it.
ZIZMOR_IGNORES = {("test-results.yml", "dangerous-triggers"): "workflow_run:"}


def jobs():
    return yaml.safe_load(LINT_WORKFLOWS.read_text())["jobs"]


def run_lines(job):
    """Every line of every `run:` step of a job, with the backslash
    continuations joined, so a command wrapped over two lines is one."""
    text = "\n".join(step.get("run", "") for step in job["steps"])
    return text.replace("\\\n", " ").splitlines()


def test_the_workflow_linters_gate_every_pull_request():
    """actionlint and zizmor are required checks, and so must report on every
    pull request: a required check that a path filter, or a missing trigger,
    keeps from running leaves the pull requests it skips waiting for a result
    that never comes. Their display names are what the ruleset matches on, so
    the names are asserted too, and not only that the ruleset names *some* job.

    Only the ruleset file makes them required. Importing it under Settings >
    Rules is the maintainer's step, which no test can take.
    """
    workflow = yaml.safe_load(LINT_WORKFLOWS.read_text())
    names = sorted(job["name"] for job in workflow["jobs"].values())
    assert names == ["actionlint", "zizmor"], (
        f"{LINT_WORKFLOWS.name} reports {names}, not the two checks the ruleset names"
    )
    rules = [r for r in json.loads(RULESET.read_text())["rules"] if r["type"] == "required_status_checks"]
    required = [c["context"] for c in rules[0]["parameters"]["required_status_checks"]]
    missing = [name for name in names if name not in required]
    assert not missing, f"linters that gate nothing, absent from the ruleset: {missing}"

    triggers = workflow[True]
    assert "pull_request" in triggers, f"{LINT_WORKFLOWS.name} does not run on pull requests"
    filters = {"branches", "branches-ignore", "paths", "paths-ignore", "types"}
    narrowed = filters & set(triggers["pull_request"] or {})
    assert not narrowed, (
        f"the pull_request trigger of {LINT_WORKFLOWS.name} is narrowed by "
        f"{sorted(narrowed)}, so a required check would not report on every pull request"
    )


def test_actionlint_is_pinned_and_run_without_the_integrations():
    """`go install` names the version, and the version is a release and not
    `latest`: an unpinned linter fails somebody's unrelated pull request on the
    day it ships a new check. The command is the one CLAUDE.md documents, with
    shellcheck and pyflakes off -- both only run if the runner image has them,
    so on it the verdict would depend on the image, and the shell in a `run:`
    block is not what the ShellCheck gate reads.
    """
    job = jobs()["actionlint"]
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


def test_zizmor_is_pinned_by_hash_and_audits_offline_and_strictly():
    """The wheel is installed with `--require-hashes`, from the hash in the
    job's environment, so pip refuses any other file under the same name. The
    audit is `--offline`: the online audits ask advisory databases whose content
    changes daily, which would turn a required check red for reasons that are in
    no pull request. And it is `--strict-collection`: without it a file zizmor
    cannot parse is skipped with a warning and the check stays green, and
    `dependabot.yml` is read by zizmor and by nothing else here.
    """
    job = jobs()["zizmor"]
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
    assert len(audits) == 1, f"expected one zizmor audit, got {audits}"
    for flag in ("--offline", "--strict-collection"):
        assert flag in audits[0], f"the audit does not run with {flag}: {audits}"


def test_the_workflow_linters_let_through_only_what_is_argued_for():
    """The suppressions are compared with the lists at the top of this file,
    so that adding one is a change here, with its reason, rather than a line
    that makes a check green. What each is for is written beside it: the
    actionlint ones in `.github/actionlint.yaml`, the zizmor one in the header
    of the workflow it sits in. Each has to still be about something: an
    actionlint ignore names an action reference the file it covers still uses,
    and a zizmor ignore sits on a line that still holds what it was written for.

    zizmor's one configured audit is checked too, because it can be turned
    into a suppression without anyone adding an `ignore`: `ref-pin` is the least
    that refuses an action with no ref at all, and `any` would stop
    `unpinned-uses` finding anything. Nothing else may be configured: in
    particular `dependabot-cooldown` keeps its default threshold of seven days,
    which is what `dependabot.yml` sets, so that the audit goes on checking that
    file against a number nobody here picked.
    """
    actionlint = yaml.safe_load(ACTIONLINT_CONFIG.read_text())
    assert set(actionlint) == {"paths"}, f"actionlint.yaml has more than paths: {sorted(actionlint)}"
    assert {path: body["ignore"] for path, body in actionlint["paths"].items()} == ACTIONLINT_IGNORES
    for path, messages in ACTIONLINT_IGNORES.items():
        text = (REPO_ROOT / path).read_text()
        for message in messages:
            for reference in re.findall(r'"([^"\s]+@[^"\s]+)"', message):
                assert f"uses: {reference}" in text, (
                    f"the actionlint ignore {message!r} is dead: {path} no longer uses {reference}"
                )

    found = {}
    for path in sorted(list(GITHUB.glob("**/*.yml")) + list(GITHUB.glob("**/*.yaml"))):
        for line in path.read_text().splitlines():
            for comment in re.findall(r"#\s*zizmor:\s*ignore\S*", line):
                audit = re.fullmatch(r"#\s*zizmor:\s*ignore\[([\w-]+)\]", comment)
                assert audit, f"{path.name}: {comment!r} is a blanket zizmor ignore; name the audit"
                found[(path.name, audit.group(1))] = line
    assert set(found) == set(ZIZMOR_IGNORES), (
        f"zizmor suppressions found {sorted(found)}, argued for {sorted(ZIZMOR_IGNORES)}"
    )
    for key, marker in ZIZMOR_IGNORES.items():
        assert marker in found[key], f"the zizmor ignore {key} no longer sits on a line with {marker!r}: {found[key]!r}"

    rules = yaml.safe_load(ZIZMOR_CONFIG.read_text())["rules"]
    assert set(rules) == {"unpinned-uses"}, (
        f"zizmor.yml configures {sorted(rules)}; only unpinned-uses is, and "
        f"dependabot-cooldown keeps zizmor's default threshold"
    )
    assert not [r for r, body in rules.items() if "ignore" in body], "zizmor.yml ignores something"
    assert rules["unpinned-uses"]["config"]["policies"] == {"*": "ref-pin"}, (
        "unpinned-uses is configured for something other than 'an action has a "
        "ref, for every action': a hash pin would fail the whole tree, and any "
        "would let an action with no ref through"
    )


def test_the_workflow_run_ignore_still_has_what_justifies_it():
    """`# zizmor: ignore[dangerous-triggers]` on the `workflow_run` line of
    `test-results.yml` exempts the whole `on:` block, not that one trigger: a
    `pull_request_target:` added next to it would pass silently. What argues for
    the ignore, in that file's header, is pinned here instead: the workflow has
    that trigger and no other; its job checks out nothing and runs no script,
    so nothing taken from the artifacts of the triggering run is ever executed,
    and no local action (`uses: ./...`, which would need a checkout) either; and
    its token carries the five permissions the header counts and nothing else.
    """
    workflow = yaml.safe_load(TEST_RESULTS.read_text())
    assert set(workflow[True]) == {"workflow_run"}, (
        f"{TEST_RESULTS.name} triggers on {sorted(workflow[True])}; the ignore "
        f"covers the whole block and was argued for a workflow_run alone"
    )
    assert workflow["permissions"] == {"actions": "read"}, workflow["permissions"]
    assert len(workflow["jobs"]) == 1, sorted(workflow["jobs"])
    (job,) = workflow["jobs"].values()
    assert job["permissions"] == {
        "checks": "write",
        "pull-requests": "write",
        "contents": "read",
        "issues": "read",
        "actions": "read",
    }, f"the job's token is no longer the five permissions the header counts: {job['permissions']}"
    assert "container" not in job and "services" not in job, "the job runs in something other than the runner"
    for step in job["steps"]:
        assert "run" not in step, (
            f"step {step.get('name')!r} runs a script; this job may only hand "
            f"the artifacts to actions as files to parse"
        )
        uses = str(step.get("uses", "")).lower()
        assert uses and not uses.startswith("actions/checkout@") and not uses.startswith(("./", "docker://")), (
            f"step {step.get('name')!r} checks out, runs a local action or a container: {step.get('uses')!r}"
        )
