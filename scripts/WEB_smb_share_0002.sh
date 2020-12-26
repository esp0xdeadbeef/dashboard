smbservehere() {
	podman kill $(podman ps | grep impacket  | cut -d' ' -f1)
    local sharename
	clear
	echo 'cd where you want to go.
Use> smbservehere <to use this smbshare, its hosted from podman.'
    [[ -z $1 ]] && sharename='SHARE' || sharename=$1
    sudo podman run --rm -it -p 445:445 -v ${PWD}':/tmp/serve' rflathers/impacket smbserver.py -smb2support $sharename /tmp/serve
}

