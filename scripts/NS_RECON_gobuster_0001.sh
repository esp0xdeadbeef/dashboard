export target_ns="http://FUZZ.cronos.htb/"
export hide_response="404,403"
#gobuster dir -w /usr/share/wordlists/dirbuster/directory-list-lowercase-2.3-small.txt - -u "cronos.htb"
#dirb https://10.10.10.60/ /usr/share/wordlists/dirbuster/directory-list-lowercase-2.3-medium.txt -X .html,.php,.txt
#gobuster dir -u https://10.10.10.60 -w /usr/share/dirbuster/wordlists/directory-list-2.3-medium.txt -k -x .php,.txt,.html,.conf --timeout 40s -t 150
