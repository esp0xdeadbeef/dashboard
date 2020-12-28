socat file:$(tty),raw,echo=0 tcp-listen:6666
whoami
ls -la
cd /
exit
