apt-get install rlwrap -y 2>/dev/null
python3 -m venv /opt/pyproxy-env
source /opt/pyproxy-env/bin/activate
yes | pip install git+https://github.com/abhinavsingh/proxy.py.git@develop 2>/dev/null
cd /opt/pyproxy-env
git clone https://github.com/abhinavsingh/proxy.py.git
cd proxy.py
pip install -r requirements.txt
pip install -r requirements-testing.txt

#make
#vim proxy/plugin/ManInTheMiddlePlugin
##https://github.com/abhinavsingh/proxy.py/issues/299
python3 -m proxy --hostname 0.0.0.0 --plugins proxy.plugin.ManInTheMiddlePlugin