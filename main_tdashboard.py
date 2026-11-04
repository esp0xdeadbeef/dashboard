#!/usr/bin/env python3
import argparse
import string
import sys
import re
import subprocess
import os
import time

import libtmux

import compat
import termstate


def run(cmd_args, check=True, capture=True):
    """Run a command as an argument list (never a shell string).

    Replaces the original os.popen()/os.system() calls, which concatenated
    paths into a shell command and swallowed all errors.
    """
    result = subprocess.run(
        cmd_args,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd_args)}"
            + (f"\nstderr: {result.stderr}" if result.stderr else "")
        )
    return result


def natural_sort(l):
    # used from  here:
    # https://stackoverflow.com/questions/4836710/is-there-a-built-in-function-for-string-natural-sort
    def convert(text):
        return int(text) if text.isdigit() else text.lower()

    def alphanum_key(key):
        return [convert(c) for c in re.split('([0-9]+)', key)]
    return sorted(l, key=alphanum_key)


def get_file_content(file_path):
    with open(file_path, 'r') as f:
        return f.read()


def get_scripts_location(path):

    if os.path.exists(path):
        return True
    else:
        return False


def get_dir_session_files(scripts_location, session_name=None):
    if not os.path.isdir(scripts_location):
        raise FileNotFoundError(
            f"scripts directory not found: {scripts_location}")
    cmd = ["ls", "-vA", scripts_location]
    os_ex = run(cmd).stdout.split()
    files = [i for i in os_ex if i]
    if session_name:
        files = [i for i in files if session_name in i]

    files_to_get = {}

    for f in files:
        curr_file = '_'.join(f.split('_')[:-1])
        files_to_get[curr_file] = f"{scripts_location}/{f}"

    return files_to_get


def list_potentional_sessions(all_functions):
    spawn_list = []
    for _function in all_functions:
        if 'spawn_' in _function:
            spawn_list.append(_function)
    return spawn_list


def renew_session(name,
                  keep_session=False,
                  start_directory='~'):
    """ 
    Returns an session object
    """
    if not isinstance(name, str):
        raise TypeError("name must be a str")
    session = compat.get_session(server, name)
    if keep_session:
        return session
    if session is not None:
        compat.kill_session(session)
    try:
        session = server.new_session(name,
                                     start_directory=start_directory)
    except ValueError:
        pass
    if session is None:
        # some tmux versions report an otherwise-successful creation here.
        session = compat.get_session(server, name)
    return session


def background_task_in_pane(pane,
                            wait_time=0.5,
                            debugging=False):
    compat.send_keys(pane, 'C-z')
    wait_time_total = 0
    backgrounded_task = False
    interpreter = False
    while wait_time_total < wait_time and not(backgrounded_task) and not(interpreter):
        last_cap = pane_capture(pane, debugging=debugging)[-1].lower()
        if debugging:
            print("{background_task_in_pane}", end=", ")
            print("trying to find background (y or n question) or interpeter in pane")
        if "background" in last_cap or "y/N" in last_cap:
            backgrounded_task = True
            if debugging:
                print("{background_task_in_pane}", end=", ")
                print("found background in text.")
        for i in interpreters:
            if i.lower() == last_cap and "Z^" not in last_cap:
                if debugging:
                    print("{background_task_in_pane}", end=", ")
                    print(f"({i.lower()} == {last_cap})" +
                          " found interpreter in text.")
                interpreter = True
        wait_time_total += (wait_time / 10)

        time.sleep((wait_time / 10))
    if backgrounded_task:
        time.sleep(1)
        compat.send_keys(pane, 'y')
        time.sleep(1)
        compat.send_keys(pane, "Enter")
        time.sleep(1)


def get_output(pane,
               last_command="dump_all",
               location="/tmp/tmux_output.txt",
               debugging=False,
               sleep_time=0.2,
               max_size=10**8
               ):

    res = pane_capture(pane, size=max_size)

    if not(last_command == "dump_all"):
        for counter, i in enumerate(res[::-1]):
            if last_command in i:
                res = res[(len(res) - counter - 1):]
                if debugging:
                    print(f'Breaking because found {last_command}')
                break
    if debugging:
        print(f'writing file {location}, from keyword {last_command}')
    with open(location, 'w') as f:
        f.write('\n'.join(res))
    if debugging:
        print(f"len of res: {len(res)}")
        print("wc output: " + run(["wc", location]).stdout)
    return res


def send_keys_to_pane(pane,
                      script_content,
                      time_out_checked=0.1,
                      time_out_unchecked=0.1,
                      skip_check_chars="# skip check comming = ",
                      in_file_exec_function="# exec ",
                      append_file="# append ",
                      wait_untill_string="# wait_untill=",
                      safe_last_output_to_file="# safe_last_output_to_file=",
                      bg_task_in_pane="# background task in pane",
                      send_enter_last_row=True,
                      debugging=False):
    """
exercise_pane = compat.require_session(server, 'test')
pane = compat.active_pane(exercise_pane)
send_keys_to_pane(pane, get_file_content(all_files["test"]))
    """
    unchecked = 0
    content = script_content.split('\n')

    last_row_send = ""
    for counter, row_to_send in enumerate(content):
        send_enter = counter != (len(content) - 1) and send_enter_last_row
        if debugging:
            print("{send_keys_to_pane}", end=", ")
            print(f"row_to_send = {row_to_send}", end="; ")
            print(f"unchecked = {str(unchecked)}", end="; ")
            print(f"send_enter = {str(send_enter)}")
        if in_file_exec_function in row_to_send:
            exec_function = row_to_send.split(in_file_exec_function)[1]
            exec(exec_function) in globals(), locals()
            continue
        if bg_task_in_pane in row_to_send:
            background_task_in_pane(pane)
            continue
        if safe_last_output_to_file in row_to_send:
            while not(at_end(pane)):
                print("{send_keys_to_pane}: waiting untill at_end")
                time.sleep(time_out_checked)
                pass
            safe_location = row_to_send.split(safe_last_output_to_file)[1]
            if debugging:
                print(
                    f'safe_location = "{safe_location}", last_row_send  = "{last_row_send}"')
            get_output(pane,
                       last_command=last_row_send,
                       debugging=True,
                       location=safe_location
                       )
            continue
        if append_file in row_to_send:
            file_in_dict = row_to_send.split(append_file)[1]
            if debugging:
                print('trying to add file_in_dict after this line.')
            for row_2_counter, row_in_file in enumerate(get_file_content(get_dir_session_files(args.scripts)[file_in_dict]).split('\n')):
                if debugging:
                    print(f'adding this line now: {row_in_file}')
                content.insert(row_2_counter + counter+1, row_in_file)
            continue
        if skip_check_chars in row_to_send:
            unchecked = int(row_to_send.split(
                skip_check_chars)[1].split('#')[0])
            continue
        if wait_untill_string in row_to_send:
            string_to_wait_for = row_to_send.split(
                wait_untill_string)[1].split('#')[0]
            wait_untill_msg(pane, string_to_wait_for)

            continue
        if row_to_send == "":
            compat.send_keys(pane, row_to_send)
            if send_enter:
                compat.send_keys(pane, "C-m")
                time.sleep(time_out_unchecked)
            if debugging:
                print('Unchecked, it\'s empty.')
        elif unchecked > 0:
            compat.send_keys(pane, row_to_send)
            if send_enter:
                compat.send_keys(pane, "C-m")
                time.sleep(time_out_unchecked)
            if debugging:
                print('Unchecked, requested by user.')
            unchecked -= 1
            last_row_send = row_to_send
        else:
            if debugging:
                print("{send_keys_to_pane}: checked_cmd: ")
            checked_cmd(pane,
                        row_to_send,
                        last_row_send,
                        time_out=time_out_checked,
                        # send_enter_last_row=send_enter,
                        # send_enter=send_enter,
                        debugging=debugging
                        )
            last_row_send = row_to_send
            if debugging:
                print("Checked.")


def wait_untill_msg(pane,
                    message,
                    time_out=0.2,
                    safe_output=None):
    while 1:
        if message in ''.join(pane_capture(pane)):
            break
        else:
            time.sleep(time_out)


def panes_from_list(session,
                    keys_to_send_list,
                    send_enter=True,
                    debugging=False,
                    all_unchecked=True,
                    start_directory=None):
    # Session.active_window / active_pane return freshly-queried objects, but
    # splitting with attach=True makes libtmux's cached window handle stale
    # ("can't find window: @N"), so re-resolve the session each iteration.
    def fresh():
        return compat.require_session(
            compat.reconnect(session.server), session.session_name)

    for i in keys_to_send_list:
        if all_unchecked:
            keys = f"# skip check comming = 99999 #all unchecked \n{i}"
        else:
            keys = i
        cur = fresh()
        send_keys_to_pane(
            compat.active_pane(cur),
            keys,
            time_out_unchecked=0,
            send_enter_last_row=send_enter,
            debugging=debugging,

        )
        compat.select_layout_for(fresh(), session.session_name, 'tiled')
        if keys_to_send_list[-1] != i:
            compat.split_pane(fresh(), session.session_name,
                              attach=True,
                              start_directory=start_directory)
    compat.select_layout_for(fresh(), session.session_name, 'tiled')


def pane_capture(pane,
                 size=15,
                 old_method=False,
                 debugging=False,
                 raw=False
                 ):
    res = []
    if old_method:
        res = pane.cmd('capture-pane', '-p',
                       '-S',  "-" + str(size)).stdout
    else:
        res_cmd = ["tmux", "capture-pane", "-t", pane.session.name,
                   "-p", "-S", "-" + str(size)]
        len_cmd = ["tmux", "capture-pane", "-t", pane.session.name,
                   "-p", "-S", "-" + str(size + 2)]
        while res == []:
            out = run(res_cmd).stdout
            res = out[:-1].split('\n') if out else []
    if raw:
        return res
    len_ = run(len_cmd).stdout[:-1].split('\n')
    if len(res) == len(len_):
        for counter, i in enumerate(res[::-1]):
            if i != '':
                break
        if counter != 0:
            reshape_to_no_spaces_at_back = (counter * -1)
            if debugging:
                dbg = f"res before reshap: {res}"
                print(dbg)
            res = res[:reshape_to_no_spaces_at_back]
            if debugging:
                dbg = f"len(res): {len(res)}, len(len_): {len(len_)}, res: {res}, counter: {counter}"
                print(dbg)

    return res


def send_file_to_pane(pane, file_name, skip_checking=False):
    if skip_checking:
        prefix_file = '# skip check comming = 99999\n'
    else:
        prefix_file = ""
    file_content = prefix_file + \
        get_file_content(get_dir_session_files(args.scripts)[file_name])
    send_keys_to_pane(pane, file_content)


def get_attached_pane(server, session_name="main"):
    return compat.active_pane(compat.require_session(server, session_name))


def at_end(pane, time_out=1, debugging=False,
           send_enter_to_check_if_interpreter=True):
    """True when the program in `pane` is blocked waiting for terminal input.

    Previous implementation typed 52 characters of junk into the pane, erased
    them, sent C-m, and compared the screen against a global list of
    remembered "interpreter" strings. That failed on the cases that matter
    (silent readers like smbclient/mysql print nothing to match; remote shells
    have arbitrary prompts; msfconsole is never "the shell") and it mutated
    the pane it was measuring.

    This asks the kernel instead: find the process that owns the pane's tty,
    then check whether it is blocked in a read. No keystrokes are sent.

    The arguments after `pane` are kept for call-site compatibility with the
    old probing version and are ignored.
    """
    target = pane.pane_id if hasattr(pane, "pane_id") else str(pane)
    state = termstate.pane_state(target)
    if debugging:
        print(f"{{at_end}} {termstate.describe(target)}")
    # ready = the tty owner wants input. safe_to_send additionally keeps a
    # command line out of a password / pager / yes-no prompt.
    return state.ready and state.safe_to_send


def checked_cmd(pane,
                row_to_send,
                last_row_send,
                time_out=1,
                debugging=False):
    while 1:
        try:
            if (len(last_row_send) > 5) and last_row_send == "".join(pane_capture(pane))[len(last_row_send):]:
                print("{checked_cmd}, last command still in last row")
                continue
        except KeyError:
            if debugging:
                print('{checked_cmd}, KEY ERROR, checked_cmd')
        if at_end(pane, debugging=debugging):
            if debugging:
                print('{checked_cmd} breaked while at_end loop')
            break
        if last_row_send is None:
            break

        if debugging:
            print('{checked_cmd} sleeping at_end = False')
        time.sleep(time_out)
    compat.send_keys(pane, row_to_send)
    compat.send_keys(pane, "C-m")
    time.sleep(time_out)


def interactive_dashboard(session_functions, debugging):
    while 1:
        global all_files
        all_files = get_dir_session_files(args.scripts)
        # print(session_functions)
        for counter, i in enumerate(session_functions):
            print(counter, "=", i)
        print("a = spawn all")
        print("exit/quit = quit app")
        id = input('id to spawn or name to spawn: ')
        if id == "":
            continue
        if id == "quit" or id == "exit":
            exit()
            break
        if not(debugging):
            run(['clear'], check=False, capture=False)
        print('id to spawn or name to spawn: ' + id)
        if "all" == id or "a" == id:
            for i in session_functions:
                start = f"{i}()"
                print(f"interactive_dashboard: start {start}")
                exec(start)

        call_direct = ""
        list_of_spawn = ["_".join(i.split('_')[1:])
                         for i in session_functions]
        for counter, spawn in enumerate(list_of_spawn):
            if id in spawn:
                call_direct = session_functions[counter]
                break
        if call_direct == "":
            # Bare number selects by index; anything else is a typo. The
            # original called int(id) unconditionally here, which raised
            # ValueError for out-of-range or non-numeric input.
            if not id.isdigit() or int(id) >= len(session_functions):
                print(f"no session matches {id!r}; try a number 0-"
                      f"{len(session_functions) - 1} or a name")
                continue
            call_direct = session_functions[int(id)]
        exec_function = f"{call_direct}()"
        print(exec_function)
        exec(exec_function)


def find_str_in_history(string_to_find, pane, steps=50):
    found = False
    size_m = -1
    while not(found):
        pane_cap = "\n".join(pane_capture(pane, size_m))
        if string_to_find in pane_cap:
            found = not(found)
        else:
            size_m += steps
    pane_cap = pane_cap.split('\n')
    pane_cap.reverse()
    for counter, row in enumerate(pane_cap):
        print(counter, row)
        if string_to_find in row:
            result_counter = len(pane_cap) - counter
            break
    return result_counter


# unused in script but easy for cli
def s_all(respawn_all=True):
    for session_function in session_functions:
        name = f"{session_function.split('_')[-1]}"
        func = f"{session_function}()"
        if respawn_all:
            name_pane = compat.active_pane(renew_session(
                name,
                keep_session=True
            ))

            print(f'Starting {func}')
            exec(func) in globals(), locals()
        else:
            print(f"Trying to get active_pane of {name}")
            try:
                name_pane = compat.active_pane(
                    compat.require_session(server, name))
                pane_name_as_var = f'global {name}_pane; {name}_pane = name_pane'
                exec(pane_name_as_var) in globals(), locals()
                continue
            except AttributeError:
                print(f'Starting {func} because its not spawned yet')
                exec(func) in globals(), locals()
                name_pane = compat.active_pane(renew_session(
                    name,
                    keep_session=True
                ))
        exec(f'{name}_pane = name_pane') in globals(), locals()


def parse_args():
    default_interpreters = [
        '>',
        r'PS C:\Windows\system32>',
        r'C:\Windows\system32',
        'meterpreter >',
        'mimikatz #',
        '└─#',
        '└─$',
        '▶'
    ]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session-file",
        help="configuration file, check the scripts directory if you dont know how to make one.",
        default="scripts/1_session.py",
        type=str
    )
    parser.add_argument(
        "--additional-interpreters",
        nargs='+',
        action='append',
        type=str,
        help="List of interpreters"
    )
    var = False
    parser.add_argument(
        '-i',
        '--interactive',
        help="""is interactive shell, 
if used, 
    it will spawn an interactive shell. 
if not used, 
    all sessions will be spawned.
""",
        action='store_const',
        default=var,
        const=not(var)
    )
    parser.add_argument(
        'scripts',
        help="location of the script called inside the session.py",
        type=str
    )
    args = parser.parse_args()
    args.interpreters = default_interpreters
    if isinstance(args.additional_interpreters, list):
        for i in args.additional_interpreters:
            if i == '':
                continue
            [args.interpreters.append(j) for j in i]
    return args


def main():
    global interpreters, server, all_files, args
    sys.setrecursionlimit(15000)

    # Refuse root before touching tmux: a tmux server is per-user, so a
    # root-run dashboard spawns into a different server and leaves root-owned
    # files behind. See AGENTS.md, "Run as a normal user".
    try:
        compat.assert_not_root()
        compat.assert_env_sane()
        compat.check_libtmux_version()
    except compat.CompatError as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 2

    args = parse_args()
    interpreters = args.interpreters
    server = connect_server()
    location = args.session_file

    # The session file is exec'd into module globals (not main()'s locals) so
    # that (a) spawn_* functions defined there become module-level names the
    # spawner can find, and (b) `dir()` below sees them. exec'ing into locals
    # would hide them from both.
    user_functionality = get_file_content(location).\
        rsplit('if __name__ == "__main__":', -1)[0]
    exec(compile(user_functionality, location, "exec"), globals())

    # dir(globals()) would list dict's own attributes; the spawn_* names live
    # in the dict itself, so pass the mapping's keys.
    session_functions = natural_sort(
        list_potentional_sessions(globals())
    )
    if args.interactive:
        interactive_dashboard(
            session_functions,
            debugging=True
        )
    else:
        all_files = get_dir_session_files(args.scripts)
        s_all(respawn_all=False)

    for session_function in session_functions:
        name = f"{session_function.split('_')[-1]}"
        named_pane = name + "_pane"
        session = compat.get_session(server, name)
        if session is None:
            continue
        globals()[named_pane] = compat.active_pane(session)

    # Leftover REPL for convenience: `python3 -i main_tdashboard.py ...`
    # exposes the pane_<name> variables bound above. Use plain `-i`, not
    # ipython: the original `#!/usr/bin/ipython3` shebang does not exist on
    # most systems and added a hard dependency for no gain.
    return 0


def connect_server():
    """Connect to this user's tmux server, with a clear error if absent."""
    try:
        return compat.connect()
    except Exception as exc:
        raise compat.CompatError(
            f"cannot reach the tmux server: {exc}\n"
            f"Start one as your normal user first (run `tmux`), and make sure "
            f"you are not inside an su/sudo shell."
        ) from exc


if __name__ == '__main__':
    try:
        sys.exit(main())
    except compat.CompatError as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        sys.exit(2)
