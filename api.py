from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask_cors import CORS
import time
import sqlite3
from datetime import datetime

DB_PATH = "search_logs.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            query TEXT,
            min_price REAL,
            max_price REAL,
            language TEXT
        )
    """)
    conn.commit()
    conn.close()

load_dotenv()

app = Flask(__name__)
CORS(app)

EXTERNAL_API_URL = "https://otapi-1688.p.rapidapi.com/BatchSearchItemsFrame"

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "78c5ed6b0fmsh2cc04c24a1dae59p1c63ebjsn6d8c7c768794")

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "API Notification")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": "otapi-1688.p.rapidapi.com"
}

RATE_API_URL = "https://" + os.getenv("SSL_DOMEN") + "/api/rate"


@app.route('/api/search', methods=['GET'])
def search_items():
    try:
        # Получаем курсы валют
        try:
            rate_response = requests.get(RATE_API_URL, timeout=5)
            rate_response.raise_for_status()
            rate_data = rate_response.json()
            rate_cny = rate_data.get("CNY", 0)
            rate_usd = rate_data.get("USD", 0)
            print(f"[DEBUG] Rates: CNY={rate_cny},USD={rate_usd}")
        except Exception as e:
            rate_cny, rate_usd = 0, 0
            print(f"[WARN] Can't get rates: {e}")

        # Параметры
        params = {
            "language": request.args.get('language', 'en'),
            "framePosition": request.args.get('framePosition', '0'),
            "frameSize": request.args.get('frameSize', '50'),
            "CategoryId": request.args.get('CategoryId'),
            "ItemTitle": request.args.get('ItemTitle'),
            "OrderBy": request.args.get('OrderBy', 'Popularity:Desc'),
            "MinPrice": request.args.get('MinPrice'),
            "MaxPrice": request.args.get('MaxPrice'),
            "MinVolume": request.args.get('MinVolume'),
            "ImageUrl": request.args.get('ImageUrl')
        }

        # Логирование
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO search_logs (timestamp, query, min_price, max_price, language)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                params.get("ItemTitle"),
                params.get("MinPrice"),
                params.get("MaxPrice"),
                params.get("language")
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[WARN] Failed to log search query: {e}")

        # Конвертируем рубли → юани
        if rate_cny > 0:
            for key in ["MinPrice", "MaxPrice"]:
                if params.get(key):
                    try:
                        rub = float(params[key])
                        params[key] = str(round(rub / rate_cny, 2))
                    except ValueError:
                        params[key] = None

        query_params = {k: v for k, v in params.items() if v is not None}

        # Запрос к внешнему API
        response = requests.get(EXTERNAL_API_URL, headers=API_HEADERS, params=query_params)
        response.raise_for_status()
        data = response.json()

        items = data.get('Result', {}).get('Items', {}).get('Items', {}).get('Content', [])
        formatted_items = []

        from urllib.parse import urlparse

        for item in items:
            physical = item.get("PhysicalParameters", {}) or {}

            # Габариты
            dimensions = {
                "weight": str(physical.get("Weight", "-")),
                "length": str(physical.get("Length", "-")),
                "width": str(physical.get("Width", "-")),
                "height": str(physical.get("Height", "-"))
            }

            # Диапазон цен
            quantity_prices = []
            quantity_ranges = item.get('QuantityRanges', [])
            if isinstance(quantity_ranges, list):
                for qr in quantity_ranges:
                    if not isinstance(qr, dict):
                        continue
                    min_q = qr.get('MinQuantity')
                    price_data = qr.get('Price', {})
                    if min_q is not None and isinstance(price_data, dict):
                        original_price = price_data.get('OriginalPrice')
                        if original_price is not None:
                            price_rub = round(original_price * rate_cny, 2) if rate_cny > 0 else None
                            price_usd = round(original_price * rate_cny / rate_usd, 2) if rate_cny > 0 and rate_usd > 0 else None
                            quantity_prices.append({
                                "min_quantity": str(min_q),
                                "original_price_cny": str(original_price),
                                "price_rub": str(price_rub) if price_rub else "-",
                                "price_usd": str(price_usd) if price_usd else "-"
                            })

            min_order_quantity = min([float(qp["min_quantity"]) for qp in quantity_prices]) if quantity_prices else 1

            # Основная цена
            if quantity_prices:
                min_q_entry = min(quantity_prices, key=lambda x: float(x["min_quantity"]))
                price_cny = float(min_q_entry.get("original_price_cny", 0))
            else:
                price_cny = item.get('Price', {}).get('OriginalPrice', 0)

            price_rub = round(price_cny * rate_cny, 2) if price_cny and rate_cny > 0 else None
            price_usd = round(price_cny * rate_cny / rate_usd, 2) if price_cny and rate_cny > 0 and rate_usd > 0 else None

            # === Локальная ссылка на изображение ===
            raw_image_url = (
                item.get("MainPictureUrl")
                or (item.get("Pictures", [{}])[0].get("Url") if item.get("Pictures") else None)
            )
            if raw_image_url and "alicdn.com" in raw_image_url:
                path = urlparse(raw_image_url).path
                image_url = f"/images{path}"
            else:
                image_url = "/assets/main/main-5.png"

            # --- Расчёт примерной цены с доставкой ---
            approx_price_rub = None
            try:
                weight = float(physical.get("Weight", 0) or 0)
                length = float(physical.get("Length", 0) or 0)
                width = float(physical.get("Width", 0) or 0)
                height = float(physical.get("Height", 0) or 0)
                volume = (length * width * height) / 1_000_000 if all([length, width, height]) else None
                min_q = float(min_order_quantity or 1)
                total_weight = weight * min_q

                if total_weight <= 500:
                    x = (price_cny * 1.13) * rate_cny
                    y = (total_weight * 4) * rate_usd
                    z1 = (x + y) * 1.1
                    approx_price_rub = round(z1)
                else:
                    if volume and volume > 0:
                        x1 = 33.2 / volume
                        x2 = (1560 / x1) * rate_usd
                        y = price_cny * rate_cny
                        y2 = (((y + x2) * 1.1 * 1.2) + 20000) * 1.1
                        approx_price_rub = round(y2)
                    else:
                        approx_price_rub = round(price_cny * rate_cny * 147.5)
            except Exception as e:
                print(f"[WARN] Approx calc failed: {e}")
                approx_price_rub = round(price_cny * rate_cny * 98.5)

            # Обновляем quantity_prices
            for qp in quantity_prices:
                try:
                    min_q2 = float(qp["min_quantity"])
                    q_weight = weight * min_q2
                    if q_weight <= 500:
                        x = (float(qp["original_price_cny"]) * 1.13) * rate_cny
                        y = (q_weight * 4) * rate_usd
                        z1 = (x + y) * 1.1
                        qp["approx_price_rub"] = str(round(z1))
                    else:
                        if volume and volume > 0:
                            x1 = 33.2 / volume
                            x2 = (1560 / x1) * rate_usd
                            y = float(qp["original_price_cny"]) * rate_cny
                            y2 = (((y + x2) * 1.1 * 1.2) + 20000) * 1.1
                            qp["approx_price_rub"] = str(round(y2))
                        else:
                            qp["approx_price_rub"] = str(round(float(qp["original_price_cny"]) * rate_cny * 147.5))
                except Exception as e:
                    qp["approx_price_rub"] = "-"
                    print(f"[WARN] Approx calc for quantity_prices failed: {e}")

            formatted_items.append({
                "id": str(item.get("Id", "-")),
                "title": str(item.get("Title", "-")),
                "original_title": str(item.get("OriginalTitle", "-")),
                "url": str(item.get("ExternalItemUrl") or item.get("TaobaoItemUrl") or "-"),
                "price_cny": str(price_cny) if price_cny else "-",
                "price_rub": str(price_rub) if price_rub else "-",
                "price_usd": str(price_usd) if price_usd else "-",
                "approx_price_rub": str(approx_price_rub) if approx_price_rub else "-",
                "image": image_url,
                "min_order_quantity": str(min_order_quantity) if min_order_quantity else "-",
                "vendor": str(item.get("VendorDisplayName", "-")),
                "location": str(item.get("Location", {}).get("City", "-")),
                "dimensions": dimensions,
                "quantity_prices": quantity_prices
            })

        return jsonify({"total": len(formatted_items), "items": formatted_items})

    except requests.exceptions.RequestException as e:
        return jsonify({'error': 'Failed to fetch data from external API', 'message': str(e)}), 500
    except Exception as e:
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM search_logs ORDER BY id DESC LIMIT 100")
    rows = cur.fetchall()
    conn.close()
    columns = ["id", "timestamp", "query", "min_price", "max_price", "language"]
    logs = [dict(zip(columns, row)) for row in rows]
    return jsonify({"logs": logs})


@app.route('/api/send-email', methods=['POST'])
def send_email_notification():
    try:
        time.sleep(5)
        data = request.get_json()
        required_fields = ['email', 'phone', 'fio', 'message']
        missing_fields = [f for f in required_fields if f not in data or not data[f]]
        if missing_fields:
            return jsonify({'error': 'Missing required fields', 'missing_fields': missing_fields}), 400

        sender_email = data['email']
        fio = data['fio']
        phone = data['phone']
        message_text = data['message']
        subject = data.get('subject', f'Новое сообщение от {fio}')

        email_content = f"""
        Новое сообщение с формы обратной связи!

        От: {fio}
        Email: {sender_email}
        Телефон: {phone}
        Сообщение:
        {message_text}
        """

        send_email(EMAIL_USER, subject, email_content)

        telegram_sent = False
        telegram_error = None
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                send_telegram_message(f"📧 Новое сообщение:\n👤 {fio}\n📧 {sender_email}\n💬 {message_text}")
                telegram_sent = True
            except Exception as e:
                telegram_error = str(e)

        return jsonify({'success': True, 'message': 'Email отправлен', 'telegram_sent': telegram_sent, 'telegram_error': telegram_error})
    except Exception as e:
        return jsonify({'error': 'Failed to send email', 'message': str(e)}), 500


def send_email(to_email, subject, message):
    if not all([EMAIL_USER, EMAIL_PASSWORD]):
        raise Exception("Email credentials not configured")
    msg = MIMEMultipart()
    msg['From'] = f'{EMAIL_FROM_NAME} <{EMAIL_USER}>'
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(message, 'plain', 'utf-8'))
    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USER, to_email, msg.as_string())


def send_telegram_message(message):
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        raise Exception("Telegram credentials not configured")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()


if __name__ == '__main__':
    init_db()
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "5000"))
    app.run(debug=True, host=host, port=port)
