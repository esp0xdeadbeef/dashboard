
Excuse me for the messy git repo.. #firstproject 

# dashboard

## Table of contents
- [Description](#description)
- [Installation](#installation)
- [Usage](#usage)

## Description
- ***Tmux ninjas***, This tool will be easy to use!

The initial version of this project will ask you to run everything as <b>root</b>! 
This is bad practice but it's <b>red-team oriented project</b>.

This project is ment for lazy people that doesn't like to type things over and over again in cli aplications.

There are solutions for this like pwntools and pwncat (and many more) but that packages are quite complex to understand without the backend knowledge. (no pun intended)



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
terminal 1) open the dashboard
./open_dashboard
terminal 2) open the cli:
cd main
./start_tmux_dashboard.py
```
