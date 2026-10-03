# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

import pytest

pytest_plugins = [
   "tests.fixtures.mailpit",
   "tests.fixtures.postfix",
   "tests.fixtures.shared_network",
   "tests.fixtures.smtp",
]


def container_output(name, container):
    """A container's log, and its stderr when there is any, ready to print."""
    stdout, stderr = container.get_logs()
    output = f"----- {name} log -----\n{stdout.decode()}"
    # "run" reports what stopped it on stderr, which is all a container that
    # refused to start has to say.
    if stderr:
        output += f"\n----- {name} stderr -----\n{stderr.decode()}"
    return output


def print_log_on_failure(request, name, container):
    """Print a container log when the test that used it failed.

    A failure is otherwise just a missing mail: the reason why postfix did
    not relay it is only in the container log, which testcontainers throws
    away together with the container. Fixtures that stop containers have to
    call this before doing so.

    Only a failure in the test body reaches the output this way: pytest shows
    what a teardown printed next to a failed test, and not next to an error in
    a fixture. A relay that never came up is therefore reported by the fixture
    that started it, with the log in the failure itself, and is not printed
    again here.
    """
    report = getattr(request.node, "report_call", None)
    if report is None or not report.failed:
        return
    if getattr(container, "log_in_failure", False):
        return
    print(container_output(name, container))


@pytest.fixture(autouse=True)
def shared_container_logs(request):
    """Show the log of the containers shared by the tests when one fails."""
    shared = []
    for name in ("postfix", "mailpit_container"):
        if name in request.fixturenames:
            shared.append((name, request.getfixturevalue(name)))

    yield

    for name, container in shared:
        print_log_on_failure(request, name, container)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    setattr(item, f"report_{report.when}", report)
    return report
