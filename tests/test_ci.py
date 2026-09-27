# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""What the build workflow publishes, what it runs against what it published,
and the licence the published image states.

`.github/workflows/ci.yml` is what puts an image in front of users, so three
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

And the licence every published image states. `docker/metadata-action`'s
labels win over the `Dockerfile`'s `LABEL` lines, so the identifier on the
image is the one `ci.yml` writes, and it has to agree with the `Dockerfile`'s.

Every publication also reaches the GHCR mirror, and the two registries must
never disagree about what a tag names: the build pushes both in one push,
**Publish latest** moves `latest` on both, and a release copies each
registry's version tags from its own `sha-` tag.

Like `test_ruleset.py` these read a file, or run a step of it against a stubbed
`docker`, and start no container, so they are part of the small half of the
suite that needs no docker daemon.
"""

import os
import subprocess
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
    """`type=ref,event=branch` names a tag after the branch it was built
    from. Master's build pushes docker_meta's tags, so it put a `:master` next
    to `sha-<commit>`, and every branch build that reached the push step
    published its own name as a permanent tag.
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


def test_the_published_image_states_its_licence():
    """docker/metadata-action fills org.opencontainers.image.licenses from
    GitHub's detection of the repository's licence, and its labels win over the
    Dockerfile's LABEL lines. So the identifier a published image carries is
    the one written here, and it has to be the one the Dockerfile writes.
    """
    workflow = yaml.safe_load(CI.read_text())
    metas = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("docker/metadata-action@")
    ]
    assert len(metas) == 1, f"expected one docker/metadata-action step, got {len(metas)}"
    labels = [line.strip() for line in metas[0]["with"].get("labels", "").splitlines()]
    assert "org.opencontainers.image.licenses=AGPL-3.0-only" in labels, labels
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert 'LABEL org.opencontainers.image.licenses="AGPL-3.0-only"' in dockerfile


def job_step(job_key, name_start):
    job = workflow()["jobs"][job_key]
    steps = [s for s in job["steps"] if s.get("name", "").startswith(name_start)]
    assert len(steps) == 1, f"{job_key} has {len(steps)} steps named {name_start!r}..."
    return steps[0]


def test_every_publication_reaches_both_registries():
    """docker_meta names both images, so each tag the build pushes -- and the
    version tags a release copies -- exists on Docker Hub and on the mirror,
    under one digest. Docker Hub stays first: it is the name the verify jobs
    pull.
    """
    meta = job_step("docker", "Docker meta")
    images = [line.strip() for line in meta["with"]["images"].splitlines() if line.strip()]
    assert images == [
        "${{ steps.reponame.outputs.DOCKER_REPO }}",
        "${{ steps.reponame.outputs.GHCR_REPO }}",
    ], images


def test_the_mirror_name_is_the_docker_hub_name_under_the_owner_lowercased(tmp_path):
    """GHCR refuses capitals, and a repository owner may have them; the image
    name is the Docker Hub one, so the two registries publish the same name.
    """
    step = job_step("docker", "Helper for custom repo name")
    output = tmp_path / "output"
    env = {**os.environ, "DOCKER_REPO": "tigerblue77/postfix_smtp_relay",
           "OWNER": "TigerBlue77", "GITHUB_OUTPUT": str(output)}
    subprocess.run(["bash", "-c", step["run"]], env=env, check=True, timeout=30)
    assert output.read_text().splitlines() == [
        "DOCKER_REPO=tigerblue77/postfix_smtp_relay",
        "GHCR_REPO=ghcr.io/tigerblue77/postfix_smtp_relay",
    ]


def test_only_the_jobs_that_publish_may_write_packages():
    """The mirror is pushed with the job's own token, so `packages: write` is
    a publishing credential like the Docker Hub one: the build job and
    **Publish latest** carry it, next to nothing they do not need, and no other
    job does.
    """
    jobs = workflow()["jobs"]
    assert jobs["docker"]["permissions"] == {"contents": "read", "packages": "write"}
    assert jobs["promote"]["permissions"] == {"packages": "write"}
    for key, job in jobs.items():
        if key in ("docker", "promote"):
            continue
        assert job.get("permissions", {}).get("packages") != "write", (
            f"{job['name']!r} can write packages"
        )


def test_latest_moves_on_the_mirror_first_then_on_docker_hub():
    """If the mirror's write fails, neither `latest` has moved and the two
    still agree; the other order would leave Docker Hub ahead with nothing
    red to say so until the next merge.
    """
    run = job_step("promote", "Point latest")["run"]
    mirror = run.find('"${GHCR_REPO}:latest"')
    docker_hub = run.find('"${REPO}:latest"')
    assert mirror != -1 and docker_hub != -1, run
    assert mirror < docker_hub, "the mirror's latest has to be written first"


DOCKER_STUB = """#!/bin/bash
printf '%s\\n' "$*" >> "$DOCKER_CALL_LOG"
if [ "$1 $2 $3" = "buildx imagetools inspect" ] ; then
  case " $MISSING " in *" $4 "*) exit 1 ;; esac
  exit 0
fi
[ "$1 $2 $3" = "buildx imagetools create" ] && exit 0
echo "unexpected docker call: $*" >&2
exit 64
"""

RELEASE_TAGS = "\n".join([
    "hub/relay:2", "hub/relay:2.0", "hub/relay:2.0.0", "hub/relay:sha-abc1234",
    "ghcr.io/o/relay:2", "ghcr.io/o/relay:2.0", "ghcr.io/o/relay:2.0.0",
    "ghcr.io/o/relay:sha-abc1234",
])


def run_release(tmp_path, missing=""):
    step = job_step("docker", "Publish the release tags")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    calls = tmp_path / "calls"
    calls.touch()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "DOCKER_CALL_LOG": str(calls), "MISSING": missing,
           "TAGS": RELEASE_TAGS, "GITHUB_REF": "refs/tags/v2.0.0"}
    result = subprocess.run(["bash", "-c", step["run"]], env=env,
                            capture_output=True, text=True, timeout=30)
    creates = [line for line in calls.read_text().splitlines() if "imagetools create" in line]
    return result, creates


def test_a_release_copies_each_registry_from_its_own_sha_tag(tmp_path):
    """Run as written, against a stubbed `docker`: one copy per registry, each
    onto its own three version tags and from its own `sha-` tag, never across.
    """
    result, creates = run_release(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert creates == [
        "buildx imagetools create -t hub/relay:2 -t hub/relay:2.0 -t hub/relay:2.0.0 hub/relay:sha-abc1234",
        "buildx imagetools create -t ghcr.io/o/relay:2 -t ghcr.io/o/relay:2.0 -t ghcr.io/o/relay:2.0.0 ghcr.io/o/relay:sha-abc1234",
    ], creates


def test_a_release_the_mirror_never_received_writes_nothing(tmp_path):
    """A commit master built before the mirror existed has no `sha-` tag on
    GHCR. The release has to stop before either registry is written, rather
    than publish the version on Docker Hub alone.
    """
    result, creates = run_release(tmp_path, missing="ghcr.io/o/relay:sha-abc1234")
    assert result.returncode != 0, result.stdout
    assert creates == [], creates
