#!/bin/bash

# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

# Answers "does every commit this pull request adds carry a Signed-off-by?".
#
# CONTRIBUTING.md requires one on every commit: it is the contributor's
# statement of the Developer Certificate of Origin, and in a dual-licensed
# project -- AGPL-3.0-only in LICENSE, plus LICENSE-COMMERCIAL.md -- it is the
# record that a contribution could be offered under both arms. A rule stated
# and checked nowhere is held by whoever happens to remember it, which is why
# this exists (issue #34).
#
# ON THE PULL REQUEST, AND ONLY THERE. Pull requests here are squash-merged, and
# a squash composes the commit message from the pull request rather than from
# the branch, so the branch's own commits are the last place the trailer can be
# read: by the time master has the squash, it is gone. Running this on a push to
# master would also leave the default branch permanently red, since the history
# it has -- where, Dependabot's commits apart, no commit carries a trailer at
# all -- cannot be signed without rewriting a published branch. So it gates
# what arrives from here on, and leaves that history alone.
#
# WHOSE NAME IS ON THE TRAILER. The DCO is first-person -- "I certify that" --
# and CONTRIBUTING.md asks for a real name and a reachable address. A commit a
# session writes is AUTHORED by the tool, because that is who wrote it, and its
# Signed-off-by names the MAINTAINER, who certifies it by reviewing and merging.
# One half of that is decidable from here and is checked below: a commit whose
# author is the agent identity must carry the maintainer's sign-off -- not the
# tool's own, and not a stranger's, since nobody else answers for what a
# session here writes -- and a commit that names the agent only as a
# co-author, with somebody else as the author, is the arrangement the author
# field exists to replace.
#
# The other half is not decidable, and no amount of trying would make it so. A
# commit a session wrote under the maintainer's name is indistinguishable from
# one they typed, and refusing "author equals sign-off" would refuse the normal
# and correct shape for every outside contributor, who authors their own work
# and certifies it themselves. So the check fires on the agent's address and
# stays silent on everybody else.
#
# MERGE COMMITS ARE SKIPPED. Merging the base branch into a branch to resolve a
# conflict is the right thing to do, git writes that commit itself with no
# sign-off, and it carries no contribution of its own to certify: everything it
# brings in was signed where it was authored.
#
# Exit 0: every commit in the range carries a well-formed sign-off.
# Exit 1: at least one does not, or one the agent authored is not signed off
#         by the maintainer, or one names the agent as a co-author of somebody
#         else's commit, or the range could not be read, or it is empty.
# Exit 2: called wrong.
#
# Which answer sits on which code is deliberate, and it is why this script, unlike
# run and healthcheck, runs under "set -e": a script that breaks somewhere inside
# itself then exits 1, so 1 has to be the answer that is safe to give by
# accident. Here that is "this pull request is not signed": a false red is read
# by a person who can look at the commits, where a false green lets through the
# very thing this exists to catch, on a run that looks fine. It fails closed.
#
# Usage: .github/check_sign_off.sh <base-sha> <head-sha>

set -euo pipefail

if [ "$#" -ne 2 ] ; then
  printf 'Usage: %s <base-sha> <head-sha>\n' "${0##*/}" >&2
  exit 2
fi

readonly BASE="$1"
readonly HEAD="$2"

# The trailer, read as a TRAILER by git's own parser and matched on its SHAPE.
# Each half closes a hole the other leaves open. Searching the message body
# instead passes a commit that merely quotes the rule -- CONTRIBUTING.md's own
# example is a well-formed line, and pasted into a paragraph explaining the rule
# it certifies nobody, while git reports no trailer on such a commit. And
# reading the trailer without looking at its value passes "Signed-off-by:" with
# nothing after it, or a name with no address, which is what a broken git config
# produces. The address only has to look like one: whether a mailbox is
# reachable is not something this script could ever decide.
#
# git has already consumed the key, which it matches case-insensitively, so this
# is matched against the value alone.
readonly SIGN_OFF_VALUE_PATTERN='^.+ <[^[:space:]<>]+@[^[:space:]<>]+>[[:space:]]*$'

# The identity .claude/hooks/session-start.sh authors a session's commits under,
# and the one it puts on their trailer. Written here as well as there because
# this runs in a workflow that never sources the hook, and held to it by
# tests/test_sign_off.py, so that changing one without the other fails rather
# than quietly stops matching. The addresses are what identify them; the names
# are deliberately not read, a contributor being free to be called anything.
readonly AGENT_EMAIL="noreply@anthropic.com"
readonly SIGN_OFF_EMAIL="37409593+tigerblue77@users.noreply.github.com"

COMMITS=""
if ! COMMITS="$(git log --no-merges --format='%H' "$BASE..$HEAD" 2> /dev/null)" ; then
  printf '::error::Could not read the commits between %s and %s. Checking out with fetch-depth 0 is what makes both of them present\n' \
    "$BASE" "$HEAD" >&2
  exit 1
fi

# An empty range is refused rather than passed. A pull request that adds no
# commit is a state nobody needs this job's opinion on, while a range that
# resolves to nothing because the base or the head was computed wrong is the
# shape of a false green, and from here the two cannot be told apart.
if [ -z "$COMMITS" ] ; then
  printf '::error::No commit between %s and %s. A range that resolves to nothing is refused rather than reported clean, since a base or head computed wrong looks exactly like this\n' \
    "$BASE" "$HEAD" >&2
  exit 1
fi

UNSIGNED_COUNT=0
SELF_CERTIFIED_COUNT=0
MISATTRIBUTED_COUNT=0
CHECKED_COUNT=0

while IFS= read -r COMMIT ; do
  [ -n "$COMMIT" ] || continue

  CHECKED_COUNT=$((CHECKED_COUNT + 1))
  SUBJECT="$(git log -1 --format='%s' "$COMMIT")"

  # Stronger than a search of the body, and not complete: a well-formed
  # quotation placed at the very end of a message is parsed as a trailer and
  # passes. That bound is known, and written down so the next reader who finds
  # it knows it was.
  SIGN_OFFS="$(git log -1 --format='%(trailers:key=Signed-off-by,valueonly)' "$COMMIT")"

  # One well-formed value is enough: a commit may carry several, and a
  # co-author's malformed line does not undo the author's certification.
  if ! printf '%s\n' "$SIGN_OFFS" | grep -qE "$SIGN_OFF_VALUE_PATTERN" ; then
    UNSIGNED_COUNT=$((UNSIGNED_COUNT + 1))
    printf '::error::%s "%s" carries no Signed-off-by\n' "${COMMIT:0:8}" "$SUBJECT" >&2
    continue
  fi

  AUTHOR_EMAIL="$(git log -1 --format='%ae' "$COMMIT")"

  if [ "${AUTHOR_EMAIL,,}" != "$AGENT_EMAIL" ] ; then
    # Not the agent's work by its author field, so whose name is on the
    # trailer is nobody's business here -- except where the agent is named as
    # a co-author of it. That puts the tool in the secondary field and a
    # person in the one git log, git blame and the contributor graph read,
    # which is the arrangement the author field replaces. A Co-Authored-By
    # naming the agent on a commit the agent DID author is only redundant, and
    # never reaches this branch.
    CO_AUTHORS="$(git log -1 --format='%(trailers:key=Co-Authored-By,valueonly)' "$COMMIT")"
    if printf '%s\n' "$CO_AUTHORS" | grep -qiF "<$AGENT_EMAIL>" ; then
      MISATTRIBUTED_COUNT=$((MISATTRIBUTED_COUNT + 1))
      printf '::error::%s "%s" names the agent as a co-author while someone else authored it. The author field is where the work is recorded\n' \
        "${COMMIT:0:8}" "$SUBJECT" >&2
    fi
    continue
  fi

  # The agent authored it, so the trailer has to name somebody who can certify
  # it: the maintainer, and not the tool. Checked on the address, as the author
  # is.
  if printf '%s\n' "$SIGN_OFFS" | grep -qiF "<$SIGN_OFF_EMAIL>" ; then
    continue
  fi

  SELF_CERTIFIED_COUNT=$((SELF_CERTIFIED_COUNT + 1))
  printf '::error::%s "%s" is authored by the agent and not signed off by the maintainer. A tool certifies nothing, so the Signed-off-by has to name the maintainer\n' \
    "${COMMIT:0:8}" "$SUBJECT" >&2
done <<< "$COMMITS"

if [ "$UNSIGNED_COUNT" -eq 0 ] && [ "$SELF_CERTIFIED_COUNT" -eq 0 ] && [ "$MISATTRIBUTED_COUNT" -eq 0 ] ; then
  printf 'All %d commits carry a sign-off\n' "$CHECKED_COUNT"
  exit 0
fi

# Reported apart because they are repaired apart, and telling one to apply the
# other's remedy is how a contributor ends up force-pushing for nothing.
if [ "$UNSIGNED_COUNT" -gt 0 ] ; then
  printf '\n%d of the %d commits in this pull request carry no sign-off.\n\n' "$UNSIGNED_COUNT" "$CHECKED_COUNT" >&2
  printf 'Adding one is your statement of the Developer Certificate of Origin, which is what\n' >&2
  printf 'lets this dual-licensed project offer your contribution under both of its licences.\n' >&2
  printf 'See CONTRIBUTING.md. To sign the commits already on this branch:\n\n' >&2
  printf '  git rebase --signoff %s\n  git push --force-with-lease\n\n' "$BASE" >&2
  printf 'and "git commit -s" from here on, or "git commit --amend -s" for the last one.\n' >&2
  printf '\nA Claude Code on the web session on the maintainer'"'"'s copy uses "git signoff"\n' >&2
  printf 'instead, never "-s": see CONTRIBUTING.md, "Contributions written by an agent".\n' >&2
fi

if [ "$SELF_CERTIFIED_COUNT" -gt 0 ] ; then
  printf '\n%d of the %d commits in this pull request are authored by the agent and not signed off by the maintainer.\n\n' \
    "$SELF_CERTIFIED_COUNT" "$CHECKED_COUNT" >&2
  printf 'A tool certifies nothing, so the trailer has to name the maintainer while the author\n' >&2
  printf 'field keeps saying who wrote the work. See CONTRIBUTING.md, "Contributions written by\n' >&2
  printf 'an agent".\n\n' >&2
  printf 'On Claude Code on the web, .claude/hooks/session-start.sh sets that up on the\n' >&2
  printf 'maintainer'"'"'s copy at the start of every session, so the usual cause is a session\n' >&2
  printf 'that started before the hook did, or ran an older one. Re-run it, then commit with\n' >&2
  printf 'the alias it defines rather than with "-s", which derives the trailer from the\n' >&2
  printf 'author and would write this same commit again:\n\n' >&2
  printf '  CLAUDE_CODE_REMOTE=true bash .claude/hooks/session-start.sh\n' >&2
  printf '  git signoff --amend --no-edit          # for the last commit\n\n' >&2
  printf 'For several, re-commit them with "git signoff"; "git rebase --signoff" derives the\n' >&2
  printf 'trailer from the author exactly as "-s" does, so it cannot repair this one.\n' >&2
fi

if [ "$MISATTRIBUTED_COUNT" -gt 0 ] ; then
  printf '\n%d of the %d commits in this pull request name the agent as a co-author while somebody else authored them.\n\n' \
    "$MISATTRIBUTED_COUNT" "$CHECKED_COUNT" >&2
  printf 'Co-Authored-By is a secondary field, and Author is the one git log, git blame,\n' >&2
  printf 'git shortlog and the contributor graph read. Some coding agents add that trailer by\n' >&2
  printf 'default. A commit you authored is yours: drop the trailer and keep your own name\n' >&2
  printf 'and sign-off:\n\n' >&2
  printf '  git commit --amend        # then remove the Co-Authored-By line\n\n' >&2
  printf 'In a Claude Code on the web session on the maintainer'"'"'s copy, the work is recorded\n' >&2
  printf 'by authoring it under the tool instead, which .claude/hooks/session-start.sh sets up.\n' >&2
  printf 'Re-run it, then re-author the commit and drop the trailer:\n\n' >&2
  printf '  CLAUDE_CODE_REMOTE=true bash .claude/hooks/session-start.sh\n' >&2
  printf '  git signoff --amend --reset-author        # then remove the Co-Authored-By line\n\n' >&2
  printf 'See CONTRIBUTING.md, "Contributions written by an agent".\n' >&2
fi

exit 1
