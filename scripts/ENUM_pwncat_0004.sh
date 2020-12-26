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

download_pwncat(){
    #arg 1, force download
    if [ $1 ]
    then
        git clone https://github.com/calebstewart/pwncat.git
    fi
    cd pwncat
    python3 setup.py install
    
}


update_pwncat_docker(){
    podman run -it --name pwncat -v "$PWD":/work -w /usr/src/myapp python:3 /bin/bash
    git clone https://github.com/calebstewart/pwncat.git
    cd pwncat
    python setup.py develop
    pip3 install -r requirements.txt
    pip3 install -U git+https://github.com/calebstewart/paramiko
}


update_pwncat(){
	export actual_dir=$(pwd)
	mkdir /opt/pwncat
	cd /opt/pwncat 
	python3 -m venv /opt/pwncat/venv
	source /opt/pwncat/venv/bin/activate
	apt-get install runc -y
	apt-get install podman -y
	#apt-get install rlwrap -y 2>/dev/null
	yes | pip install pwntools wheel 2>/dev/null
	pip install ipython
	git clone https://github.com/calebstewart/pwncat.git
	cd pwncat
	python setup.py develop
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
pwncat --listen -p 9051

