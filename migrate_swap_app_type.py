"""
migrate_swap_app_type.py
شغّله مرة واحدة بس:
    python3 migrate_swap_app_type.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot.db")

print(f"[*] فتح DB: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)

try:
    # sms_numbers
    r = conn.execute("UPDATE sms_numbers SET app_type = CASE WHEN app_type='whatsapp' THEN 'telegram' ELSE 'whatsapp' END")
    print(f"[✓] sms_numbers: {r.rowcount} صف اتعدّل")

    # sms_country_prices
    r = conn.execute("UPDATE sms_country_prices SET app_type = CASE WHEN app_type='whatsapp' THEN 'telegram' ELSE 'whatsapp' END")
    print(f"[✓] sms_country_prices: {r.rowcount} صف اتعدّل")

    # sms_orders
    r = conn.execute("UPDATE sms_orders SET app_type = CASE WHEN app_type='whatsapp' THEN 'telegram' ELSE 'whatsapp' END")
    print(f"[✓] sms_orders: {r.rowcount} صف اتعدّل")

    conn.commit()
    print("[✓] تم الحفظ بنجاح")
except Exception as e:
    conn.rollback()
    print(f"[✗] خطأ: {e}")
finally:
    conn.close()
