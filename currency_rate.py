import requests
from flask import Flask, request, jsonify
import redis
import os
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

app = Flask(__name__)
REDIS_HOST=os.getenv("REDIS_HOST")
REDIS_PASSWORD=os.getenv("REDIS_PASSWORD")


def get_cbr_rate():
    try:
        url = "https://www.cbr-xml-daily.ru/daily_json.js"
        response = requests.get(url)
        data = response.json()
        cny_rate = data['Valute']['CNY']['Value']
        usd_rate = data['Valute']['USD']['Value']
        client = redis.Redis(host=REDIS_HOST,port=6379,password=REDIS_PASSWORD, db=0, decode_responses=True)
        client.set('cny_rate',cny_rate)
        client.set('usd_rate', usd_rate)
        print(f"[ОК] Курс CNY обновлен: {cny_rate}")
        print(f"[ОК] Курс USD обновлен: {usd_rate}")
        client.close()
        return cny_rate, usd_rate
    except Exception as e:
        print(f"[Ошибка] Не удалось обновить курсы: {e}")

@app.route('/api/rate', methods=['GET'])
def get_rate():
    client = redis.Redis(host=REDIS_HOST,port=6379,password=REDIS_PASSWORD, db=0, decode_responses=True)
    cny_rate = client.get('cny_rate')
    usd_rate = client.get('usd_rate')
    if cny_rate and usd_rate:
        return jsonify({'CNY':float(cny_rate),'USD':float(usd_rate)})
    else:
        return jsonify({'error': 'Курс ещё не установлен'}),404

scheduler = BackgroundScheduler()
scheduler.add_job(get_cbr_rate,'cron',hour=8,minute=0,timezone='Europe/Moscow')
scheduler.start()

if __name__ == '__main__':
    get_cbr_rate()
    host = os.getenv("API_HOST", "0.0.0.0")  # По умолчанию доступен на всех интерфейсах
    port = int(os.getenv("CURRENCY_PORT", "5000"))  # По умолчанию порт 5000
    app.run(debug=True, host=host, port=port)