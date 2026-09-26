#!/bin/bash

# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

# SessionStart hook for Claude Code on the web.
#
# Everything that gates a pull request needs something this container does not
# have when a session starts: the Pytest jobs in .github/workflows/test.yml run
# a suite whose fixtures build and run containers through testcontainers, and
# Build Image in .github/workflows/ci.yml builds the image. So there are two
# jobs here, a running docker daemon and the dependencies from
# tests/requirements.txt -- and a third that gates a pull request too: the
# git identity and the "git signoff" alias a commit made here needs to pass
# .github/workflows/sign_off.yml.
#
# Deliberately best-effort, and deliberately without "set -e": a step that
# fails reports on stderr and the hook still exits 0, so an incomplete
# environment degrades the session instead of blocking it from starting.

# Do nothing outside a remote session. An unset variable, or "false", is a
# local checkout whose environment belongs to whoever set it up.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] ; then
  exit 0
fi

repoDir="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
requirements="$repoDir/tests/requirements.txt"
dockerLog="/tmp/session-start-dockerd.log"

warn()
{
    echo "session-start: $*" >&2
}

# Whose copy of the repository this is, which decides whether the identity
# below is set at all. This file is cloned with the tree, so a contributor's
# session on their own fork runs it exactly as the maintainer's does -- and
# there the sign-off alias would put the maintainer's Developer Certificate of
# Origin attestation on work the maintainer has never seen, the one thing
# CONTRIBUTING.md tells a contributor not to do. The owner is read from origin
# in either URL form, "https://github.com/<owner>/..." and
# "git@github.com:<owner>/...", lower-cased because a clone URL keeps whatever
# case was typed while a GitHub login compares case-insensitively. Anything
# else, no origin included, reads as not this repository: the opposite default
# hands a stranger's session an identity that is not theirs.
maintainerLogin="tigerblue77"
originUrl="$(git -C "$repoDir" remote get-url origin 2> /dev/null)"
originUrl="${originUrl,,}"
maintainersCopy=no
case "$originUrl" in
  */"$maintainerLogin"/*|*:"$maintainerLogin"/*) maintainersCopy=yes ;;
esac

# The two identities a commit made here carries (issue #34). The author is who
# wrote the work, and that is the tool: git log, git blame, git shortlog and the
# contributor graph all read that field, so recording the tool anywhere else is
# not recording it. The Signed-off-by trailer is who certifies it, and the
# DCO's text is first-person -- "I certify that" -- which a tool cannot say, so
# that one is the maintainer's, made true by their review and merge.
# CONTRIBUTING.md, "Contributions written by an agent", is the full argument.
#
# The trailer therefore cannot come from "commit -s", which derives it from
# user.* -- the very fields that have to stay the tool's. It is passed whole
# through an alias instead, so it is a command rather than something to
# remember. Not "trailer.<token>.key": spelled with the separator in it
# ("Signed-off-by: ") that config writes a line which looks exactly right and
# which a keyed read of the trailers, the one .github/check_sign_off.sh makes,
# returns empty -- a refusal with nothing visible to explain it.
#
# The addresses are written in .github/check_sign_off.sh too, which runs in a
# workflow that never sources this file; tests/test_sign_off.py holds the two
# together. Repository-local, so nothing reaches into a configuration the
# session may share with other work.
signOffName="Tigerblue77"
signOffEmail="37409593+tigerblue77@users.noreply.github.com"
agentName="Claude"
agentEmail="noreply@anthropic.com"

setIdentity()
{
    git -C "$repoDir" config user.name "$agentName" &&
      git -C "$repoDir" config user.email "$agentEmail" &&
      git -C "$repoDir" config alias.signoff "commit --trailer \"Signed-off-by: $signOffName <$signOffEmail>\""
}

# The image build and every test need a daemon, and the container starts
# without one. Idempotent: an already-running daemon is left alone, which is
# what a resumed or cleared session hits.
startDocker()
{
    if docker info > /dev/null 2>&1 ; then
      return 0
    fi

    if ! command -v dockerd > /dev/null 2>&1 ; then
      warn "no dockerd in this image: 'docker build' and the test suite cannot run"
      return 1
    fi

    nohup dockerd > "$dockerLog" 2>&1 &

    # Bounded wait, so a daemon that never comes up cannot hang start-up.
    for _ in $(seq 1 30) ; do
      if docker info > /dev/null 2>&1 ; then
        return 0
      fi
      sleep 1
    done

    warn "docker daemon did not come up within 30s, see $dockerLog"
    return 1
}

# Collection imports tests/conftest.py, every fixture module and every test
# module, so it fails exactly when a dependency is missing -- and it needs no
# daemon, because xdist does not distribute a collect-only run. The "cd" is
# required: tests is a package and its modules import each other by absolute
# name. This doubles as the idempotency check: a second run installs nothing.
testDepsReady()
{
    ( cd "$repoDir" && pytest --collect-only -q tests > /dev/null 2>&1 )
}

installTestDeps()
{
    if [ ! -f "$requirements" ] ; then
      warn "$requirements is missing, skipping test dependencies"
      return 1
    fi

    if testDepsReady ; then
      return 0
    fi

    # The image ships pytest as a uv-managed tool whose environment is isolated
    # from pip's site-packages, and its shim comes first on PATH. Installing
    # the requirements with pip alone therefore leaves the pytest that actually
    # runs without them -- and since pytest.ini's addopts pass xdist-only
    # flags, that pytest does not even reach collection: it dies on
    # "unrecognized arguments: -n". Going through uv keeps one pytest that can
    # see the whole requirements file.
    if command -v uv > /dev/null 2>&1 ; then
      uv tool install --force --with-requirements "$requirements" pytest > /dev/null 2>&1
      if testDepsReady ; then
        return 0
      fi
    fi

    # No uv, or uv did not resolve it: fall back to what the CI does.
    pip install --quiet --requirement "$requirements" > /dev/null 2>&1 ||
      pip install --quiet --break-system-packages --requirement "$requirements" > /dev/null 2>&1
    if testDepsReady ; then
      return 0
    fi

    warn "could not make 'pytest' import the test dependencies from $requirements"
    return 1
}

incomplete=no

# First, so a session never commits before it has both identities. On a fork
# the one sentence that is the contributor's rather than this repository's goes
# to stdout, which is what Claude Code hands the session from a hook that exits
# 0: a contributor's agent learns here, rather than from a red pull request,
# that its own commits need its own sign-off.
if [ "$maintainersCopy" == "yes" ] ; then
  if ! setIdentity ; then
    warn "could not set the git identity and the signoff alias: a commit made here would be authored and signed off by whatever git defaults to"
    incomplete=yes
  fi
else
  echo "session-start: this is not $maintainerLogin's copy of the repository, so no git identity was set: sign your own work, with your own name (CONTRIBUTING.md)"
fi

startDocker || incomplete=yes
installTestDeps || incomplete=yes

if [ "$incomplete" == "yes" ] ; then
  warn "environment is incomplete: see the messages above before trusting a failing build or test run"
fi

exit 0
