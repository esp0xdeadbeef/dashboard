## compatablity
I would like to make this script accessable with ssh.
I need to change some things to get this working. 

# ssh -t $username@$ip tmux `command`
# ssh -A -J $username@$ip $ip_with_tmux tmux `commands`
