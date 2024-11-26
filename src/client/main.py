import atexit
import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psutil
import requests

# noinspection DuplicatedCode
ENDPOINT = os.getenv("ENDPOINT", "http://127.0.0.1:5000/client")
HASH_FILE = os.getenv("HASH_FILE", "device.hash")
LOG_FILE = os.getenv("LOG_FILE", "killer-client.txt")
NOT_SERVER = os.getenv("NOT_SERVER", "0")

server = True
if NOT_SERVER == "1":
    server = False


# noinspection t
def get_ip_mac_addresses():
    interfaces = psutil.net_if_addrs()
    interface_stats = psutil.net_if_stats()
    ifaces = []
    for iface_name, addrs in interfaces.items():
        if interface_stats[iface_name].isup:
            ip, mac = None, None
            ip6, mac6 = None, None
            for addr in addrs:
                if addr.family == socket.AF_INET:  # IPv4
                    ip = addr.address
                elif addr.family == psutil.AF_LINK:  # MAC
                    mac = addr.address.replace("-", ":")
                if addr.family == socket.AF_INET6:  # IPv6
                    ip6 = addr.address
                elif addr.family == psutil.AF_LINK:  # MAC
                    mac6 = addr.address.replace("-", ":")
            if ip.startswith(('127.', '224.', '239.')):
                continue
            if ip6 == "::1":
                continue
            if "00:00:00:00:00:00" in (mac, mac6):
                continue
            if None not in (ip, mac):
                ifaces.append((ip, mac))
            if None not in (ip6, mac6):
                ifaces.append((ip6, mac6))
    print("Found interfaces:", ifaces)
    return ifaces

def shutdown(log_file=LOG_FILE):
    operating_system = platform.system()
    with open(log_file, "a") as f:
        f.write("[{}] Shutdown request from killer server.\n".format(datetime.now()))
    if operating_system == "Windows":
        os.system("shutdown /s /t 1")
    else:
        os.system("shutdown -P now")
    # sys.exit(0)


class Host:
    ping_interval = timedelta(seconds=0)
    update_interval = timedelta(seconds=0)

    def __init__(self, endpoint, hash_file):
        self.run = False

        self.endpoint = endpoint
        self.hash_file = Path(hash_file)
        self.session = requests.Session()

        self.ips = []
        self.macs = []
        self.hostname = None
        self._update_params()

        self.last_update = None
        self.device_hash = None

    def _update_params(self):
        self.hostname = socket.gethostname()
        ifaces = get_ip_mac_addresses()
        self.ips = [ip for ip, _ in ifaces]
        self.macs = [mac for _, mac in ifaces]

    def _save_hash(self):
        if self.last_update is None or self.device_hash is None:
            print("Can't save hash: last_update or device_hash is None")
            return
        with open(self.hash_file, "w") as f:
            f.write(f"{self.last_update.timestamp()}::{self.device_hash}")

    def _read_hash(self):
        if not self.hash_file.exists():
            return
        with open(self.hash_file, "r") as f:
            d = f.read().strip()
        last_update, self.device_hash = d.split("::", 1)
        self.last_update = datetime.fromtimestamp(float(last_update), timezone.utc)

    def api(self, act):
        j = {"act": act, "device_hash": self.device_hash}
        if act not in ('ping', 'exit'):
            j.update({
                "hostname": self.hostname,
                "ips": self.ips,
                "macs": self.macs,
                "server": server
            })
        try:
            s = self.session.post(self.endpoint, json=j).json()
        except requests.exceptions.RequestException as e:
            print(f"[API] Error: {e}")
            if self.run:
                return {}
            sys.exit(1)
        if s.get("error"):
            if s['code'] != 3:
                print(f"[API] Error: {s}")
        return s

    def shutdown(self, reason="atexit"):
        self.api("shutdown")
        self.run = False
        self._save_hash()
        print("Exited ({})...".format(reason))

    def _new_hash(self, device_hash):
        self.last_update = datetime.now(timezone.utc)
        self.device_hash = device_hash
        self._save_hash()

    def register(self):
        print("Registering...")
        u = self.api("register")
        if u.get("code") == 3 and u['device_hash'] == self.device_hash:
            print(f" - Already registered. Cached device_hash: {self.device_hash}")
            return
        else:
            self._new_hash(u['device_hash'])
            print(f" - Ready. New device_hash: {self.device_hash}")

    def update(self):
        print("Updating...")
        u = self.api("update")
        _old = self.device_hash
        if u.get("device_hash") != self.device_hash:
            print(f" - Device hash changed: {self.device_hash} -> {u['device_hash']}")
        else:
            print(" - Device hash not updated")
        _pi, _ui = u['ping_interval'], u['update_interval']
        if self.ping_interval.total_seconds() != _pi or self.update_interval.total_seconds() != _ui:
            self.ping_interval = timedelta(seconds=_pi)
            self.update_interval = timedelta(seconds=_ui)
            print(f" - Intervals updated: ping={self.ping_interval}; update={self.update_interval}")
        else:
            print(f" - Intervals not updated")

    def _pre_start(self, i=0):
        if i > 3:
            print("Can't connect to server. Exiting...")
            sys.exit(1)
        self.register()
        p = self.api("ping")
        if p.get("code") == 4:
            self.device_hash = None
            return self._pre_start(i+1)
        if self.api("ping").get("message") == "pong":
            print("Connected to server")
            self.run = True

    def start(self):
        print(f'Mode: {"server" if server else "app"}')
        self._read_hash()
        self._pre_start()
        self.update()
        while self.run:
            if datetime.now(timezone.utc) - self.update_interval > self.last_update:
                self.update()
            p = self.api("ping")
            if p.get("code") == 4:
                print('wtf')
                self._pre_start()

            kill_first, kill_second = p['status']
            if kill_first:
                if not server:
                    print("Received kill_first request. Shutting down...")
                    shutdown(LOG_FILE)
                else:
                    print("Received kill_first request, but client registered as server. Ignoring...")
            if kill_second:
                print("Received kill_second request. Shutting down...")
                shutdown(LOG_FILE)

            time.sleep(self.ping_interval.total_seconds())


if __name__ == '__main__':
    print("Starting client...")
    host = Host(ENDPOINT, HASH_FILE)
    atexit.register(host.shutdown)
    try:
        host.start()
    except KeyboardInterrupt:
        pass
    finally:
        host.shutdown("finally")
