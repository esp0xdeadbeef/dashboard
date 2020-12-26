#!/bin/bash

usefull_commands_pwncat(){
echo "examples:
# Connect to a bind shell
pwncat connect://10.10.10.10:4444
pwncat 10.10.10.10:4444
pwncat 10.10.10.10 4444
# Listen for reverse shell
pwncat bind://0.0.0.0:4444
pwncat 0.0.0.0:4444
pwncat :4444
pwncat -lp 4444
# Connect via ssh
pwncat ssh://user:password@10.10.10.10
pwncat user@10.10.10.10
pwncat user:password@10.10.10.10
pwncat -i id_rsa user@10.10.10.10
# SSH w/ non-standard port
pwncat -p 2222 user@10.10.10.10
pwncat user@10.10.10.10:2222
# Reconnect utilizing installed persistence
#   If reconnection failes and no protocol is specified,
#   SSH is used as a fallback.
pwncat reconnect://user@10.10.10.10
pwncat reconnect://user@c228fc49e515628a0c13bdc4759a12bf
pwncat user@10.10.10.10
pwncat c228fc49e515628a0c13bdc4759a12bf
pwncat 10.10.10.10"
}

update_pwncat(){
	export actual_dir=$(pwd)
	cd /opt/
	rm -r pwncat
	mkdir /opt/pwncat
	cd /opt/pwncat 
	apt-get install python3-venv
	python3 -m venv /opt/pwncat/venv
	source /opt/pwncat/venv/bin/activate
	apt-get install runc -y
	apt-get install podman -y
	apt-get install rlwrap -y 2>/dev/null
	yes | pip3 install pwntools wheel 2>/dev/null
	pip3 install ipython
	git clone https://github.com/calebstewart/pwncat.git
	cd pwncat
	python3 setup.py develop
	/opt/pwncat/venv/bin/pip3 install -r requirements.txt
	/opt/pwncat/venv/bin/pip3 install -U git+https://github.com/calebstewart/paramiko
	cd $actual_dir
}
#check if the activate exsists, activate source. 
if [[ -f /opt/pwncat/venv/bin/activate ]]
then
    source /opt/pwncat/venv/bin/activate
else
	update_pwncat
fi

#update_pwncat
#exit
# pwncat --listen -p 9051

