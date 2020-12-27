#podman run --rm -it -v /opt/nuclei-templates:/app/nuclei-templates -v /opt/nuclei/config:/app/.nuclei-config.json projectdiscovery/nuclei  -update-templates
update_nuclei(){
	rm -r /opt/nuclei
	mkdir /opt/nuclei
	cd /opt/nuclei
	git clone https://github.com/projectdiscovery/nuclei.git
	cd nuclei/v2/cmd/nuclei/
	go build
	git clone https://github.com/projectdiscovery/nuclei-templates.git
	#mv nuclei /usr/local/bin/; 
	./nuclei -t nuclei-templates -update-templates
}
cd /opt/nuclei/nuclei/v2/cmd/nuclei/

#update_nuclei  # adviceable to update first before using it
./nuclei -version
#./nuclei -t nuclei-templates -target http://localhost:8000