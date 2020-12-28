#!/usr/bin/python3
#importing custom lib:
import run_latest_version as run

#import default libs:
import os
import time
import re
import json
from pprint import pprint

#this sleep is used:
# by making new sessions (sleep_short * 2)
# by selecting a window, this is really buggy in the tmux api.
# by sending a file every 200 characters
sleep_short = 0.20
sleep_at_chars = 200
files = run.get_last_version_of_files('../scripts/')
# tmp_config is needed for the tinydb reader 
# tinydb reads the db with the open(file, 'a') flag.
# so its trying to open the file with rw persmissions, this will fail if it is read only.
tmp_config = "/tmp/dashboard_tinydb.json"

class Session():
    def __init__(self, session_dict, spawn_dir):
        # init of an session
        self.file_content = {}
        self.spawn_dir = spawn_dir
        self.make_session(session_dict[0]['session_name'])
        self.current_pane = 0
        spawned_tabs = {}
        win_pane = {}
        
        # loop through the session dict
        for counter, row in enumerate(session_dict):
            name = row['window_name']
            self.actual_window_name = name
            if (counter == 0):
                self.rename_window(name)
                # print(row)
                win_pane[name] = row['same_pane']
            try:
                #causes an KeyError if not available
                win_pane[name]
                if win_pane[name] != row['same_pane']:
                    self.split('v')
                    self.set_mode('even-vertical')
                win_pane[name] = row['same_pane']
            except KeyError:
                self.set_mode()
                self.new_window(name)
                win_pane[name] = row['same_pane']
            
            #dont show change dir
            #self.send_keys("clear", send_enter = True)
            if row['exec_script'] == '':
                self.send_keys(row['pre_arg'] + "\n" + ' '.join(row['args']), send_enter=row['send_enter'])
            else:
                self.send_file(row['exec_script'], send_enter=row['send_enter'], pre_arg = row['pre_arg'], args=' '.join(row['args']))
            #print(win_pane)
        self.set_mode('tiled')
        
    
    def new_window(self, name):
        self.own_os_system("(cd " + self.spawn_dir +  " ; tmux new-window" + self.dash_t() + " /bin/bash)")
        self.current_pane = 0
        self.rename_window(name)
        self.actual_window(name)
    
    def own_os_system(self, cmd):
        #print(cmd)
        os.system(cmd)
    
    def set_mode(self, mode = 'tiled'):
        output = "tmux select-layout" + self.dash_t() + "" + mode
        #print(output)
        self.own_os_system(output)
    
    def make_session(self, session_name):
        print('Making session: ' + session_name + " (manual connect: tmux attach -t " + session_name + ")")
        self.session_name = session_name
        self.kill_session()
        self.own_os_system('tmux -2 new-session -d -s ' + session_name)
    
    def kill_session(self):
        output = "tmux kill-session" + self.dash_t() + "2>/dev/null"
        #print(output)
        self.own_os_system(output)
        
    # unused function because its not 
    def select_window(self, name):
        #time.sleep(sleep_short)
        self.own_os_system("tmux select-window" + self.dash_t()[:-1] + ":" + name)
    
    def rename_window(self, name):
        self.own_os_system("tmux rename-window" + self.dash_t() + name)
        self.send_keys("cd " + self.spawn_dir, send_enter = True)
        self.own_os_system('tmux bind c new-window -c "#{pane_current_path}"')
    
    
    def actual_window(self, name):
        self.actual_window_name = name
        
    def dash_t(self):
        return ' -t ' + self.session_name + ' '
    
    def dash_t_with_pane(self):
        return ' -t ' + self.session_name + ':' + self.actual_window_name + ' '
    
    def send_keys(self, keys, send_enter=False):
        keys_to_send = keys.replace('\n', '" C-m "')
        self.send_keys_raw(keys_to_send, send_enter)
    
    def convert_quotes(self, cmd):
        filtered_cmd_rows = []
        for cmd_row in cmd.split('\n'):
            keys_to_send = ""
            keys_to_send = cmd_row.replace('"', "`echo '22' | xxd -p -r`")
            if r"\`echo '22' | xxd -p -r`" in keys_to_send:
                keys_to_send = keys_to_send.replace(r"\`echo '22' | xxd -p -r`", r"\\`echo '22' | xxd -p -r`")
            keys_to_send = keys_to_send.replace('$', '\$')
            #rightsplit last semicolon
            replace_last = keys_to_send.rsplit(';', 1)
            keys_to_send = '\;'.join(replace_last)
            
            filtered_cmd_rows.append(keys_to_send)
        return '\n'.join(filtered_cmd_rows)
        
        
    def send_keys_raw(self, cmd, send_enter=False):
        send_string = "tmux send-keys" + self.dash_t() + "\""+ cmd + "\""
        if send_enter:
            send_string += " C-m"
        self.own_os_system(send_string)
    
    # splitting the current pane
    def split(self, char):
        time.sleep(sleep_short)
        self.own_os_system("tmux split-window" + self.dash_t() + "-" + char)
        self.send_keys("cd " + self.spawn_dir, send_enter = True)
    
    def move_pane (self, from_nr, to_nr):
        send_string = "tmux movep -s " + str(from_nr) + " -t " + str(to_nr)
        print(send_string)
        self.send_keys(send_string, send_enter=True)
        
    def select_pane(self, pane_number):
        self.current_pane = pane_number
        send_string = "tmux select-pane" + self.dash_t_with_pane() + "-t " + str(pane_number)
        # print(send_string)
        self.own_os_system(send_string)
    
    def get_file_content(self, file_name_middle_part):
        # print(files.get_list())
        # path = [string for string in files.get_list() if re.match(re.compile('.*' + file_name_middle_part + '.*'), string)][0]
        path = files.get_specific_file(file_name_middle_part)
        
        try:
            retval = self.file_content[path]
        except KeyError:
            with open(path, 'r') as file:
                retval = ''.join(file.readlines())
        self.file_content[path] = retval
        return retval
    
    def send_file(self, filename, send_enter = False, auto_increase = True, pre_arg = "", args=""):
        #print(filename)
        #file_content = files.get_specific_file(filename)
        file_content = self.get_file_content(filename)
        file_content_plus_args = pre_arg + "\n" + file_content + args
        #self.select_pane(self.current_pane)
        content_converted = self.convert_quotes(file_content_plus_args)
        #print(content_converted)
        send_counter = 0
        for i in content_converted.split('\n')[:-1]:
            send_counter =+ len(i)
            if send_counter > sleep_at_chars:
                #print('sleeping')
                send_counter = 0
                time.sleep(sleep_short)
            self.send_keys(i, send_enter=True)
        self.send_keys(content_converted.split('\n')[-1], send_enter)
        #self.send_keys(content_converted, send_enter)
        
        if auto_increase:
            self.current_pane += 1 
    

# user input function 
# returns [is_valid_input, is_empty, input value] if executed normaly
def user_input(input_message):
    try:
        ret_val = input(input_message)
        if ret_val == "":
            return [True, True, ""]
        return [True, False, str(ret_val)]
    except KeyboardInterrupt:
        return [False, 0, ""]

def exit_():
    os.popen('/usr/bin/rm ' + tmp_config)
    print('\nCya next time ;)', end="")
    exit(0)

def info():
    print("This cli will (re)start sessions by the syntax:")
    print("Type:") 
    print("\tq - to close program")
    print("\ta - for spawning all tmux sessions")
    print("\t-index- for spawning a specific session")

def create_tmp():
    caller_db = files.get_specific_file('caller_db')
    # creating a temp file so you dont have to change perms.
    cp_func = 'cp ' + caller_db + " " + tmp_config
    os.popen(cp_func).readlines()
    os.popen("chmod +rw " + tmp_config).readlines()

def interactive_interface(spawn_dir):
    print("This is a program for spawning tmux processes.\n")
    create_tmp()
    db = TinyDB(tmp_config)
    query = Query()
    all_records = []
    db_table_default = db.table('_default')
    sections = []
    for i in range(len(db_table_default)):
        session = db_table_default.get(doc_id=i+1)['session_name']
        #print(str(i) , str(db_table_default.get(doc_id=i+1)))
        if not (session in sections):
            sections.append(session)
    
    number_with_sessions = []
    for counter, i in enumerate(sections):
        number_with_sessions.append([counter, i])
    
    
    while 1:
        #print(db.search(query.session_name == 'VPN'))
        print("The following sessions are available:")
        print('--------------------')
        for counter, section in enumerate(sections):
            print(counter, section)
        print('--------------------')
        info()
        selected_input = user_input("Enter the corresponding number to respawn it: ")
        if(selected_input[1]):
            print("Sorry i didn't understand that.")
            continue
        if not(selected_input[0]) or selected_input[2][0] == 'q':
            exit_()
        filterd_input_var = selected_input[2]
        if filterd_input_var[0] == 'a':
            print('Making all sessions:')
            for session in sections:
                session_json = db.search(query.session_name == session)
                Session(session_json, spawn_dir)
        else:
            try:
                print("Index selected: " + sections[int(filterd_input_var)])
                actual_db = db.search(query.session_name == sections[int(filterd_input_var)])
                Session(actual_db, spawn_dir)
                time.sleep(sleep_short * 2)
            except KeyboardInterrupt:
                exit_()
            except ValueError:
                print("Sorry i didn't understand that.")
            # except Exception as e: 
            #     print("an error has accured: " + str(e))


if __name__ == "__main__":
    from tinydb import TinyDB, Query
    path = '/tmp'
    user_path = user_input('Path to spawn tmux clients in:')
    if (not(user_path[0])):
        exit_()
    else:
        if not(user_path[1]):
            path = user_path[2]
    print('using: ' + path)
    if (os.path.isdir(path)):
        interactive_interface(path)
    print("selected path (" + str(path) + ")")
    print("doesn't exists. Exiting now.")