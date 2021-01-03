#!/bin/bash
if [ \$UID -gt 0 ]; then echo 'run as root'; exit; fi

while true;clear; do tmux at -t MAIN; sleep 1; done
