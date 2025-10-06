from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = Flask(__name__)

# Конфигурация внешнего API
EXTERNAL_API_URL = "https://otapi-1688.p.rapidapi.com/BatchSearchItemsFrame"

# Получаем API-ключ из переменной окружения, с дефолтным значением
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

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

@app.route('/api/search', methods=['GET'])
def search_items():
    try:
        # Получаем параметры из запроса с пояснениями
        params = {
            "language": request.args.get('language', 'en'),          # Язык ответа (например, 'en' для английского, 'cn' для китайского)
            "framePosition": request.args.get('framePosition', '0'), # Начальная позиция в списке результатов (для пагинации, по умолчанию 0)
            "frameSize": request.args.get('frameSize', '50'),       # Количество возвращаемых элементов (максимум на странице, по умолчанию 50)
            "CategoryId": request.args.get('CategoryId'),           # ID категории для фильтрации товаров (например, 'abb-201034004')
            "ItemTitle": request.args.get('ItemTitle'),             # Поиск по названию товара (строка для фильтрации)
            "OrderBy": request.args.get('OrderBy', 'Popularity:Desc'), # Сортировка (например, 'Popularity:Desc' - по убыванию популярности, 'Price:Asc' - по возрастанию цены)
            "MinPrice": request.args.get('MinPrice'),               # Минимальная цена в юанях (CNY) для фильтрации
            "MaxPrice": request.args.get('MaxPrice'),               # Максимальная цена в юанях (CNY) для фильтрации
            "MinVolume": request.args.get('MinVolume'),             # Минимальный объем (количество доступных единиц) для фильтрации
            "ImageUrl": request.args.get('ImageUrl')                # URL изображения для поиска похожих товаров (если поддерживается API)
        }

        # Удаляем None значения из параметров, чтобы не отправлять пустые фильтры
        query_params = {k: v for k, v in params.items() if v is not None}

        # Выполняем запрос к внешнему API
        response = requests.get(
            EXTERNAL_API_URL,
            headers=API_HEADERS,
            params=query_params
        )

        # Проверяем успешность запроса
        response.raise_for_status()

        # Возвращаем JSON ответ от RapidAPI
        return jsonify(response.json())

    except requests.exceptions.RequestException as e:
        # Обработка ошибок внешнего API (например, проблемы с сетью или неверный ключ)
        return jsonify({
            'error': 'Failed to fetch data from external API',
            'message': str(e)
        }), 500

    except Exception as e:
        # Обработка внутренних ошибок сервера
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500


@app.route('/api/send-email', methods=['POST'])
def send_email_notification():
    try:
        data = request.get_json()
        
        # Проверяем обязательные поля
        required_fields = ['email', 'fio', 'message']
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            return jsonify({
                'error': 'Missing required fields',
                'missing_fields': missing_fields
            }), 400
        
        sender_email = data['email']  # email отправителя (для связи)
        fio = data['fio']
        message_text = data['message']
        subject = data.get('subject', f'Новое сообщение от {fio}')
        
        # Формируем содержимое письма (будет отправлено НАМ)
        email_content = f"""
        Новое сообщение с формы обратной связи!
        
        От: {fio}
        Email для связи: {sender_email}
        
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
            'recipient': EMAIL_USER,  # показываем куда отправили
            'sender': {
                'fio': fio,
                'email': sender_email
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