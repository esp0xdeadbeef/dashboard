#!/usr/bin/env python3
# `compat` is provided by the dashboard: session files are exec'd into its
# globals, so the compat helpers are already in scope here.
#
# This is the tutorial session: it drives a few interactive languages, a
# socat relay, and vim, so you can see the spawner work end to end.
#
# Two rules a session file should follow, learned the hard way:
#
#   1. Do not end a pane's content with `exit`. A window dies with its last
#      pane, and a session dies with its last window -- so `exit` in every
#      pane deletes the session you just built (and the dashboard, which is
#      still holding it, fails on the next step).
#   2. Do not assume an interpreter is installed. This file checks with
#      `command -v` and says so in the pane instead of filling the window with
#      "command not found". Pass `--target HOST` to run the same checks on the
#      remote host, since that is where they are evaluated.


import time


def _has(program, fallback_message, command=None):
    """Shell fragment that runs `command`, or explains that `program` is absent."""
    run = command or program
    return (f"command -v {program} >/dev/null 2>&1 && {run} || "
            f"printf '%s\\n' {fallback_message!r}")


def _demo(program, body, skip_message, command=None):
    """Shell script running `body` *inside* `program`, or saying it is absent.

    `body` is the interpreter's own source (PHP, Python, PowerShell), so it
    must never reach a plain shell: a missing interpreter would then make
    every following line a shell command, and the pane fills with unrelated
    errors that look like the dashboard misfired. The here-document is fed to
    the interpreter on stdin, so the body is never shell input.
    """
    run = command or program
    return (
        f"if command -v {program} >/dev/null 2>&1; then\n"
        f"  {run} <<'__DASHBOARD_DEMO__'\n"
        f"{body}\n"
        f"__DASHBOARD_DEMO__\n"
        f"else\n"
        f"  printf '%s\\n' {skip_message!r}\n"
        f"fi"
    )


def spawn_main():
    """You don't  need a main function.
Everything that starts with spawn_ will be regonised by the dashboard spawner.
"""
    main_session = renew_session(
        'main',
        # keep_session=True,
        # start_directory="/tmp/"
    )
    # Name the window that renew_session created. Using
    # `rename_window(active_window(session))` looks equivalent but is not:
    # `active_window()` on a stale handle reports the *previous* window, so
    # with two windows open the rename silently lands on the wrong one.
    window = compat.window_id_named(main_session.session_name, 'tmux') \
        or compat.windows_of_session(main_session.session_name)[0][0]
    compat.rename_window(
        compat.window_by_id(window), 'programming')

    # Each pane runs one interpreter, feeds it the matching file from
    # scripts/, and then returns to the shell *without* exiting it: the pane
    # must survive so the window does.
    php = _demo("php",
                get_file_content(all_files["PHP_code_with_errors"]),
                "php is not installed; skipping the PHP demo",
                command="php -a")
    ipython = _demo(
        "ipython3",
        get_file_content(all_files["Python_code_with_errors"])
        + "string_example)",
        "ipython3 is not installed; skipping the Python demo",
        command="ipython3 -i")
    pwsh = _demo("pwsh",
                 get_file_content(all_files["POWERSHELL_code_with_errors"]),
                 "pwsh is not installed; skipping the PowerShell demo")

    panes_from_list(main_session,
                    [
                        php,
                        ipython,
                        pwsh,
                    ],
                    send_enter=False,
                    all_unchecked=False,
                    start_directory='~/../'
                    )

    socat_window = compat.new_window_named(main_session, 'socat')
    # The listener and the client are both driven here, so the relay is
    # exercised without needing a second machine. `socat` is often absent, so
    # fall back to a plain nc-less demo rather than printing errors.
    socat_v = ("sleep 2\n"
               + _has("socat",
                      "socat not installed: skipping the relay demo") + "\n"
               "socat exec:'bash -li',pty,stderr,setsid,sigint,sane "
               "tcp:localhost:6666\n")
    socat_a = (_has("socat",
                    "socat not installed: skipping the relay demo") + "\n"
               'socat file:$(tty),raw,echo=0 tcp-listen:6666\n'
               'whoami\nls -la\ncd /\n')
    panes_from_list(main_session,
                    [
                        socat_v,
                        socat_a
                    ],
                    send_enter=True,
                    all_unchecked=True
                    )
    # Best effort: if the relay never logs back in (socat missing, or a
    # listener that did not bind), move on rather than hang forever. This used
    # to loop with no deadline, which looked exactly like "still working".
    wait_untill_msg(compat.active_pane_of_window(socat_window), 'logout',
                    timeout=10)

    vim_window = compat.new_window_named(main_session, 'vim? :O')

    # This window is driven step by step rather than through panes_from_list
    # with all_unchecked=True. A single "vim ... \n i \n text" blast races
    # the editor's startup: the `i` (and worse, the Escape) can arrive while
    # the shell is still launching vim, so they are echoed as literal text and
    # the buffer is never written. Waiting for each state is both correct and
    # the only way to show what the dashboard's detection is for.
    #
    # Target the window we created: `active_pane(main_session)` is a stale
    # handle and resolves to whichever window the session had active before,
    # which sent the keystrokes into the *programming* window instead.
    vim_pane = compat.active_pane_of_window(vim_window)

    # `-n` (no swap file) is essential for an unattended edit: a leftover swap
    # file turns startup into an interactive "Swap file exists!" prompt, which
    # swallows everything that follows.
    compat.send_keys(vim_pane, 'vim -n /tmp/testing')
    compat.send_keys(vim_pane, 'C-m')
    # Wait for vim to take over the pane before typing into it.
    wait_untill_msg(vim_pane, '/tmp/testing', timeout=10)

    compat.send_keys(vim_pane, 'i')
    compat.send_keys(vim_pane, 'testing :D ')
    compat.send_keys(vim_pane, 'C-m')
    compat.send_keys(vim_pane, '')
    time.sleep(0.3)

    compat.send_keys(vim_pane, 'Escape')
    time.sleep(0.3)
    compat.send_keys(vim_pane, ':wq!')
    compat.send_keys(vim_pane, 'C-m')

    # Back at the shell once vim has exited (its :wq! leaves the prompt). Then
    # report what was actually written, which is the point of the demo.
    deadline = time.time() + 10
    while time.time() < deadline and not at_end(vim_pane):
        time.sleep(0.2)
    compat.send_keys(vim_pane, 'cat /tmp/testing')
    compat.send_keys(vim_pane, 'C-m')


if __name__ == "__main__":
    """this functions are not usefull for anything, don't run this function directly. Void import will make syntaxhighlighting working in vscode. Nothing more."""

    from main_tdashboard import natural_sort,\
        get_file_content,\
        get_dir_session_files, \
        list_potentional_sessions,\
        renew_session,\
        background_task_in_pane,\
        get_output,\
        send_keys_to_pane,\
        wait_untill_msg,\
        panes_from_list,\
        pane_capture,\
        send_file_to_pane,\
        get_attached_pane,\
        at_end,\
        checked_cmd,\
        interactive_dashboard,\
        find_str_in_history,\
        s_all,\
        _demo

    all_files = get_dir_session_files()
    session_functions = natural_sort(list_potentional_sessions(dir()))
    raise("Don't run the session.py directly.")
