
Excuse me for the messy git repo.. #firstproject 

# dashboard

## Table of contents
- [Description](#description)
- [Installation](#installation)
- [Usage](#usage)

## Description
- ***This tool will be easy to use for the fellow tmux users***, 

The initial version of this project will ask you to run everything as <b>root</b>! 
This is bad practice but it's <b>red-team oriented project</b>.

This project is ment for lazy people that doesn't like to type things over and over again in cli applications.

There are solutions for this like pwntools and pwncat (and many more) but that packages are quite complex to understand without the backend knowledge. (no pun intended)



Spawning tmux session with a main session for your liking. 

In the folder scripts are a few examples how you can use the tmux spawner to spawn some tasks. 
In the configuration write_cfg.py you can change the config.

## Installation
#### 1. Run the following line in your terminal
```bash 
git clone https://github.com/esp0xdeadbeef/dashboard.git
cd dashboard
pip install -r requirements.txt
```

## Usage
#### From the command line:
``` bash
terminal 1) open the dashboard
./open_dashboard
terminal 2) open the cli:
cd main
./start_tmux_dashboard.py
```
#### edit your own config inside write_cfg.py

code example:

db.insert({'session_name': "MAIN", 'window_name': "tipl", 'same_pane': True, 'send_enter':1, "pre_arg":"php -a", 'exec_script': 'PHP_code_with_errors', 'args': ['\nexit']})

This will make a session MAIN;

creates a window or tab in tmux with the name tipl

The first same pane doesn't matter if true or false, but second command will run in the same pane or not. depending on this variable.

"pre_arg":"php -a" will be executed before the exec_script and is unfilterd, so watch the syntax of tmux. there will be an enter appended (\n)

"exec_script" will run the latest version inside the script folder.
  important, you should add version numbering behind the file (filename_XXXX) whereby the XXXX are integers from 0000-9999. (this might be patched after a while)

"args" array will put the args behind the exec script.

