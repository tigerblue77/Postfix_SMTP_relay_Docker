"""The checks that gate a merge, against the jobs that report them.

`.github/rulesets/master.json` records the ruleset protecting master so the
gate can be checked rather than believed. These tests are what keep that record
true: a required check is matched by a job's display `name:`, so renaming a
job without editing the ruleset leaves a context that never reports, and a
context that never reports blocks every pull request until someone with admin
rights notices. The same goes for the merge method the Dependabot auto-merge
asks for, which the ruleset can refuse just as silently.

Unlike every other module here these tests read files and start nothing, so
they are the one part of the suite that needs no docker daemon.
"""

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RULESET = REPO_ROOT / ".github" / "rulesets" / "master.json"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
AUTO_MERGE = WORKFLOWS / "dependabot-auto-merge.yml"
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
