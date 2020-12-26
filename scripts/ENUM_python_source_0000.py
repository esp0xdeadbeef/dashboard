
import sys
import time
from pwn import process, PTY, PIPE
from pwn import *

def get_base_prefix_compat():
    """Get base/real prefix, or sys.prefix if there is none."""
    return getattr(sys, "base_prefix", None) or getattr(sys, "real_prefix", None) or sys.prefix

# if not in in virtualenv exit the app. 
if not get_base_prefix_compat() != sys.prefix:
	quit()

# if this is displayed in python and no errors exept the if [ True statement then 
# you're good to go! :D
# else 
# restart the ENUM_pwncat_XXXX and call the function update_pwncat


# time.sleep(5)
# !nc -e /bin/bash localhost 9051
def spawn_process(port_nc):
    retval = process(['/opt/pwncat/venv/bin/python3', '-m', 'pwncat', '--listen' , '-p', str(port_nc)])
    retval.recvuntil(b'connection ', drop=False)
    print('client_connected')
    return retval

# process(['/opt/pwncat/venv/bin/python3', '-c', 'import os; print(os.popen("echo `tput lines` `tput cols`").read())'], shell=False).recv(timeout=0.1)

#retval = process(['/opt/pwncat/venv/bin/python3', '-m', 'pwncat', '--listen' , '-p', str(9050)], aslr=False, shell=False)
# retval = process(['script', '-c', 'bash', '/opt/pwncat/venv/bin/python3 -m pwncat --listen -p ' + str(9050)], aslr=False, shell=True)
#retval.interactive()
#print(retval.recvuntil('connection'))
#throws an error.
# https://github.com/Gallopsled/pwntools/blob/dev/examples/options.py
# retval.sendlines('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA :) ')
# process(['python3', '-c', 'import os; print(os.popen("echo \`tput lines\` \`tput cols\`").read())'], shell=False).recv(timeout=0.1)
# process(['python3', '-c', 'import os; columns, rows = os.get_terminal_size(0)'], aslr=False, shell=False).recv(timeout=0.1)
# process(['python3', '-c', 'import os; print(os.popen("echo \`tput lines\` \`tput cols\`").read())'], shell=False).recv(timeout=0.1)
# process(['python3', '-c', 'import os; print(os.popen("echo \`tput lines\` \`tput cols\`").read())'], shell=False, stdin=PTY).recv(timeout=0.1)
# process(['python3', '-c', 'import os; print(os.get_terminal_size(0))'], aslr=False, shell=False, stdin=PTY).recv(timeout=0.1)
# process(['python3', '-m', 'pwncat', '--listen -p ' + str(9050)], aslr=False, shell=True, stdin=PTY).interactive()
pwntools_args_arr = "pwncat --listen -p 9050".split(' ')
pwntools_args = ' '.join(pwntools_args_arr)
# !$pwntools_args
# process(pwntools_args_arr, shell=True, stdin=PTY, stdout=PTY).interactive()
# testpwnproc(pwntools_args).interactive()


#python3 -c 'import pdb; pdb.set_trace();import os;print(os.get_terminal_size(0))'
# env_ = dict(os.environ)
# env_.pop("PWNLIB_NOTERM", None)
# env_.pop('PS1', None)
# env_.pop('LS_COLORS',None)

# string_cmd_to_exec = "python3 -c 'import os;print(os.get_terminal_size(0))'"
import fcntl
import termios
from pwntools import *
env_ = {}
env_["TERM"] = "xterm-256color"
env_['COLUMNS'] = '90'
env_['LINES'] = '90'
output_path = "/tmp/test_pdb.py"
# string_cmd_to_exec = "python3 -c 'import pdb; pdb.set_trace();import os;print(os.get_terminal_size(0))'"
string_cmd_to_exec = "python3 -m pdb '" + output_path + "'"
test_file_content = """#!python3
import pdb
pdb.set_trace()
"""
!echo "$test_file_content" > $output_path
!chmod 777  $output_path
!cat $output_path
args_python_script = string_cmd_to_exec.split("'")[1]
array_cmd_to_exec_inc_none = string_cmd_to_exec.split("'")[0].split(' ')
array_cmd_to_exec_inc_none.append("'" + args_python_script + "'")
array_cmd_to_exec = list(filter(None, array_cmd_to_exec_inc_none))

print(str(env_) + "\n" + string_cmd_to_exec + "\n"+str(array_cmd_to_exec))
p = process(array_cmd_to_exec, env=env_, stdin=PTY, stdout=PTY)
void = fcntl.ioctl(p.stdout.fileno(), termios.TIOCSWINSZ, struct.pack("hh", 80, 80))
p.recvall()
p = process(array_cmd_to_exec, env=env_, stdin=PIPE, stdout=PIPE)
void = fcntl.ioctl(p.stdout.fileno(), termios.TIOCSWINSZ, struct.pack("hh", 80, 80))
p.recvall()

!$string_cmd_to_exec
