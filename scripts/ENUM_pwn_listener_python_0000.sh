#check if the activate exsists, activate source. 
if [[ -f /opt/pwncat/venv/bin/activate ]]
then
    source /opt/pwncat/venv/bin/activate
	python3
else
	echo "start the ENUM_pwncat_XXXX.sh first"
	sleep 60
	exit
fi
#checking if venv/bin/activate is executed
%autoindent 0
#exit the program if still in bash 
if [ True ];then exit;fi

import sys

def get_base_prefix_compat():
    """Get base/real prefix, or sys.prefix if there is none."""
    return getattr(sys, "base_prefix", None) or getattr(sys, "real_prefix", None) or sys.prefix

def in_virtualenv():
    return get_base_prefix_compat() != sys.prefix

if not in_virtualenv():
	quit()

# if this is displayed in python and no errors exept the if [ True statement then 
# you're good to go! :D
# else 
# restart the ENUM_pwncat_XXXX and call the function update_pwncat

import time
from pwn import process


# time.sleep(5)
# !nc -e /bin/bash localhost 9051
def spawn_process(port_nc):
    retval = process(['/opt/pwncat/venv/bin/python3', '-m', 'pwncat', '--listen' , '-p', str(port_nc)])
    retval.recvuntil(b'connection ', drop=False)
    print('client_connected')
    return retval

process(['/opt/pwncat/venv/bin/python3', '-c', 'import os; print(os.popen("echo `tput lines` `tput cols`").read())'], shell=False).recv(timeout=0.1)

retval = process(['/opt/pwncat/venv/bin/python3', '-m', 'pwncat', '--listen' , '-p', str(9050)], aslr=False, shell=False)
# retval = process(['script', '-c', 'bash', '/opt/pwncat/venv/bin/python3 -m pwncat --listen -p ' + str(9050)], aslr=False, shell=True)
retval.interactive()
print(retval.recvuntil('connection'))
#throws an error.
https://github.com/Gallopsled/pwntools/blob/dev/examples/options.py
retval.sendlines('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA :) ')
process(['/opt/pwncat/venv/bin/python3', '-c', 'import os; print(os.popen("echo `tput lines` `tput cols`").read())'], shell=False).recv(timeout=0.1)


