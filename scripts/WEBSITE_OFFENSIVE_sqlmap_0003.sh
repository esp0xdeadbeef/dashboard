ipython3

%autoindent 0
import os
import requests
page_latest_browser = requests.get('https://www.whatismybrowser.com/guides/the-latest-user-agent/firefox')
for i in page_latest_browser.text.split('<li><span class="code">'):
    if len(i) > 400:
        pass
    else:
        user_agent = i.split('</span>')[0]
        print(user_agent)
        break

#export user_agents=$(curl -s https://gist.githubusercontent.com/pzb/b4b6f57144aea7827ae4/raw/cf847b76a142955b1410c8bcef3aabe221a63db1/user-agents.txt 2> /dev/null)
# a = os.popen("ip addr | grep -E -o '([0-9]{1,3}[\.]){3}[0-9]{1,3}'").read().split('\n')[1]
# b = a.split('.')[:-1]
# proxy_ip = '.'.join(b) + '.1'
# print(proxy_ip)
proxy_ip = "localhost"

url = "http://google.com/test"
url = "http://localhost:8000"

# mitm
proxy_port = 8899
#burp
proxy_port = 8080

proxy_url = "http://" + proxy_ip + ":" + str(proxy_port)

!sqlmap --user-agent="$user_agent" -u $url --proxy $proxy_url
