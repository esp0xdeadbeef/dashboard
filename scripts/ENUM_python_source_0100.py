import sys
import time
import fcntl
import termios
from pwn import *

def get_base_prefix_compat():
    """Get base/real prefix, or sys.prefix if there is none."""
    return getattr(sys, "base_prefix", None) or getattr(sys, "real_prefix", None) or sys.prefix

# if not in in virtualenv exit the app. 
if not get_base_prefix_compat() != sys.prefix:
	quit()

########## COPY FROM HERE ##########
env_ = {}
env_["TERM"] = "xterm-256color"
cols_and_lines = 90
env_['COLUMNS'] = str(cols_and_lines)
env_['LINES'] = str(cols_and_lines)
output_path = "/tmp/test_pdb.py"
# string_cmd_to_exec = "python3 -c 'import pdb; pdb.set_trace();import os;print(os.get_terminal_size(0))'"
string_cmd_to_exec = "python3 -m pdb '" + output_path + "'"
test_file_content = """#!python3
import pdb
pdb.set_trace()
"""
!echo "$test_file_content" > $output_path
!chmod 777  $output_path; cat $output_path
args_python_script = string_cmd_to_exec.split("'")[1]
array_cmd_to_exec_inc_none = string_cmd_to_exec.split("'")[0].split(' ')
array_cmd_to_exec_inc_none.append("'" + args_python_script + "'")
array_cmd_to_exec = list(filter(None, array_cmd_to_exec_inc_none))
print(str(env_) + "\n" + string_cmd_to_exec + "\n"+str(array_cmd_to_exec))
p = process(array_cmd_to_exec, env=env_, stdin=PTY, stdout=PTY)
fcntl.ioctl(p.stdout.fileno(), termios.TIOCSWINSZ, struct.pack("hh", cols_and_lines, cols_and_lines))
p.recvall()
p = process(array_cmd_to_exec, env=env_, stdin=PIPE, stdout=PIPE)
fcntl.ioctl(p.stdout.fileno(), termios.TIOCSWINSZ, struct.pack("hh", cols_and_lines, cols_and_lines))
p.recvall()
#!$string_cmd_to_exec

def spawn_process(port_nc):
    retval = process(['/opt/pwncat/venv/bin/python3', '-m', 'pwncat', '--listen' , '-p', str(port_nc)])
    retval.recvuntil(b'connection ', drop=False)
    print('client_connected')
    return retval

spawn_process
