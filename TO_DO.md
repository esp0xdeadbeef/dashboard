## compatablity
I would like to make this script accessable with ssh.
I need to change some things to get this working. 

The temp fix would be to set an alias on tmux to `ssh -t $username@$ip tmux` or `ssh -A -J $username@$ip $ip_with_tmux tmux`:
