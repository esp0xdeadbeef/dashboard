#!/usr/bin/python3

import os
if (os.geteuid() != 0):
    print('run as admin')
    os._exit(-1)

from tinydb import TinyDB, Query
from pprint import pprint
import run_latest_version as run

query = Query()
files = run.get_last_version_of_files('../scripts/').get_list()

file = '../scripts/1_caller_db_0000.json'

with open(file, 'w') as rm_all:
    rm_all.writelines('')

MAIN = "MAIN"
with TinyDB(file, indent=4, separators=(', ', ': ')) as db:
    db.insert({'session_name': MAIN, 'window_name': "tutorial", 'same_pane': False, 'send_enter':1, 'exec_script': '', 'args': []})
    db.insert({'session_name': MAIN, 'window_name': "tutorial", 'same_pane': True, 'send_enter':0, 'exec_script': '', 'args': ['some_args']})
    db.insert({'session_name': MAIN, 'window_name': "tutorial2", 'same_pane': False, 'send_enter':0, 'exec_script': '', 'args': ['some_args']})
    
