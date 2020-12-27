#!/usr/bin/python3

#import default libs:
import os
import time
import re
import json
from pprint import pprint

# run as admin.
if (os.geteuid() != 0):
    print('run as admin')
    os._exit(-1)

#importing custom lib:
import run_0004 as run
sleep_short = 0.20
files = run.get_last_version_of_files('scripts/')

class Session():
    def __init__(self, session_dict, spawn_dir):
        self.file_content = {}
        self.spawn_dir = spawn_dir
        #session_dict[0]
        self.make_session(session_dict[0]['session_name'])
        self.current_pane = 0
        win_pane = {}
        
        for counter, row in enumerate(session_dict):
            name = row['window_name']
            self.actual_window_name = name
            if (counter == 0):
                self.rename_window(name)
                win_pane[name] = row['pane_nr']
            try:
                #causes an KeyError if not available
                win_pane[name]
                if win_pane[name] != row['pane_nr']:
                    self.split('v')
                    self.set_mode('even-vertical')
                win_pane[name] = row['pane_nr']
            except KeyError:
                self.set_mode()
                self.new_window(name)
                win_pane[name] = row['pane_nr']
            
            if row['exec_script'] == '':
                self.send_keys(' '.join(row['args']), send_enter=row['send_enter'])
            else:
                self.send_file(row['exec_script'], send_enter=row['send_enter'], args=' '.join(row['args']))
        self.set_mode('tiled')
        
    
    def new_window(self, name):
        self.own_os_system("(cd " + self.spawn_dir +  " ; tmux new-window" + self.dash_t() + " /bin/bash)")
        self.current_pane = 0
        self.rename_window(name)
        self.actual_window(name)
    
    def own_os_system(self, cmd):
        # time.sleep(sleep_short)
        # print(cmd)
        os.system(cmd)
    
    def set_mode(self, mode = 'tiled'):
        output = "tmux select-layout" + self.dash_t() + "" + mode
        #print(output)
        self.own_os_system(output)
    
    def make_session(self, session_name):
        print('Making session: ' + session_name)
        self.session_name = session_name
        #print('tmux -2 new-session -d -s ' + session_name)
        self.kill_session()
        self.own_os_system('tmux -2 new-session -d -s ' + session_name)
    
    def kill_session(self):
        output = "tmux kill-session" + self.dash_t() + "2>/dev/null"
        #print(output)
        self.own_os_system(output)
        
    
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
        keys_to_send = cmd.replace('"', "`echo '22' | xxd -p -r`")
        if r"\`echo '22' | xxd -p -r`" in keys_to_send:
            #print(keys_to_send)
            keys_to_send = keys_to_send.replace(r"\`echo '22' | xxd -p -r`", r"\\`echo '22' | xxd -p -r`")
        keys_to_send = keys_to_send.replace('$', '\$')
        return keys_to_send
        
        
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
            with open(path) as file:
                retval = ''.join(file.readlines())
        self.file_content[path] = retval
        return retval
    
    def send_file(self, filename, send_enter = False, auto_increase = True, args=""):
        #print(filename)
        #file_content = files.get_specific_file(filename)
        file_content = self.get_file_content(filename)
        #print(file_content)
        file_content_plus_args = file_content + args
        #self.select_pane(self.current_pane)
        content_converted = self.convert_quotes(file_content_plus_args)
        send_counter = 0
        for i in content_converted.split('\n')[:-1]:
            send_counter =+ len(i)
            if send_counter > 200:
                #print('sleeping')
                send_counter = 0
                time.sleep(sleep_short)
            self.send_keys(i, send_enter=True)
        self.send_keys(content_converted.split('\n')[-1], send_enter)
        #self.send_keys(content_converted, send_enter)
        
        if auto_increase:
            self.current_pane += 1 
    


def run_from__init__(spawn_dir = '/mnt/hgfs/hacking/HTB/academy'):
    # tinydb for selecting the right order, can be edited to a dict or json.
    
    #file = get_file('1_MAIN__init__')
    file = files.get_specific_file('1_MAIN__init__')
    db = TinyDB(file)
    query = Query()
    sessions_spawned = {}
    
    for row in db.all():
        session_name = row['session_name']
        try:
            if sessions_spawned[session_name][0]:
                continue
        except KeyError:
            sessions_spawned[session_name] = [True, db.search(query.session_name == session_name)]
            actual_db = db.search(query.session_name == session_name)
            Session(actual_db, spawn_dir)
        time.sleep(sleep_short * 4)

def interactive_interface(spawn_dir = '/mnt/hgfs/hacking/devel'):
    file = files.get_specific_file('1_MAIN__init__')
    db = TinyDB(file)
    query = Query()
    all_records = []
    db_table_default = db.table('_default')
    sections = []
    for i in range(len(db_table_default)):
        session = db_table_default.get(doc_id=i+1)['session_name']
        # print(str(i) , str(db_table_default.get(doc_id=i+1)))
        if not (session in sections):
            sections.append(session)
    
    number_with_sessions = []
    for counter, i in enumerate(sections):
        number_with_sessions.append([counter, i])
    
    print("Welcome to the program for spawning tmux processes!\n")
    print("This interface will restart serviceses of your need. (type: `quit or q to close program, type a for spawning all tmux sessions`) ")
    while 1:
        #print(db.search(query.session_name == 'VPN'))
        print("The following sessions are available:")
        for counter, section in enumerate(sections):
            print(counter, section)
        selected_input = input("Enter the corresponding number to respawn it: ")
        if selected_input[0] == 'q':
            return 0
        elif selected_input[0] == 'a':
            run_from__init__(spawn_dir)
        else:
            try:
                print("selected: " + sections[int(selected_input)])
                actual_db = db.search(query.session_name == sections[int(selected_input)])
                Session(actual_db, spawn_dir)
            except Exception as e: print(e)
        #print(sections)
        
        #time.sleep(10)

if __name__ == "__main__":
    from tinydb import TinyDB, Query
    path = '/mnt/hgfs/hacking/HTB/unbalanced'
    tmp_path = input('Path to spawn tmux clients in:')
    if tmp_path != '':
        path = tmp_path
    # import sys
    # if sys.args[1]
    interactive_interface(path)
    #run_from__init__()
    # print('EOF')
