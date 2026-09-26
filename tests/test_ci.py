"""What the build workflow publishes, and what it runs against what it published.

`.github/workflows/ci.yml` is what puts an image in front of users, so two
things about it are pinned here.

Which refs reach the registry at all. Only `master` and release tags do: a
branch or a pull request builds on all three architectures and pushes nothing,
and no tag is derived from the ref. Pushing branches made every one of them a
permanent Docker Hub tag, which deleting the branch did not remove.

What the two **Verify Published Image** jobs run, which are the last thing to
look at an image before **Publish latest** moves the tag onto it. That is not
the same question on every run: a merge has `test.yml` running the whole suite
against a build of the same tree in parallel, so the smoke tests are all that
is left to learn, while a no-cache rebuild is a `workflow_dispatch` of `ci.yml`
alone and `test.yml` never sees it at all.

Like `test_ruleset.py` these read a file and start nothing, so they are part of
the small half of the suite that needs no docker daemon.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


MASTER_ONLY = "github.ref == 'refs/heads/master'"
PUBLISHING_REFS_ONLY = (
    "(github.ref == 'refs/heads/master' || startsWith(github.ref, 'refs/tags/'))"
    " && github.actor != 'dependabot[bot]'"
)


def workflow():
    return yaml.safe_load(CI.read_text())


def verify_jobs():
    """The two jobs that pull the published image back and test it."""
    return [job for key, job in workflow()["jobs"].items() if key.startswith("verify_published")]


def steps_using(action):
    """Every step, in any job, that runs `action`, with the job it sits in."""
    return [
        (job, step)
        for job in workflow()["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith(action + "@")
    ]


def test_a_branch_or_a_pull_request_publishes_nothing():
    """The only build that pushes is master's. Every other build step has to
    carry a literal `push: false`, not an expression: the expression this
    replaced excluded pull requests and Dependabot and so pushed every other
    branch, one Docker Hub tag per branch that nothing ever deleted.
    """
    builds = steps_using("docker/build-push-action")
    assert builds, "ci.yml has no docker/build-push-action step left"
    for _job, step in builds:
        if step.get("if") == MASTER_ONLY:
            continue
        assert step["with"].get("push") is False, (
            f"{step['name']!r} runs on {step.get('if')!r} and pushes "
            f"{step['with'].get('push')!r}: only master's build may publish"
        )


def test_no_published_tag_is_named_after_the_ref():
    """`type=ref` names a tag after the branch or pull request it was built
    from. Master's build pushes docker_meta's tags, so a ref tag would put a
    `:master` next to `latest`, and a release would pick up a branch-named
    alias it never asked for.
    """
    metas = steps_using("docker/metadata-action")
    assert len(metas) == 1, f"expected one docker/metadata-action step, got {len(metas)}"
    _, meta = metas[0]
    rules = [line.strip() for line in meta["with"]["tags"].splitlines() if line.strip()]
    assert not [rule for rule in rules if rule.startswith("type=ref")], (
        f"docker_meta derives a tag from the ref: {rules}"
    )
    assert "type=sha" in rules, "master's build needs its sha- tag to be promoted and released"


def test_only_the_refs_that_publish_log_in_to_the_registry():
    """A run that cannot publish should not hold the credentials either. The
    build job logs in for master and release tags only; any other job that
    logs in must itself be master-only.
    """
    logins = steps_using("docker/login-action")
    assert logins, "ci.yml no longer logs in anywhere; how does it publish?"
    for job, step in logins:
        if job.get("if") == MASTER_ONLY:
            continue
        assert step.get("if") == PUBLISHING_REFS_ONLY, (
            f"{job['name']!r} logs in on {step.get('if')!r}; "
            f"expected {PUBLISHING_REFS_ONLY!r} or a master-only job"
        )


def test_a_no_cache_rebuild_is_verified_by_the_whole_suite():
    """A rebuild is a `workflow_dispatch` of this workflow, and `test.yml` is
    started by a push to `master`, a pull request or a dispatch of its own --
    never by that one. So on a rebuild these two jobs are the only thing that
    looks at the image before the tag moves onto it, and the package set they
    would be smoke-testing is the one thing about that image the suite has
    never seen.
    """
    jobs = verify_jobs()
    assert len(jobs) == 2, f"expected two verify jobs, got {len(jobs)}"
    for job in jobs:
        named = [s for s in job["steps"] if s["name"].startswith("Run the tests")]
        assert named, (
            f"{job['name']} has no step named 'Run the tests...'; steps are "
            f"{[s['name'] for s in job['steps']]}"
        )
        step = named[0]
        assert step["env"]["NO_CACHE"] == "${{ inputs.no-cache || false }}"
        assert "pytest -m smoke" in step["run"], "a merge must still only smoke-test"
        assert "pytest" in step["run"].replace("pytest -m smoke", ""), (
            f"{job['name']} smoke-tests a no-cache rebuild, which is the one "
            f"image no run of the whole suite ever sees"
        )
