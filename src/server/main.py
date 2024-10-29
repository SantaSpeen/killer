import hashlib
import secrets
import threading
from datetime import timedelta
from venv import logger

from flask import Flask, request, render_template, redirect, url_for, make_response, flash

from core import InterceptHandler, HostDatabase, Host

host_db = HostDatabase("hosts.json")
app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(16)
app.logger.addHandler(InterceptHandler()) # Эксепшены с фласка будут попадать в логи

def generate_hash(login, password, salt):
    return hashlib.sha256(f"{login}{salt}{password}".encode()).hexdigest()

_login = "admin"
_password = "password123"
login_hash = generate_hash(_login, _password, '')
login_hash_cookie = generate_hash(_login, _password, app.secret_key)

def get_error(code, message=None, http_code=200):
    err = {"error": None, "code": code, "http_code": http_code}
    match code:
        case 1:
            err['error'] = f"missing data: {message}"
        case 2:
            err['error'] = f"register first ({message})"
        case 3:
            err['error'] = f"already registered"
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

@app.route('/client', methods=['GET'])
def client_update():
    data = request.json
    device_hash = data.get('device_hash')  # Ожидаем, что клиент отправит свой уникальный хеш
    act = data.get('act')  # Что хочет клиент
    if not all((device_hash, act)):
        return get_error(1, "device_hash or act")
    if len(device_hash) != 64 and act != "register":
        return get_error(2, "bad device_hash")
    hostname, ips, macs = data.get('hostname'), data.get('ips'), data.get('macs')
    # Проверяем данные
    if act in ("register", "update"):
        if not all((hostname, ips, macs)):
            return get_error(1, "hostname, ips, macs")
        if isinstance(hostname, str):
            return get_error(4, "hostname must be a string")
        if not isinstance(ips, list) or not isinstance(macs, list):
            return get_error(4, "ips and macs must be lists")
    match act:
        case "register":  # Регистрируем новое устройство
            host = Host(hostname, ips, macs)
            if host_db.get(host.device_hash) is not None:
                return get_error(3, host.device_hash)
            host_db.add(host)
            return {"device_hash": host.device_hash}
        case "update":  # раз в 12 часов обновляем данные от клиента
            host = host_db.get(device_hash)
            if host is None:
                return get_error(2)
            _device_hash, updated = host.update(hostname, ips, macs)
            return {"device_hash": _device_hash, "updated": updated}
        case "ping":  # раз в 1 минуту клиент шлет пинг
            host = host_db.get(device_hash)
            if host is None:
                return get_error(4, "unknown device")
            host.ping()
            return {"message": "pong"}
        case _:
            return get_error(4, "act")

def check_cookie(need_flash=True):
    if request.cookies.get('login') == login_hash_cookie:
        return True
    if need_flash:
        flash("Bad cookie", "error")
    return False

# Обработка данных после отправки формы
@app.route('/admin', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    if generate_hash(username, password, '') == login_hash:
        response = make_response(redirect(url_for('admin_dashboard')))
        response.set_cookie('login', login_hash_cookie, httponly=True, max_age=timedelta(hours=1))
        return response
    else:
        flash("Invalid login or password", "error")
        return redirect(url_for('admin_index'))

@app.route('/admin', methods=['GET'])
def admin_index():
    if check_cookie(False):
        return redirect(url_for('admin_dashboard'))
    return render_template('index.html')

@app.route('/admin/dashboard', methods=['GET'])
def admin_dashboard():
    if not check_cookie():
        return redirect(url_for('admin_index'))
    return render_template('dashboard.html', hosts=host_db.all())

@app.route('/admin/kill_all', methods=['POST'])
def kill_all():
    if not check_cookie():
        return redirect(url_for('admin_index'))
    return {"message": "Command added to queue"}

@app.errorhandler(Exception)
def handle_error(error):
    status_code, code = 500, 9
    if hasattr(error, 'code'):
        status_code = error.code
    if status_code < 500:
        code = 8
    return get_error(code, str(error), status_code), status_code


def check_clients():
    while True:
        for host in host_db.find_inactive():
            logger.warning(f"Host {host} is inactive")
        threading.Event().wait(60)  # Пауза между проверками (1 минута)

if __name__ == '__main__':
    # Запускаем фоновую задачу проверки клиентов
    threading.Thread(target=check_clients, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
