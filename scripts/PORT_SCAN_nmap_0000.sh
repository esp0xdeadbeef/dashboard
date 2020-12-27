#hping3 --scan 80 $ip_adress
export ip_adress="10.10.10.13"

#nmap -p- -A -T4 $ip_adress
/mnt/hgfs/hacking/programs_kali/nmapAutomator.sh $ip_adress All > nmap_scan