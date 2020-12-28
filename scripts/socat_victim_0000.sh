sleep 5
socat exec:'bash -li',pty,stderr,setsid,sigint,sane tcp:localhost:6666
