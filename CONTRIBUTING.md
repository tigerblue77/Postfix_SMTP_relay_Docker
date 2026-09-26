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

## Licence headers

Every source file carries a two-line [SPDX](https://spdx.dev/) header: right after the shebang in a script, at the very top of a Python module, a workflow, `.github/dependabot.yml` or the `Dockerfile`, and in an HTML comment at the top of this page and of [`LICENSE-COMMERCIAL.md`](./LICENSE-COMMERCIAL.md). The JSON files, `pytest.ini`, `tests/requirements.txt`, the ignore files, the licence texts and the rest of the documentation carry none.

```bash
#!/bin/bash

# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only
```

Copy it into any new source file you add, tests and fixtures included. It is what lets a downstream packager or an automated scanner tell what the file is under without reading the whole repository, and it is how AGPL-3.0 section 5(a) is satisfied file by file.

Do not add your own copyright line: the collective notice above already covers every contributor, and the commit history is the authoritative record of who wrote what. If you would rather be named explicitly, ask in your pull request and it will be added to [`NOTICE`](./NOTICE).

## Before opening a pull request

- Run the test suite: `pytest`, from the repository root, with a Docker daemon running. The README's [Testing](./README.md#testing) section has the setup.
- Add a test for what you changed. Behaviour the README promises is pinned by a test here, and a behaviour with no test is one the next change is free to break.
- Keep the two linters quiet: `shellcheck -S error run healthcheck .claude/hooks/session-start.sh` and `ruff check --no-cache --select F,B tests`. CI runs both on every pull request.
- If your change makes the README or `CLAUDE.md` wrong, the change is not finished.
