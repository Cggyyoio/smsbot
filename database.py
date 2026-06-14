"""
🗄️ database.py
"""
import sqlite3
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._path = path
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    tg_id       INTEGER PRIMARY KEY,
                    username    TEXT,
                    first_name  TEXT,
                    balance     REAL DEFAULT 0.0,
                    is_banned   INTEGER DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS numbers (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone        TEXT UNIQUE NOT NULL,
                    country_code TEXT NOT NULL,
                    country_name TEXT NOT NULL,
                    country_flag TEXT NOT NULL,
                    session_path TEXT NOT NULL,
                    twofa        TEXT,
                    status       TEXT DEFAULT 'available',
                    sold_to      INTEGER,
                    sold_at      TIMESTAMP,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_tg_id    INTEGER NOT NULL,
                    txid          TEXT UNIQUE NOT NULL,
                    network       TEXT NOT NULL,
                    usdt_amount   REAL NOT NULL,
                    credit_amount REAL NOT NULL,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_tg_id   INTEGER NOT NULL,
                    number_id    INTEGER NOT NULL,
                    phone        TEXT NOT NULL,
                    country_code TEXT NOT NULL,
                    cost         REAL NOT NULL,
                    twofa        TEXT,
                    otp_code     TEXT,
                    otp_msg_id   INTEGER,
                    status       TEXT DEFAULT 'pending',
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS country_prices (
                    country_code TEXT PRIMARY KEY,
                    price        REAL DEFAULT 0.5
                );
                CREATE TABLE IF NOT EXISTS deposits (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_tg_id  INTEGER NOT NULL,
                    amount      REAL NOT NULL,
                    method      TEXT NOT NULL,
                    txid        TEXT,
                    status      TEXT DEFAULT 'pending',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS sms_numbers (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone      TEXT UNIQUE NOT NULL,
                    api_url    TEXT NOT NULL,
                    country    TEXT NOT NULL,
                    app_type   TEXT NOT NULL DEFAULT 'whatsapp',
                    status     TEXT DEFAULT 'available',
                    locked_by  INTEGER,
                    locked_at  TIMESTAMP,
                    fail_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sms_orders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_tg_id INTEGER NOT NULL,
                    sms_num_id INTEGER NOT NULL,
                    phone      TEXT NOT NULL,
                    country    TEXT NOT NULL,
                    cost       REAL NOT NULL,
                    otp_code   TEXT,
                    msg_id     INTEGER,
                    status     TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sms_country_prices (
                    country    TEXT NOT NULL,
                    app_type   TEXT NOT NULL DEFAULT 'whatsapp',
                    price      REAL NOT NULL DEFAULT 0.5,
                    PRIMARY KEY (country, app_type)
                );
                CREATE TABLE IF NOT EXISTS coupons (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    code       TEXT UNIQUE NOT NULL,
                    type       TEXT NOT NULL,
                    value      REAL NOT NULL,
                    max_uses   INTEGER DEFAULT 1,
                    used_count INTEGER DEFAULT 0,
                    expires_at TEXT,
                    is_active  INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS coupon_uses (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    coupon_id  INTEGER NOT NULL,
                    user_tg_id INTEGER NOT NULL,
                    used_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(coupon_id, user_tg_id)
                );
                CREATE TABLE IF NOT EXISTS referrals (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id  INTEGER NOT NULL,
                    referred_id  INTEGER NOT NULL UNIQUE,
                    earned       REAL DEFAULT 0.0,
                    pending      REAL DEFAULT 0.0,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # migrate: add is_banned if not exist
            cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
            if "is_banned" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
            if "lang" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ar'")
            if "onboarded" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN onboarded INTEGER DEFAULT 0")
            # migrate: add twofa to orders if not exist
            ocols = [r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()]
            if "twofa" not in ocols:
                conn.execute("ALTER TABLE orders ADD COLUMN twofa TEXT")
            # migrate: add fail_count to sms_numbers if not exist
            sms_cols = [r[1] for r in conn.execute("PRAGMA table_info(sms_numbers)").fetchall()]
            if "fail_count" not in sms_cols and sms_cols:
                conn.execute("ALTER TABLE sms_numbers ADD COLUMN fail_count INTEGER DEFAULT 0")
            if "app_type" not in sms_cols and sms_cols:
                conn.execute("ALTER TABLE sms_numbers ADD COLUMN app_type TEXT DEFAULT 'whatsapp'")
            # migrate: sms_country_prices - add app_type column if missing
            scp_cols = [r[1] for r in conn.execute("PRAGMA table_info(sms_country_prices)").fetchall()]
            if scp_cols and "app_type" not in scp_cols:
                conn.execute("ALTER TABLE sms_country_prices RENAME TO sms_country_prices_old")
                conn.execute("""
                    CREATE TABLE sms_country_prices (
                        country  TEXT NOT NULL,
                        app_type TEXT NOT NULL DEFAULT 'whatsapp',
                        price    REAL NOT NULL DEFAULT 0.5,
                        PRIMARY KEY (country, app_type)
                    )
                """)
                conn.execute("""
                    INSERT OR IGNORE INTO sms_country_prices (country, app_type, price)
                    SELECT country, 'whatsapp', price FROM sms_country_prices_old
                """)
                conn.execute("DROP TABLE sms_country_prices_old")
        logger.info("[DB] جاهزة ✅")

    # ══ Settings ══════════════════════════════════════════
    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return r[0] if r else default

    def set_setting(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))

    # ══ Users ═════════════════════════════════════════════
    def ensure_user(self, tg_id: int, username: str = None, first_name: str = None) -> bool:
        """Returns True if NEW user"""
        with self._conn() as conn:
            before = conn.execute("SELECT tg_id FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO users(tg_id,username,first_name) VALUES(?,?,?)",
                (tg_id, username, first_name)
            )
            return before is None

    def get_user(self, tg_id: int) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            return dict(r) if r else None

    def get_balance(self, tg_id: int) -> float:
        u = self.get_user(tg_id)
        return u["balance"] if u else 0.0

    def add_balance(self, tg_id: int, amount: float):
        with self._conn() as conn:
            conn.execute("UPDATE users SET balance=balance+? WHERE tg_id=?", (amount, tg_id))

    def deduct_balance(self, tg_id: int, amount: float) -> bool:
        with self._conn() as conn:
            r = conn.execute("SELECT balance FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            if not r or r[0] < amount:
                return False
            conn.execute("UPDATE users SET balance=balance-? WHERE tg_id=?", (amount, tg_id))
            return True

    def set_balance(self, tg_id: int, amount: float):
        with self._conn() as conn:
            conn.execute("UPDATE users SET balance=? WHERE tg_id=?", (amount, tg_id))

    def ban_user(self, tg_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE users SET is_banned=1 WHERE tg_id=?", (tg_id,))

    def unban_user(self, tg_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE users SET is_banned=0 WHERE tg_id=?", (tg_id,))

    def is_banned(self, tg_id: int) -> bool:
        u = self.get_user(tg_id)
        return bool(u and u.get("is_banned"))

    def get_all_users(self) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC"
            ).fetchall()]

    def search_user(self, query: str) -> Optional[dict]:
        """بحث بـ tg_id أو username"""
        with self._conn() as conn:
            # بـ ID
            if query.lstrip("-").isdigit():
                r = conn.execute("SELECT * FROM users WHERE tg_id=?", (int(query),)).fetchone()
                if r:
                    return dict(r)
            # بـ username
            uname = query.lstrip("@")
            r = conn.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
            return dict(r) if r else None

    # ══ Numbers ═══════════════════════════════════════════
    def add_number(self, phone: str, country_code: str, country_name: str,
                   country_flag: str, session_path: str, twofa: str = None):
        with self._conn() as conn:
            existing = conn.execute("SELECT id FROM numbers WHERE phone=?", (phone,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE numbers
                       SET country_code=?, country_name=?, country_flag=?,
                           session_path=?, twofa=?,
                           status='available', sold_to=NULL, sold_at=NULL
                       WHERE phone=?""",
                    (country_code, country_name, country_flag, session_path, twofa, phone)
                )
            else:
                conn.execute(
                    """INSERT INTO numbers
                       (phone,country_code,country_name,country_flag,session_path,twofa)
                       VALUES (?,?,?,?,?,?)""",
                    (phone, country_code, country_name, country_flag, session_path, twofa)
                )

    def get_available_countries(self) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT country_code, country_name, country_flag,
                       COUNT(*) as total,
                       SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) as available
                FROM numbers GROUP BY country_code HAVING available > 0
                ORDER BY country_name
            """).fetchall()
            return [dict(r) for r in rows]

    def get_numbers_by_country(self, country_code: str) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM numbers WHERE country_code=? ORDER BY created_at",
                (country_code,)
            ).fetchall()]

    def count_available(self, country_code: str) -> int:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT COUNT(*) FROM numbers WHERE country_code=? AND status='available'",
                (country_code,)
            ).fetchone()
            return r[0] if r else 0

    def get_number(self, number_id: int) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM numbers WHERE id=?", (number_id,)).fetchone()
            return dict(r) if r else None

    def get_available_number(self, country_code: str) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM numbers WHERE country_code=? AND status='available' LIMIT 1",
                (country_code,)
            ).fetchone()
            return dict(r) if r else None

    def mark_number_sold(self, number_id: int, user_tg_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE numbers SET status='sold', sold_to=?, sold_at=CURRENT_TIMESTAMP WHERE id=?",
                (user_tg_id, number_id)
            )

    def delete_number(self, number_id: int):
        """حذف من DB وحذف ملف الـ session"""
        num = self.get_number(number_id)
        if num:
            path = num.get("session_path", "")
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        with self._conn() as conn:
            conn.execute("DELETE FROM numbers WHERE id=?", (number_id,))

    def release_number(self, number_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE numbers SET status='available', sold_to=NULL, sold_at=NULL WHERE id=?",
                (number_id,)
            )

    def cancel_order(self, order_id: int, reason: str = ""):
        with self._conn() as conn:
            conn.execute(
                "UPDATE orders SET status='cancelled', otp_code=? WHERE id=?",
                (f"cancelled:{reason}" if reason else "cancelled", order_id)
            )

    def get_all_numbers_grouped(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM numbers ORDER BY country_code, status"
            ).fetchall()
        grouped = {}
        for r in rows:
            d = dict(r)
            grouped.setdefault(d["country_code"], []).append(d)
        return grouped

    # ══ Country Prices ════════════════════════════════════
    def get_price(self, country_code: str) -> float:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT price FROM country_prices WHERE country_code=?", (country_code,)
            ).fetchone()
            return r[0] if r else float(self.get_setting("default_price", "0.5"))

    def set_price(self, country_code: str, price: float):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO country_prices(country_code,price) VALUES(?,?)",
                (country_code, price)
            )

    def get_all_prices(self) -> dict:
        with self._conn() as conn:
            return {r["country_code"]: r["price"] for r in
                    conn.execute("SELECT * FROM country_prices").fetchall()}

    # ══ Orders ════════════════════════════════════════════
    def create_order(self, user_tg_id: int, number_id: int, phone: str,
                     country_code: str, cost: float, twofa: str = None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders(user_tg_id,number_id,phone,country_code,cost,twofa) VALUES(?,?,?,?,?,?)",
                (user_tg_id, number_id, phone, country_code, cost, twofa)
            )
            return cur.lastrowid

    def get_order(self, order_id: int) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            return dict(r) if r else None

    def get_orders_by_user(self, user_tg_id: int, limit: int = 10) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM orders WHERE user_tg_id=? ORDER BY id DESC LIMIT ?",
                (user_tg_id, limit)
            ).fetchall()]

    def set_order_otp(self, order_id: int, otp: str, msg_id: int = None):
        with self._conn() as conn:
            if msg_id is not None:
                conn.execute(
                    "UPDATE orders SET otp_code=?, otp_msg_id=?, status='completed' WHERE id=?",
                    (otp, msg_id, order_id)
                )
            else:
                conn.execute(
                    "UPDATE orders SET otp_code=?, status='completed' WHERE id=?",
                    (otp, order_id)
                )

    def set_order_msg_id(self, order_id: int, msg_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE orders SET otp_msg_id=? WHERE id=?", (msg_id, order_id))

    def get_recent_orders(self, limit: int = 20) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]

    # ══ Deposits ══════════════════════════════════════════
    def create_deposit(self, user_tg_id: int, amount: float,
                       method: str, txid: str = None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO deposits(user_tg_id,amount,method,txid) VALUES(?,?,?,?)",
                (user_tg_id, amount, method, txid)
            )
            return cur.lastrowid

    def approve_deposit(self, deposit_id: int):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM deposits WHERE id=?", (deposit_id,)).fetchone()
            if r and r["status"] == "pending":
                conn.execute("UPDATE deposits SET status='approved' WHERE id=?", (deposit_id,))
                conn.execute("UPDATE users SET balance=balance+? WHERE tg_id=?",
                             (r["amount"], r["user_tg_id"]))

    def reject_deposit(self, deposit_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE deposits SET status='rejected' WHERE id=?", (deposit_id,))

    def get_deposit(self, deposit_id: int) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM deposits WHERE id=?", (deposit_id,)).fetchone()
            return dict(r) if r else None

    def get_pending_deposits(self) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM deposits WHERE status='pending' ORDER BY id DESC"
            ).fetchall()]

    def process_crypto_deposit(self, user_tg_id: int, txid: str, network: str,
                                usdt_amount: float, credit_amount: float) -> bool:
        import sqlite3 as _sq
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO transactions(user_tg_id,txid,network,usdt_amount,credit_amount) VALUES(?,?,?,?,?)",
                    (user_tg_id, txid, network, usdt_amount, credit_amount)
                )
                conn.execute("UPDATE users SET balance=balance+? WHERE tg_id=?",
                             (credit_amount, user_tg_id))
            return True
        except _sq.IntegrityError:
            return False

    # ══ Stats ═════════════════════════════════════════════
    def get_stats(self) -> dict:
        with self._conn() as conn:
            users   = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            banned  = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
            nums    = conn.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
            avail   = conn.execute("SELECT COUNT(*) FROM numbers WHERE status='available'").fetchone()[0]
            sold    = conn.execute("SELECT COUNT(*) FROM numbers WHERE status='sold'").fetchone()[0]
            revenue = conn.execute("SELECT COALESCE(SUM(cost),0) FROM orders WHERE status='completed'").fetchone()[0]
            orders  = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            today   = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE status='completed' AND date(created_at)=date('now')"
            ).fetchone()[0]
            # SMS
            sms_orders    = conn.execute("SELECT COUNT(*) FROM sms_orders").fetchone()[0]
            sms_completed = conn.execute("SELECT COUNT(*) FROM sms_orders WHERE status='completed'").fetchone()[0]
            sms_revenue   = conn.execute("SELECT COALESCE(SUM(cost),0) FROM sms_orders WHERE status='completed'").fetchone()[0]
            sms_today     = conn.execute(
                "SELECT COUNT(*) FROM sms_orders WHERE status='completed' AND date(created_at)=date('now')"
            ).fetchone()[0]
            sms_avail     = conn.execute("SELECT COUNT(*) FROM sms_numbers WHERE status='available'").fetchone()[0]
        return {
            "users": users, "banned": banned, "numbers": nums,
            "available": avail, "sold": sold,
            "revenue": revenue, "orders": orders, "today": today,
            "sms_orders": sms_orders, "sms_completed": sms_completed,
            "sms_revenue": sms_revenue, "sms_today": sms_today, "sms_avail": sms_avail,
        }

    # ══ SMS Numbers ═══════════════════════════════════════
    def add_sms_numbers_bulk(self, numbers: list) -> int:
        """numbers = [{"phone": "+1234", "api_url": "...", "country": "US", "app_type": "whatsapp"}, ...]"""
        added = 0
        with self._conn() as conn:
            for n in numbers:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO sms_numbers(phone,api_url,country,app_type) VALUES(?,?,?,?)",
                        (n["phone"], n["api_url"], n["country"], n.get("app_type", "whatsapp"))
                    )
                    added += 1
                except Exception:
                    pass
        return added

    def get_sms_countries(self, app_type: str = None) -> list:
        with self._conn() as conn:
            where = "AND n.app_type=?" if app_type else ""
            args  = (app_type,) if app_type else ()
            rows  = conn.execute("""
                SELECT n.country, n.app_type,
                       COUNT(*) as total,
                       SUM(CASE WHEN n.status='available' THEN 1 ELSE 0 END) as available,
                       COALESCE(p.price,
                           (SELECT CAST(value AS REAL) FROM settings WHERE key='sms_price'),
                           0.5) as price
                FROM sms_numbers n
                LEFT JOIN sms_country_prices p ON p.country = n.country AND p.app_type = n.app_type
                WHERE 1=1 {}
                GROUP BY n.country, n.app_type HAVING available > 0
                ORDER BY n.country
            """.format(where), args).fetchall()
            return [dict(r) for r in rows]

    def lock_sms_number(self, country: str, user_tg_id: int, app_type: str = "whatsapp") -> dict | None:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM sms_numbers WHERE country=? AND app_type=? AND status='available' LIMIT 1",
                (country, app_type)
            ).fetchone()
            if not r:
                return None
            conn.execute(
                "UPDATE sms_numbers SET status='locked', locked_by=?, locked_at=CURRENT_TIMESTAMP WHERE id=?",
                (user_tg_id, r["id"])
            )
            return dict(r)

    def get_sms_total_available(self, app_type: str = None) -> int:
        with self._conn() as conn:
            if app_type:
                r = conn.execute(
                    "SELECT COUNT(*) FROM sms_numbers WHERE status='available' AND app_type=?", (app_type,)
                ).fetchone()
            else:
                r = conn.execute("SELECT COUNT(*) FROM sms_numbers WHERE status='available'").fetchone()
            return r[0] if r else 0

    def delete_sms_by_country(self, country: str, app_type: str = None):
        with self._conn() as conn:
            if app_type:
                conn.execute("DELETE FROM sms_numbers WHERE country=? AND app_type=?", (country, app_type))
            else:
                conn.execute("DELETE FROM sms_numbers WHERE country=?", (country,))

    def delete_sms_by_phone(self, phone: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM sms_numbers WHERE phone=?", (phone,))

    def delete_all_sms_numbers(self, app_type: str = None):
        with self._conn() as conn:
            if app_type:
                conn.execute("DELETE FROM sms_numbers WHERE app_type=?", (app_type,))
            else:
                conn.execute("DELETE FROM sms_numbers")

    def release_sms_number(self, sms_num_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE sms_numbers SET status='available', locked_by=NULL, locked_at=NULL WHERE id=?",
                (sms_num_id,)
            )

    def increment_sms_fail(self, sms_num_id: int) -> dict:
        """يزيد عداد الفشل ويرجع dict فيه fail_count و phone و api_url"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE sms_numbers SET fail_count = fail_count + 1 WHERE id=?",
                (sms_num_id,)
            )
            r = conn.execute(
                "SELECT fail_count, phone, api_url FROM sms_numbers WHERE id=?",
                (sms_num_id,)
            ).fetchone()
            return dict(r) if r else {"fail_count": 0, "phone": "", "api_url": ""}

    def delete_sms_number(self, sms_num_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM sms_numbers WHERE id=?", (sms_num_id,))

    # ══ SMS Country Prices ════════════════════════════════
    def get_sms_price(self, country: str, app_type: str = "whatsapp") -> float:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT price FROM sms_country_prices WHERE country=? AND app_type=?",
                (country, app_type)
            ).fetchone()
            if r:
                return r[0]
            r2 = conn.execute("SELECT value FROM settings WHERE key='sms_price'").fetchone()
            try:
                return float(r2[0]) if r2 else 0.5
            except Exception:
                return 0.5

    def set_sms_country_price(self, country: str, price: float, app_type: str = "whatsapp"):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sms_country_prices(country, app_type, price) VALUES(?,?,?)",
                (country, app_type, price)
            )

    def get_all_sms_country_prices(self) -> dict:
        with self._conn() as conn:
            return {"{}_{}".format(r["country"], r["app_type"]): r["price"] for r in
                    conn.execute("SELECT * FROM sms_country_prices").fetchall()}

    def count_sms_available(self, country: str) -> int:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT COUNT(*) FROM sms_numbers WHERE country=? AND status='available'",
                (country,)
            ).fetchone()
            return r[0] if r else 0

    # ══ SMS Orders ════════════════════════════════════════
    def create_sms_order(self, user_tg_id: int, sms_num_id: int,
                         phone: str, country: str, cost: float) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sms_orders(user_tg_id,sms_num_id,phone,country,cost) VALUES(?,?,?,?,?)",
                (user_tg_id, sms_num_id, phone, country, cost)
            )
            return cur.lastrowid

    def get_sms_order(self, order_id: int) -> dict | None:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM sms_orders WHERE id=?", (order_id,)).fetchone()
            return dict(r) if r else None

    def set_sms_order_msg_id(self, order_id: int, msg_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE sms_orders SET msg_id=? WHERE id=?", (msg_id, order_id))

    def complete_sms_order(self, order_id: int, otp: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE sms_orders SET otp_code=?, status='completed' WHERE id=?",
                (otp, order_id)
            )

    def cancel_sms_order(self, order_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE sms_orders SET status='cancelled' WHERE id=?",
                (order_id,)
            )

    def get_sms_orders_by_user(self, user_tg_id: int, limit: int = 10) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM sms_orders WHERE user_tg_id=? ORDER BY id DESC LIMIT ?",
                (user_tg_id, limit)
            ).fetchall()]

    # ══ Forced Subscription Channels ══════════════════════
    def get_force_channels(self) -> list:
        """يرجع قائمة القنوات الإجبارية [{"id": -100x, "name": "...", "link": "..."}]"""
        raw = self.get_setting("force_channels", "[]")
        try:
            return json.loads(raw)
        except Exception:
            return []

    def set_force_channels(self, channels: list):
        self.set_setting("force_channels", json.dumps(channels, ensure_ascii=False))

    # ══ User Language & Onboarding ════════════════════════
    def get_user_lang(self, tg_id: int) -> str:
        with self._conn() as conn:
            r = conn.execute("SELECT lang FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            return (r[0] or "ar") if r else "ar"

    def set_user_lang(self, tg_id: int, lang: str):
        with self._conn() as conn:
            conn.execute("UPDATE users SET lang=? WHERE tg_id=?", (lang, tg_id))

    def is_onboarded(self, tg_id: int) -> bool:
        with self._conn() as conn:
            r = conn.execute("SELECT onboarded FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            return bool(r and r[0])

    def set_onboarded(self, tg_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE users SET onboarded=1 WHERE tg_id=?", (tg_id,))

    # ══ Coupons ═══════════════════════════════════════════
    def create_coupon(self, code: str, type_: str, value: float,
                      max_uses: int = 1, expires_at: str = None) -> bool:
        """type_: 'fixed' أو 'percent'"""
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO coupons(code,type,value,max_uses,expires_at) VALUES(?,?,?,?,?)",
                    (code.upper(), type_, value, max_uses, expires_at)
                )
            return True
        except Exception:
            return False

    def get_coupon(self, code: str) -> dict | None:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM coupons WHERE code=? AND is_active=1", (code.upper(),)
            ).fetchone()
            return dict(r) if r else None

    def use_coupon(self, code: str, user_tg_id: int, balance_to_add: float) -> tuple:
        """يطبق الكوبون. يرجع (True, discount) أو (False, reason)"""
        import datetime as _dt
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM coupons WHERE code=? AND is_active=1", (code.upper(),)
            ).fetchone()
            if not r:
                return False, "الكوبون غير موجود أو غير فعال"
            c = dict(r)
            if c["expires_at"] and _dt.datetime.utcnow().strftime("%Y-%m-%d") > c["expires_at"]:
                return False, "انتهت صلاحية الكوبون"
            if c["used_count"] >= c["max_uses"]:
                return False, "تجاوز الكوبون الحد الأقصى للاستخدام"
            used = conn.execute(
                "SELECT id FROM coupon_uses WHERE coupon_id=? AND user_tg_id=?",
                (c["id"], user_tg_id)
            ).fetchone()
            if used:
                return False, "استخدمت هذا الكوبون من قبل"
            # احسب الخصم
            if c["type"] == "percent":
                discount = round(balance_to_add * c["value"] / 100, 4)
            else:
                discount = c["value"]
            # سجّل الاستخدام
            conn.execute(
                "INSERT INTO coupon_uses(coupon_id, user_tg_id) VALUES(?,?)",
                (c["id"], user_tg_id)
            )
            conn.execute(
                "UPDATE coupons SET used_count=used_count+1 WHERE id=?", (c["id"],)
            )
            return True, discount

    def get_all_coupons(self) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM coupons ORDER BY id DESC"
            ).fetchall()]

    def toggle_coupon(self, coupon_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE coupons SET is_active=1-is_active WHERE id=?", (coupon_id,)
            )

    def delete_coupon(self, coupon_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM coupon_uses WHERE coupon_id=?", (coupon_id,))
            conn.execute("DELETE FROM coupons WHERE id=?", (coupon_id,))

    # ══ Discounts (خصم تلقائي على عدد طلبات) ════════════
    def get_discounts(self) -> list:
        """يرجع قائمة الخصومات مرتبة تصاعدياً بعدد الطلبات"""
        raw = self.get_setting("auto_discounts", "[]")
        try:
            import json as _j
            return sorted(_j.loads(raw), key=lambda x: x["orders"])
        except Exception:
            return []

    def set_discounts(self, discounts: list):
        import json as _j
        self.set_setting("auto_discounts", _j.dumps(discounts))

    def get_user_discount(self, user_tg_id: int) -> float:
        """يرجع نسبة خصم المستخدم (0.0 - 100.0)"""
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE user_tg_id=? AND status='completed'",
                (user_tg_id,)
            ).fetchone()[0]
            sms_total = conn.execute(
                "SELECT COUNT(*) FROM sms_orders WHERE user_tg_id=? AND status='completed'",
                (user_tg_id,)
            ).fetchone()[0]
        count    = total + sms_total
        discount = 0.0
        for d in self.get_discounts():
            if count >= d["orders"]:
                discount = d["percent"]
        return discount

    # ══ Referrals ═════════════════════════════════════════
    def set_referrer(self, referred_id: int, referrer_id: int) -> bool:
        """يسجّل من أحضر المستخدم — مرة واحدة فقط"""
        if referred_id == referrer_id:
            return False
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO referrals(referrer_id, referred_id) VALUES(?,?)",
                    (referrer_id, referred_id)
                )
            return True
        except Exception:
            return False

    def get_referrer(self, referred_id: int) -> int | None:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT referrer_id FROM referrals WHERE referred_id=?", (referred_id,)
            ).fetchone()
            return r[0] if r else None

    def add_referral_earning(self, referrer_id: int, amount: float):
        """يضيف أرباح للمُحيل في الرصيد المعلّق"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE referrals SET pending=pending+?, earned=earned+? WHERE referrer_id=?",
                (amount, amount, referrer_id)
            )

    def get_referral_stats(self, user_tg_id: int) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pending),0), COALESCE(SUM(earned),0), COUNT(*) "
                "FROM referrals WHERE referrer_id=?", (user_tg_id,)
            ).fetchone()
            pending  = float(row[0]) if row else 0.0
            earned   = float(row[1]) if row else 0.0
            count    = int(row[2])   if row else 0
        return {"pending": pending, "earned": earned, "count": count}

    def withdraw_referral(self, user_tg_id: int) -> float:
        """يحوّل الرصيد المعلّق إلى رصيد قابل للاستخدام"""
        min_wd = float(self.get_setting("referral_min_withdraw", "1.0"))
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pending),0) FROM referrals WHERE referrer_id=?",
                (user_tg_id,)
            ).fetchone()
            pending = float(row[0]) if row else 0.0
            if pending < min_wd:
                return 0.0
            conn.execute(
                "UPDATE referrals SET pending=0 WHERE referrer_id=?", (user_tg_id,)
            )
            conn.execute(
                "UPDATE users SET balance=balance+? WHERE tg_id=?", (pending, user_tg_id)
            )
        return pending

    def get_total_users_balance(self) -> float:
        with self._conn() as conn:
            r = conn.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()
            return float(r[0]) if r else 0.0

    # ══ Custom Categories (أرقام بدون تقسيم على الدول) ═══
    def get_categories(self) -> list:
        """يرجع قائمة أسماء الفئات المخصصة الموجودة فعلياً"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT country_name FROM numbers WHERE country_code LIKE 'CAT_%' ORDER BY country_name"
            ).fetchall()
            return [r[0] for r in rows]
