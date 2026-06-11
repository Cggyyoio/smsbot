"""
🎁 features.py
نظام الكوبونات، الخصومات، الإحالة، التقرير اليومي، النسخ الاحتياطي
"""
import asyncio
import logging
import os
import shutil
import datetime

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  Daily Report — يُرسَل تلقائياً
# ══════════════════════════════════════════════════════════

async def send_daily_report(bot, db):
    try:
        admin_ch = db.get_setting("admin_report_channel", "").strip()
        if not admin_ch or admin_ch == "0":
            return
        stats = db.get_stats()
        with db._conn() as conn:
            rev_today = conn.execute(
                "SELECT COALESCE(SUM(cost),0) FROM orders WHERE status='completed' AND date(created_at)=date('now')"
            ).fetchone()[0]
            sms_rev_today = conn.execute(
                "SELECT COALESCE(SUM(cost),0) FROM sms_orders WHERE status='completed' AND date(created_at)=date('now')"
            ).fetchone()[0]
            orders_today = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE date(created_at)=date('now')"
            ).fetchone()[0]
            sms_today = conn.execute(
                "SELECT COUNT(*) FROM sms_orders WHERE date(created_at)=date('now')"
            ).fetchone()[0]
            new_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE date(created_at)=date('now')"
            ).fetchone()[0]
            total_bal = conn.execute(
                "SELECT COALESCE(SUM(balance),0) FROM users"
            ).fetchone()[0]

        now = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        text = (
            "📊 <b>التقرير اليومي — {date}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💰 <b>إيرادات اليوم</b>\n"
            "  📱 أرقام TG: <b>${tg_rev:.2f}</b>\n"
            "  💬 أرقام SMS: <b>${sms_rev:.2f}</b>\n"
            "  📦 الإجمالي: <b>${total_rev:.2f}</b>\n\n"
            "📦 <b>الطلبات</b>\n"
            "  📱 TG: <b>{tg_ord}</b>  |  💬 SMS: <b>{sms_ord}</b>\n\n"
            "👥 <b>المستخدمون</b>\n"
            "  🆕 جديد اليوم: <b>{new}</b>\n"
            "  📊 الإجمالي: <b>{total}</b>\n\n"
            "💳 <b>رصيد المستخدمين</b>: <b>${total_bal:.2f}</b>\n"
            "📱 TG متاح: <b>{tg_avail}</b>  |  💬 SMS متاح: <b>{sms_avail}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        ).format(
            date=now,
            tg_rev=float(rev_today), sms_rev=float(sms_rev_today),
            total_rev=float(rev_today) + float(sms_rev_today),
            tg_ord=orders_today, sms_ord=sms_today,
            new=new_users, total=stats["users"],
            total_bal=float(total_bal),
            tg_avail=stats["available"], sms_avail=stats["sms_avail"]
        )
        await bot.send_message(chat_id=int(admin_ch), text=text, parse_mode="HTML")
    except Exception as e:
        logger.warning("daily_report error: %s", e)


async def daily_report_loop(bot, db):
    """يبعت تقرير يومي الساعة 00:00 UTC"""
    while True:
        now = datetime.datetime.utcnow()
        nxt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((nxt - now).total_seconds())
        await send_daily_report(bot, db)


# ══════════════════════════════════════════════════════════
#  Backup — كل 6 ساعات
# ══════════════════════════════════════════════════════════

BACKUP_DIR = "data/backups"

def make_backup(db_path: str) -> str:
    """ينسخ قاعدة البيانات ويرجع مسار النسخة"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now  = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, "bot_{}.db".format(now))
    shutil.copy2(db_path, dest)
    # احتفظ بآخر 28 نسخة فقط (7 أيام × 4 نسخ يومياً)
    files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
        reverse=True
    )
    for old in files[28:]:
        try: os.remove(os.path.join(BACKUP_DIR, old))
        except: pass
    return dest


async def backup_loop(bot, db):
    """يعمل نسخة احتياطية كل 6 ساعات"""
    while True:
        await asyncio.sleep(6 * 3600)
        try:
            path = make_backup(db._path)
            admin_ch = db.get_setting("admin_report_channel", "").strip()
            if admin_ch and admin_ch != "0":
                fname = os.path.basename(path)
                await bot.send_document(
                    chat_id=int(admin_ch),
                    document=open(path, "rb"),
                    filename=fname,
                    caption="💾 <b>نسخة احتياطية تلقائية</b>\n📅 {}".format(
                        datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                    ),
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.warning("backup_loop error: %s", e)
