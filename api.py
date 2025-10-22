from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask_cors import CORS
import time

load_dotenv()

app = Flask(__name__)
CORS(app)

# Конфигурация внешнего API
EXTERNAL_API_URL = "https://otapi-1688.p.rapidapi.com/BatchSearchItemsFrame"

# Получаем API-ключ из переменной окружения, с дефолтным значением
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "78c5ed6b0fmsh2cc04c24a1dae59p1c63ebjsn6d8c7c768794")

# Конфигурация для email
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

RATE_API_URL = "http://"+os.getenv("API_HOST")+"/api/rate"

@app.route('/api/search', methods=['GET'])
def search_items():
    try:
        # Получаем актуальные курсы валют
        try:
            rate_response = requests.get(RATE_API_URL, timeout=5)
            rate_response.raise_for_status()
            rate_data = rate_response.json()
            rate_cny = rate_data.get("CNY", 0)
            rate_usd = rate_data.get("USD", 0)
        except Exception as e:
            rate_cny, rate_usd = 0, 0
            print(f"[WARN] Can't get rates: {e}")

        # Параметры из запроса
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

        # Конвертируем MinPrice / MaxPrice из рублей в юани
        if rate_cny > 0:
            if params.get("MinPrice"):
                try:
                    rub = float(params["MinPrice"])
                    params["MinPrice"] = str(round(rub / rate_cny, 2))
                except ValueError:
                    params["MinPrice"] = None
            if params.get("MaxPrice"):
                try:
                    rub = float(params["MaxPrice"])
                    params["MaxPrice"] = str(round(rub / rate_cny, 2))
                except ValueError:
                    params["MaxPrice"] = None

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

            # Диапазоны цен
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
                            price_rub = None
                            price_usd = None
                            if rate_cny > 0:
                                price_rub = round(original_price * rate_cny, 2)
                            if rate_cny > 0 and rate_usd > 0:
                                price_usd = round(original_price * rate_cny / rate_usd, 2)
                            quantity_prices.append({
                                "min_quantity": str(min_q),
                                "original_price_cny": str(original_price),
                                "price_rub": str(price_rub) if price_rub is not None else "-",
                                "price_usd": str(price_usd) if price_usd is not None else "-"
                            })

            min_order_quantity = (
                min([float(qp["min_quantity"]) for qp in quantity_prices])
                if quantity_prices else None
            )

            # Основная цена
            if quantity_prices:
                min_q_entry = min(quantity_prices, key=lambda x: float(x["min_quantity"]))
                price_cny = float(min_q_entry.get("original_price_cny", 0))
            else:
                price_cny = item.get('Price', {}).get('OriginalPrice', 0)

            price_rub = round(price_cny * rate_cny, 2) if price_cny and rate_cny > 0 else None
            price_usd = round(price_cny * rate_cny / rate_usd, 2) if price_cny and rate_cny > 0 and rate_usd > 0 else None

            # === Подмена ссылки на "локальную" ===
            raw_image_url = (
                item.get("MainPictureUrl")
                or (item.get("Pictures", [{}])[0].get("Url") if item.get("Pictures") else None)
            )

            if raw_image_url and "alicdn.com" in raw_image_url:
                path = urlparse(raw_image_url).path
                image_url = f"/images{path}"  # фронт не знает, что это прокси
            else:
                image_url = "/assets/main/main-5.png"

            formatted_items.append({
                "id": str(item.get("Id", "-")),
                "title": str(item.get("Title", "-")),
                "original_title": str(item.get("OriginalTitle", "-")),
                "url": str(item.get("ExternalItemUrl") or item.get("TaobaoItemUrl") or "-"),
                "price_cny": str(price_cny) if price_cny else "-",
                "price_rub": str(price_rub) if price_rub else "-",
                "price_usd": str(price_usd) if price_usd else "-",
                "image": image_url,
                "min_order_quantity": str(min_order_quantity) if min_order_quantity else "-",
                "vendor": str(item.get("VendorDisplayName", "-")),
                "location": str(item.get("Location", {}).get("City", "-")),
                "dimensions": dimensions,
                "quantity_prices": quantity_prices if quantity_prices else []
            })

        return jsonify({
            "total": len(formatted_items),
            "items": formatted_items
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            'error': 'Failed to fetch data from external API',
            'message': str(e)
        }), 500

    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500



@app.route('/api/send-email', methods=['POST'])
def send_email_notification():
    try:
        time.sleep(5)
        data = request.get_json()
        
        # Проверяем обязательные поля
        required_fields = ['email','phone', 'fio', 'message']
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            return jsonify({
                'error': 'Missing required fields',
                'missing_fields': missing_fields
            }), 400
        
        sender_email = data['email']  # email отправителя (для связи)
        fio = data['fio']
        phone = data['phone']
        message_text = data['message']
        subject = data.get('subject', f'Новое сообщение от {fio}')
        
        # Формируем содержимое письма (будет отправлено НАМ)
        email_content = f"""
        Новое сообщение с формы обратной связи!
        
        От: {fio}
        Email для связи: {sender_email}
        Телефон для связи: {phone}
        Сообщение:
        {message_text}
        
        ---
        Это автоматическое уведомление от системы.
        """
        
        # Отправляем email НАМ (на EMAIL_USER)
        send_email(EMAIL_USER, subject, email_content)
        
        # Отправляем уведомление в Telegram
        telegram_sent = False
        telegram_error = None
        
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                send_telegram_message(f"📧 Новое сообщение с формы:\n\n👤 От: {fio}\n📧 Email: {sender_email}\n\n💬 Сообщение:\n{message_text}")
                telegram_sent = True
            except Exception as e:
                telegram_error = str(e)

        return jsonify({
            'success': True,
            'message': 'Email успешно отправлен',
            'telegram_sent': telegram_sent,
            'telegram_error': telegram_error,
        #    'recipient': EMAIL_USER,  # показываем куда отправили
            'sender': {
                'fio': fio,
                'email': sender_email,
                'phone': phone
            }
        })
        
    except Exception as e:
        return jsonify({
            'error': 'Failed to send email',
            'message': str(e)
        }), 500

def send_email(to_email, subject, message):
    """Отправка email через SMTP"""
    if not all([EMAIL_USER, EMAIL_PASSWORD]):
        raise Exception("Email credentials not configured")

    msg = MIMEMultipart()
    msg['From'] = f'{EMAIL_FROM_NAME} <{EMAIL_USER}>'
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(message, 'plain', 'utf-8'))

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USER, to_email, msg.as_string())
    except Exception as e:
        raise Exception(f"SMTP error: {str(e)}")

def send_telegram_message(message):
    """Отправка сообщения в Telegram"""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        raise Exception("Telegram credentials not configured")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    response = requests.post(url, json=payload)
    response.raise_for_status()
    
    return response.json()

if __name__ == '__main__':
    # Получаем IP-адрес и порт из переменных окружения, с дефолтными значениями
    host = os.getenv("API_HOST", "0.0.0.0")  # По умолчанию доступен на всех интерфейсах
    port = int(os.getenv("API_PORT", "5000"))  # По умолчанию порт 5000
    
    app.run(debug=True, host=host, port=port)
