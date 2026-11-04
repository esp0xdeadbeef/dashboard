#!/usr/bin/env python3
# msf session example for the tmux dashboard.
#
# `compat` and `termstate` are provided by the dashboard: session files are
# exec'd into its globals, so the helpers are already in scope here.
#
# Everything here stays on localhost. It exercises the parts of the dashboard
# that are easy to get wrong:
#   * a REPL that takes 10-30s to become usable (msfconsole)
#   * a REPL that owns the tty forever, so "is the shell at a prompt" is never
#     the right question (msfconsole again)
#   * a non-interactive tool that just exits (msfvenom)
#   * a silent reader that prints no prompt at all (cat / nc)
#
# Determinable state is what matters: the dashboard must know when each pane
# is actually ready before sending the next line.


def spawn_msf():
    """msfconsole drive-by: wait for the prompt, run a command, background it.

    The interesting line is the `# wait_untill=` directive: it blocks until
    the string appears in the pane, which works regardless of what the prompt
    looks like.
    """
    session = renew_session(
        'msf',
        start_directory='~/../',
    )
    compat.rename_window(compat.active_window(session), 'console')

    # msfconsole prints a banner and a `msf6 >` prompt; the dashboard must not
    # type into it until it is actually reading input.
    msf = 'msfconsole -q\n' \
        '# wait_untill=msf6 >\n' \
        'version\n' \
        '# wait_untill=Framework Version\n' \
        'exit\n'

    panes_from_list(
        session,
        [msf],
        send_enter=False,
        all_unchecked=False,
        start_directory='~/../',
    )


def spawn_msfvenom():
    """msfvenom is non-interactive: it prints, exits, and must not hang.

    This is the opposite failure mode to msfconsole. If `at_end` were still
    keystroke-probing, it would be typing into a pane that is running a
    one-shot command.
    """
    session = renew_session('payload', start_directory='~/../')
    compat.rename_window(compat.active_window(session), 'msfvenom')

    gen = (
        'msfvenom -p linux/x64/shell_reverse_tcp '
        'LHOST=127.0.0.1 LPORT=4444 -f elf -o /tmp/msf_test.elf\n'
        '# wait_untill=Payload size\n'
        'ls -l /tmp/msf_test.elf\n'
        'file /tmp/msf_test.elf\n'
        'rm -f /tmp/msf_test.elf\n'
    )

    panes_from_list(
        session,
        [gen],
        send_enter=False,
        all_unchecked=False,
        start_directory='~/../',
    )


def spawn_silent_readers():
    """Programs that wait for input while printing nothing at all.

    `smbclient`, `ftp`, `mysql -p`, and a bare `cat` all look like this: the
    pane is blank but the program is consuming keystrokes. Screen-scraping
    cannot detect this; the tty owner + wchan check can.
    """
    session = renew_session('readers', start_directory='~/../')
    compat.rename_window(compat.active_window(session), 'silent')

    # `cat` reads stdin forever and echoes nothing when given no tty content.
    reader = 'cat\n'
    quiet = 'sh -c "read x; echo got:$x"\n'

    panes_from_list(
        session,
        [reader, quiet],
        send_enter=False,
        all_unchecked=False,
        start_directory='~/../',
    )


if __name__ == "__main__":
    from main_tdashboard import (
        compat, termstate,
        natural_sort,
        get_file_content,
        get_dir_session_files,
        list_potentional_sessions,
        renew_session,
        background_task_in_pane,
        get_output,
        send_keys_to_pane,
        wait_untill_msg,
        panes_from_list,
        pane_capture,
        send_file_to_pane,
        get_attached_pane,
        at_end,
        checked_cmd,
        interactive_dashboard,
        find_str_in_history,
        s_all,
    )
    raise SystemExit("Don't run the session.py directly; run main_tdashboard.py")
