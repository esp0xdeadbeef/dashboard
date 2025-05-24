WIP.

# dashboard in tmux

## Table of contents
- [Description](#description)
- [Installation](#installation)
- [Usage](#usage)

## Description

People who do not like to type repeating themselves in CLI applications might like this project.

You can send files to your tmux panes or you could use the libtmux in cli. 

In the `scripts` folder are a few examples of how you can use the tmux spawner these are included:
  
 - programming: 
   - ipython3 (with errors)
   - php (with errors)
   - powershell (with errors)
 - socat
   - setup a listener
   - rev shell to yourself
 - vim
   - edit a file in vim, safe it under /tmp/testing
   - cat the file

In the configuration write_cfg.py, you can change the config.

## Installation
#### 1. Run the following line in your terminal
```bash 
# This can be used to generate multiple sessions
unset $TMUX
cd /tmp
git clone https://github.com/esp0xdeadbeef/dashboard.git
cd dashboard
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

## Usage
### From the command line:

option 1 open tmux:
```bash
export dashboard_path="/tmp/dashboard"
pip3 install -r $dashboard_path/requirements.txt
ipython3 $dashboard_path/main_tdashboard.py -i -- $dashboard_path/scripts --session-file $dashboard_path/scripts/1_session.py
```


```bash
terminal 2) open the cli (option 2):
alias spawn-tmux-session='
tmux kill-server
sleep 0.2
export dashboard_path="/opt/dashboard"
export scripts_path="$dashboard_path/scripts"
tmux new-session -t spawn-all\; send-keys "
if ! [ -d $dashboard_path/venv ]; 
then 
  python3 -m venv $dashboard_path/venv
fi
source $dashboard_path/venv/bin/activate
pip3 install -r $dashboard_path/requirements.txt
ipython3 $dashboard_path/main_tdashboard.py -i -- $scripts_path --session-file $scripts_path/1_session.py" C-m
'
#and use:
spawn-tmux-session
# whenever you want to spawn the tmux-dashbaord.
```
