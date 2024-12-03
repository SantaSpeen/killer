# pip install snimpy
from snimpy.manager import Manager, load
from snimpy.snmp import SNMPException
import requests
import time

# Настройки SNMP
host = "192.168.1.1"  # IP-адрес APC
community = "public"  # Коммьюнити строка SNMP
version = 2           # Версия SNMP
timeout = 1           # Таймаут в секундах
battery_trigger = 10 * 60  # 10 мин

api_endpoint = "http://127.0.0.1:5000"

# Настройки авторизации
login_url = api_endpoint+"/admin"  # URL для авторизации
username = "admin"                      # Имя пользователя
password = "password"                   # Пароль

request_url = api_endpoint+"/admin/kill_all"  # URL для дальнейших запросов


def send_killall():
    response = requests.post(
        login_url,
        data={"username": username, "password": password}
    )
    response.raise_for_status()
    cookies = response.cookies
    k = requests.post(request_url, cookies=cookies)
    print(k)

def main():
    try:
        # Создание менеджера SNMP
        manager = Manager(host, community, version=version, timeout=timeout)

        while True:
            try:
                # Получение оставшегося времени на батарее
                battery_runtime = manager.upsAdvBatteryRunTimeRemaining
                runtime_minutes = battery_runtime

                print(f"APC Battery: {runtime_minutes} min")

                if battery_runtime < battery_trigger:
                    print("Battery is low. Sending killall request...")
                    send_killall()

            except SNMPException as e:
                print(f"SNMP error: {e}")

            # Ожидание 50 секунд
            time.sleep(50)

    except Exception as e:
        print(f"Error: {e}")


# Загрузка MIB
load("UPS-MIB")

if __name__ == "__main__":
    main()
