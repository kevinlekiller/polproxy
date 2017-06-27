# polproxy
This is a proxy server for poloniex / gunbot for Linux (untested on Windows / BSD).

## Notes:

Note, use this on a server where only gunbot will run, like a virtual machine or a VPS, this proxy will not forward non API requests to poloniex.com.

The performance of the proxy is not very high. If you have many gunbot pairs, you will need to set gunbot's `BOT_SLEEP_DELAY` pretty high or the connections to the proxy will build up and timeout, you can monitor how many threads are waiting with with `htop -p $(pgrep -f polproxy.py)`, if you have more than roughly 20 threads waiting, then increase the `BOT_SLEEP_DELAY`. For 30 pairs, I run at 120 seconds `BOT_SLEEP_DELAY`.

## Installation:

Install dnsmasq / dig (dnsutils in arch linux) / python 3 / pycurl (python-pycurl in arch, or use pip install pycurl on other distros)

Edit the following files:

/etc/dnsmasq.conf (add in the file):

    strict-order
    listen-address=127.0.0.1
    address=/poloniex.com/127.0.0.1

If using dhcpcd:
/etc/dhcpcd.conf (add in the file, this is to make dhcpcd not overwite resolv.conf):

    nohook resolv.conf

Restart dhcpcd:

    sudo systemctl restart dhcpcd

/etc/resolv.conf (add to the top of the file, make sure it's the first nameserver in that file):

    nameserver 127.0.0.1

Enable / start dnsmasq:

    sudo systemctl enable dnsmasq && sudo systemctl start dnsmasq

Create a new poloniex api key: https://poloniex.com/apiKeys

Edit polproxy.py, the settings are at the top.

Since the proxy runs on port 443, you need to either allow python to bind to port 443 ( `sudo setcap CAP_NET_BIND_SERVICE=+eip $(readlink -f $(which python))` ) or run polproxy.py as root.

Run polproxy.py

    python polproxy.py

Run gunbot like this (since we are using a self signed certificate on our proxy) : `NODE_TLS_REJECT_UNAUTHORIZED=0 ./gunthy-linuxx64 BTC_XMR poloniex`

## License:

See the LICENSE file.

## Donations:

If you would like to send me a donation (very appreciated), here are my cryptocurrency addresses:

BTC: 16Ur2djxEMyHUkg4aT1GEYhLXwnfFRBhNd

ETH: 0x1fe89717f971445b8cf5637f05e2b85c35cc2c70

LTC: LcMuFL1QB8jFVcQaTJZA741DZd7CrWz8BR

XMR: 485KKqeDHk9QcsCw5rpL9L6DymkV3Ph69jGxogSzX1QAccFxqCqJ1UtDXac2SA3taNB9DJSWqCDNcTdAkuhnaExfDd6Acmm
