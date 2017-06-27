#!/usr/bin/env python
# https://stackoverflow.com/questions/23828264/how-to-make-a-simple-multithreaded-socket-server-in-python-that-remembers-client/23828265#23828265
import hmac, hashlib, os.path, pycurl, re, socket, ssl, subprocess, sys, threading, time, yaml
from io import BytesIO
from urllib.parse import urlencode

class ThreadedServer(object):
    def __init__(self):
        self.config = {"api_key": "", "api_secret": "", "bind_address": "", "bind_port": "", "cache_time": "", "ssl_cert": "", "ssl_key": "", "api_throttle": ""}
        self.getConfig()
        self.cache = {"pr": {}, "pb": {}}
        self.err = "HTTP/1.1 400 Bad Request\r\n"
        self.polo_ip = "104.20.12.48"
        self.polo_ip_time = self.nonce = 0
        self.nonce_inc = 1
        self.cacheable = ["returnBalances", "returnDepositAddresses", "returnFeeInfo", "returnTradableBalances", "returnMarginAccountSummary", "returnOpenLoanOffers", "returnActiveLoans"]
        self.lock = threading.Lock()
        self.startSocket()

    def startSocket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(None)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock = ssl.wrap_socket(sock, certfile=self.config["ssl_cert"], keyfile=self.config["ssl_key"])
        self.sock.bind((self.config["bind_address"], self.config["bind_port"]))


    def getConfig(self):
        if not os.path.exists("settings.yml"):
            print("Error: You must copy settings.yml.example to settings.yml and edit it.")
            sys.exit(1)
        with open("settings.yml", "r") as handle:
            config = yaml.load(handle)
        for key in self.config:
            try:
                config[key]
            except KeyError:
                print("Error: Invalid settings.yml file, try recopying settings.yaml.example. (the " + key + " line is missing)")
                sys.exit(1)
            else:
                if not config[key]:
                    print("Error: The setting " + key + " in settings.yml must not be empty.")
                    sys.exit(1)
            self.config[key] = config[key]
        self.config["api_secret"] = self.config["api_secret"].encode("utf-8")


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
                if not self.processGet(data, client):
                    return False
            elif data.startswith("POST"):
                self.processPost(data, client)
            else:
                client.sendall(self.err.encode("utf-8"))
            with self.lock:
                time.sleep(self.config["api_throttle"])
            client.close()
            return
        else:
            print("Client disconnected.")
            return False


    def processPost(self, data, client):
        post = data.split("\n")
        for line in post:
            if "command=" in line:
                post = line
                break
        command = self.getCommand(post)
        cacheable = cached = False
        if command in self.cacheable:
            cacheable = True
            if self.checkCache(command, public=False):
                client.sendall(self.cache["pr"][command]["d"].encode("utf-8"))
                print(str(time.time()) + ": POST Command (Cached) : " + command)
                cached = True
        if not cached:
            print(str(time.time()) + ": POST Command : " + command)
            with self.lock:
                self.nonce = int(self.nonce) + self.nonce_inc
                if "nonce=" in post:
                    post = re.sub("nonce=\d+", "nonce=" + str(self.nonce), post)
                else:
                    post = post + "&nonce=" + str(self.nonce)
                headers = [
                    "Key: " + self.config["api_key"],
                    "Sign: " + hmac.new(self.config["api_secret"], post.encode("utf-8"), hashlib.sha512).hexdigest()
                ]
                buff = re.sub("Transfer-Encoding: chunked[\r\n]*", "" , self.curlRequest("https://" + self.polo_ip + "/tradingApi", headers, post))
                if buff == "":
                    buff = self.err
                elif "{\"error\":" in buff:
                    if "Nonce" in buff:
                        self.nonce = re.search("greater than (\d+)", buff)
                        self.nonce = self.nonce.group(1)
                    print("Poloniex API error: " + buff)
                client.sendall(buff.encode("utf-8"))
            if cacheable:
                self.cache["pr"][command]["d"] = buff
                self.cache["pr"][command]["t"] = time.time()
                #print("Cached private API command " + command)
            #print("Sent private API request " + command)


    def processGet(self, data, client):
        command = self.getCommand(data)
        if command == False:
            print("ERROR: Wrong public API command sent")
            client.sendall(self.err.encode("utf-8"))
            client.close()
            return False
        request = data.split(" ")[1]
        if not self.checkCache(command):
            # The replace is so we can just send all the data in 1 shot to gunbot.
            self.cache["pb"][command] = {"d": re.sub("Transfer-Encoding: chunked[\r\n]*", "" ,self.curlRequest("https://" + self.polo_ip + request)), "t": time.time()}
            print(str(time.time()) + ": GET Command : " + command)
        else:
            print(str(time.time()) + ": GET Command (Cached) : " + command)
        if self.cache["pb"][command]["d"] == "":
            self.cache["pb"][command]["d"] = self.err
            self.cache["pb"][command]["t"] = 0
        client.sendall(self.cache["pb"][command]["d"].encode("utf-8"))
        #print("Sent " + command + " public API request.")
        return True


    def checkCache(self, command, public=True):
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
            if ctime > (time.time() - self.config["cache_time"]):
                #if public == True:
                    #print("Updated stale API cache for " + command)
                return False
            else:
                #print("Fetched API data from cache for " + command)
                return True


    def getCommand(self, buffer):
        command = re.search("command=([a-zA-Z]+)", buffer)
        try:
            command
        except NameError:
            return False
        else:
            return command.group(1)


    def curlRequest(self, url, headers = False, post = False, returnHeaders=True):
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
    ThreadedServer().listen()
