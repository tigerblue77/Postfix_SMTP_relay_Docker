# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""The sign-off gate, and the identity a session commits under.

CONTRIBUTING.md requires a Signed-off-by on every commit, and
.github/check_sign_off.sh is what refuses a pull request without one. These
tests build throwaway git repositories and run that script against them, so
what they pin is the decision itself: which commits pass, which are refused,
and that the refusal fails closed where the range cannot be trusted.

The other half is .claude/hooks/session-start.sh, which gives a session the
two identities the gate expects -- the tool as the author, the maintainer on
the trailer -- through a `git signoff` alias. The hook is run here against a
sandbox too, with the docker daemon and pytest stubbed out, and the commit its
alias makes is handed to the gate: the two files state the same addresses and
nothing else keeps them in step.

Like test_ruleset.py, test_ci.py and test_scan.py, nothing here starts a
container, so these tests need no docker daemon. They need git.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".github" / "check_sign_off.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sign_off.yml"
HOOK = REPO_ROOT / ".claude" / "hooks" / "session-start.sh"

AGENT = ("Claude", "noreply@anthropic.com")
MAINTAINER = ("Tigerblue77", "37409593+tigerblue77@users.noreply.github.com")
CONTRIBUTOR = ("Random J Developer", "random@developer.example.org")


def identity(person):
    return f"{person[0]} <{person[1]}>"


class Sandbox:
    """A git repository nobody's configuration reaches into.

    The global and system configs are switched off so that an alias, a
    commit hook or an identity on the machine running the tests cannot decide
    what a commit here looks like.
    """

    def __init__(self, path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        (path.parent / "gitconfig").touch()
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))},
            "GIT_CONFIG_GLOBAL": str(path.parent / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.git("init", "--quiet", "--initial-branch=master")
        self.base = self.commit("The base the pull request starts from", sign_off=CONTRIBUTOR)

    def git(self, *args, person=CONTRIBUTOR):
        env = {
            **self.env,
            "GIT_AUTHOR_NAME": person[0],
            "GIT_AUTHOR_EMAIL": person[1],
            "GIT_COMMITTER_NAME": person[0],
            "GIT_COMMITTER_EMAIL": person[1],
        }
        return subprocess.run(
            ["git", *args], cwd=self.path, env=env, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def commit(self, subject, author=CONTRIBUTOR, sign_off=None, co_author=None, message=()):
        args = ["commit", "--quiet", "--allow-empty", "--no-verify", "-m", subject]
        for paragraph in message:
            args += ["-m", paragraph]
        if sign_off:
            args += ["--trailer", f"Signed-off-by: {identity(sign_off)}"]
        if co_author:
            args += ["--trailer", f"Co-Authored-By: {identity(co_author)}"]
        self.git(*args, person=author)
        return self.git("rev-parse", "HEAD")

    def check(self, *args):
        return subprocess.run(
            [str(SCRIPT), *args], cwd=self.path, env=self.env,
            capture_output=True, text=True,
        )

    def check_branch(self):
        """The script as the workflow calls it: the base, then the head."""
        return self.check(self.base, self.git("rev-parse", "HEAD"))


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path / "repository")


def output(result):
    return result.stdout + result.stderr


def test_a_branch_whose_commits_are_all_signed_is_accepted(sandbox):
    sandbox.commit("The first change", sign_off=CONTRIBUTOR)
    sandbox.commit("The second change", sign_off=CONTRIBUTOR)
    result = sandbox.check_branch()
    assert result.returncode == 0, output(result)
    assert "All 2 commits" in output(result)


def test_a_single_unsigned_commit_fails_the_branch(sandbox):
    sandbox.commit("The one that remembered", sign_off=CONTRIBUTOR)
    sandbox.commit("The one that forgot")
    result = sandbox.check_branch()
    assert result.returncode == 1, output(result)
    assert "The one that forgot" in output(result)
    assert "1 of the 2 commits" in output(result)


def test_every_unsigned_commit_is_reported_and_not_only_the_first(sandbox):
    sandbox.commit("The first one that forgot")
    sandbox.commit("The second one that forgot")
    result = sandbox.check_branch()
    assert result.returncode == 1
    assert "The first one that forgot" in output(result)
    assert "The second one that forgot" in output(result)


def test_a_merge_commit_is_not_asked_for_a_sign_off(sandbox):
    """Merging the base in to resolve a conflict is the right thing to do,
    and git writes that commit itself with nothing to certify. The range is
    read from the base's new tip, the way a pull request event gives it."""
    sandbox.git("switch", "--quiet", "-c", "branch")
    sandbox.commit("The branch, signed as it should be", sign_off=CONTRIBUTOR)
    sandbox.git("switch", "--quiet", "master")
    sandbox.commit("Master moves on meanwhile", sign_off=CONTRIBUTOR)
    moved = sandbox.git("rev-parse", "HEAD")
    sandbox.git("switch", "--quiet", "branch")
    sandbox.git("merge", "--quiet", "--no-ff", "--no-edit", "master")
    result = sandbox.check(moved, sandbox.git("rev-parse", "HEAD"))
    assert result.returncode == 0, output(result)


def test_a_message_that_merely_quotes_the_rule_certifies_nothing(sandbox):
    """A commit explaining the rule quotes it, and CONTRIBUTING.md's own
    example is a well-formed line. Inside a paragraph it is not a trailer --
    git says so -- and a search of the message body would still find it."""
    quote = f"Signed-off-by: {identity(CONTRIBUTOR)}"
    sandbox.commit(
        "Explain the sign-off",
        message=(f"The line reads:\n{quote}\nin the middle of a paragraph.", "And the message goes on."),
    )
    trailers = sandbox.git("log", "-1", "--format=%(trailers:key=Signed-off-by,valueonly)")
    assert trailers == "", "the premise: git records no trailer on this commit"
    assert quote in sandbox.git("log", "-1", "--format=%B"), "while the line is in the message"
    result = sandbox.check_branch()
    assert result.returncode == 1, output(result)


@pytest.mark.parametrize("trailer", ["Signed-off-by:", f"Signed-off-by: {CONTRIBUTOR[0]}"])
def test_a_sign_off_naming_nobody_reachable_is_refused(sandbox, trailer):
    """What a broken git config produces: the key with nothing that could
    certify anything, or a name with no address to reach it at."""
    sandbox.commit("A change", message=(trailer,))
    result = sandbox.check_branch()
    assert result.returncode == 1, output(result)


def test_a_range_holding_no_commit_is_refused_rather_than_reported_clean(sandbox):
    """A base or a head computed wrong looks exactly like a pull request that
    adds nothing, and the cheap mistake is the red one."""
    head = sandbox.git("rev-parse", "HEAD")
    result = sandbox.check(head, head)
    assert result.returncode == 1
    assert "No commit" in output(result)


def test_a_range_that_cannot_be_read_fails_closed(sandbox):
    """What a shallow checkout looks like from inside the script: an end of
    the range the repository does not have."""
    result = sandbox.check("0" * 40, sandbox.git("rev-parse", "HEAD"))
    assert result.returncode == 1
    assert "fetch-depth" in output(result)


@pytest.mark.parametrize("args", [(), ("only-a-base",), ("a", "b", "c")])
def test_the_gate_refuses_to_run_without_a_range(sandbox, args):
    assert sandbox.check(*args).returncode == 2


def test_a_commit_the_agent_authored_and_certified_under_is_refused(sandbox):
    """What a session produces when it commits with "-s", or before the hook
    ran: a well-formed trailer naming a tool, which certifies nothing."""
    sandbox.commit("A session's change", author=AGENT, sign_off=AGENT)
    result = sandbox.check_branch()
    assert result.returncode == 1
    assert "authored by the agent" in output(result)
    assert "git signoff" in output(result)
    assert "carries no Signed-off-by" not in output(result)


def test_a_commit_the_agent_authored_and_the_maintainer_certified_is_accepted(sandbox):
    """The arrangement `git signoff` produces."""
    sandbox.commit("A session's change", author=AGENT, sign_off=MAINTAINER)
    result = sandbox.check_branch()
    assert result.returncode == 0, output(result)


def test_a_contributor_certifying_their_own_work_is_left_alone(sandbox):
    """Author and trailer naming the same person is the normal shape for
    everybody who is not a tool, which is why the gate keys on the agent's
    address rather than on the two fields being equal."""
    sandbox.commit("A contribution", author=CONTRIBUTOR, sign_off=CONTRIBUTOR)
    result = sandbox.check_branch()
    assert result.returncode == 0, output(result)
    assert "authored by the agent" not in output(result)


def test_the_agent_as_a_co_author_of_somebody_elses_commit_is_refused(sandbox):
    """The tool in the secondary field and a person in the one git log, git
    blame and the contributor graph read: the work is misattributed however
    well-formed the sign-off is."""
    sandbox.commit("A change", author=MAINTAINER, sign_off=MAINTAINER, co_author=AGENT)
    result = sandbox.check_branch()
    assert result.returncode == 1
    assert "names the agent as a co-author" in output(result)
    assert "--reset-author" in output(result)


def test_a_redundant_co_author_on_a_commit_the_agent_authored_is_left_alone(sandbox):
    """The author field already says it; the extra trailer contradicts
    nothing."""
    sandbox.commit("A session's change", author=AGENT, sign_off=MAINTAINER, co_author=AGENT)
    result = sandbox.check_branch()
    assert result.returncode == 0, output(result)


def test_the_workflow_runs_the_gate_on_pull_requests_only_with_the_whole_history():
    """A squash composes master's commit from the pull request, so the
    branch's own commits are the only place the trailer can be read; and
    without fetch-depth 0 neither end of the range is present, which the
    script can only answer by failing closed on every pull request."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert list(workflow[True]) == ["pull_request"], (
        f"{WORKFLOW.name} should run on pull requests alone, got {list(workflow[True])}"
    )
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    checkouts = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
    assert [s.get("with", {}).get("fetch-depth") for s in checkouts] == [0]
    assert any(".github/check_sign_off.sh" in s.get("run", "") for s in steps)


def hook_value(name):
    match = re.search(rf'^\s*{name}="([^"]*)"$', HOOK.read_text(), re.MULTILINE)
    assert match, f"{HOOK.name} should still set {name}"
    return match.group(1)


def script_value(name):
    match = re.search(rf'^readonly {name}="([^"]*)"$', SCRIPT.read_text(), re.MULTILINE)
    assert match, f"{SCRIPT.name} should still set {name}"
    return match.group(1)


def test_the_gate_knows_the_identities_the_hook_sets():
    """The gate runs in a workflow that never sources the hook, so both
    addresses are written in both files. A change to one that missed the other
    would not fail: the gate would quietly stop matching, and refuse every
    commit a session makes -- or, the other way round, accept the ones it
    exists to refuse."""
    assert hook_value("agentEmail") == script_value("AGENT_EMAIL") == AGENT[1]
    assert hook_value("signOffEmail") == script_value("SIGN_OFF_EMAIL") == MAINTAINER[1]


def test_the_trailer_names_the_account_the_hook_recognises_as_the_maintainer():
    """GitHub's noreply address carries the account's id and login, so the
    login the hook checks origin against and the address it signs off with
    can be held together. A wrong login is refused by nothing -- the hook
    simply never sets the identity on the maintainer's own copy."""
    address = hook_value("signOffEmail")
    match = re.fullmatch(r"[0-9]+\+([^@]+)@users\.noreply\.github\.com", address)
    assert match, f"{address} is not a GitHub noreply address"
    assert match.group(1).lower() == hook_value("maintainerLogin").lower()


def run_hook(tmp_path, origin):
    """The hook, run the way a session runs it, against a sandbox.

    Starting a docker daemon and installing the test dependencies are what
    the rest of the hook does, and both are stubbed out: a `docker` that is
    already running and a `pytest` that already collects, which is the state
    a resumed session finds.
    """
    sandbox = Sandbox(tmp_path / "checkout")
    if origin:
        sandbox.git("remote", "add", "origin", origin)
    (sandbox.path / "tests").mkdir()
    (sandbox.path / "tests" / "requirements.txt").touch()
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("docker", "pytest"):
        (stubs / name).write_text("#!/bin/sh\nexit 0\n")
        (stubs / name).chmod(0o755)
    result = subprocess.run(
        ["bash", str(HOOK)],
        env={
            **sandbox.env,
            "CLAUDE_CODE_REMOTE": "true",
            "CLAUDE_PROJECT_DIR": str(sandbox.path),
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        },
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, output(result)
    return sandbox, result


@pytest.mark.parametrize("origin", [
    "https://github.com/tigerblue77/Postfix_SMTP_relay_Docker.git",
    "git@github.com:TigerBlue77/Postfix_SMTP_relay_Docker.git",
])
def test_a_commit_made_with_the_hooks_alias_passes_the_gate(tmp_path, origin):
    """End to end: the identity and alias the hook sets on the maintainer's
    copy, in either URL form, make a commit the gate accepts -- authored by
    the tool, signed off by the maintainer."""
    sandbox, _ = run_hook(tmp_path, origin)
    base = sandbox.git("rev-parse", "HEAD")
    subprocess.run(
        ["git", "signoff", "--quiet", "--allow-empty", "-m", "A session's change"],
        cwd=sandbox.path, env=sandbox.env, check=True,
    )
    assert sandbox.git("log", "-1", "--format=%an <%ae>") == identity(AGENT)
    trailer = sandbox.git("log", "-1", "--format=%(trailers:key=Signed-off-by,valueonly)")
    assert trailer == identity(MAINTAINER)
    result = sandbox.check(base, sandbox.git("rev-parse", "HEAD"))
    assert result.returncode == 0, output(result)


@pytest.mark.parametrize("origin", [
    "https://github.com/somebody-else/Postfix_SMTP_relay_Docker.git",
    None,
])
def test_a_fork_is_given_no_identity_and_told_to_sign_its_own_work(tmp_path, origin):
    """On a contributor's fork the alias would put the maintainer's
    certification on work the maintainer has never seen. No origin at all
    reads the same way: the opposite default hands a stranger's session an
    identity that is not theirs."""
    sandbox, result = run_hook(tmp_path, origin)
    configured = subprocess.run(
        ["git", "config", "--local", "--get-regexp", r"^(alias\.signoff|user\.)"],
        cwd=sandbox.path, env=sandbox.env, capture_output=True, text=True,
    )
    assert configured.stdout == "", f"the hook configured a fork: {configured.stdout}"
    assert "sign your own work" in result.stdout
    # Nor is the issue and pull request rule addressed to them: GitHub drops
    # "assignees" from a caller without write access, and a contributor's
    # draft is what the branch updater's filter is there to leave alone.
    assert "assigned to" not in result.stdout, output(result)
    assert "never a draft" not in result.stdout, output(result)


@pytest.mark.parametrize("origin", [
    "https://github.com/tigerblue77/Postfix_SMTP_relay_Docker.git",
    "git@github.com:TigerBlue77/Postfix_SMTP_relay_Docker.git",
])
def test_the_maintainers_session_is_told_to_assign_and_never_to_draft(tmp_path, origin):
    """An issue and a pull request are not settings: both fields are decided
    on the call that creates them, a web session's harness says to open the
    pull request as a draft, and nobody says to assign anything. So the hook
    says both, on the maintainer's copy, before the session makes that call.
    CLAUDE.md, "Conventions", carries why."""
    _, result = run_hook(tmp_path, origin)
    assert "assigned to tigerblue77" in result.stdout, output(result)
    assert "never a draft" in result.stdout, output(result)
