# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""The checks that gate a merge, against the jobs that report them.

`.github/rulesets/master.json` records the ruleset protecting master so the
gate can be checked rather than believed. These tests are what keep that record
true: a required check is matched by a job's display `name:`, so renaming a
job without editing the ruleset leaves a context that never reports, and a
context that never reports blocks every pull request until someone with admin
rights notices. The same goes for the merge method the Dependabot auto-merge
asks for, which the ruleset can refuse just as silently, and for the branch
updater, which the ruleset leaves best effort by not requiring branches to be
up to date.

These tests read files, and run the branch updater's step against a stubbed
`gh`; they start no container, so they need no docker daemon.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RULESET = REPO_ROOT / ".github" / "rulesets" / "master.json"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
AUTO_MERGE = WORKFLOWS / "dependabot-auto-merge.yml"
UPDATER = WORKFLOWS / "auto_update_pull_request_branches.yml"
MERGE_METHODS = {"--merge": "merge", "--squash": "squash", "--rebase": "rebase"}


def ruleset():
    return json.loads(RULESET.read_text())


def required_contexts():
    rules = [r for r in ruleset()["rules"] if r["type"] == "required_status_checks"]
    assert len(rules) == 1, f"expected one required_status_checks rule, got {len(rules)}"
    return [c["context"] for c in rules[0]["parameters"]["required_status_checks"]]


def job_display_names():
    """Every check name a workflow can report, mapped to the file reporting it.

    A job without a `name:` reports under its key -- that is how the
    auto-merge job appears -- so the key is the default rather than a skip.
    """
    names = {}
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for key, job in yaml.safe_load(workflow.read_text())["jobs"].items():
            names[job.get("name", key)] = workflow.name
    return names


def test_every_required_check_names_a_job_that_exists():
    reported = job_display_names()
    missing = [c for c in required_contexts() if c not in reported]
    assert not missing, (
        f"required contexts naming no job: {missing}. Such a context never "
        f"reports and blocks every pull request. Names that do report: "
        f"{sorted(reported)}"
    )


def test_the_ruleset_still_gates_the_default_branch():
    """A re-export made after fiddling in the web UI can bring back a file
    that records a gate which does not gate.

    Every way it can stop gating while still parsing, so that the file being
    re-importable is not mistaken for it being the same file: disabled or in
    "evaluate" mode, aimed at something other than the default branch, the
    default branch excluded again underneath, opened to a bypass actor, its
    rule requiring checks dropped or emptied, or a required approval added.

    The file is the whole of the live ruleset, not only its checks: master is
    also protected against deletion and force-pushes, takes pull requests
    only, and keeps a linear history, and a file carrying the checks alone
    would drop all four the day it was imported in place of the live one.
    Those four are not asserted here -- they are protections, not what makes
    the gate pass or fail. The approval count is: one required approval holds
    every Dependabot update for a person, however green, which is the thing
    the auto-merge workflow exists to stop.
    """
    recorded = ruleset()
    assert recorded["target"] == "branch"
    assert recorded["enforcement"] == "active"
    assert recorded["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert recorded["conditions"]["ref_name"]["exclude"] == []
    assert recorded["bypass_actors"] == []
    checks = [r for r in recorded["rules"] if r["type"] == "required_status_checks"]
    assert len(checks) == 1, "the ruleset carries exactly one rule that requires checks"
    assert checks[0]["parameters"]["required_status_checks"], (
        "a ruleset requiring no check lets auto-merge land an update with "
        "nothing checked"
    )
    approvals = [
        r["parameters"]["required_approving_review_count"]
        for r in recorded["rules"]
        if r["type"] == "pull_request"
    ]
    assert not any(approvals), (
        f"required approvals {approvals}: one holds every Dependabot update "
        f"for a person, however green"
    )


def auto_merge_methods():
    """The merge methods the Dependabot auto-merge workflow asks `gh` for."""
    methods = []
    for job in yaml.safe_load(AUTO_MERGE.read_text())["jobs"].values():
        for step in job.get("steps", []):
            words = step.get("run", "").split()
            if words[:3] == ["gh", "pr", "merge"]:
                methods += [MERGE_METHODS[w] for w in words if w in MERGE_METHODS]
    return methods


def test_dependabot_merges_by_a_method_the_ruleset_allows():
    """`gh pr merge --auto` asks for one merge method, and the ruleset decides
    which ones master takes: the pull request rule can narrow the list, and a
    linear history refuses a merge commit whatever that list says.

    That is how the auto-merge came to ask for `--merge` on a master that
    requires a linear history: the flag was written when the ruleset carried
    only its checks, and nothing read the two side by side.
    """
    methods = auto_merge_methods()
    assert len(methods) == 1, (
        f"expected {AUTO_MERGE.name} to ask for exactly one merge method, "
        f"got {methods}"
    )
    rules = {r["type"]: r.get("parameters", {}) for r in ruleset()["rules"]}
    allowed = set(
        rules.get("pull_request", {}).get("allowed_merge_methods", MERGE_METHODS.values())
    )
    if "required_linear_history" in rules:
        allowed.discard("merge")
    assert methods[0] in allowed, (
        f"{AUTO_MERGE.name} merges by {methods[0]!r}, which the ruleset does "
        f"not allow; it allows {sorted(allowed)}"
    )


def test_branches_are_not_required_to_be_up_to_date():
    """"Require branches to be up to date before merging" stays off. With it
    on, each merge leaves every other open pull request *blocked* until its
    branch is updated, and what updates them is best effort: the branch
    updater leaves alone a pull request that conflicts, one from a fork, a
    draft and Dependabot's own, and it only hears of a Dependabot merge on its
    next scheduled run, a push made with the `GITHUB_TOKEN` starting no
    workflow. Each of those would turn from behind into blocked. What the
    setting bought, a pull request tested against the master it lands on, is
    what the updater gives wherever it can reach, and is paid for after the
    merge everywhere else: **Verify Published Image** runs on every push to
    `master`, and `latest` does not move until it passes.
    """
    checks = [r for r in ruleset()["rules"] if r["type"] == "required_status_checks"]
    assert checks[0]["parameters"]["strict_required_status_checks_policy"] is False, (
        "requiring branches to be up to date blocks every pull request the "
        "branch updater cannot reach, and after a Dependabot merge all of them "
        "until its next scheduled run"
    )


def test_the_branch_updater_runs_after_every_merge_and_hourly():
    """A merge made in the `GITHUB_TOKEN`'s name -- every one the Dependabot
    auto-merge makes -- starts no workflow, so the push trigger alone leaves
    what such a merge left behind until somebody else merges. The schedule is
    what reaches those.
    """
    triggers = yaml.safe_load(UPDATER.read_text())[True]
    assert triggers["push"]["branches"] == ["master"], (
        f"{UPDATER.name} has to run on every push to master, got {triggers}"
    )
    assert triggers.get("schedule"), (
        f"{UPDATER.name} has to run on a schedule too, or nothing updates the "
        "pull requests a Dependabot merge leaves behind"
    )


GH_STUB = r"""#!/bin/bash
# Pull request 11 is Dependabot's and 12 a person's, both mergeable and both
# two commits behind master. --jq is not applied: each answer is already what
# that filter would extract. Anything else is refused, so a call this stub was
# not written for fails loudly instead of answering empty
set -uo pipefail
printf '%s\n' "$*" >> "$GH_CALL_LOG"
case "$1 ${2:-}" in
  "pr list")
    echo '[{"number":11,"isDraft":false},{"number":12,"isDraft":false}]' ;;
  "api repos/example/repository/commits/master")
    echo 'master-sha' ;;
  "api repos/example/repository/pulls/11")
    echo '{"user":{"login":"dependabot[bot]"},"mergeable":true,"head":{"sha":"dependabot-sha"},"node_id":"DEPENDABOT_NODE"}' ;;
  "api repos/example/repository/pulls/12")
    echo '{"user":{"login":"tigerblue77"},"mergeable":true,"head":{"sha":"person-sha"},"node_id":"PERSON_NODE"}' ;;
  "api repos/example/repository/compare/"*)
    echo '2' ;;
  "api graphql")
    echo '{"data":{"updatePullRequestBranch":{"pullRequest":{"headRefOid":"rebased-sha"}}}}' ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 64 ;;
esac
"""


def test_the_branch_updater_leaves_dependabot_pull_requests_to_dependabot(tmp_path):
    """A rebase pushed by anyone but Dependabot replaces the commit Dependabot
    signed, and `dependabot/fetch-metadata` in `dependabot-auto-merge.yml`
    refuses the result, so an update whose merge was not queued yet never gets
    queued -- which is not a hypothesis: an updater without this filter left
    every open Dependabot pull request it reached unmerged.

    The step runs here as written, over two pull requests equally far behind
    master, against a stubbed `gh` that records its calls: the one Dependabot
    opened must see no update at all, and the other must still be rebased, so
    that a filter skipping everything fails this too.
    """
    if shutil.which("jq") is None:
        pytest.skip("the step reads every answer with jq, which is not installed")
    steps = yaml.safe_load(UPDATER.read_text())["jobs"]["update-pull-request-branches"]["steps"]
    [step] = [s for s in steps if s.get("name", "").startswith("Rebase every conflict-free")]
    script = tmp_path / "step.sh"
    script.write_text(step["run"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    calls = tmp_path / "gh_calls.log"
    calls.touch()

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_CALL_LOG": str(calls),
        "GH_TOKEN": "unused",
        "UPDATING_AS": "the GitHub App",
        "REPOSITORY": "example/repository",
        "FALL_BACK_TO_MERGE": "true",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, (
        f"the updater's step failed against the stubbed API:\n{result.stdout}{result.stderr}"
    )
    logged = calls.read_text()
    assert "pullRequestId=DEPENDABOT_NODE" not in logged, (
        f"the updater pushed to Dependabot's pull request:\n{result.stdout}"
    )
    assert "pullRequestId=PERSON_NODE" in logged, (
        f"the updater skipped a person's pull request as well:\n{result.stdout}"
    )
