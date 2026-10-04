<!--
SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
SPDX-License-Identifier: AGPL-3.0-only
-->

# Contributing

Contributions are welcome: bug reports, documentation, tests and code alike.

This page covers the licensing side of contributing. For the practical side — how the image is built and tested, what gates a merge, and the decisions in the code that look like bugs but are not — see the [Testing](./README.md#testing) section of the README and [`CLAUDE.md`](./CLAUDE.md), which is written for any contributor, human or not.

## Licensing of your contributions

This project is dual-licensed: [AGPL-3.0-only](./LICENSE) for everyone, plus a [separate commercial licence](./LICENSE-COMMERCIAL.md) for parties who cannot meet the AGPL's obligations. A dual licence only works if every line in the tree can be offered under both arms — a single contribution that arrives under the AGPL alone would make the commercial arm impossible to grant honestly from that point on.

So, **by submitting a contribution to this repository, you agree that**:

1. your contribution is licensed to the public under the **GNU Affero General Public License, version 3** (`AGPL-3.0-only`), the same terms as the rest of the project; and
2. you grant **Tigerblue77** ([@tigerblue77](https://github.com/tigerblue77)) a perpetual, worldwide, non-exclusive, royalty-free, irrevocable licence to reproduce, prepare derivative works of, publicly display, sublicense and distribute your contribution **under other terms as well, including proprietary commercial terms**; and
3. you have the right to grant both — the work is yours, or you are authorised to submit it (your employer's IP policy included).

What this is **not**:

- **It is not a copyright assignment.** You keep the copyright in what you wrote, in full. You may relicense, reuse or sell your own contribution elsewhere, exactly as you could before.
- **It is not exclusive.** Point 2 gives the maintainer a licence alongside yours, not instead of it.
- **It does not put your work behind a paywall.** Everything you contribute stays available to everyone under the AGPL, permanently. Point 2 only lets the maintainer *additionally* offer the same code to a party who is paying for terms the AGPL cannot give them.

If you are not comfortable with point 2, say so in your pull request rather than staying silent: a contribution the maintainer cannot dual-license is better identified at review time than after it is merged.

Everything that was in this repository before the relicensing recorded in [`NOTICE`](./NOTICE) arrived under the MIT licence, which already grants the right to sublicense. That is what lets both arms cover the whole tree, including the years before this page existed.

## Sign your work — Developer Certificate of Origin

Every commit must carry a `Signed-off-by` line. Adding one is your statement of the [Developer Certificate of Origin 1.1](https://developercertificate.org/):

> By making a contribution to this project, I certify that:
>
> &nbsp;&nbsp;&nbsp;&nbsp;(a) The contribution was created in whole or in part by me and I have the right to submit it under the open source license indicated in the file; or
>
> &nbsp;&nbsp;&nbsp;&nbsp;(b) The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same open source license (unless I am permitted to submit under a different license), as indicated in the file; or
>
> &nbsp;&nbsp;&nbsp;&nbsp;(c) The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.
>
> &nbsp;&nbsp;&nbsp;&nbsp;(d) I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.

In a dual-licensed project that statement carries weight: it is the record that your contribution could be offered under both of the licences above.

Sign off with the `-s` flag, using a real name and a reachable address:

```bash
git commit -s -m "Your commit message"
```

which appends:

```
Signed-off-by: Random J Developer <random@developer.example.org>
```

Forgot it on the last commit? `git commit --amend -s`. On several? `git rebase --signoff <base>`, then `git push --force-with-lease`.

The **Sign-off** check reads the commits of every pull request and refuses one that lacks it — on the pull request, because pull requests here are squash-merged and the squash composes `master`'s commit from the pull request, so the branch is the last place the trailer can be read. A commit made in GitHub's web editor carries one only if the repository asks for it, which is a setting rather than a file.

### Contributions written by an agent

Some of the code here is written by a coding agent working on the maintainer's instruction. The DCO does not bend for that, and this project cannot afford it to: the sign-off is what records that a contribution could be offered under **both** licences, which is what keeps the commercial arm grantable.

An agent is a tool. A tool cannot certify anything, and a `Signed-off-by` naming one would be a trailer that satisfies a checker while naming nobody who could make the statement above. But it is also what actually wrote the code, and a commit has room to say both. So for those commits:

- **the author is the agent.** `git log`, `git blame`, `git shortlog` and GitHub's contributor graph all read that field, so it is the one place where recording who wrote the work counts. Naming the maintainer there would say they typed what a tool wrote;
- **the `Signed-off-by` is the maintainer's**, because the certification is theirs to make. It cannot come from `git commit -s`, which derives the trailer from the author — the field that has to stay the agent's — so it is passed explicitly through the `git signoff` alias that `.claude/hooks/session-start.sh` sets at the start of every Claude Code on the web session on the maintainer's copy of the repository. A local session commits as the person at the keyboard, who signs off with `-s` as anyone else does;
- **the certification is the maintainer's act of reviewing and merging.** The trailer states it; the review is what makes it true. A pull request merged unread carries a sign-off that means nothing, and no workflow can tell the difference. [`.github/check_sign_off.sh`](./.github/check_sign_off.sh) reads the trailer's shape and — on a commit the agent authored — whose address is on it, so that a tool cannot end up certifying its own work. Whether the person behind that address actually reviewed anything is what it cannot see, and never will.

No `Co-Authored-By` accompanies them: the author field already names the agent, and a secondary attribution repeating it would only be another place to fall out of step. Naming the agent as a co-author of a commit somebody else authored is refused outright, since it records the work in the one field nothing reads.

If you are a contributor rather than the maintainer, most of this does not concern you: author and sign your own work, with your own name. Two parts do. A commit authored under the agent's address (`noreply@anthropic.com`) is accepted only with the maintainer's sign-off. And a commit you authored must not name the agent as a co-author: some coding agents add a `Co-Authored-By` trailer for themselves by default, and the check refuses it, since the author field is where the work is recorded. The hook knows the difference — it sets the agent identity only where `origin` is the maintainer's repository, and says so on a fork.

## Licence headers

Every source file carries a two-line [SPDX](https://spdx.dev/) header: right after the shebang in a script, at the very top of a Python module, a workflow, `.github/dependabot.yml`, `.github/actionlint.yaml`, `.github/zizmor.yml` or the `Dockerfile`, and in an HTML comment at the top of this page and of [`LICENSE-COMMERCIAL.md`](./LICENSE-COMMERCIAL.md). The JSON files, `pytest.ini`, `tests/requirements.txt`, the ignore files, the licence texts and the rest of the documentation carry none.

```bash
#!/bin/bash

# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only
```

Copy it into any new source file you add, tests and fixtures included. It is what lets a downstream packager or an automated scanner tell what the file is under without reading the whole repository, and it is how AGPL-3.0 section 5(a) is satisfied file by file.

Do not add your own copyright line: the collective notice above already covers every contributor, and the commit history is the authoritative record of who wrote what. If you would rather be named explicitly, ask in your pull request and it will be added to [`NOTICE`](./NOTICE).

## Before opening a pull request

- Run the test suite: `pytest`, from the repository root, with a Docker daemon running. The README's [Testing](./README.md#testing) section has the setup.
- Sign off every commit, as [above](#sign-your-work--developer-certificate-of-origin).
- Add a test for what you changed. Behaviour the README promises is pinned by a test here, and a behaviour with no test is one the next change is free to break.
- Keep the two linters quiet: `shellcheck -S error run healthcheck .claude/hooks/session-start.sh .github/check_sign_off.sh` and `ruff check --no-cache --select F,B tests`. CI runs both on every pull request.
- If your change makes the README or `CLAUDE.md` wrong, the change is not finished.
