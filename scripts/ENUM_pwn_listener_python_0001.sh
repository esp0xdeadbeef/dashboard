#check if the activate exsists, activate source. 
if [[ -f /opt/pwncat/venv/bin/activate ]]
then
    source /opt/pwncat/venv/bin/activate
	ipython3
else
	echo "start the ENUM_pwncat_XXXX.sh first"
	sleep 60
	exit
fi

%autoindent 0
#exit the program if still in bash 
if [ True ];then exit;fi
