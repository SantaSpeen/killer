import hashlib
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from loguru import logger

class Host:
    _host_db = None
    inactive_timeout = timedelta(minutes=1, seconds=15)

    def __init__(self, hostname, ips, macs, server: bool, last_request: int = None, last_update: int = None, enable=True):
        if self._host_db is None:
            raise ValueError("Host database is not configured")
        self.hostname = hostname
        self.device_hash = None
        self.ips = ips
        self.macs = macs
        self.server = server
        if last_request is None:
            last_request = int(datetime.now(timezone.utc).timestamp())
        self.last_request = datetime.fromtimestamp(last_request, timezone.utc)
        if last_update is None:
            last_update = int(datetime.now(timezone.utc).timestamp())
        self.last_update = datetime.fromtimestamp(last_update, timezone.utc)
        self.enable = enable  # Если хост отключили, и не нужно его алертить
        self.generate_hash()

    def registered(self):
        return self._host_db.get(self.device_hash) is not None

    def save(self):
        if not self.registered():
            self._host_db.add(self)
        else:
            self._host_db.update(self)

    def last_request_local(self, plus):
        return self.last_request.astimezone(timezone(timedelta(hours=plus)))

    def last_update_local(self, plus):
        return self.last_update.astimezone(timezone(timedelta(hours=plus)))

    def _check_enable(self):
        if not self.enable:
            self.enable = True
            logger.info(f"[{self.hostname}] Host marked as active")
            [callback(self) for callback in HostDatabase.enable_callbacks]

    def update(self, hostname, ips, macs, server):
        """Обновление данных хоста"""
        self._check_enable()
        self.hostname = hostname
        self.ips = ips
        self.macs = macs
        self.server = server
        self.last_update = datetime.now(timezone.utc)
        old_device_hash = self.device_hash
        self.generate_hash()
        self.ping()
        logger.info(f"[datastore] Host data updated: {self}")
        if self.device_hash != old_device_hash:
            self._host_db.replace(old_device_hash, self)
        else:
            self._host_db.update(self)
        return self.device_hash

    def ping(self):
        """Обновление времени последнего запроса"""
        self._check_enable()
        self.last_request = datetime.now(timezone.utc)
        logger.info(f"[{self.hostname}] ping: {self.last_request}")
        self.save()

    def shutdown(self):
        """Хост сообщил о завершении работы"""
        if not self.enable:
            return # Хост уже отключен
        self.enable = False
        logger.info(f"[{self.hostname}] Host marked as inactive")
        self.save()
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
        hostname, device_hash, ips, macs, server, last_request, last_update, enable = line
        host = cls(hostname, ips, macs, server, last_request, last_update, enable)
        host.generate_hash()
        if device_hash != host.device_hash:
            logger.error(f"[datastore] Hash mismatch of host {hostname}: {device_hash} != {host.device_hash}")
        return host

    def to_tuple(self) -> tuple:
        """Преобразование объекта хоста в кортеж"""
        return (
            self.hostname, self.device_hash, self.ips, self.macs, self.server,
            int(self.last_request.timestamp()), int(self.last_update.timestamp()),
            self.enable
        )

    def to_dict(self):
        """Преобразование объекта хоста в словарь"""
        return {
            "hostname": self.hostname,
            "device_hash": self.device_hash,
            "ips": self.ips,
            "macs": self.macs,
            "server": self.server,
            "last_request": self.last_request.timestamp(),
            "last_update": self.last_update.timestamp(),
            "enable": self.enable
        }

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
        Host._host_db = self
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
        _sleep_parts = [0] * int(Host.inactive_timeout.total_seconds())
        while self.run:
            for host in self.find_inactive():
                logger.warning(f"Host {host.hostname!r} is inactive")
                [callback(host) for callback in self.inactive_callbacks]
            for _ in _sleep_parts:
                threading.Event().wait(1)  # Пауза между проверками
                if not self.run:
                    return

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

    def all(self, _asdict=False):
        data = list(map(Host.from_tuple, self.data.values()))
        if not _asdict:
            return data
        return [host.to_dict() for host in data]

    def find_inactive(self):
        for host in self.all():
            if not host.enable:
                continue
            if not host.is_active():
                yield host

    def start_checking(self):
        self.t = threading.Thread(target=self._check_clients)
        self.t.start()

    def stop_checking(self):
        self.run = False
        self.t.join()
        self.t = None
