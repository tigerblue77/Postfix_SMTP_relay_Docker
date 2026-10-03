# SPDX-FileCopyrightText: 2015-2026 Mattias Wadman, Tigerblue77 and the postfix-relay contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""What the container logs and where.

Everything goes through rsyslog, configured from RSYSLOG_ variables, and
the container log is the only place a user gets postfix messages from
unless they ask for more (issue wader/postfix-relay#58).
"""

import re

from tests.helpers import (container_exec, container_log, container_stderr,
                           exit_code_within, file_missing, process_running,
                           restart, send, wait_for_file, wait_for_log, wait_for_log_line)

# "postfix-script" is one of the programs that log, hyphen and all.
MAIL_LOG_LINE = re.compile(r'^postfix/[\w-]+\[\d+\]: ')
TIMESTAMPED_MAIL_LOG_LINE = re.compile(
    r'^\d{4}-\d{2}-\d{2}T[\d:.+]+ \S+ postfix/[\w-]+\[\d+\]: ')

# The init script says what it is doing without ending the line, so the first
# thing postfix logs while it starts or stops follows that text on the same one.
INIT_SCRIPT_TEXT = re.compile(r'^(Starting|Stopping) the Postfix mail system: /etc/postfix')


def postfix_log_lines(container):
    lines = (INIT_SCRIPT_TEXT.sub('', line) for line in container_log(container).splitlines())
    return [line for line in lines if 'postfix/' in line]


def test_container_log_has_no_timestamps_by_default(postfix, mailpit, smtp):
    """RSYSLOG_TIMESTAMP defaults to "no".

    Docker timestamps the lines it collects itself, so repeating the time in
    every message only makes the log harder to read.
    """
    smtp.sendmail('sender@example.com', ['receiver@example.com'],
                  'Subject: no timestamps\r\n\r\nbody\r\n')
    mailpit.wait_for_message('no timestamps')

    lines = postfix_log_lines(postfix)

    assert lines
    assert all(MAIL_LOG_LINE.match(line) for line in lines), lines[:3]


def test_timestamps_can_be_asked_for(postfix_factory, mailpit):
    relay = postfix_factory(env={'RSYSLOG_TIMESTAMP': 'yes'})

    send(relay, subject='with timestamps')
    mailpit.wait_for_message('with timestamps')

    lines = postfix_log_lines(relay)

    assert lines
    assert all(TIMESTAMPED_MAIL_LOG_LINE.match(line) for line in lines), lines[:3]


def test_mail_can_also_be_logged_to_a_file(postfix_factory, mailpit):
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes'})

    send(relay, subject='logged to file')
    mailpit.wait_for_message('logged to file')

    assert wait_for_file(relay, '/var/log/mail.log', 'status=sent')


def test_rsyslog_d_configuration_is_included(postfix_factory, mailpit):
    """Dropping a .conf file in /etc/rsyslog.d extends the configuration."""
    relay = postfix_factory(
        files={'/etc/rsyslog.d/99-test.conf': 'mail.* /var/log/from-include.log\n'})

    send(relay, subject='logged by an include')
    mailpit.wait_for_message('logged by an include')

    assert wait_for_file(relay, '/var/log/from-include.log', 'status=sent')


def test_an_include_keeps_the_rsyslog_default_format(postfix_factory, mailpit):
    """RSYSLOG_TIMESTAMP does not reach a .conf file of your own.

    It is the same relay as the test above, read for its format rather than
    its content: the container log has no timestamps here, the include's
    file does. The property is an ordering -- "run" emits the include above
    the $template pair, and a directive applies only to actions written
    after it -- so tidying the include down next to the other file actions
    would make the README's sentence false with nothing else failing. That
    tidy-up would look like it was tightening invariant 12, which is about
    the same pair one line further up.
    """
    relay = postfix_factory(
        files={'/etc/rsyslog.d/99-test.conf': 'mail.* /var/log/from-include.log\n'})

    send(relay, subject='format from an include')
    mailpit.wait_for_message('format from an include')
    assert wait_for_file(relay, '/var/log/from-include.log', 'status=sent')

    included = [line for line in
                container_exec(relay, ["cat", "/var/log/from-include.log"]).splitlines()
                if 'postfix/' in line]

    assert included, "the include logged nothing to read a format from"
    assert all(TIMESTAMPED_MAIL_LOG_LINE.match(line) for line in included), included[:3]
    assert all(MAIL_LOG_LINE.match(line) for line in postfix_log_lines(relay)), \
        "the container log should still be the untimestamped one"


def test_an_existing_rsyslog_conf_is_left_alone(postfix_factory, mailpit):
    """A mounted /etc/rsyslog.conf replaces the generated one.

    Which also means the RSYSLOG_ variables stop doing anything, since the
    whole block that reads them is skipped.
    """
    config = ('$ModLoad imuxsock\n'
              '$WorkDirectory /var/spool/rsyslog\n'
              '*.* /var/log/mounted.log\n')

    relay = postfix_factory(files={'/etc/rsyslog.conf': config},
                            env={'RSYSLOG_LOG_TO_FILE': 'yes'})

    assert 'Skipping /etc/rsyslog.conf generating' in container_log(relay)
    assert container_exec(relay, ["cat", "/etc/rsyslog.conf"]) == config
    assert file_missing(relay, '/var/log/mail.log')

    send(relay, subject='logged as configured')
    mailpit.wait_for_message('logged as configured')

    assert wait_for_file(relay, '/var/log/mounted.log', 'status=sent')
    # Nothing was sent to stdout, the mounted configuration does not ask for it.
    assert postfix_log_lines(relay) == []


def test_messages_are_forwarded_to_a_remote_syslog_server(postfix_factory, mailpit):
    """RSYSLOG_REMOTE_HOST forwards everything, over UDP and port 514 by default.

    The receiver is the image itself with an /etc/rsyslog.d file turning on
    imudp, so the forwarding is checked by reading what actually arrived rather
    than by reading back the configuration that was written.
    """
    receiver = postfix_factory(alias='syslog-receiver', files={
        '/etc/rsyslog.d/10-receiver.conf': ('module(load="imudp")\n'
                                            'input(type="imudp" port="514")\n'
                                            '*.* /var/log/received.log\n')})
    sender = postfix_factory(env={'RSYSLOG_REMOTE_HOST': 'syslog-receiver'})

    send(sender, subject='forwarded')
    mailpit.wait_for_message('forwarded')

    received = wait_for_file(receiver, '/var/log/received.log', 'status=sent')
    # The forwarded lines carry the sending container's hostname, so this is
    # the sender's log and not the receiver's own.
    assert sender.get_wrapped_container().id[:12] in received


def test_the_remote_port_and_template_can_be_changed(postfix_factory):
    relay = postfix_factory(env={
        'RSYSLOG_REMOTE_HOST': 'syslog.example',
        'RSYSLOG_REMOTE_PORT': '5514',
        'RSYSLOG_REMOTE_TEMPLATE': 'RSYSLOG_SyslogProtocol23Format',
    })

    assert 'target="syslog.example" port="5514" ' \
           'template="RSYSLOG_SyslogProtocol23Format"' in \
        container_exec(relay, ["cat", "/etc/rsyslog.conf"])


def test_the_timezone_is_used_in_log_timestamps(postfix_factory, mailpit):
    """TZ is handled by the base image, and the README says so."""
    relay = postfix_factory(env={'TZ': 'Europe/Prague', 'RSYSLOG_TIMESTAMP': 'yes'})

    send(relay, subject='in local time')
    mailpit.wait_for_message('in local time')

    lines = postfix_log_lines(relay)

    assert lines
    # Prague is one or two hours ahead of UTC, depending on the season.
    assert all(re.search(r'T[\d:.]+\+0[12]:00 ', line) for line in lines), lines[:3]


def test_authentication_messages_are_kept_off_stdout(postfix_shared):
    """The generated configuration is "*.*;auth,authpriv.none /dev/stdout".

    saslauthd and PAM write to the auth facility, which is where a password
    can end up in a log line, so those two facilities are the ones docker
    logs does not collect. Everything else has to reach it.
    """
    relay = postfix_shared(env={'RSYSLOG_LOG_TO_FILE': 'no'})

    container_exec(relay, ["logger", "-p", "auth.info", "-t", "probe", "a login attempt"])
    container_exec(relay, ["logger", "-p", "authpriv.info", "-t", "probe", "a password"])
    container_exec(relay, ["logger", "-p", "mail.info", "-t", "probe", "a delivery"])

    log = wait_for_log(relay, 'a delivery')

    assert 'a login attempt' not in log
    assert 'a password' not in log


def test_every_line_names_the_daemon_that_wrote_it(postfix, mailpit, smtp):
    """A relay writes as five or six different programs at once, and the
    tag is the only thing that says which."""
    smtp.sendmail('sender@example.com', ['receiver@example.com'],
                  'Subject: tagged\r\n\r\nbody\r\n')
    mailpit.wait_for_message('tagged')

    tags = {line.split('[')[0] for line in postfix_log_lines(postfix)}

    assert 'postfix/smtpd' in tags
    assert 'postfix/smtp' in tags
    assert 'postfix/qmgr' in tags


def test_a_file_log_is_written_beside_the_container_log_and_not_instead_of_it(
        postfix_factory, mailpit):
    """RSYSLOG_LOG_TO_FILE adds a destination.

    A user who mounts /var/log to keep a history must not lose "docker logs"
    for it, which is where every other tool looks.
    """
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes'})

    send(relay, subject='in both places')
    mailpit.wait_for_message('in both places')

    assert wait_for_file(relay, '/var/log/mail.log', 'status=sent')
    assert postfix_log_lines(relay)


def test_a_file_log_truncated_in_place_is_written_again_from_its_start(
        postfix_factory, mailpit):
    """What copytruncate does to the file, done by hand.

    The container rotates nothing, so the README has the file rotated from the
    host with copytruncate, which works only if rsyslogd appends. One that
    wrote at the offset it had reached would put the next line after a hole as
    long as everything truncated, and the rotation would free nothing.
    Issue #30.
    """
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes'})

    send(relay, subject='before the truncation')
    mailpit.wait_for_message('before the truncation')
    wait_for_file(relay, '/var/log/mail.log', 'status=sent')

    container_exec(relay, ["truncate", "-s", "0", "/var/log/mail.log"])

    send(relay, subject='after the truncation')
    mailpit.wait_for_message('after the truncation')
    logged = wait_for_file(relay, '/var/log/mail.log', 'status=sent')

    assert '\0' not in logged
    assert logged.count('status=sent') == 1


# One logger process sends every line back to back, so rsyslogd takes them in
# batches, which is the worst case for the size of the file (see below).
FILLER = ('for i in $(seq 1 1000) ; do '
          'echo "filler line $i, to take the file log past its limit" ; done > /tmp/filler ; '
          'logger -p mail.info -f /tmp/filler')

# rsyslogd looks at the size of the file when it writes its buffer out, not at
# every line: omfile's ioBufferSize, 4096 bytes unless set. A file that is
# under the limit before a write can therefore be over it by up to one buffer
# afterwards. Lines that arrive one at a time hide that, and a loaded runner
# does not.
IO_BUFFER = 4096


def test_the_file_log_is_capped_and_keeps_the_file_before(postfix_factory):
    """Nothing else in the container rotates the file, so it is bounded by
    RSYSLOG_LOG_FILE_MAX_SIZE: at the limit it becomes mail.log.1, replacing
    the one before, and a new mail.log is started (issue #30). A small limit
    here, so a thousand lines, fifty kilobytes, go past it many times over.
    """
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes',
                                 'RSYSLOG_LOG_FILE_MAX_SIZE': '4k'})

    container_exec(relay, ["sh", "-c", FILLER])
    wait_for_file(relay, '/var/log/mail.log', 'filler line 1000')

    sizes = container_exec(relay, ["stat", "-c", "%n %s",
                                   "/var/log/mail.log", "/var/log/mail.log.1"])
    # Over the limit by up to one buffer, as IO_BUFFER says, and no more: an
    # unrotated file would hold all fifty kilobytes.
    for line in sizes.splitlines():
        name, size = line.split()
        assert int(size) <= 4096 + IO_BUFFER, sizes
    assert 'filler line' in container_exec(relay, ["cat", "/var/log/mail.log.1"])


def test_the_file_log_is_capped_at_100m_unless_told_otherwise(postfix_factory):
    """The limit is on by default, so that the file log the README shows how
    to mount cannot fill the host's disk unattended (issue #30)."""
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes'})

    config = container_exec(relay, ["cat", "/etc/rsyslog.conf"])

    assert 'rotation.sizeLimit="100m"' in config


def test_an_empty_limit_leaves_the_file_log_unbounded(postfix_factory):
    """For whoever already rotates the file from the host and wants nothing
    to move it under them."""
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes',
                                 'RSYSLOG_LOG_FILE_MAX_SIZE': ''})

    config = container_exec(relay, ["cat", "/etc/rsyslog.conf"])

    assert 'mail.* -/var/log/mail.log' in config
    assert 'sizeLimit' not in config


def test_a_limit_rsyslogd_cannot_read_stops_the_container(postfix_factory):
    """rsyslogd reads a size it does not understand as no limit at all, which
    is the one thing the setting is there to prevent, so it is refused before
    anything starts."""
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes',
                                 'RSYSLOG_LOG_FILE_MAX_SIZE': '100 MB'},
                            wait_ready=False)

    assert exit_code_within(relay, seconds=20) == 1
    assert "RSYSLOG_LOG_FILE_MAX_SIZE is '100 MB'" in container_stderr(relay)


def test_a_renamed_file_log_is_reopened_when_rsyslogd_is_sent_hup(postfix_factory, mailpit):
    """The README's other rotation: rename, then "pkill -HUP rsyslogd".

    rsyslogd goes on writing into a renamed file until it is told to reopen it,
    and HUP is how. It reopens rather than exiting, which matters as much: the
    supervision loop in run stops the relay when rsyslogd goes away. Issue #30.
    """
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes'})

    send(relay, subject='before the rename')
    mailpit.wait_for_message('before the rename')
    wait_for_file(relay, '/var/log/mail.log', 'status=sent')

    container_exec(relay, ["mv", "/var/log/mail.log", "/var/log/mail.log.1"])
    container_exec(relay, ["pkill", "-HUP", "-x", "rsyslogd"])

    send(relay, subject='after the rename')
    mailpit.wait_for_message('after the rename')

    assert wait_for_file(relay, '/var/log/mail.log', 'status=sent').count('status=sent') == 1
    assert container_exec(relay, ["cat", "/var/log/mail.log.1"]).count('status=sent') == 1
    assert process_running(relay, 'rsyslogd')
    relay.get_wrapped_container().reload()
    assert relay.get_wrapped_container().status == 'running'


def test_the_timestamp_setting_applies_to_the_file_log_too(postfix_factory, mailpit):
    """The template is set once, before both destinations are written, so
    asking for no timestamps means none anywhere -- worth knowing before
    mounting the file somewhere that has no timestamps of its own."""
    relay = postfix_factory(env={'RSYSLOG_LOG_TO_FILE': 'yes'})

    send(relay, subject='no timestamps in the file either')
    mailpit.wait_for_message('no timestamps in the file either')

    logged = wait_for_file(relay, '/var/log/mail.log', 'status=sent')
    lines = [line for line in logged.splitlines() if 'postfix/' in line]

    assert lines
    assert all(MAIL_LOG_LINE.match(line) for line in lines), lines[:3]


def test_forwarding_defaults_to_udp_on_the_standard_syslog_port(postfix_shared):
    """RSYSLOG_REMOTE_HOST on its own is the documented minimum."""
    configuration = container_exec(
        postfix_shared(env={'RSYSLOG_REMOTE_HOST': 'syslog.example'}),
        ["cat", "/etc/rsyslog.conf"])

    assert 'action(type="omfwd" target="syslog.example" port="514" ' \
           'template="RSYSLOG_ForwardFormat")' in configuration


def test_what_postfix_logs_while_it_starts_reaches_the_container_log(postfix_factory):
    """rsyslogd is up before the daemons, so the first thing they say is kept.

    Until it is, nothing listens on /dev/log and syslog(3) drops what it is
    given without an error. Master's own "daemon started" line is the first
    thing postfix logs, and it was gone: the container log began at the last
    daemon to start instead of the first (issue #11). No mail is sent, so a
    line found here was written while starting.
    """
    relay = postfix_factory()

    line = wait_for_log_line(relay, 'daemon started')

    assert line.startswith('postfix/master[')


def test_the_configuration_is_generated_once_and_kept_across_restarts(
        postfix_factory, mailpit):
    """It is written to the container's own filesystem, so the second start
    finds it and says so instead of writing it again."""
    relay = postfix_factory(env={'RSYSLOG_TIMESTAMP': 'yes'})
    generated = container_exec(relay, ["cat", "/etc/rsyslog.conf"])

    restart(relay)

    assert container_exec(relay, ["cat", "/etc/rsyslog.conf"]) == generated
    assert 'Skipping /etc/rsyslog.conf generating' in container_log(relay)

    send(relay, subject='logged after a restart')
    mailpit.wait_for_message('logged after a restart')

    # Only what the second start wrote, which begins at that line now that
    # rsyslogd comes up first. The init script's own progress text has no
    # trailing newline, so the first thing postfix logs follows it.
    restarted = container_log(relay).split('Skipping /etc/rsyslog.conf generating')[-1]
    lines = [INIT_SCRIPT_TEXT.sub('', line) for line in restarted.splitlines()]
    lines = [line for line in lines if 'postfix/' in line]

    assert lines
    assert all(TIMESTAMPED_MAIL_LOG_LINE.match(line) for line in lines), lines[:3]
