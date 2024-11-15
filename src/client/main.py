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
KILLER_APP = os.getenv("KILLER_APP", "0")

app = False
if KILLER_APP == "1":
    app = True


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
            if None not in (ip, mac):
                ifaces.append((ip, mac))
            if None not in (ip6, mac6):
                ifaces.append((ip6, mac6))
    print("Found interfaces:", ifaces)
    return ifaces

def shutdown(log_file=LOG_FILE):
    operating_system = platform.system()
    if operating_system == "Windows":
        with open(log_file, "a") as f:
            f.write(f"{datetime.now()} Shutdown request from killer server.\n")
        os.system("shutdown /s /t 1")
    else:
        with open(log_file, "a") as f:
            f.write(f"{datetime.now()} Shutdown request from killer server.")
        os.system("shutdown -P now")
    sys.exit(0)


class Host:
    ping_interval = timedelta(minutes=1)
    update_interval = timedelta(hours=12)

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
        if act not in ['ping', 'exit']:
            j = {"act": act, "device_hash": self.device_hash, "hostname": self.hostname, "ips": self.ips, "macs": self.macs}
        try:
            s = self.session.post(self.endpoint, json=j).json()
        except requests.exceptions.RequestException as e:
            print(f"[API] Error: {e}")
            if self.run:
                return {}
            exit(1)
        if s.get("error"):
            print(f"[API] Error: {s}")
        return s

    def shutdown(self):
        self.api("shutdown")
        self.run = False
        self._save_hash()
        print("Exited...")

    def _new_hash(self, device_hash):
        self.last_update = datetime.now(timezone.utc)
        self.device_hash = device_hash
        self._save_hash()

    def register(self):
        print("Registering...")
        u = self.api("register")
        if u.get("device_hash"):
            self._new_hash(u['device_hash'])
            print(f"Registered with device hash: {self.device_hash}")
        else:
            print("Failed to register")
            exit(1)

    def update(self):
        print("Updating...")
        u = self.api("update")
        if u.get("updated"):
            self._new_hash(u['device_hash'])
            print(f"Updated device hash: {self.device_hash}")
        else:
            print("Device hash not updated")

    def _pre_start(self):
        if self.device_hash is None:
            self.register()
        else:
            print(f"Using cashed hash: {self.device_hash}")
        p = self.api("ping")
        if p.get("code") == 4:
            self.device_hash = None
            return self._pre_start()
        if self.api("ping").get("message") == "pong":
            print("Connected to server")
            self.run = True

    def start(self):
        print(f"Ping interval: {self.ping_interval}; Update interval: {self.update_interval};")
        self._read_hash()
        self._pre_start()
        while self.run:
            if datetime.now(timezone.utc) - self.last_update > self.update_interval:
                self.update()
            p = self.api("ping")
            if p.get("code") == 4:
                print('wtf')
                self._pre_start()

            if p.get("kill_apps"):
                if app:
                    print("Received kill_apps request. Shutting down...")
                    shutdown(LOG_FILE)
                else:
                    print("Received kill_apps request, but client registered not as app-host. Ignoring...")
            if p.get("kill_other"):
                print("Received kill_other request. Shutting down...")
                shutdown(LOG_FILE)

            time.sleep(self.ping_interval.total_seconds())


if __name__ == '__main__':
    print("Starting client...")
    host = Host(ENDPOINT, HASH_FILE)
    try:
        host.start()
    except KeyboardInterrupt:
        pass
    finally:
        host.shutdown()
