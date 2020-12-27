while [ 1 ]
do
  	clear
    sudo ip addr | grep -E -o '([0-9]{1,3}[\.]){3}[0-9]{1,3}'
	sleep 5
done
