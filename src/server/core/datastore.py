import hashlib
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from loguru import logger


class Host:
    inactive_timeout = timedelta(minutes=1, seconds=15)

    def __init__(self, hostname, ips, macs, last_request: int = None, enable=True):
        self.hostname = hostname
        self.device_hash = None
        self.ips = ips
        self.macs = macs
        if last_request is None:
            last_request = int(datetime.now(timezone.utc).timestamp())
        self.last_request = datetime.fromtimestamp(last_request, timezone.utc)
        self.last_update = datetime.now(timezone.utc).timestamp()
        self.enable = enable  # Если хост отключили, и не нужно его алертить
        self.generate_hash()

    def _check_enable(self):
        if not self.enable:
            self.enable = True
            logger.info(f"[{self.hostname}] Host marked as active")
            [callback(self) for callback in HostDatabase.enable_callbacks]

    def update(self, hostname, ips, macs):
        """Обновление данных хоста"""
        self._check_enable()
        self.hostname = hostname
        self.ips = ips
        self.macs = macs
        self.last_update = datetime.now(timezone.utc).timestamp()
        old_device_hash = self.device_hash
        self.generate_hash()
        self.ping()
        logger.info(f"[datastore] Host data updated: {self}")
        return self.device_hash, self.device_hash != old_device_hash

    def ping(self):
        """Обновление времени последнего запроса"""
        self._check_enable()
        self.last_request = datetime.now(timezone.utc)
        logger.info(f"[{self.hostname}] ping: {self.last_request}")

    def shutdown(self):
        """Хост сообщил о завершении работы"""
        self.enable = False
        logger.info(f"[{self.hostname}] Host marked as inactive")
        [callback(self) for callback in HostDatabase.shutdown_callbacks]

    def generate_hash(self):
        """Генерация уникального хеша для хоста по его MAC и IP адресам"""
        hash_form = f'{self.hostname}{self.macs}'
        self.device_hash = hashlib.sha256(hash_form.encode()).hexdigest()

    def is_active(self):
        """Проверка активности хоста"""
        if not self.enable:
            return False
        current_time = datetime.now(timezone.utc)
        if (current_time - self.last_request) > self.inactive_timeout:
            return False
        return True

    @classmethod
    def from_tuple(cls, line):
        """Создание объекта хоста из кортежа"""
        if line is None:
            return line
        hostname, device_hash, ips, macs, last_request, enable = line
        host = cls(hostname, ips, macs, last_request, enable)
        host.generate_hash()
        if device_hash != host.device_hash:
            logger.error(f"[datastore] Hash mismatch of host {hostname}: {device_hash} != {host.device_hash}")
        return host

    def to_tuple(self) -> tuple:
        """Преобразование объекта хоста в кортеж"""
        return self.hostname, self.device_hash, self.ips, self.macs, int(self.last_request.timestamp()), self.enable

    def __eq__(self, other):
        return self.to_tuple() == other.to_tuple()

    def __str__(self):
        return f"Host(name='{self.hostname}' identifier=('{self.device_hash}'; {self.macs}; {self.ips}))"


class HostDatabase:
    inactive_callbacks = []
    shutdown_callbacks = []
    enable_callbacks = []

    def __init__(self, data_file):
        self.t = None
        self.run = True
        self.file = Path(data_file)
        self.data = {}  # hash: (hostname, device_hash, ips, macs, last_request, enable)
        self._read()

    def _read(self):
        if not self.file.exists():
            self._write()
        with open(self.file, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        logger.success(f"[datastore] Loaded {len(self.all())} hosts")

    def _write(self):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def _check_clients(self):
        while True:
            for host in self.find_inactive():
                logger.warning(f"Host {host.hostname!r} is inactive")
                [callback(host) for callback in self.inactive_callbacks]
            threading.Event().wait(Host.inactive_timeout.total_seconds())  # Пауза между проверками

    def get(self, device_hash):
        host = self.data.get(device_hash)
        return Host.from_tuple(host)

    def add(self, host: Host):
        if self.data.get(host.device_hash):
            return
        if host.device_hash is None:
            host.generate_hash()
        self.data[host.device_hash] = host.to_tuple()
        logger.info(f"[datastore] Add new host: {host}")
        self._write()

    def update(self, host: Host):
        if self.data.get(host.device_hash) is None:
            return
        self.data[host.device_hash] = host.to_tuple()
        self._write()

    def replace(self, old_device_hash, new_host: Host):
        if self.data.get(old_device_hash) is None:
            return
        self.data.pop(old_device_hash)
        self.data[new_host.device_hash] = new_host.to_tuple()
        logger.info(f"[datastore] device_hash replaced for {new_host.hostname!r}: {old_device_hash} -> {new_host.device_hash}")
        self._write()

    def all(self):
        return list(map(Host.from_tuple, self.data.values()))

    def find_inactive(self):
        for host in self.all():
            if not host.enable:
                continue
            if not host.is_active():
                yield host
