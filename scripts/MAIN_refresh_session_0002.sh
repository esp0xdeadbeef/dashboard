refresh_session(){
unset TMUX
while true
do
	sleep 0.2
    clear
    tmux at -t $1
done
}
refresh_session 