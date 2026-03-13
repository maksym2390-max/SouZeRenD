#!/usr/bin/env python3
# Torn Market Scanner - Сканування ринку міста (Item Market)
# Використовує ID предметів з вашого JSON файлу
# Збирає ВСІ пропозиції через пагінацію та фільтрує нереальні ціни

import requests
import time
import json
import sqlite3
import os
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sys

# ============ КОНФІГУРАЦІЯ ============
API_KEY = "yGfG9P4pDhU97zAE"  # Ваш Torn API ключ
TELEGRAM_TOKEN = "8632913737:AAHjO0kGCP8dbvSvuZXQWEDgQ67q_7Na8Sk"
TELEGRAM_CHAT_ID = "ваш_chat_id_сюди"  # Отримаєте пізніше

DB_FILE = "torn_market.db"
REQUEST_DELAY = 0.25  # 250ms між запитами
BATCH_SIZE = 90  # 90 запитів на батч
BATCH_DELAY = 65  # 65 секунд між батчами
MIN_PROFIT = 5  # Мінімальний відсоток прибутку для угоди
BUDGET = 10000000  # Бюджет для розрахунку потенційного прибутку ($10M)

# ============ РОЗУМНІ ЛІМІТИ ЦІН ДЛЯ ПОПУЛЯРНИХ ПРЕДМЕТІВ ============
REASONABLE_PRICE_LIMITS = {
    206: 2000000,   # Xanax - не дорожче 2M
    61: 5000,       # Personal Computer
    258: 50000,     # Jaguar Plushie
    97: 1000,       # Bunch of Flowers
    186: 5000,      # Sheep Plushie
    283: 50000000,  # Donator Pack
}

# ============ БАЗОВА URL ДЛЯ API v2 ============
TORN_API_V2 = "https://api.torn.com/v2"

# ============ ЗАВАНТАЖЕННЯ ID З ВАШОГО JSON ============
def load_items_from_json() -> Tuple[List[int], Dict[int, str]]:
    """
    Завантажує ID та назви предметів з вашого JSON файлу
    """
    items_file = 'items.json'
    
    if not os.path.exists(items_file):
        print(f"❌ Файл {items_file} не знайдено!")
        print("Будь ласка, створіть файл items.json з вашими даними")
        return [], {}
    
    try:
        with open(items_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        all_items = []
        item_names = {}
        
        if "items" in data:
            items_data = data["items"]
            print(f"📋 Знайдено {len(items_data)} предметів у JSON")
            
            for item_id_str, item_info in items_data.items():
                try:
                    item_id = int(item_id_str)
                    all_items.append(item_id)
                    
                    if "name" in item_info:
                        item_names[item_id] = item_info["name"]
                    else:
                        item_names[item_id] = f"Item {item_id}"
                        
                except (ValueError, KeyError) as e:
                    print(f"⚠️ Помилка обробки ID {item_id_str}: {e}")
                    continue
        
        # Сортуємо ID для зручності
        all_items.sort()
        print(f"✅ Завантажено {len(all_items)} ID предметів")
        
        return all_items, item_names
        
    except json.JSONDecodeError as e:
        print(f"❌ Помилка парсингу JSON: {e}")
        return [], {}
    except Exception as e:
        print(f"❌ Помилка читання файлу: {e}")
        return [], {}

# ============ ФУНКЦІЇ ДЛЯ TELEGRAM ============
def send_telegram_message(message: str, parse_mode: str = "HTML"):
    """Відправляє повідомлення в Telegram"""
    if TELEGRAM_CHAT_ID == "ваш_chat_id_сюди":
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode
    }
    
    try:
        requests.post(url, data=data, timeout=10)
    except:
        pass

# ============ ФУНКЦІЯ СКАНУВАННЯ З ПАГІНАЦІЄЮ ============
def scan_item(item_id: int) -> Optional[Dict]:
    """
    Сканує один предмет через Torn API v2
    Збирає ВСІ пропозиції через пагінацію
    """
    all_listings = []
    offset = 0
    limit = 100
    page = 1
    
    print(f"    🔍 Початок сканування ID {item_id}...")
    
    while True:
        url = f"{TORN_API_V2}/market/{item_id}/itemmarket?key={API_KEY}&limit={limit}&offset={offset}"
        
        try:
            response = requests.get(url, timeout=30)
            
            if response.status_code != 200:
                print(f"    ⚠️ Помилка HTTP {response.status_code} на сторінці {page}")
                break
            
            data = response.json()
            
            if "error" in data:
                print(f"    ⚠️ Помилка API: {data['error']}")
                break
            
            # Отримуємо пропозиції з поточної сторінки
            itemmarket = data.get("itemmarket", {})
            listings = itemmarket.get("listings", [])
            
            if not listings:
                print(f"    ℹ️ Сторінка {page} не має пропозицій")
                break
            
            all_listings.extend(listings)
            print(f"    📄 Сторінка {page}: +{len(listings)} пропозицій (всього: {len(all_listings)})")
            
            # Перевіряємо, чи є наступна сторінка
            metadata = data.get("_metadata", {})
            if not metadata.get("next"):
                print(f"    ✅ Всі пропозиції зібрано. Загалом: {len(all_listings)}")
                break
                
            offset += limit
            page += 1
            time.sleep(0.1)  # Невелика затримка між сторінками
            
        except requests.exceptions.Timeout:
            print(f"    ⚠️ Таймаут на сторінці {page}")
            break
        except requests.exceptions.ConnectionError as e:
            print(f"    ⚠️ Помилка з'єднання: {e}")
            break
        except Exception as e:
            print(f"    ⚠️ Інша помилка: {e}")
            break
    
    if all_listings:
        # Повертаємо в форматі, який очікує save_item_price
        return {
            "itemmarket": {
                "listings": all_listings,
                "item": itemmarket.get("item", {}) if 'itemmarket' in locals() else {}
            }
        }
    return None

# ============ ФУНКЦІЯ ЗБЕРЕЖЕННЯ З ФІЛЬТРАЦІЄЮ ЦІН ============
def save_item_price(item_id: int, item_name: str, market_data: Dict) -> bool:
    """
    Зберігає ціни з ринку в базу даних
    Відсіває нереальні ціни (викиди)
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        itemmarket = market_data.get("itemmarket", {})
        listings = itemmarket.get("listings", [])
        
        if not isinstance(listings, list):
            print(f"    ⚠️ listings не є списком для {item_id}")
            listings = []
        
        if listings:
            # Збираємо всі ціни з урахуванням кількості
            all_prices = []
            total_quantity = 0
            
            for listing in listings:
                if not isinstance(listing, dict):
                    continue
                    
                price = listing.get("price", 0)
                quantity = listing.get("amount", 1)
                
                if price and price > 0:
                    # Додаємо ціну для кожної одиниці товару
                    all_prices.extend([price] * quantity)
                    total_quantity += quantity
            
            if all_prices:
                # Сортуємо для легшого аналізу
                all_prices.sort()
                
                # Обчислюємо базову статистику
                n = len(all_prices)
                q1 = all_prices[n // 4]
                q3 = all_prices[3 * n // 4]
                iqr = q3 - q1
                
                # Стандартний IQR метод
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr
                
                # Додатковий метод за медіаною
                median = all_prices[n // 2]
                median_upper = median * 3  # Не більше ніж в 3 рази дорожче за медіану
                
                # Використовуємо найсуворіший upper bound
                final_upper = min(upper_bound, median_upper)
                
                # Якщо є індивідуальний ліміт для предмета
                if item_id in REASONABLE_PRICE_LIMITS:
                    final_upper = min(final_upper, REASONABLE_PRICE_LIMITS[item_id])
                
                # Фільтруємо ціни
                filtered_prices = [p for p in all_prices if p <= final_upper]
                
                if filtered_prices:
                    min_price = min(filtered_prices)
                    max_price = max(filtered_prices)
                    avg_price = sum(filtered_prices) / len(filtered_prices)
                    
                    print(f"    📊 Статистика:")
                    print(f"       Всього цін: {len(all_prices)}")
                    print(f"       Медіана: ${median:,}")
                    print(f"       Q1: ${q1:,}, Q3: ${q3:,}")
                    print(f"       Upper bound: ${final_upper:,}")
                    print(f"       Відфільтровано {len(all_prices) - len(filtered_prices)} викидів")
                    print(f"    ✅ Після фільтрації:")
                    print(f"       min=${min_price:,}, avg=${avg_price:,.0f}, max=${max_price:,}")
                else:
                    # Якщо все відфільтрувалось, використовуємо оригінальні дані
                    min_price = min(all_prices)
                    max_price = max(all_prices)
                    avg_price = sum(all_prices) / len(all_prices)
                    print(f"    ⚠️ Всі ціни були відфільтровані, використовую оригінальні")
                
                listings_count = len(listings)
                print(f"    📊 Всього пропозицій: {listings_count}, загальна кількість: {total_quantity}")
            else:
                min_price = max_price = avg_price = None
                listings_count = total_quantity = 0
                print(f"    ⚠️ Немає цін для {item_id}")
        else:
            min_price = max_price = avg_price = None
            listings_count = total_quantity = 0
            print(f"    ⚠️ Немає пропозицій для {item_id}")
        
        # Вставляємо запис
        cursor.execute("""
            INSERT OR REPLACE INTO price_history 
            (item_id, item_name, min_price, avg_price, max_price, listings_count, total_quantity, date, scan_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item_id, item_name, min_price, avg_price, max_price, listings_count, total_quantity, today, now))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"    ❌ Помилка збереження предмета {item_id}: {e}")
        traceback.print_exc()
        return False

# ============ АНАЛІЗ ТРЕНДІВ ============
def analyze_trends(item_id: int, days: int = 30) -> Dict:
    """
    Аналізує тренди цін для предмета
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date, min_price, avg_price
        FROM price_history
        WHERE item_id = ? AND min_price IS NOT NULL
        ORDER BY date DESC
        LIMIT ?
    """, (item_id, days))
    
    history = cursor.fetchall()
    conn.close()
    
    if len(history) < 3:
        return {}
    
    prices = [h[1] for h in history if h[1] is not None]
    
    if not prices:
        return {}
    
    avg_price = sum(prices) / len(prices)
    
    # Волатильність
    if len(prices) > 1:
        variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
        volatility = (variance ** 0.5) / avg_price * 100
    else:
        volatility = 0
    
    # Тренд (остання ціна vs середня)
    last_price = prices[0]
    trend_percent = ((last_price - avg_price) / avg_price) * 100
    
    return {
        "avg_7day": sum(prices[:7]) / min(7, len(prices)) if len(prices) >= 1 else None,
        "avg_30day": avg_price,
        "current_price": last_price,
        "volatility": round(volatility, 2),
        "trend": round(trend_percent, 2),
        "data_points": len(prices)
    }

# ============ ПОШУК ВИГІДНИХ УГОД ============
def find_best_deals() -> List[Dict]:
    """
    Шукає найвигідніші угоди на основі історичних даних
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Отримуємо сьогоднішні ціни
    cursor.execute("""
        SELECT item_id, item_name, min_price
        FROM price_history
        WHERE date = ? AND min_price IS NOT NULL
    """, (today,))
    
    today_prices = cursor.fetchall()
    
    deals = []
    
    for item_id, item_name, current_price in today_prices:
        # Аналізуємо тренди
        trends = analyze_trends(item_id)
        
        if not trends or not trends.get("avg_7day"):
            continue
        
        avg_7day = trends["avg_7day"]
        
        # Розраховуємо потенційний прибуток (з урахуванням 10% комісії)
        profit_percent = ((avg_7day - current_price) / current_price * 100) - 10
        
        if profit_percent > MIN_PROFIT:
            # Скільки можна купити на бюджет
            max_qty = BUDGET // current_price
            potential_profit = max_qty * (avg_7day - current_price) * 0.9
            
            deals.append({
                "item_id": item_id,
                "item_name": item_name,
                "current_price": current_price,
                "avg_7day": round(avg_7day),
                "avg_30day": round(trends["avg_30day"]) if trends.get("avg_30day") else None,
                "profit_percent": round(profit_percent, 2),
                "volatility": trends["volatility"],
                "trend": trends["trend"],
                "max_qty": max_qty,
                "potential_profit": round(potential_profit),
                "data_points": trends["data_points"]
            })
    
    conn.close()
    
    # Сортуємо за прибутком
    deals.sort(key=lambda x: x["profit_percent"], reverse=True)
    
    return deals

# ============ ЗБЕРЕЖЕННЯ УГОД ============
def save_deals(deals: List[Dict]):
    """Зберігає угоди в базу"""
    if not deals:
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for deal in deals:
        cursor.execute("""
            INSERT INTO deals (item_id, item_name, current_price, avg_7day, profit_percent, potential_profit, date_found)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            deal["item_id"],
            deal["item_name"],
            deal["current_price"],
            deal["avg_7day"],
            deal["profit_percent"],
            deal["potential_profit"],
            today
        ))
    
    conn.commit()
    conn.close()
    print(f"✅ Збережено {len(deals)} угод")

# ============ ОНОВЛЕНА ФУНКЦІЯ ФОРМАТУВАННЯ ЗВІТУ ============
def format_deals_report(deals: List[Dict]) -> str:
    """Форматує звіт про вигідні угоди"""
    if not deals:
        return "🤷 Сьогодні немає вигідних угод"
    
    report = "🔥 <b>НАЙКРАЩІ УГОДИ СЬОГОДНІ</b>\n\n"
    
    for i, deal in enumerate(deals[:10], 1):
        profit_per_item = (deal['avg_7day'] - deal['current_price']) * 0.9
        
        report += f"{i}. <b>{deal['item_name']}</b> (ID: {deal['item_id']})\n"
        report += f"   💰 Ціна покупки: <b>${deal['current_price']:,}</b>\n"
        report += f"   📈 Середня ціна продажу: ${deal['avg_7day']:,}\n"
        report += f"   📊 Прибуток з одиниці: <b>${profit_per_item:,.0f}</b>\n"
        report += f"   💰 Прибуток: <b>{deal['profit_percent']}%</b>\n"
        report += f"   📦 Можна купити: {deal['max_qty']} шт.\n"
        report += f"   💎 Загальний прибуток: <b>${deal['potential_profit']:,}</b>\n\n"
    
    return report

# ============ ФОРМАТУВАННЯ СТАТИСТИКИ ============
def format_scan_report(successful: int, failed: int, deals: int, duration: int) -> str:
    """Форматує звіт про сканування"""
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    seconds = duration % 60
    
    report = f"📊 <b>ЗВІТ ПРО СКАНУВАННЯ</b>\n"
    report += f"📅 Час: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    report += f"✅ Проскановано: {successful} предметів\n"
    report += f"⚠️ Помилок: {failed}\n"
    report += f"🔥 Знайдено угод: {deals}\n"
    report += f"⏱️ Час виконання: "
    
    if hours > 0:
        report += f"{hours}год {minutes}хв {seconds}с"
    elif minutes > 0:
        report += f"{minutes}хв {seconds}с"
    else:
        report += f"{seconds}с"
    
    return report

# ============ ЕКСПОРТ В CSV ============
def export_to_csv():
    """Експортує дані в CSV файл"""
    import csv
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Експорт історії цін
    cursor.execute("""
        SELECT item_id, item_name, min_price, avg_price, max_price, listings_count, total_quantity, date
        FROM price_history
        WHERE min_price IS NOT NULL
        ORDER BY date DESC, item_id
    """)
    
    prices = cursor.fetchall()
    
    prices_file = f'prices_{datetime.now().strftime("%Y%m%d")}.csv'
    with open(prices_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['item_id', 'item_name', 'min_price', 'avg_price', 'max_price', 'listings', 'quantity', 'date'])
        writer.writerows(prices)
    
    # Експорт угод
    cursor.execute("""
        SELECT item_id, item_name, current_price, avg_7day, profit_percent, potential_profit, date_found
        FROM deals
        ORDER BY profit_percent DESC
        LIMIT 50
    """)
    
    deals_data = cursor.fetchall()
    
    deals_file = f'deals_{datetime.now().strftime("%Y%m%d")}.csv'
    with open(deals_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['item_id', 'item_name', 'current_price', 'avg_7day', 'profit_percent', 'potential_profit', 'date_found'])
        writer.writerows(deals_data)
    
    conn.close()
    
    print(f"✅ Експортовано {len(prices)} цін та {len(deals_data)} угод")
    return prices_file, deals_file

# ============ ІНІЦІАЛІЗАЦІЯ БАЗИ ДАНИХ ============
def init_database():
    """Створює таблиці в SQLite базі даних"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Видаляємо старі таблиці
    cursor.execute("DROP TABLE IF EXISTS price_history")
    cursor.execute("DROP TABLE IF EXISTS scan_log")
    cursor.execute("DROP TABLE IF EXISTS deals")
    
    # Таблиця для історії цін
    cursor.execute("""
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_name TEXT,
            min_price INTEGER,
            avg_price REAL,
            max_price INTEGER,
            listings_count INTEGER DEFAULT 0,
            total_quantity INTEGER DEFAULT 0,
            date TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            UNIQUE(item_id, date)
        )
    """)
    
    # Таблиця для логування сканувань
    cursor.execute("""
        CREATE TABLE scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT NOT NULL,
            items_scanned INTEGER NOT NULL,
            items_failed INTEGER NOT NULL,
            deals_found INTEGER NOT NULL,
            duration_seconds INTEGER NOT NULL
        )
    """)
    
    # Таблиця для вигідних угод
    cursor.execute("""
        CREATE TABLE deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            item_name TEXT,
            current_price INTEGER,
            avg_7day REAL,
            profit_percent REAL,
            potential_profit INTEGER,
            date_found TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    print("✅ Базу даних ініціалізовано")

# ============ СКАНУВАННЯ БАТЧА ============
def scan_batch(items: List[int], item_names: Dict[int, str]) -> Tuple[int, int]:
    """Сканує батч предметів"""
    successful = 0
    failed = 0
    
    for i, item_id in enumerate(items):
        item_name = item_names.get(item_id, f"Item {item_id}")
        print(f"  📦 Сканування {i+1}/{len(items)} (ID: {item_id} - {item_name})")
        
        data = scan_item(item_id)
        if data:
            if save_item_price(item_id, item_name, data):
                successful += 1
            else:
                failed += 1
        else:
            failed += 1
        
        if i < len(items) - 1:
            time.sleep(REQUEST_DELAY)
    
    return successful, failed

# ============ ГОЛОВНА ФУНКЦІЯ ============
def main_scan():
    """Головна функція сканування"""
    start_time = time.time()
    
    print(f"\n{'='*60}")
    print(f"🚀 Початок сканування ринку Torn (Item Market)")
    print(f"📅 Час: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # Завантажуємо ID з вашого JSON файлу
    print("📋 Завантаження ID предметів з вашого JSON...")
    all_items, item_names = load_items_from_json()
    
    if not all_items:
        print("❌ Не вдалося завантажити предмети з JSON")
        return
    
    print(f"✅ Знайдено {len(all_items)} предметів\n")
    print(f"📝 Наприклад: ID 206 - {item_names.get(206, 'Unknown')} (Xanax)")
    print(f"📝 Наприклад: ID 258 - {item_names.get(258, 'Unknown')} (Jaguar Plushie)\n")
    
    total_successful = 0
    total_failed = 0
    batch_number = 1
    
    # Скануємо батчами
    for i in range(0, len(all_items), BATCH_SIZE):
        batch = all_items[i:i + BATCH_SIZE]
        
        print(f"\n📊 Батч #{batch_number} ({len(batch)} предметів)")
        print(f"⏱️ Початок: {datetime.now().strftime('%H:%M:%S')}")
        
        successful, failed = scan_batch(batch, item_names)
        total_successful += successful
        total_failed += failed
        
        print(f"✅ Батч завершено: +{successful} успішно, {failed} помилок")
        
        if i + BATCH_SIZE < len(all_items):
            wait_until = time.time() + BATCH_DELAY
            print(f"⏳ Чекаємо {BATCH_DELAY}с до {datetime.fromtimestamp(wait_until).strftime('%H:%M:%S')}")
            time.sleep(BATCH_DELAY)
        
        batch_number += 1
    
    # Аналізуємо угоди
    print("\n🔍 Пошук вигідних угод...")
    deals = find_best_deals()
    save_deals(deals)
    
    duration = int(time.time() - start_time)
    
    # Логуємо результати
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scan_log (scan_date, items_scanned, items_failed, deals_found, duration_seconds)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), total_successful, total_failed, len(deals), duration))
    conn.commit()
    conn.close()
    
    # Виводимо результати
    print(f"\n{'='*60}")
    print(f"✅ СКАНУВАННЯ ЗАВЕРШЕНО")
    print(f"📊 Всього проскановано: {total_successful} предметів")
    print(f"⚠️ Помилок: {total_failed}")
    print(f"🔥 Знайдено угод: {len(deals)}")
    print(f"⏱️ Час виконання: {duration//60}хв {duration%60}с")
    print(f"{'='*60}\n")
    
    # Показуємо топ-угоди
    if deals:
        print("🏆 ТОП-5 НАЙКРАЩИХ УГОД:")
        for i, deal in enumerate(deals[:5], 1):
            profit_per_item = (deal['avg_7day'] - deal['current_price']) * 0.9
            print(f"{i}. {deal['item_name']} (ID: {deal['item_id']}):")
            print(f"   💰 Купуй за < ${deal['current_price']:,}")
            print(f"   📈 Продавай за ~${deal['avg_7day']:,}")
            print(f"   💎 Прибуток: {deal['profit_percent']}% (${profit_per_item:,.0f}/шт), всього ${deal['potential_profit']:,}")
    else:
        print("ℹ️ Потрібно більше даних для аналізу. Запустіть сканування ще кілька днів.")
    
    # Експортуємо в CSV
    export_to_csv()

# ============ ТОЧКА ВХОДУ ============
if __name__ == "__main__":
    init_database()
    main_scan()