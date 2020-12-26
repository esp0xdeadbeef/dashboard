generate_keys(){
#https://www.akadia.com/services/ssh_test_certificate.html
export cert_location="/etc/pki/"
export cert_location="/tmp/pki/"
mkdir $cert_location
cd $cert_location

#openssl req -x509 -nodes -new -sha256 -days 1024 -newkey rsa:2048 -keyout RootCA.key -out RootCA.pem -subj "/C=US/CN=Example-Root-CA"
#openssl x509 -outform pem -in RootCA.pem -out RootCA.crt
#ls
openssl req -x509 -nodes -new -sha256 -days 1024 -newkey rsa:2048 -keyout RootCA.key -out RootCA.pem -subj "/C=US/CN=1_Example-Root-CA"
openssl x509 -outform pem -in RootCA.pem -out RootCA.crt
echo "authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
DNS.2 = fake1.local
DNS.3 = fake2.local" > domains.ext
openssl req -new -nodes -newkey rsa:2048 -keyout localhost.key -out localhost.csr -subj "/C=US/ST=YourState/L=YourCity/O=1_Example-Certificates/CN=localhost.local"
openssl x509 -req -sha256 -days 1024 -in localhost.csr -CA RootCA.pem -CAkey RootCA.key -CAcreateserial -extfile domains.ext -out localhost.crt
ipython3
import ssl
from http.server import HTTPServer, SimpleHTTPRequestHandler
httpd = HTTPServer(('localhost', 4443), SimpleHTTPRequestHandler)
httpd.socket = ssl.wrap_socket(httpd.socket, certfile='localhost.crt',keyfile='localhost.key', server_side=True)
httpd.serve_forever() 
}

serve_http() {
cd $1
clear
printf "We are currently in dir: $(pwd)\n"
printf "The content of this folder is:\n$(ls)\n"
python3 -m http.server $2
}

 