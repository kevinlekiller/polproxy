#!/usr/bin/env python
# https://stackoverflow.com/questions/23828264/how-to-make-a-simple-multithreaded-socket-server-in-python-that-remembers-client/23828265#23828265
import hmac, hashlib, pycurl, re, socket, ssl, subprocess, sys, threading, time
from io import BytesIO
from urllib.parse import urlencode

# Put a new poloniex key / secret here.
API_KEY = ""
API_SECRET = ""

SSL_CERT = "polproxy.crt.pem"
SSL_KEY = "polproxy.key.pem"
PROXY_ADDRESS="127.0.0.1"
PROXY_PORT=443
CACHE_TIME=20

class ThreadedServer(object):
    def __init__(self, host, port, akey, asec, cacheTime, scert, skey):
        self.locked = False
        self.cache = {}
        self.cache["pr"] = {}
        self.cache["pb"] = {}
        self.err = "HTTP/1.1 400 Bad Request\n"
        self.polo_ip = "104.20.12.48"
        self.polo_ip_time = 0
        self.nonce = 0
        self.nonce_inc = 1
        self.host = host
        self.port = port
        self.akey = akey
        self.asec = asec.encode("utf-8")
        self.cacheTime = cacheTime
        self.scert = scert
        self.skey = skey
        self.cacheable = ["returnBalances", "returnDepositAddresses", "returnFeeInfo", "returnTradableBalances", "returnMarginAccountSummary", "returnOpenLoanOffers", "returnActiveLoans"]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(None)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock = ssl.wrap_socket(sock, certfile=self.scert, keyfile=self.skey)
        self.sock.bind((self.host, self.port))


    def getPoloIp(self):
        if self.polo_ip_time > time.time() - 300:
            return
        print ("Updating polo ip")
        tmpip = subprocess.Popen("dig @8.8.8.8 +short poloniex.com | head -1", shell=True, stdout=subprocess.PIPE).stdout.read().decode().rstrip()
        if tmpip != "":
            self.polo_ip = tmpip
        self.polo_ip_time = time.time()


    def listen(self):
        self.sock.listen(250)
        while True:
            self.getPoloIp()
            client, address = self.sock.accept()
            client.settimeout(240)
            threading.Thread(target = self.listenToClient,args = (client,address)).start()


    def listenToClient(self, client, address):
        size = 4096
        data = ""
        # I know this looks stupid, but gunbot doesn't always return line endings so I had to do this to make the socket not block.
        while True:
            try:
                buff = client.recv(size).decode("iso-8859-1")
                data = data + buff
                if "command=" in buff:
                    break
            except Exception as e:
                print(e)
                client.close()
                return False
        if data:
            data = data.strip()
            if data.startswith("GET"):
                if not self.process_get(data, client):
                    return False
            elif data.startswith("POST"):
                self.process_post(data, client)
            else:
                client.sendall(self.err.encode("utf-8"))
            client.close()
            return
        else:
            print("Client disconnected.")
            return False


    def process_post(self, data, client):
        post = data.split("\n")
        for line in post:
            if "command=" in line:
                post = line
                break
        command = self.get_command(post)
        cacheable = cached = False
        if command in self.cacheable:
            cacheable = True
            if self.check_cache(command, public=False):
                client.sendall(self.cache["pr"][command]["d"].encode("utf-8"))
                print(str(time.time()) + ": POST Command (Cached) : " + command)
                cached = True
        if not cached:
            print(str(time.time()) + ": POST Command : " + command)
            self.lock_thread()
            self.locked = True
            self.nonce = int(self.nonce) + self.nonce_inc
            if "nonce=" in post:
                post = re.sub("nonce=\d+", "nonce=" + str(self.nonce), post)
            else:
                post = post + "&nonce=" + str(self.nonce)
            headers = [
                "Key: " + self.akey,
                "Sign: " + hmac.new(self.asec, post.encode("utf-8"), hashlib.sha512).hexdigest()
            ]
            buff = re.sub("Transfer-Encoding: chunked[\r\n]*", "" , self.curl_request("https://" + self.polo_ip + "/tradingApi", headers, post))
            if buff == "":
                buff = self.err
            elif "{\"error\":\"Nonce" in buff:
                self.nonce = re.search("greater than (\d+)", buff)
                self.nonce = self.nonce.group(1)
            client.sendall(buff.encode("utf-8"))
            self.locked = False
            if cacheable:
                self.cache["pr"][command]["d"] = buff
                self.cache["pr"][command]["t"] = time.time()
                #print("Cached private API command " + command)
            #print("Sent private API request " + command)


    def process_get(self, data, client):
        command = self.get_command(data)
        if command == False:
            print("ERROR: Wrong public API command sent")
            client.sendall(self.err.encode("utf-8"))
            client.close()
            return False
        request = data.split(" ")[1]
        if not self.check_cache(command):
            # The replace is so we can just send all the data in 1 shot to gunbot.
            self.cache["pb"][command] = {"d": re.sub("Transfer-Encoding: chunked[\r\n]*", "" ,self.curl_request("https://" + self.polo_ip + request)), "t": time.time()}
            print(str(time.time()) + ": GET Command : " + command)
        else:
            print(str(time.time()) + ": GET Command (Cached) : " + command)
        if self.cache["pb"][command]["d"] == "":
            self.cache["pb"][command]["d"] = self.err
            self.cache["pb"][command]["t"] = 0
        client.sendall(self.cache["pb"][command]["d"].encode("utf-8"))
        #print("Sent " + command + " public API request.")
        return True


    def lock_thread(self):
        # Shitty way to lock the thread, works for now
        while self.locked:
            time.sleep(0.002)


    def check_cache(self, command, public=True):
        ctime = 0
        try:
            if public:
                ctime = self.cache["pb"][command]["t"]
            else:
                ctime = self.cache["pr"][command]["t"]
        except KeyError:
            #if public == True:
                #print("Fetched data from API for " + command)
            return False
        else:
            if ctime > (time.time() - self.cacheTime):
                #if public == True:
                    #print("Updated stale API cache for " + command)
                return False
            else:
                #print("Fetched API data from cache for " + command)
                return True


    def get_command(self, buffer):
        command = re.search("command=([a-zA-Z]+)", buffer)
        try:
            command
        except NameError:
            return False
        else:
            return command.group(1)


    def curl_request(self, url, headers = False, post = False, returnHeaders=True):
        ch = pycurl.Curl()
        ch.setopt(pycurl.URL, url)
        hdrs = [
                "Host: poloniex.com",
                "Connection: close",
                "User-Agent: Mozilla/5.0 (CLI; Linux x86_64) polproxy",
                "accept: application/json"
        ]
        if post != False:
            ch.setopt(pycurl.POSTFIELDS, post)
            hdrs = hdrs + ["content-type: application/x-www-form-urlencoded", "content-length: " + str(len(post))]
        if headers != False:
            hdrs = hdrs + headers
        ch.setopt(pycurl.HTTPHEADER, hdrs)
        ch.setopt(pycurl.SSL_VERIFYHOST, 0)
        ch.setopt(pycurl.FOLLOWLOCATION, True)
        ch.setopt(pycurl.CONNECTTIMEOUT, 10)
        ch.setopt(pycurl.TIMEOUT, 10)
        ret = BytesIO()
        if returnHeaders:
            ch.setopt(pycurl.HEADERFUNCTION, ret.write)
        ch.setopt(pycurl.WRITEFUNCTION, ret.write)
        try:
            ch.perform()
        except:
            return ""
        ch.close()
        return ret.getvalue().decode("ISO-8859-1")


if __name__ == "__main__":
    ThreadedServer(PROXY_ADDRESS,PROXY_PORT,API_KEY,API_SECRET,CACHE_TIME,SSL_CERT,SSL_KEY).listen()
