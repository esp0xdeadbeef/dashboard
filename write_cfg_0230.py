#!/usr/bin/python3
#pip3 install tinydb

import os
if (os.geteuid() != 0):
    print('run as admin')
    os._exit(-1)



from tinydb import TinyDB, Query
from pprint import pprint
import run_0004 as run
query = Query()
files = run.get_last_version_of_files('scripts/').get_list()

file = 'scripts/1_MAIN__init__0000.json'

with open(file, 'w') as rm_all:
    rm_all.writelines('')
ENUM = 'ENUM'
WWW = 'WWW'
USER = 'USER'
ROOT = 'ROOT'
VPN = 'VPN'
WEB = 'WEB_LOCAL'
NS_RECON = 'NS_RECON'
PORT_SCAN = 'PORT_SCAN'
MAIN = "MAIN"
TESTING='TESTING'
WEB_OFFENSIVE="OFFENSIVE_WEB"
PORT=9050
BASH = 'BASH'
with TinyDB(file, indent=4, separators=(', ', ': ')) as db:
    db.insert({'session_name': MAIN, 'window_name': VPN, 'pane_nr': 0, 'send_enter':1, 'exec_script': 'refresh_session', 'args': [VPN,]})
    db.insert({'session_name': MAIN, 'window_name': WEB, 'pane_nr': 0, 'send_enter':1, 'exec_script': 'refresh_session', 'args': [WEB,]})
    db.insert({'session_name': MAIN, 'window_name': ENUM, 'pane_nr': 0, 'send_enter':1, 'exec_script': 'refresh_session', 'args': [ENUM + "\npkill socat",]})
    db.insert({'session_name': MAIN, 'window_name': NS_RECON, 'pane_nr': 0, 'send_enter':1, 'exec_script': 'refresh_session', 'args': [NS_RECON,]})
    db.insert({'session_name': MAIN, 'window_name': PORT_SCAN, 'pane_nr': 0, 'send_enter':1, 'exec_script': 'refresh_session', 'args': [PORT_SCAN,]})
    db.insert({'session_name': MAIN, 'window_name': WEB_OFFENSIVE, 'pane_nr': 0, 'send_enter':1, 'exec_script': 'refresh_session', 'args': [WEB_OFFENSIVE,]})
    db.insert({'session_name': MAIN, 'window_name': 'BASH', 'pane_nr': 0, 'send_enter':1, 'exec_script': 'refresh_session', 'args': [BASH,]})
    db.insert({'session_name': VPN, 'window_name': 'Connect', 'pane_nr': 0, 'send_enter':1, 'exec_script': 'VPN_hack_the_box', 'args': ['',]})
    db.insert({'session_name': VPN, 'window_name': 'Connect', 'pane_nr': 1, 'send_enter':1, 'exec_script': 'VPN_loop_get_internal_ip_addr', 'args': ['',]})
    db.insert({'session_name': VPN, 'window_name': 'Connect', 'pane_nr': 2, 'send_enter':1, 'exec_script': 'VPN_ping_external', 'args': ['',]})
    db.insert({'session_name': VPN, 'window_name': 'Connect', 'pane_nr': 3, 'send_enter':1, 'exec_script': 'VPN_ping_internal', 'args': ['',]})
    db.insert({'session_name': VPN, 'window_name': 'Connect', 'pane_nr': 4, 'send_enter':0, 'exec_script': 'VPN_get_external_ip', 'args': ['',]})
    db.insert({'session_name': WEB, 'window_name': '0', 'pane_nr': 0, 'send_enter':1, 'exec_script': 'WEB_http_python', 'args': ['serve_http', '/mnt/hgfs/hacking/programs_kali/linux/', '8000']})
    db.insert({'session_name': WEB, 'window_name': '0', 'pane_nr': 3, 'send_enter':1, 'exec_script': 'WEB_http_python', 'args': ['serve_http', '/mnt/hgfs/hacking/programs_kali/windows/', '8010']})
    db.insert({'session_name': WEB, 'window_name': '0', 'pane_nr': 2, 'send_enter':1, 'exec_script': 'WEB_smb_share', 'args': ['cd /mnt/hgfs/hacking/programs_kali/smb_exposed \nsmbservehere',]})
    db.insert({'session_name': WEB, 'window_name': '0', 'pane_nr': 3, 'send_enter':1, 'exec_script': '', 'args': ['',]})
    db.insert({'session_name': ENUM, 'window_name': '0', 'pane_nr': 0, 'send_enter':0, 'exec_script': 'ENUM_pwn_listener_python', 'args': [''+str(PORT)+"\n",]})
    db.insert({'session_name': ENUM, 'window_name': '0', 'pane_nr': 0, 'send_enter':0, 'exec_script': 'ENUM_python_source', 'args': ['',]})
    db.insert({'session_name': ENUM, 'window_name': '0', 'pane_nr': 1, 'send_enter':0, 'exec_script': 'ENUM_pwncat', 'args': [''+str(PORT+1),]})
    db.insert({'session_name': NS_RECON, 'window_name': '0', 'pane_nr': 0, 'send_enter':0, 'exec_script': 'NS_RECON_wfuzz', 'args': ['',]})
    db.insert({'session_name': NS_RECON, 'window_name': '0', 'pane_nr': 1, 'send_enter':0, 'exec_script': 'NS_RECON_dnsrecon', 'args': ['',]})
    db.insert({'session_name': NS_RECON, 'window_name': '0', 'pane_nr': 2, 'send_enter':1, 'exec_script': '', 'args': ['vim /etc/hosts',]})
    db.insert({'session_name': NS_RECON, 'window_name': '0', 'pane_nr': 3, 'send_enter':0, 'exec_script': 'NS_RECON_gobuster', 'args': ['',]})
    db.insert({'session_name': NS_RECON, 'window_name': '0', 'pane_nr': 4, 'send_enter':0, 'exec_script': 'NS_RECON_cewl', 'args': ['',]})
    db.insert({'session_name': NS_RECON, 'window_name': '0', 'pane_nr': 5, 'send_enter':0, 'exec_script': '', 'args': ['go get -u github.com/ffuf/ffuf; cd ~/go/bin;./ffuf --version\n./ffuf -w /usr/share/wordlists/rockyou.txt -u https://codingo.io/FUZZ',]})
    db.insert({'session_name': PORT_SCAN, 'window_name': '0', 'pane_nr': 0, 'send_enter':0, 'exec_script': 'PORT_SCAN_nmap', 'args': ['',]})
    db.insert({'session_name': WEB_OFFENSIVE, 'window_name': '0', 'pane_nr': 1, 'send_enter':0, 'exec_script': 'WEBSITE_OFFENSIVE_tplmap', 'args': ['',]})
    db.insert({'session_name': WEB_OFFENSIVE, 'window_name': '0', 'pane_nr': 2, 'send_enter':0, 'exec_script': 'WEBSITE_OFFENSIVE_sqlmap', 'args': ['',]})
    db.insert({'session_name': WEB_OFFENSIVE, 'window_name': '0', 'pane_nr': 3, 'send_enter':0, 'exec_script': 'WEBSITE_OFFENSIVE_proxy_server_', 'args': ['',]})
    db.insert({'session_name': WEB_OFFENSIVE, 'window_name': '0', 'pane_nr': 4, 'send_enter':0, 'exec_script': 'WEBSITE_OFFENSIVE_nuclei_', 'args': ['',]})
    db.insert({'session_name': BASH, 'window_name': '0', 'pane_nr': 0, 'send_enter':0, 'exec_script': '', 'args': ['',]})

