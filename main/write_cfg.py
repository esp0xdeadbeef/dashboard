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
    tutorial_interactive_programming_languages = "tipl"
    tutorial_reverse_shell = "trs"
    db.insert({'session_name': MAIN, 'window_name': tutorial_interactive_programming_languages, 'same_pane': False,
               'send_enter': 0, "pre_arg": "php -a", 'exec_script': 'PHP_code_with_errors', 'args': ['\nexit']})
    db.insert({'session_name': MAIN, 'window_name': tutorial_interactive_programming_languages, 'same_pane': False,
               'send_enter': 0, 'exec_script': 'Python_code_with_errors', "pre_arg": "ipython3", 'args': ['string_example)\nexit()']})
    db.insert({'session_name': MAIN, 'window_name': tutorial_interactive_programming_languages, 'same_pane': False,
               'send_enter': 0, 'exec_script': 'POWERSHELL_code_with_errors', "pre_arg": "pwsh", 'args': ['\nexit']})
    db.insert({'session_name': MAIN, 'window_name': tutorial_reverse_shell, 'same_pane': True,
               'send_enter': 0, 'exec_script': 'socat_attacker', "pre_arg": "", 'args': ['']})
    db.insert({'session_name': MAIN, 'window_name': tutorial_reverse_shell, 'same_pane': False,
               'send_enter': 0, 'exec_script': 'socat_victim', "pre_arg": "", 'args': [""]})
    db.insert({'session_name': MAIN, 'window_name': "try_out", 'same_pane': False,
               'send_enter': 1, 'exec_script': 'functions_tryout', "pre_arg": "", 'args': [""]})
