## compatablity

I would like to make this script accessable with ssh.
I need to change some things to get this working.

make sure you've added your ssh key with the `ssh-copy-id $username@$ip` command

The temp fix would be to set an alias on `tmux` to `ssh -t $username@$ip tmux` or `ssh -A -J $username@$ip $ip_with_tmux tmux`

# planned to integrate libtmux in this project

`https://libtmux.git-pull.com/`
