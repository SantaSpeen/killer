import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, request

from core import InterceptHandler

app = Flask(__name__)
# эксепшены с фласка будут попадать в логи
app.logger.addHandler(InterceptHandler())

# Хранилище для клиентов
clients = {}

# Таймаут для уведомления (2 минуты)
timeout = timedelta(minutes=2)

def check_clients():
    while True:
        current_time = datetime.now(timezone.utc)
        for client_id, last_seen in list(clients.items()):
            if current_time - last_seen > timeout:
                print(f"Client {client_id} missed the update!")
                # Уведомление или другое действие
                del clients[client_id]
        threading.Event().wait(60)  # Пауза между проверками (1 минута)

@app.route('/client', methods=['GET'])
def client_update():
    data = request.json
    device_hash = data.get('device_hash')  # Ожидаем, что клиент отправит свой уникальный хеш
    if device_hash:
        clients[device_hash] = datetime.utcnow()
        return {"status": "ok"}
    else:
        return {"error": "missing client_id"}

if __name__ == '__main__':
    # Запускаем фоновую задачу проверки клиентов
    threading.Thread(target=check_clients, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
