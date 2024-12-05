import hashlib
import json
import platform
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from easydict import EasyDict as edict
from loguru import logger


@dataclass
class Delays:
    kill_first: int
    kill_second: int
    history: list[float] = field(default_factory=lambda: [0.0, ])

    def __is_kill_first(self):
        current_time = datetime.now(timezone.utc).timestamp()
        if current_time - self.history[-1] < self.kill_first:
            return True
        return False

    def __is_kill_second(self):
        current_time = datetime.now(timezone.utc).timestamp()
        return current_time - self.history[-1] < self.kill_first + self.kill_second

    def status(self) -> tuple[bool, bool]:
        # app -> severs
        if self.__is_kill_first():
            return True, False
        elif self.__is_kill_second():
            return False, True
        return False, False

    def kill_request(self):
        self.history.append(datetime.now(timezone.utc).timestamp())
        logger.warning(f"Killing history updated: {self.history}")


def generate_hash(login, password, salt=''):
    return hashlib.sha256(f"{login}{salt}{password}".encode()).hexdigest()

@dataclass
class Auth:
    login: str
    password: str
    woraw: str = field(init=False)  # raw
    wsolt: str = field(init=False)  # salt

    def __eq__(self, other):
        if isinstance(other, Auth):
            return generate_hash(self.login, self.password) == generate_hash(other.login, other.password)
        if isinstance(other, str):
            return generate_hash(self.login, self.password) == other
        if isinstance(other, (tuple, list)):
            return generate_hash(self.login, self.password) == generate_hash(*other)

    def generate_cookies(self, salt):
        self.woraw = generate_hash(self.login, self.password)
        self.wsolt = generate_hash(self.login, self.password, salt)

    def check_cookies(self, woraw, wsolt):
        return self.woraw == woraw and self.wsolt == wsolt

@dataclass
class Notify:
    enabled: bool
    template: str

    def render_template(self, time, host, status, act):
        return self.template.format(time, host, status, act)

    def notify(self, message):
        pass

@dataclass
class Telegram(Notify):
    enabled: bool
    template: str
    token: str
    chat_id: int
    settings: dict

    def notify(self, message):
        requests.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data={"chat_id": self.chat_id, "text": message, **self.settings})



class Config:
    def __init__(self, file):
        self.config_file = Path(file)
        self.__config_raw = edict({
            "client": {
                "update_interval": 43200,
                "ping_interval": 60
            },
            "auth": [
                {"login": "admin", "password": "P@ssw0rd"}
            ],
            "delays": {
                "kill_first": 60,
                "kill_second": 120
            },
            "log": {
                "stdout": {
                    "enabled": True,
                    "level": "DEBUG",
                    "format": "| {level: <8} | {message}",
                    "colorize": False,
                    "enqueue": True,
                    "backtrace": False,
                    "diagnose": False
                },
                "file": {
                    "enabled": True,
                    "dir": "/var/log/",
                    "file": "killer.log",
                    "format": "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
                    "level": "DEBUG",
                    "rotation": "10 MB",
                    "retention": "30 day"
                }
            },
            "storage": {
                "dir": "/etc/killer/",
                "hosts": "hosts.json"
            },
            "notify": {
                "telegram": {
                    "enabled": False,
                    "template": "Killer notification:\n"
                                "  {time}\n"
                                "  Host: `{host}`\n"
                                "  Status: {status}\n"
                                "  Act: `{act}`",
                    "token": "TOKEN_HERE",
                    "chat_id": 0,
                    "settings": {
                        "parse_mode": "Markdown"
                    }
                }
            }
        })
        self.secret_key = secrets.token_urlsafe(16)
        self.__init_config_file()
        self.__prepare()

    def __init_config_file(self):
        if not self.config_file.exists():
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            self.config_file.write_text(json.dumps(self.__config_raw, indent=4), "utf-8")
            print("File with configuration created.")
        try:
            _raw = json.loads(self.config_file.read_text("utf-8"))
            self.__config_raw.update(_raw)
            self.__config_raw['auth'] = _raw['auth']
            self.__config_raw['delays'].update(_raw['delays'])
            self.__config_raw['log'].update(_raw['log'])
            self.__config_raw['storage'].update(_raw['storage'])
            self.__config_raw['notify'].update(_raw['notify'])
        except json.JSONDecodeError:
            print("Error while loading configuration file.")
            sys.exit(0)
        print("Configuration loaded.")

    def __prepare(self):
        # Готовим конфигурацию к использованию
        self.__config_raw['auth'] = list(map(lambda x: Auth(**x), self.__config_raw['auth']))
        for a in self.__config_raw['auth']:
            a.generate_cookies(self.secret_key)
        self.__config_raw['log']['file']['dir'] = Path(self.__config_raw['log']['file']['dir'])
        self.__config_raw['storage']['dir'] = Path(self.__config_raw['storage']['dir'])
        if platform.system() == "Linux":
            # Создаем папки, если их нет
            # log
            self.__config_raw['log']['file']['dir'] = self.__config_raw['log']['file']['dir'] / self.__config_raw['log']['file']['file']
            if not self.__config_raw['log']['file']['dir'].exists():
                self.__config_raw['log']['file']['dir'].mkdir(parents=True, exist_ok=True)
            # storage
            self.__config_raw['storage']['hosts'] = self.__config_raw['storage']['dir'] / self.__config_raw['storage']['hosts']
            if not self.__config_raw['storage']['dir'].exists():
                self.__config_raw['storage']['dir'].mkdir(parents=True, exist_ok=True)
        self.__config_raw['notify']['telegram'] = Telegram(**self.__config_raw['notify']['telegram'])
        self.__config_raw['delays'] = Delays(**self.__config_raw['delays'])

    @property
    def client(self):
        return self.__config_raw['client']

    @property
    def auth(self):
        return self.__config_raw['auth']

    @property
    def log(self):
        return self.__config_raw['log']

    @property
    def stdout_log(self):
        s = self.__config_raw['log']['stdout'].copy()
        s['sink'] = sys.stdout
        del s['enabled']
        return s

    @property
    def file_log(self):
        f_args = self.__config_raw['log']['file'].copy()
        f = f_args['dir'] / f_args['file']
        del f_args['enabled']
        del f_args['dir']
        del f_args['file']
        return f, f_args

    @property
    def delays(self):
        return self.__config_raw['delays']

    @property
    def storage(self):
        return self.__config_raw['storage']

    @property
    def notify(self):
        return self.__config_raw['notify']

