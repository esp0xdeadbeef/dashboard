
Excuse me for the messy git repo.. #firstproject 

# dashboard

## Table of contents
- [Description](#description)
- [Installation](#installation)
- [Usage](#usage)

## Description
### Dont use this in a host env. Everything is runned as root.

The initial version of this project will ask you to run everything as <b>root</b>! This is bad practice but it's <b>red-team oriented project</b>.

This project is ment for lazy people that doesn't like to type things over and over again in cli aplications.

There are solutions for this like pwntools and pwncat (and many more) but that packages are quite complex to understand without the backend knowledge. (no pun intended)

- ***If you're a Tmux ninja***, this will add another deadly weapon to your agile arsenal  ⚔️  

Spawning tmux session with a main session for your liking. 

In the folder scripts are a few examples how you can use the tmux spawner to spawn some tasks. 
In the configuration .py 

## Installation
#### 1. Run the following line in your terminal
```bash 
git clone https://github.com/esp0xdeadbeef/dashboard.git
cd dashboard

```

## Usage
#### From the command line:
``` bash
# this will attach the main session of the tmux session.
sudo ./open_dashboard
# this will run `write_cfg.py` and `start_dashboard.py`
sudo ./run_0004.py
#start dashboard will answer with an interactive session so you can restart a specific tmux session. ALL PROGRESS WILL BE REMOVED AND YOU WILL NOT BE PROMPED!!! 
```
