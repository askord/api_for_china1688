from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Конфигурация внешнего API
EXTERNAL_API_URL = "https://otapi-1688.p.rapidapi.com/BatchSearchItemsFrame"

# Получаем API-ключ из переменной окружения, с дефолтным значением
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

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

if __name__ == '__main__':
    # Получаем IP-адрес и порт из переменных окружения, с дефолтными значениями
    host = os.getenv("API_HOST", "0.0.0.0")  # По умолчанию доступен на всех интерфейсах
    port = int(os.getenv("API_PORT", "5000"))  # По умолчанию порт 5000
    
    app.run(debug=True, host=host, port=port)