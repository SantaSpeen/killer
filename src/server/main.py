import json
import os
import platform
from datetime import timedelta, datetime

from flask import Flask, request, render_template, redirect, url_for, make_response, flash
from loguru import logger

from core import InterceptHandler, HostDatabase, Host, config

app = Flask(__name__)
app.secret_key = config.secret_key
app.logger.addHandler(InterceptHandler())  # Эксепшены с фласка будут попадать в логи
host_db = HostDatabase(config.storage.hosts)
# Сначала убиваем все приложения, потом остальные
#      web     |                            kill_app_timeout + kill_timeout                                |
# -> kill_all -> kill_apps: true -kill_app_timeout-> kill_apps: false; kill_other: true -kill_serv_timeout-> kill_self
timeouts = config.timeout
_index = {
    "login": []
}


def kill_self():
    logger.warning("Killing server")
    operating_system = platform.system()
    if operating_system == "Windows":
        with open("killer-client.txt", "a") as f:
            f.write(f"{datetime.now()} Shutdown request from killer server.\n")
        os.system("shutdown /s /t 1")
    else:
        with open("/var/log/killer-client", "a") as f:
            f.write(f"{datetime.now()} Shutdown request from killer server.")
        os.system("shutdown -P now")


def get_error(code, message=None, http_code=200):
    err = {"error": None, "code": code, "http_code": http_code}
    match code:
        case 1:
            err['error'] = f"missing data: {message}"
        case 2:
            err['error'] = f"register first ({message})"
        case 3:
            err['error'] = "already registered"
            err['device_hash'] = message
        case 4:
            err['error'] = f"invalid data: {message}"
        case 8:
            err['error'] = f"external client error: {message}"
        case 9:
            err['error'] = f"internal server error: {message}"
        case _:
            err['error'] = f"unknown error ({message})"
    return err


def _get_host_info(act, data):
    hostname, ips, macs, server = data.get('hostname'), data.get('ips'), data.get('macs'), data.get("server")
    # Проверяем данные
    if act in ("register", "update"):
        if not all((hostname, ips, macs)):
            return False, get_error(1, "hostname, ips, macs")
        if not isinstance(hostname, str):
            return False, get_error(4, "hostname must be a string")
        if not isinstance(ips, list) or not isinstance(macs, list):
            return False, get_error(4, "ips and macs must be lists")
        if not isinstance(server, bool):
            return False, get_error(4, "server must be a boolean")
    return True, hostname, ips, macs, server


def _check_cookie(need_flash=True):
    auth = request.cookies.get('woraw'), request.cookies.get('wsolt')
    if auth in _index['login']:
        return True
    if need_flash:
        logger.warning(f"Bad cookie from {request.remote_addr}")
        flash("Bad cookie", "error")
    return False


@app.route('/client', methods=['POST'])
def client_update():
    data = request.json
    if isinstance(data, str):
        data = json.loads(data)
    device_hash = data.get('device_hash')  # Ожидаем, что клиент отправит свой уникальный хеш
    act = data.get('act')  # Что хочет клиент
    if act != "register":
        if not all((device_hash, act)):
            return get_error(1, "device_hash or act")
        if len(device_hash) != 64:
            return get_error(2, "bad device_hash")
    _tmp = _get_host_info(act, data)
    ok, host_info = _tmp[0], _tmp[1:]
    if not ok:
        return _tmp[1]  # Ошибка
    match act:
        case "register":  # Регистрируем новое устройство
            host = Host(*host_info)
            if host_db.get(host.device_hash) is not None:
                return get_error(3, host.device_hash)
            host_db.add(host)
            return {"device_hash": host.device_hash}
        case "update":  # раз в 12 часов обновляем данные от клиента
            host = host_db.get(device_hash)
            if host is None:
                return get_error(2)
            _device_hash, updated = host.update(*host_info)
            if updated:
                host_db.replace(device_hash, host)
            return {"device_hash": _device_hash, "updated": updated}
        case "ping":  # раз в 1 минуту клиент шлет пинг
            host = host_db.get(device_hash)
            if host is None:
                return get_error(4, "unknown device")
            host.ping()
            host_db.update(host)
            # TODO: Переделать на статусы
            kill_apps, kill_other = timeouts.status()
            return {"message": "pong", "kill_apps": kill_apps, "kill_other": kill_other}
        case "shutdown":  # клиент завершает работу
            host = host_db.get(device_hash)
            if host is None:
                return get_error(4, "unknown device")
            host.shutdown()
            host_db.update(host)
            return {"message": 0}
        case _:
            return get_error(4, "act")


# Обработка данных после отправки формы
@app.route('/admin', methods=['POST'])
def login():
    user = None
    auth = request.form.get('username'), request.form.get('password')
    for i in config.auth:
        if i == auth:
            user = i
    if user is not None:
        logger.success(f"Admin logged in from {request.remote_addr}")
        response = make_response(redirect(url_for('admin_dashboard')))
        response.set_cookie('woraw', user.woraw, max_age=timedelta(hours=1))
        response.set_cookie('wsolt', user.wsolt, max_age=timedelta(hours=1))
        _index['login'].append((user.woraw, user.wsolt))
        return response
    else:
        logger.warning(f"Invalid login or password from {request.remote_addr}")
        flash("Invalid login or password", "error")
        return redirect(url_for('admin_index'))


@app.route('/admin', methods=['GET'])
def admin_index():
    if _check_cookie(False):
        return redirect(url_for('admin_dashboard'))
    logger.info(f"Login page opened from {request.remote_addr}")
    return render_template('index.html')


@app.route('/admin/dashboard', methods=['GET'])
def admin_dashboard():
    if not _check_cookie():
        return redirect(url_for('admin_index'))
    logger.info(f"Admin dashboard opened from {request.remote_addr}")
    p = {
        "timeouts": timeouts,
        "hosts": host_db.all()
    }
    return render_template('dashboard.html', **p)


@app.route(f'/admin/api/<method>', methods=['POST'])
def admin_api(method):
    if not _check_cookie():
        return get_error(4, "invalid cookie"), 403
    match method:
        case "kill_all":
            logger.info(f"Kill all command received from {request.remote_addr}")
            timeouts.kill_request()
            return {"message": "Command added to queue"}
        case "updates":
            return {"status": timeouts.status(), "hosts": host_db.all(True)}


@app.errorhandler(Exception)
def handle_error(error):
    status_code, code = 500, 9
    if hasattr(error, 'code'):
        status_code = error.code
    if status_code < 500:
        code = 8
    if status_code == 500:
        logger.exception(error)
    return get_error(code, str(error), status_code), status_code


if __name__ == '__main__':
    # Запускаем фоновую задачу проверки клиентов
    try:
        host_db.start_checking()
        app.run(host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        pass
    finally:
        host_db.stop_checking()
