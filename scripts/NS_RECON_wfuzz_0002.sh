export hide_amount_char="12454"
export hide_response="404,403"
export wordlist="/usr/share/dnsrecon/subdomains-top1mil.txt"
export target_ip="10.10.10.13"
export target_ns="http://FUZZ.cronos.htb/"
#wfuzz --hc $hide_response --hh $hide_amount_char -w /usr/share/dnsrecon/subdomains-top1mil.txt --ip 10.10.10.13 http://FUZZ.cronos.htb/
#wfuzz --hc $hide_response --hh $hide_amount_char -z list,admin-ns1-test-everythingworkswouw --ip 10.10.10.13 http://FUZZ.cronos.htb/
#wfuzz --hc $hide_response --hh $hide_amount_char -w /usr/share/wordlists/rockyou.txt --ip 10.10.10.13 http://FUZZ.cronos.htb/
#wfuzz --hc $hide_response --hh $hide_amount_char -w $wordlist --ip $target_ip $target_ns
#wfuzz --hc XXX -w /usr/share/dnsrecon/subdomains-top1mil-5000.txt -Z http://FUZZ.docters.htb
