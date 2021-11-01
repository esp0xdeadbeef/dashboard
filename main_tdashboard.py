#!/usr/bin/ipython3
import ast
import json
import argparse
import string
import sys
import re
import libtmux
import os
import time


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
    if session_name:
        cmd = f"ls -vA " + scripts_location + " | grep " + session_name
    else:
        cmd = f"ls -vA " + scripts_location
    os_ex = os.popen(cmd).read().split()
    files = [i for i in os_ex if i]

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
    if not(isinstance(name, str)):
        raise "use with name is a str obj"
    session = server.find_where({"session_name": name})
    if keep_session:
        return session
    if session != None:
        session.kill_session()
    try:
        # somehow it will give an key error on arch, and return None in session.
        session = server.new_session(name,
                                     start_directory=start_directory)
    except ValueError:
        pass
    if session is None:
        # specialy for arch:
        session = server.find_where({"session_name": name})
    return session


def background_task_in_pane(pane,
                            wait_time=0.5,
                            debugging=False):
    pane.cmd('send-keys', 'C-z')
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
        pane.cmd('send-keys', 'y')
        time.sleep(1)
        pane.cmd('send-keys', "Enter")
        time.sleep(1)


def get_output(pane,
               last_command="dump_all",
               location="/tmp/tmux_output.txt",
               debugging=False,
               sleep_time=0.2,
               max_size=10**10000
               ):

    res = pane_capture(pane, size=max_size)
    time.sleep(sleep_time)

    if not(last_command == "dump_all"):
        for counter, i in enumerate(res[::-1]):
            if last_command in i:
                res = res[(len(res) - counter - 1):]
                break
    if debugging:
        print(f'writing file {location}, from keyword {last_command}')
    with open(location, 'w') as f:
        f.write('\n'.join(res))
    if debugging:
        print("wc output: " + os.popen('wc ' + location).read())
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
exercise_pane = server.find_where({'session_name': 'test'})
pane = exercise_pane.attached_pane
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
            pane.cmd("send-keys", row_to_send)
            if send_enter:
                pane.cmd("send-keys", "C-m")
                time.sleep(time_out_unchecked)
            if debugging:
                print('Unchecked, it\'s empty.')
        elif unchecked > 0:
            pane.cmd("send-keys", row_to_send)
            if send_enter:
                pane.cmd("send-keys", "C-m")
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
    for i in keys_to_send_list:
        if all_unchecked:
            keys = f"# skip check comming = 99999 #all unchecked \n{i}"
        else:
            keys = i
        send_keys_to_pane(
            session.attached_pane,
            keys,
            time_out_unchecked=0,
            send_enter_last_row=send_enter,
            debugging=debugging,

        )
        session.attached_window.select_layout('tiled')
        if keys_to_send_list[-1] != i:
            session.attached_pane.split_window(
                attach=True,
                start_directory=start_directory
            )
    session.attached_window.select_layout('tiled')


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
        res_cmd = "tmux capture-pane -t " + \
            pane.session.name + " -p -S -" + str(size)
        len_cmd = "tmux capture-pane -t " + \
            pane.session.name + " -p -S -" + str(size + 2)
        while res == []:
            res = os.popen(res_cmd).read()[:-1].split('\n')
        if raw:
            return res
        len_ = os.popen(len_cmd).read()[:-1].split('\n')
        if len(res) == len(len_):
            for counter, i in enumerate(res[::-1]):
                if i != '':
                    break
            if counter != 0:
                reshape_to_no_spaces_at_back = (counter * -1)
                if debugging:
                    print(f"res before reshap: {res}")
                res = res[:reshape_to_no_spaces_at_back]
                if debugging:
                    print(
                        f"len(res): {len(res)}, len(len_): {len(len_)}, res: {res}, counter: {counter}")

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
    return server.find_where({'session_name': session_name}).attached_pane


def at_end(pane,
           time_out=1,
           debugging=False,
           send_enter_to_check_if_interpreter=True):
    """
exercise_pane = server.find_where({'session_name': 'main'})
pane = exercise_pane.attached_pane
at_end(pane, time_out=1, debugging=True, send_enter_to_check_if_interpreter=True)
    """

    global interpreters
    no_interpreters = [string.ascii_lowercase, "'", '"', "|", ',', ';']

    if debugging:
        print('{at_end}', end="; ")
    pane_c = pane_capture(pane)[-1]
    if pane_c == "":
        if debugging:
            print(f'"{pane_c}" == ""')
        return False

    for i in no_interpreters:
        if i in pane_c:
            if debugging:
                print(f'"{i}" == "{pane_c}"')
            return False

    if debugging:
        print('send-keys', '-N', f'{len(string.ascii_lowercase * 2)}', 'C-?')
    pane.cmd('send-keys', '-N', f'{len(string.ascii_lowercase * 2)}', 'C-?')

    for interpreter in interpreters:
        if interpreter in pane_c:
            if interpreter == pane_c or interpreter == pane_c[:-1]:
                if debugging:
                    print('Interpreter is in pane and in the right position.')
                return True

    if debugging:
        print(f"new potentional interpreter {pane_c}", interpreters)
    if debugging:
        print('{at_end}', end="; ")
    pane.cmd('send-keys', string.ascii_lowercase)
    time.sleep(time_out)
    last_call = "".join(pane_capture(
        pane))[-len(string.ascii_lowercase):]
    if not(string.ascii_lowercase in last_call):
        if debugging:
            print("at_end: False {not(ascii_letters in " + last_call + ")")
        pane.cmd('send-keys', '-N', f'{len(string.ascii_lowercase)}', 'C-?')
        return False

    pane.cmd('send-keys', '-N', f'{len(string.ascii_lowercase)}', 'C-?')
    time.sleep(time_out)
    if send_enter_to_check_if_interpreter:
        if debugging:
            print("Sending an enter to double check.")
        pane.cmd('send-keys', 'C-m')
        time.sleep(time_out)
    if pane_capture(pane)[-1] == pane_c:
        if debugging:
            print(
                f'at_end added {pane_c} to the interpreters ({interpreters})')
        interpreters.append(pane_c)
        return True
    else:
        if debugging:
            print("at_end: Didn't catch the same cli.")
        return False


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
    pane.cmd("send-keys", row_to_send)
    pane.cmd("send-keys", "C-m")
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
            os.system('clear')
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
        exec_function = f"{call_direct}()"
        if call_direct == "":
            exec_function = session_functions[int(id)] + '()'
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
            name_pane = renew_session(
                name,
                keep_session=True
            ).attached_pane

            print(f'Starting {func}')
            exec(func) in globals(), locals()
        else:
            print(f"Trying to get active_pane of {name}")
            try:
                name_pane = server.find_where(
                    {"session_name": name}).attached_pane
                pane_name_as_var = f'global {name}_pane; {name}_pane = name_pane'
                exec(pane_name_as_var) in globals(), locals()
                continue
            except AttributeError:
                print(f'Starting {func} because its not spawned yet')
                exec(func) in globals(), locals()
                name_pane = renew_session(
                    name,
                    keep_session=True
                ).attached_pane
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


if __name__ == '__main__':
    # set the maximum depth as 1500
    sys.setrecursionlimit(15000)
    args = parse_args()
    interpreters = args.interpreters
    server = libtmux.Server()
    location = args.session_file

    user_functionality = get_file_content(location).\
        rsplit('if __name__ == "__main__":', -1)[0]
    exec(user_functionality)

    session_functions = natural_sort(
        list_potentional_sessions(dir())
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
        session_struct = {'session_name': name}
        full_command = f"{named_pane} = server.find_where({session_struct}).attached_pane"
        exec(full_command)
    # interactive ipython3 session.
