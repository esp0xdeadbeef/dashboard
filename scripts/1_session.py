#!/usr/bin/env python3
# `compat` is provided by the dashboard: session files are exec'd into its
# globals, so the compat helpers are already in scope here.


def spawn_main():
    """You don't  need a main function. 
Everything that starts with spawn_ will be regonised by the dashboard spawner.
"""
    main_session = renew_session(
        'main',
        # keep_session=True,
        # start_directory="/tmp/"
    )
    compat.rename_window(compat.active_window(main_session), 'programming')
    php = 'php -a\n' + \
        get_file_content(all_files["PHP_code_with_errors"]) + '\nexit'
    python = 'ipython3\n' + \
        get_file_content(
            all_files["Python_code_with_errors"]) + 'string_example)\nexit()'
    pwsh = 'pwsh\n' + \
        get_file_content(all_files["POWERSHELL_code_with_errors"]) + '\nexit'
    panes_from_list(main_session,
                    [
                        php,
                        python,
                        pwsh,
                    ],
                    send_enter=False,
                    all_unchecked=False,
                    start_directory='~/../'
                    )
    main_session.new_window()
    compat.rename_window(compat.active_window(main_session), 'socat')
    socat_v = "sleep 5\nsocat exec:'bash -li',pty,stderr,setsid,sigint,sane tcp:localhost:6666\n"
    socat_a = 'socat file:$(tty),raw,echo=0 tcp-listen:6666\n\nwhoami\nls -la\ncd /\nexit\n'
    panes_from_list(main_session,
                    [
                        socat_v,
                        socat_a
                    ],
                    send_enter=True,
                    all_unchecked=True
                    )
    wait_untill_msg(compat.active_pane(main_session), 'logout')
    main_session.new_window()
    compat.rename_window(compat.active_window(main_session), 'vim? :O')
    edit_a_test_file_with_vim = """vim /tmp/testing
i
testing :D 

"""
    panes_from_list(main_session,
                    [
                        edit_a_test_file_with_vim
                    ],
                    all_unchecked=True
                    )
    compat.send_keys(compat.active_pane(main_session), 'Escape')
    compat.send_keys(compat.active_pane(main_session), ':wq!\n')
    while not(at_end(compat.active_pane(main_session))):
        pass
    compat.send_keys(compat.active_pane(main_session), 'cat /tmp/testing\n')


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
        s_all

    all_files = get_dir_session_files()
    session_functions = natural_sort(list_potentional_sessions(dir()))
    raise("Don't run the session.py directly.")
