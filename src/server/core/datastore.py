import json
import time
from datetime import datetime, timezone
from pathlib import Path


class Host:
    def __init__(self, device_hash, ips, macs, hostname, last_request=None):
        self.device_hash = device_hash
        self.ips = ips
        self.macs = macs
        self.hostname = hostname
        if last_request is None:
            last_request = int(datetime.now(timezone.utc).timestamp())
        self.last_request = last_request

    @classmethod
    def from_tuple(cls, line):
        device_hash, ips, macs, hostname, last_request = line
        return cls(device_hash, ips, macs, hostname, last_request)

    def to_tuple(self) -> tuple:
        return self.device_hash, self.ips, self.macs, self.hostname, self.last_request

    def __eq__(self, other):
        return self.to_tuple() == other.to_tuple()

    def __str__(self):
        return f"Host(name='{self.hostname}' identifier=({self.device_hash} @ {self.ips})"


class HostDatabase:
    def __init__(self, data_file):
        self.t = None
        self.run = True
        self.file = Path(data_file)
        self.data = {}  # hash: {ip, hostname, last_used}
        self._read()

    def _read(self):
        if not self.file.exists():
            self._write()
        with open(self.file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def _write(self):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def get(self, ip=None, mac=None):
        if ip:
            mac = self.data['index']['ip'].get(str(ip))
        if self.data['devices'].get(mac):
            return Host.from_tuple(self.data['devices'][mac])

    def add(self, host: Host):
        if host.ips:
            self.data['index']['ip'][host.ips] = host.device_hash
        self.data['devices'][host.device_hash] = host.to_tuple()
        self._write()

    def inactive(self, host: Host):
        if host.ips:
            del self.data['index']['ip'][host.ips]
        del self.data['devices'][host.device_hash]

    def all(self):
        return list(map(Host.from_tuple, self.data['devices'].values()))

    def flush(self):
        now = time.time()
        for host in self.all():
            if host.last_request == 0:
                continue
            if now - host.last_request > self.conf.lease_time:
                self.inactive(host)
        self._write()
