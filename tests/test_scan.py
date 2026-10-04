# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""What the daily image scan does with what it finds.

`.github/workflows/scan.yml` is the only thing in the tree that writes to the
issue tracker and the only one that starts another workflow. Both happen on a
clock, against an image this repository published rather than anything a pull
request builds, so no other gate exercises them: the first time a mistake in
that file is noticed is the morning it files the wrong issue -- or the morning
it files one and then never takes it back.

That second case is the one these tests are mostly about. The job used to
dispatch a rebuild and return, which left the remedy automatic and the
verification manual, and nothing in the tree could report back: `ci.yml` has no
`issues` permission, no trigger here fires on another workflow finishing, and
the close step reads the count from the scan its own run already did. So an
issue could only be closed by a *later* run, and the only thing that starts one
is the next day's cron. Issue wader/postfix-relay#381 spent a day open over an
image the rebuild had already fixed. Each assertion below names the step that
keeps that from happening again.

Like `test_ruleset.py` these read files and start nothing, so they are part of
the small half of the suite that needs no docker daemon.
"""

import os
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN = REPO_ROOT / ".github" / "workflows" / "scan.yml"


def scan_steps():
    """The one job's steps, keyed by the `name:` each is written under."""
    workflow = yaml.safe_load(SCAN.read_text())
    steps = workflow["jobs"]["trivy"]["steps"]
    return {step["name"]: step for step in steps}


def test_the_rebuild_is_waited_for_rather_than_only_dispatched():
    steps = scan_steps()
    rebuild = steps["Trigger a no-cache rebuild and wait for it"]
    assert rebuild.get("id") == "rebuild"
    assert "gh workflow run ci.yml" in rebuild["run"]
    assert "gh run view" in rebuild["run"], (
        "the step dispatches a rebuild but never looks at the run it started, "
        "so nothing in this workflow can tell whether the remedy worked"
    )
    assert "conclusion=" in rebuild["run"]


def test_a_finished_rebuild_is_re_scanned():
    steps = scan_steps()
    rescan = steps["Re-scan what the rebuild published"]
    assert rescan.get("id") == "rescan"
    assert rescan["if"] == "steps.rebuild.outputs.conclusion == 'success'"
    assert "--ignore-unfixed" in rescan["run"]
    assert "--severity HIGH,CRITICAL" in rescan["run"], (
        "the re-scan has to ask the first scan's question; a wider or narrower "
        "one cannot answer whether the finding that opened the issue is gone"
    )


def test_the_re_scan_compares_digests_before_believing_its_count():
    """ci.yml's "Publish latest" stands down without failing when master's head
    moved under it, so a ci run can conclude success having left `latest`
    exactly where it was. The count then comes back unchanged, and calling
    that a rebuild that did not work would describe a rebuild that never
    reached the tag.
    """
    steps = scan_steps()
    assert "digest=" in steps["Scan the published image"]["run"]
    rescan = steps["Re-scan what the rebuild published"]
    assert rescan["env"]["BEFORE"] == "${{ steps.scan.outputs.digest }}"
    assert "RepoDigests" in rescan["run"]


def test_a_clean_re_scan_closes_the_issue_and_spares_the_run():
    steps = scan_steps()
    close = steps["Close the finding issue"]["if"]
    fail = steps["Fail the run"]["if"]
    assert "steps.rescan.outputs.verdict == 'clean'" in close, (
        "only the first scan can close the issue, so a run that found "
        "something, fixed it and watched the fix land still leaves it open"
    )
    assert "steps.rescan.outputs.verdict != 'clean'" in fail, (
        "the run goes red even when its own rebuild cleared the finding, "
        "which is an email nobody has anything to act on"
    )
    assert "verdict=clean" in steps["Re-scan what the rebuild published"]["run"]


def test_no_condition_reads_a_skipped_step_as_a_number():
    """A step that did not run contributes no outputs, so a reference to one is
    Null -- and github coerces a mismatched comparison to numbers, where Null
    is 0 and so is the string "0", and so is the empty string. Comparing an
    output that may not be there against a numeric literal is therefore true
    exactly when the step did not run, which is the inverse of what such a
    condition is ever written to mean. A word is safe because it parses as NaN
    and NaN equals nothing, itself included.
    """
    workflow = yaml.safe_load(SCAN.read_text())
    steps = workflow["jobs"]["trivy"]["steps"]
    skippable = {s["id"] for s in steps if "if" in s and "id" in s}

    numeric = []
    for step in steps:
        for ref, literal in re.findall(
            r"steps\.(\w+)\.outputs\.\w+\s*[=!]=\s*'([^']*)'", step.get("if", "")
        ):
            if ref not in skippable:
                continue
            try:
                float(literal)
            except ValueError:
                continue
            numeric.append(f"{step['name']}: compares {ref}'s output against '{literal}'")
        if "''" in step.get("if", ""):
            numeric.append(f"{step['name']}: compares against the empty string, which coerces to 0")

    assert not numeric, (
        "these conditions are true exactly when the step they read was "
        "skipped: " + "; ".join(numeric)
    )


def test_every_step_that_reaches_github_says_which_repository():
    """Nothing here is checked out, so `gh` has no git remote to fall back on
    and exits "failed to run git: fatal: not a git repository" before reaching
    the API. `GH_REPO` is what each of those steps has instead.
    """
    missing = [
        name
        for name, step in scan_steps().items()
        if "gh " in step.get("run", "") and "GH_REPO" not in step.get("env", {})
    ]
    assert not missing, f"steps calling gh without GH_REPO set: {missing}"


def test_the_attempt_budget_is_per_finding_and_not_per_issue():
    """The issue is matched on its title alone and held open until the scan is
    clean about everything, so a vulnerability arriving while it is open would
    otherwise inherit the budget the previous one had already spent -- and a
    brand-new one turning up on day three would reach the give-up branch with
    no rebuild ever attempted for it. The ids the attempts were spent on are
    what tell those apart.
    """
    steps = scan_steps()
    assert "ids=" in steps["Scan the published image"]["run"]
    assert "VulnerabilityID" in steps["Scan the published image"]["run"]

    issue = steps["Open or retry the finding issue"]
    assert issue["env"]["IDS"] == "${{ steps.scan.outputs.ids }}"
    assert "seen=" in issue["run"], (
        "the marker records only a count, so nothing says which finding the "
        "attempts were spent on and a new one inherits a spent budget"
    )
    assert "attempts=0" in issue["run"], (
        "nothing restarts the budget, so an id never retried for still lands "
        "in the give-up branch"
    )



def test_a_recorded_attempt_is_read_back_before_it_is_spent():
    """The attempt counter is the only state this job keeps, and it keeps it in
    an issue body other things write to -- wader/postfix-relay#381 acquired an
    assignee nothing in the workflow sets, 87 seconds after the workflow
    created it. A marker that goes missing reads back as attempt 0, so the
    budget restarts and the cap never engages: the same silent shape as the sed
    no-op of wader/postfix-relay#379, which cost a day of retries before anyone
    noticed it was not counting.
    """
    issue = scan_steps()["Open or retry the finding issue"]["run"]
    assert "confirmStamp" in issue, (
        "the marker is written and never read back, so losing it is silent"
    )
    assert issue.count("confirmStamp \"$next\"") == 2, (
        "both branches that bump the counter must confirm it landed"
    )
    after = issue.split("confirmStamp()", 1)[1]
    assert "exit 1" in after, (
        "a run that cannot record an attempt must not go on to spend one"
    )


def test_an_attempt_the_rebuild_never_used_is_given_back():
    """An attempt is a rebuild that got its chance and did not clear the
    finding. `ci.yml`'s concurrency group puts a dispatch on `master` in the
    same group as the push run for that commit and cancels it when a third
    arrives, so a rebuild can be cancelled before it builds anything -- and one
    that never appeared never built either. Neither is what the three attempts
    are slack for, which is a rebuild that ran and failed.
    """
    steps = scan_steps()
    rebuild = steps["Trigger a no-cache rebuild and wait for it"]["run"]
    assert rebuild.count("refund=yes") == 2, (
        "exactly the two ways out where the rebuild never ran -- cancelled, "
        "and never appeared -- give the attempt back"
    )
    for kept in ("timeout", "unreadable"):
        assert f'conclusion={kept}" >> "${{GITHUB_OUTPUT}}"\n' in rebuild + "\n", (
            f"'{kept}' must stay a spent attempt: the run may still be building"
        )

    refund = steps["Give back an attempt the rebuild never used"]
    assert refund["if"] == "steps.rebuild.outputs.refund == 'yes'"
    assert refund["env"]["RESTORE"] == "${{ steps.issue.outputs.restore }}", (
        "restoring the value read beats decrementing the value found, in a "
        "body other things edit"
    )
    assert "gh issue comment" in refund["run"], (
        "the step above already said an attempt was dispatched; walking that "
        "back in silence leaves the issue claiming a count it no longer has"
    )


def test_the_scan_job_allows_the_longest_wait_on_another_workflow():
    """It is the only job that spends most of its time waiting for another
    workflow, so CLAUDE.md says its `timeout-minutes` is the longest of any
    job that does. That is the kind of claim a later job quietly overtakes,
    and the number underneath it is load-bearing: the wait has a bound of its
    own that has to stay well inside this one, because a job killed by
    `timeout-minutes` is *cancelled* rather than failed and github's
    notification for a scheduled run fires on failure.

    The branch updater's job is longer and is left out of the comparison: it
    sleeps for a quiet period of its own choosing and waits on no workflow, so
    its limit follows that sleep and says nothing about this wait's bound.
    """
    workflows = sorted((SCAN.parent).glob("*.yml"))
    timeouts = {}
    for path in workflows:
        for key, job in yaml.safe_load(path.read_text())["jobs"].items():
            timeouts[f"{path.name}:{job.get('name', key)}"] = job.get("timeout-minutes")

    missing = [name for name, value in timeouts.items() if value is None]
    assert not missing, f"jobs with no timeout-minutes, which default to six hours: {missing}"

    scan = timeouts["scan.yml:Image Scan"]
    longer = {
        n: v for n, v in timeouts.items()
        if v >= scan and n != "scan.yml:Image Scan"
        and not n.startswith("auto_update_pull_request_branches.yml:")
    }
    assert not longer, (
        f"CLAUDE.md says the scan job's timeout is the longest of the jobs "
        f"that wait on another workflow; these reach or pass it: {longer}"
    )


def test_the_documented_marker_is_the_one_the_workflow_writes():
    """The marker is described in CLAUDE.md where the pacing is explained and
    again where the per-finding budget is, and the second description is the
    one that grew a `seen=` list. A reader who stops at the first gets a shape
    the workflow has not written since, which is how the two came apart in the
    first place: whoever adds a field to the marker edits the paragraph they
    are working in and not the other one.
    """
    candidates = re.findall(
        r"<!-- rebuild-attempts=.*?-->",
        scan_steps()["Open or retry the finding issue"]["run"],
    )
    # One of those is the search side of stampAttempts' sed, which carries a
    # character class rather than a value and deliberately matches a marker
    # with no ids in it -- that is what migrates an older one.
    written = [marker for marker in candidates if "[0-9]" not in marker]
    assert written, "the create path no longer writes a marker at all"
    stale_writes = [marker for marker in written if "seen=" not in marker]
    assert not stale_writes, f"the workflow still writes a marker with no ids: {stale_writes}"

    documented = re.findall(
        r"<!-- rebuild-attempts=.*?-->", (REPO_ROOT / "CLAUDE.md").read_text()
    )
    assert documented, "CLAUDE.md no longer spells the marker out anywhere"
    stale = [marker for marker in documented if "seen=" not in marker]
    assert not stale, (
        f"CLAUDE.md spells the marker without the ids the workflow puts in it: {stale}"
    )


def test_every_workflow_states_what_its_token_may_do():
    """Without a top-level `permissions:`, a workflow's token gets whatever
    the repository's default is, which no diff shows and anyone with admin
    rights can change. `ci.yml` runs with the registry credentials in its
    environment, and until issue #18 it and two other workflows stated nothing.
    A job may widen what the workflow grants, as the two in `ci.yml` that push
    the GHCR mirror do; the workflow still has to say what everything else
    gets.
    """
    workflows = sorted((SCAN.parent).glob("*.yml"))
    silent = [path.name for path in workflows
              if "permissions" not in yaml.safe_load(path.read_text())]

    assert workflows
    assert not silent, f"workflows leaving their token to the repository default: {silent}"


# Checkouts that keep the job token for the steps after them, as
# {(file, job, step): why}, one entry per step: a job with two checkouts needs
# two entries, and the one that is not listed is still refused. The step is its
# `name:`, or "step N" when it has none. Empty, and meant to stay so: a checkout
# belongs here only when a later step of the same job runs `git push`, or a
# `git fetch` through the remote, and has nothing else to authenticate with. The
# reason says which step, so that the next person to touch that job knows what
# removing the entry would break.
PERSISTED_CHECKOUTS = {}

# Directories no action or workflow lives in, and a walk of the tree should not
# enter: a virtualenv or a vendored package may hold hundreds of action.yml.
SKIPPED_DIRECTORIES = {".git", ".venv", "venv", "node_modules"}


def checkout_steps(root=REPO_ROOT):
    """Every `actions/checkout` step, as ((file, job, step), step).

    The workflows are `.github/workflows/*.yml` and `*.yaml` -- github reads
    both -- and the composite actions are every `action.yml` and `action.yaml`
    under the root, wherever they sit, since a local action can be used from
    anywhere (`uses: ./path`). A composite action has no job, so its place in the
    key is "(composite action)". The name of the action is matched without regard
    to case, because github resolves `Actions/Checkout` to the same action.
    """
    found = []

    def collect(file, job, steps):
        seen = set()
        for number, step in enumerate(steps or [], start=1):
            label = step.get("name") or f"step {number}"
            if label in seen:
                label = f"{label} (step {number})"
            seen.add(label)
            if str(step.get("uses", "")).lower().startswith("actions/checkout@"):
                found.append(((file, job, label), step))

    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        for job, body in (yaml.safe_load(path.read_text()) or {}).get("jobs", {}).items():
            collect(path.name, job, body.get("steps"))
    for directory, directories, files in os.walk(root):
        directories[:] = sorted(d for d in directories if d not in SKIPPED_DIRECTORIES)
        for name in sorted(files):
            if name in ("action.yml", "action.yaml"):
                path = Path(directory, name)
                action = yaml.safe_load(path.read_text()) or {}
                collect(path.relative_to(root).as_posix(), "(composite action)",
                        (action.get("runs") or {}).get("steps"))
    return found


def drops_the_token(step):
    """Whether the step sets `persist-credentials` to false: the boolean, or
    the string github reads as one. An expression is not accepted, since it can
    turn into anything."""
    value = (step.get("with") or {}).get("persist-credentials")
    return value is False or (isinstance(value, str) and value.strip().lower() == "false")


def checkout_problems(root, allowed):
    """What is wrong with the checkouts under `root`, given an allow-list."""
    kept = {where for where, step in checkout_steps(root) if not drops_the_token(step)}
    problems = [f"{where} leaves the job token to the steps after it" for where in sorted(kept - set(allowed))]
    problems += [f"{where} is on the allow-list but no longer keeps the token" for where in sorted(set(allowed) - kept)]
    problems += [f"{where} is on the allow-list with no reason" for where, why in sorted(allowed.items())
                 if not (isinstance(why, str) and why.strip())]
    return problems


def test_every_checkout_drops_the_job_token_or_says_which_step_needs_it():
    """`actions/checkout` sets up a credential for the steps after it unless
    told not to: it writes the job's token to a credentials file in the
    runner's temp directory, outside the workspace, points `.git/config` at that
    file with `includeIf` entries, and removes both when the job ends. Until
    then any later step of the job inherits it, through git or through the
    file. With `persist-credentials: false` the action removes that credential
    right after its own fetch (the "Removing auth" group of its log), so no later
    step inherits it. That is all it does: a step that names
    `secrets.GITHUB_TOKEN`, a registry login for one, still has the token.
    zizmor's `artipacked` audit flags the default however the action stores it.
    Nothing here needs the credential the checkout sets up: no
    job with one pushes or fetches through git, the registry logins are the
    actions' own, the `gh` steps carry their own `GH_TOKEN`, and the one
    `git ls-remote`, in `ci.yml`'s promote job, runs in a job with no checkout at
    all. So each checkout sets `persist-credentials: false`, and the exceptions
    are PERSISTED_CHECKOUTS above, one step each, with the reason written next to
    it.
    """
    assert checkout_steps(REPO_ROOT), "no actions/checkout step found at all; the walk is broken"
    assert not checkout_problems(REPO_ROOT, PERSISTED_CHECKOUTS)


def test_the_checkout_rule_sees_every_place_a_checkout_can_be(tmp_path):
    """The rule above is only as good as its walk, so each way a checkout can
    hide is planted in a throwaway tree and has to be found: a workflow with the
    other yaml extension, an action name in capitals, composite actions at the
    root and deep in the tree, the same job with one checkout that is fine and
    one that is not, a flag that is an expression, and an allow-list entry with
    no reason or for a step that does not keep the token. What is fine -- the
    boolean, the string, and a directory the walk skips -- is not flagged.
    """
    def write(path, text):
        path = tmp_path / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    steps = "    steps:\n      - name: Checkout\n        uses: {uses}\n{with_}"
    flagged = "        with:\n          persist-credentials: {value}\n"
    workflow = "on: push\njobs:\n  job:\n    runs-on: ubuntu-latest\n" + steps
    write(".github/workflows/plain.yml", workflow.format(uses="actions/checkout@v7", with_=flagged.format(value="false")))
    write(".github/workflows/string.yml", workflow.format(uses="actions/checkout@v7", with_=flagged.format(value="'false'")))
    write(".github/workflows/yaml-extension.yaml", workflow.format(uses="actions/checkout@v7", with_=""))
    write(".github/workflows/capitals.yml", workflow.format(uses="Actions/Checkout@v7", with_=""))
    write(".github/workflows/expression.yml",
          workflow.format(uses="actions/checkout@v7", with_=flagged.format(value="${{ inputs.persist }}")))
    write(".github/workflows/two.yml",
          "on: push\njobs:\n  job:\n    runs-on: ubuntu-latest\n    steps:\n"
          "      - name: Fine\n        uses: actions/checkout@v7\n        with:\n          persist-credentials: false\n"
          "      - name: Not fine\n        uses: actions/checkout@v7\n")
    composite = "name: x\ndescription: x\nruns:\n  using: composite\n  steps:\n    - uses: actions/checkout@v7\n      shell: bash\n"
    write("action.yml", composite)
    write("deep/er/action.yaml", composite)
    write("node_modules/package/action.yml", composite)

    expected = {
        ("yaml-extension.yaml", "job", "Checkout"),
        ("capitals.yml", "job", "Checkout"),
        ("expression.yml", "job", "Checkout"),
        ("two.yml", "job", "Not fine"),
        ("action.yml", "(composite action)", "step 1"),
        ("deep/er/action.yaml", "(composite action)", "step 1"),
    }
    seen = {where for where, step in checkout_steps(tmp_path)}
    assert expected < seen and not any("node_modules" in w[0] for w in seen), sorted(seen)
    problems = checkout_problems(tmp_path, {})
    assert len(problems) == len(expected), problems
    for where in expected:
        assert any(str(where) in problem for problem in problems), (where, problems)

    allowed = {where: "a later step runs git push" for where in expected}
    assert checkout_problems(tmp_path, allowed) == []
    assert checkout_problems(tmp_path, {**allowed, ("two.yml", "job", "Not fine"): "  "}) == [
        "('two.yml', 'job', 'Not fine') is on the allow-list with no reason"
    ]
    assert checkout_problems(tmp_path, {**allowed, ("plain.yml", "job", "Checkout"): "why"}) == [
        "('plain.yml', 'job', 'Checkout') is on the allow-list but no longer keeps the token"
    ]
    assert checkout_problems(tmp_path, {k: v for k, v in allowed.items() if k != ("two.yml", "job", "Not fine")}) == [
        "('two.yml', 'job', 'Not fine') leaves the job token to the steps after it"
    ]
