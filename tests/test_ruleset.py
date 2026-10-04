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
up to date. And the auto-merge is only as safe as what reaches it: the update
entries of `.github/dependabot.yml` each set a cooldown of at least seven days,
bar the one dependency, the Debian base image, that is deliberately excluded.

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
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
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


def dependabot_updates():
    """The `updates` entries of `.github/dependabot.yml`, keyed by what makes
    each one distinct: its ecosystem and the directory it reads."""
    updates = yaml.safe_load(DEPENDABOT.read_text())["updates"]
    keyed = {(u["package-ecosystem"], u["directory"]): u for u in updates}
    assert len(keyed) == len(updates), (
        "two update entries share an ecosystem and a directory; Dependabot "
        "refuses the file, and this test could not tell them apart"
    )
    return keyed


# The Dockerfile's base image, the one entry whose dependency is excluded from
# the cooldown: it is the official Debian image, a new tag is how a security fix
# reaches the base the image is built on, and the Dockerfile pulls the packages'
# own fixes at build time anyway. Its comment in dependabot.yml says the same.
BASE_IMAGE_UPDATE = ("docker", "/")
BASE_IMAGE_DEPENDENCY = "debian"
# Dependabot waits three days after a release whenever an entry has no
# `cooldown` block, and whenever a block does not say `default-days`. Seven is
# what this repository sets instead, and what zizmor's dependabot-cooldown audit
# asks for unless it is told otherwise.
MINIMUM_COOLDOWN_DAYS = 7
# The ecosystems whose cooldown takes a number of days per semver level; the
# others take `default-days` alone.
SEMVER_ECOSYSTEMS = {"pip"}
SEMVER_DAYS = ("semver-major-days", "semver-minor-days", "semver-patch-days")


def test_every_dependabot_update_sets_a_cooldown_and_only_the_base_image_excludes_one():
    """The auto-merge merges a semver minor or patch bump by itself once the
    checks pass. Dependabot already waits three days after a release before it
    proposes a version update, with no `cooldown` at all; an entry without the
    block is therefore not exempt, it gets that default, and a missing block
    cannot be told from a forgotten one. So every entry sets `default-days`,
    to at least seven, and a cooldown applies to version updates only: a
    security update is never delayed.

    The base image of the Dockerfile is the one dependency that goes without:
    its entry excludes `debian` from the cooldown, so that a new tag is
    proposed at once. Both halves are pinned, so that a new entry cannot be
    added without a cooldown, and the exclusion cannot spread to the entries
    that are auto-merged by copying the base image's.
    """
    updates = dependabot_updates()
    for key, u in updates.items():
        cooldown = u.get("cooldown")
        assert cooldown, (
            f"the update entry {key} has no cooldown block, so it waits "
            f"Dependabot's default of three days; set `default-days` to at "
            f"least {MINIMUM_COOLDOWN_DAYS}"
        )
        days = cooldown.get("default-days")
        assert isinstance(days, int) and days >= MINIMUM_COOLDOWN_DAYS, (
            f"the cooldown of {key} has a `default-days` of {days!r}, under "
            f"the {MINIMUM_COOLDOWN_DAYS} days this repository sets"
        )
    excluding = {key: u["cooldown"]["exclude"] for key, u in updates.items() if "exclude" in u["cooldown"]}
    assert excluding == {BASE_IMAGE_UPDATE: [BASE_IMAGE_DEPENDENCY]}, (
        f"cooldown exclusions are {excluding}; expected only the base image "
        f"{BASE_IMAGE_UPDATE} excluding {BASE_IMAGE_DEPENDENCY!r}. An excluded "
        f"dependency is updated the day it is released, so each one is a "
        f"decision to argue in dependabot.yml and in this test"
    )
    assert all("include" not in u["cooldown"] for u in updates.values()), (
        "an `include` list narrows a cooldown to the dependencies it names, "
        "which leaves every other one on Dependabot's three days"
    )


def test_dependabot_cooldowns_only_use_keys_their_ecosystem_takes():
    """`semver-major-days`, `-minor-days` and `-patch-days` exist for the
    semver ecosystems only (here pip); github-actions and docker take
    `default-days`, and `include` and `exclude`, alone. No workflow validates
    the file: Dependabot's own check on a pull request that touches it is not
    a required one, and what Dependabot reports once the file is on master
    shows only on the repository's Insights > Dependency graph > Dependabot
    page, so what can be checked from the file is checked here. pip's major
    releases wait at least as long as its minor and patch ones, which is the
    reason it has the per-level keys at all, and none waits less than the
    minimum.
    """
    for (ecosystem, directory), u in dependabot_updates().items():
        cooldown = u.get("cooldown", {})
        takes = {"default-days", "include", "exclude"}
        if ecosystem in SEMVER_ECOSYSTEMS:
            takes |= set(SEMVER_DAYS)
        stray = set(cooldown) - takes
        assert not stray, (
            f"the {ecosystem} entry on {directory} gives its cooldown {sorted(stray)}, "
            f"which that ecosystem does not take; it takes {sorted(takes)}"
        )
        if ecosystem in SEMVER_ECOSYSTEMS:
            major, minor, patch = (cooldown.get(k) for k in SEMVER_DAYS)
            assert all(isinstance(d, int) for d in (major, minor, patch)), (
                f"the {ecosystem} cooldown sets {SEMVER_DAYS} to "
                f"{(major, minor, patch)}; every level needs a number of days"
            )
            assert major >= minor and min(minor, patch) >= MINIMUM_COOLDOWN_DAYS, (
                f"the {ecosystem} cooldown waits {major}, {minor} and {patch} "
                f"days for a major, minor and patch release; a major release "
                f"should wait at least as long as a minor one, and none may wait "
                f"under {MINIMUM_COOLDOWN_DAYS}"
            )


def test_branches_are_not_required_to_be_up_to_date():
    """"Require branches to be up to date before merging" stays off. With it
    on, each merge leaves every other open pull request *blocked* until its
    branch is updated, and what updates them is best effort: the branch
    updater leaves alone a pull request that conflicts, one from a fork, a
    draft and Dependabot's own, and it only hears of a Dependabot merge on the
    next push to master made any other way, a push made with the
    `GITHUB_TOKEN` starting no workflow. Each of those would turn from behind
    into blocked. What the
    setting bought, a pull request tested against the master it lands on, is
    what the updater gives wherever it can reach, and is paid for after the
    merge everywhere else: **Verify Published Image** runs on every push to
    `master`, and `latest` does not move until it passes.
    """
    checks = [r for r in ruleset()["rules"] if r["type"] == "required_status_checks"]
    assert checks[0]["parameters"]["strict_required_status_checks_policy"] is False, (
        "requiring branches to be up to date blocks every pull request the "
        "branch updater cannot reach, and after a Dependabot merge all of them "
        "until the next push to master made any other way"
    )


def test_the_branch_updater_waits_for_master_to_stay_quiet():
    """A pass after every merge force-pushes every pull request it updates,
    and each force-push is a notification, so a series of merges used to cost
    one round of both per merge. The updater now starts a run on every push to
    master, and the run sleeps for a quiet period before it touches anything:
    the next push cancels it, so only the run that follows the last push of a
    series ever wakes up.

    That holds only with all of its parts, and each fails silently without the
    others. A `schedule:` starts a pass that no push cancels, and is what this
    replaced. A concurrency group that queues instead of cancelling leaves the
    sleeper to wake up behind the run that was meant to replace it. The wait
    has to come before the step that mints the App's installation token, which
    lives an hour. The job's timeout has to outlast the wait, or the pass
    never happens. And the wait is for a push only: a run started by hand is
    there to act now.

    A merge made in the `GITHUB_TOKEN`'s name -- every one the Dependabot
    auto-merge makes -- starts no workflow, so it starts no wait either; what
    it leaves behind is brought level after the next push made any other way,
    and nothing is blocked meanwhile, since branches are not required to be up
    to date.
    """
    workflow = yaml.safe_load(UPDATER.read_text())
    triggers = workflow[True]
    assert triggers["push"]["branches"] == ["master"], (
        f"{UPDATER.name} has to start its wait on every push to master, got {triggers}"
    )
    assert "workflow_dispatch" in triggers, (
        f"{UPDATER.name} has to be startable by hand, without the wait"
    )
    assert "schedule" not in triggers, (
        f"{UPDATER.name} has a schedule: a scheduled run is a pass no push "
        "cancels, which is the one pass per merge the wait exists to remove"
    )
    assert workflow["concurrency"]["cancel-in-progress"] is True, (
        "the next push has to cancel a run that is still asleep, or the wait "
        "is not a wait for master to stay quiet"
    )

    job = workflow["jobs"]["update-pull-request-branches"]
    quiet_period = int(job["env"]["QUIET_PERIOD_MINUTES"])
    assert quiet_period > 0
    assert job["timeout-minutes"] > quiet_period, (
        f"the job times out after {job['timeout-minutes']} minutes, which is "
        f"not past the {quiet_period}-minute wait it starts with"
    )

    steps = job["steps"]
    wait = steps[0]
    assert wait["name"].startswith("Wait for master to stay quiet"), (
        f"the wait has to be the first step, before the token is minted, got {wait['name']!r}"
    )
    assert wait["if"] == "github.event_name == 'push'", (
        "the wait is for a push only: a run started by hand is there to act now"
    )
    assert "QUIET_PERIOD_MINUTES" in wait["run"] and "sleep" in wait["run"], (
        "the first step has to sleep for QUIET_PERIOD_MINUTES"
    )
    assert [s.get("id") for s in steps].index("app-token") > 0, (
        "the App token has to be minted after the wait, not before it"
    )


# What the workflow writes first in a comment that announces a conflict, and
# what a later pass searches for. Written here, not read from the workflow, so
# that changing it fails this module: a marker that moved would orphan every
# comment already posted, and the next pass would announce each conflict again
CONFLICT_MARKER = "<!-- auto-update-pull-request-branches: conflict -->"

GH_STUB = r"""#!/bin/bash
# Six pull requests, all mergeable except where said, and all two commits
# behind master. 11 is Dependabot's and 12 a person's, with no comment. 13
# conflicts and has never been announced, 14 conflicts and already carries the
# announcement, 15 is conflict-free again and still carries one, next to a
# person's own comment, and 16 conflicts but its comments cannot be read.
# --jq is not applied: each answer is already what that filter would extract.
# Anything else is refused, so a call this stub was not written for fails
# loudly instead of answering empty -- 11's comments included, which nothing
# may ask for
set -uo pipefail
printf '%s\n' "$*" >> "$GH_CALL_LOG"
case "$1 ${2:-}" in
  "pr list")
    echo '[{"number":11,"isDraft":false},{"number":12,"isDraft":false},{"number":13,"isDraft":false},{"number":14,"isDraft":false},{"number":15,"isDraft":false},{"number":16,"isDraft":false}]' ;;
  "api repos/example/repository/commits/master")
    echo 'master-sha' ;;
  "api repos/example/repository/pulls/11")
    echo '{"user":{"login":"dependabot[bot]"},"mergeable":true,"head":{"sha":"dependabot-sha"},"node_id":"DEPENDABOT_NODE"}' ;;
  "api repos/example/repository/pulls/12")
    echo '{"user":{"login":"tigerblue77"},"mergeable":true,"head":{"sha":"person-sha"},"node_id":"PERSON_NODE"}' ;;
  "api repos/example/repository/pulls/13")
    echo '{"user":{"login":"tigerblue77"},"mergeable":false,"head":{"sha":"conflict-sha"},"node_id":"CONFLICT_NODE"}' ;;
  "api repos/example/repository/pulls/14")
    echo '{"user":{"login":"tigerblue77"},"mergeable":false,"head":{"sha":"announced-sha"},"node_id":"ANNOUNCED_NODE"}' ;;
  "api repos/example/repository/pulls/15")
    echo '{"user":{"login":"tigerblue77"},"mergeable":true,"head":{"sha":"resolved-sha"},"node_id":"RESOLVED_NODE"}' ;;
  "api repos/example/repository/pulls/16")
    echo '{"user":{"login":"tigerblue77"},"mergeable":false,"head":{"sha":"unreadable-sha"},"node_id":"UNREADABLE_NODE"}' ;;
  "api repos/example/repository/compare/"*)
    echo '2' ;;
  "api graphql")
    echo '{"data":{"updatePullRequestBranch":{"pullRequest":{"headRefOid":"rebased-sha"}}}}' ;;
  "api repos/example/repository/issues/"*"/comments")
    number="${2#repos/example/repository/issues/}"
    number="${number%/comments}"
    case " $* " in
      *" --raw-field "*)
        echo '{}' ;;
      *)
        case "$number" in
          12|13)
            echo '[]' ;;
          14)
            echo '[{"id":1401,"body":"@MARKER@\n\nan earlier pass wrote this"}]' ;;
          15)
            echo '[{"id":1501,"body":"@MARKER@\n\nan earlier pass wrote this"},{"id":1502,"body":"a person wrote this"}]' ;;
          16)
            echo "the comments cannot be read" >&2
            exit 1 ;;
          *)
            echo "unexpected comments read: $*" >&2
            exit 64 ;;
        esac ;;
    esac ;;
  "api --method")
    ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 64 ;;
esac
""".replace("@MARKER@", CONFLICT_MARKER)


def run_updater_step(tmp_path):
    """Run the updater's step as written, over the pull requests GH_STUB
    describes, against a stubbed `gh` that records its calls.

    Returns the finished process, what `gh` was asked, and the step summary.
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
    summary = tmp_path / "summary"

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_CALL_LOG": str(calls),
        "GH_TOKEN": "unused",
        "UPDATING_AS": "the GitHub App",
        "REPOSITORY": "example/repository",
        "FALL_BACK_TO_MERGE": "true",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, (
        f"the updater's step failed against the stubbed API:\n{result.stdout}{result.stderr}"
    )
    return result, calls.read_text(), summary.read_text()


def test_the_branch_updater_leaves_dependabot_pull_requests_to_dependabot(tmp_path):
    """A rebase pushed by anyone but Dependabot replaces the commit Dependabot
    signed, and `dependabot/fetch-metadata` in `dependabot-auto-merge.yml`
    refuses the result, so an update whose merge was not queued yet never gets
    queued -- which is not a hypothesis: an updater without this filter left
    every open Dependabot pull request it reached unmerged.

    The step runs here as written, over pull requests equally far behind
    master, against a stubbed `gh` that records its calls: the one Dependabot
    opened must see no update at all, and the other must still be rebased, so
    that a filter skipping everything fails this too. Nor may the updater so
    much as read or write a comment there: an announcement on Dependabot's
    pull request is one more thing it would be pushing into a branch that is
    Dependabot's to keep.
    """
    result, logged, _ = run_updater_step(tmp_path)
    assert "pullRequestId=DEPENDABOT_NODE" not in logged, (
        f"the updater pushed to Dependabot's pull request:\n{result.stdout}"
    )
    assert "issues/11/" not in logged, (
        f"the updater touched the comments of Dependabot's pull request:\n{logged}"
    )
    assert "pullRequestId=PERSON_NODE" in logged, (
        f"the updater skipped a person's pull request as well:\n{result.stdout}"
    )


def test_the_branch_updater_announces_a_conflict_once_and_forgets_it_when_it_is_over(tmp_path):
    """A pull request that conflicts is left to its author, and the comment is
    the only way the author hears of it: a line in a run log is read by nobody.
    The comment carries a marker, which is the whole of the bookkeeping. A
    pass writes one where there is none, and a pass that finds the marker
    already there writes nothing, or the author would be emailed again on every
    push to master for as long as the conflict lasts. A pass that finds the pull
    request conflict-free again deletes it, and only it, so that the next
    conflict is announced in turn and a person's own comment stays.

    A comment that cannot be read is a warning and no more. The pull requests
    behind it still have to be walked, and writing a second announcement on a
    pull request whose first one cannot be seen is exactly the duplicate the
    marker is there to prevent.

    The step runs here as written, against the stubbed `gh` of the test above,
    which also says what each pull request's comments hold.
    """
    result, logged, summary = run_updater_step(tmp_path)
    posts = [line for line in logged.splitlines() if "/comments --raw-field body=" in line]
    assert len(posts) == 1 and "issues/13/comments" in posts[0], (
        f"expected one announcement, on the conflicting pull request 13 alone:\n{logged}"
    )
    assert f"body={CONFLICT_MARKER}" in posts[0], (
        f"the announcement does not start with the marker a later pass searches for:\n{posts[0]}"
    )
    assert "issues/14/comments --raw-field" not in logged, (
        f"a conflict that was already announced was announced again:\n{logged}"
    )
    assert "issues/16/comments --raw-field" not in logged, (
        f"a conflict was announced on a pull request whose comments could not be read:\n{logged}"
    )
    assert "::warning::Pull request #16" in result.stdout, (
        f"comments that cannot be read went unreported:\n{result.stdout}"
    )
    deletions = [line for line in logged.splitlines() if "--method DELETE" in line]
    assert deletions == ["api --method DELETE repos/example/repository/issues/comments/1501"], (
        f"expected the marked comment of the resolved pull request 15 to be "
        f"deleted, and nothing else:\n{logged}"
    )
    assert summary.strip() == "Updated 2 pull request(s), announced 1 conflict(s).", (
        f"the step summary does not say what the pass did:\n{summary}"
    )
