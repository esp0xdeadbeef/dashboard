get_cewl_list(){
	cewl $1 > cewl_list.txt
}
export hostname="http://.htb"
get_cewl_list $hostname