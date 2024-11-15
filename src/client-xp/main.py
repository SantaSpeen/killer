import atexit
import json
import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import wmi

# noinspection DuplicatedCode
ENDPOINT = os.getenv("ENDPOINT", "http://127.0.0.1:5000/client")
HASH_FILE = os.getenv("HASH_FILE", "device.hash")
LOG_FILE = os.getenv("LOG_FILE", "killer-client.txt")
KILLER_APP = os.getenv("KILLER_APP", "0")

app = False
if KILLER_APP == "1":
    app = True


def get_ip_mac_addresses():
    ifaces = []
    c = wmi.WMI()

    for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
        ip = nic.Description
        mac = nic.MACAddress
        # Получаем IP-адреса
        ip_addresses = nic.IPAddress
        if ip_addresses:
            for ip_address in ip_addresses:
                ifaces.append((ip_address, mac))
    print("Found interfaces:", ifaces)
    return ifaces

def shutdown(log_file=LOG_FILE):
    operating_system = platform.system()
    if operating_system == "Windows":
        with open(log_file, "a") as f:
            f.write("{} Shutdown request from killer server.\n".format(datetime.now()))
        os.system("shutdown /s /t 1")
    else:
        with open(log_file, "a") as f:
            f.write("{} Shutdown request from killer server.".format(datetime.now()))
        os.system("shutdown -P now")
    # sys.exit(0)


class Host(object):
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
        with open(str(self.hash_file), "w") as f:
            f.write("{}::{:s}".format(self.last_update.timestamp(), self.device_hash))

    def _read_hash(self):
        if not self.hash_file.exists():
            return
        with open(str(self.hash_file), "r") as f:
            d = f.read().strip()
        last_update, self.device_hash = d.split("::", 1)
        self.last_update = datetime.fromtimestamp(float(last_update), timezone.utc)

    def api(self, act):
        headers = {'Content-Type': 'application/json'}
        j = {"act": act, "device_hash": self.device_hash}
        if act not in ['ping', 'exit']:
            j = {
                "act": act,
                "device_hash": self.device_hash,
                "hostname": self.hostname,
                "ips": self.ips,
                "macs": self.macs,
                "is_app": app
            }
        try:
            s = self.session.post(self.endpoint, json=json.dumps(j), headers=headers).json()
        except requests.exceptions.RequestException as e:
            print("[API] Error: {}".format(e))
            if self.run:
                return {}
            sys.exit(1)
        if s.get("error"):
            print("[API] Error: {}".format(s))
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
            print("Registered with device hash: {}".format(self.device_hash))
        else:
            print("Failed to register")
            sys.exit(1)

    def update(self):
        print("Updating...")
        u = self.api("update")
        if u.get("updated"):
            self._new_hash(u['device_hash'])
            print("Updated device hash: {}".format(self.device_hash))
        else:
            print("Device hash not updated")

    def _pre_start(self):
        if self.device_hash is None:
            self.register()
        else:
            print("Using cashed hash: {}".format(self.device_hash))
        p = self.api("ping")
        if p.get("code") == 4:
            self.device_hash = None
            return self._pre_start()
        if self.api("ping").get("message") == "pong":
            print("Connected to server")
            self.run = True

    def start(self):
        print("Ping interval: {}; Update interval: {};".format(self.ping_interval, self.update_interval))
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
    atexit.register(host.shutdown)
    try:
        host.start()
    except KeyboardInterrupt:
        pass
    finally:
        host.shutdown()
