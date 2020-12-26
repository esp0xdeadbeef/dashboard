alias wanip='dig @ns1.google.com TXT o-o.myaddr.l.google.com +short'
while [ 1 ]
do
 	clear
    wanip | grep -E -o '([0-9]{1,3}[\.]){3}[0-9]{1,3}' 
    sleep 5
done