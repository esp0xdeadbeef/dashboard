#!/usr/bin/python3


def spawn_main():
    """You don't  need a main function. 
Everything that starts with spawn_ will be regonised by the dashboard spawner.
"""
    main_session = renew_session('main')
    main_session.attached_window.rename_window('programming')
    php = 'php -a\n' + all_files["PHP_code_with_errors"] + '\nexit'
    python = 'ipython3\n' + \
        all_files["Python_code_with_errors"] + 'string_example)\nexit()'
    pwsh = 'pwsh' + all_files["POWERSHELL_code_with_errors"] + '\nexit'
    pane = main_session.attached_pane
    panes_from_list(pane,
                    [
                        php,
                        python,
                        pwsh,
                    ],
                    send_enter=False
                    )
    main_session.new_window()
    main_session.attached_window.rename_window('socat')
    panes_from_list(main_session.attached_pane,
                    [
                        all_files["socat_attacker"],
                        all_files["socat_victim"]
                    ],
                    send_enter=False
                    )
    main_session.new_window()
    main_session.attached_window.rename_window('tryout')
    panes_from_list(main_session.attached_pane,
                    [
                        all_files["functions_tryout"]
                    ],
                    send_enter=False
                    )


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
