"""
⭐ نجوم تيليغرام + 💛 Binance Pay
"""

import logging
import aiohttp
import hmac
import hashlib
import time

from telegram import Update, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from database import Database
from utils.safe_send import safe_answer, safe_edit, safe_send
from utils.keyboards import back_to_main_kb, cancel_kb

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  مساعدات
# ══════════════════════════════════════════════════════════

def _admin_id(db: Database) -> int:
    try: return int(db.get_setting("admin_id", "0"))
    except: return 0

def _stars_rate(db: Database) -> float:
    try: return float(db.get_setting("stars_rate", "85"))
    except: return 85.0

def _stars_min_usd(db: Database) -> float:
    try: return float(db.get_setting("stars_min_usd", "1"))
    except: return 1.0

def _bnb_min_usd(db: Database) -> float:
    try: return float(db.get_setting("binance_min_usd", "0.01"))
    except: return 0.01

def _bnb_pay_id(db: Database) -> str:
    return db.get_setting("binance_pay_id", "").strip()

def _bnb_api_key(db: Database) -> str:
    return db.get_setting("binance_api_key", "").strip()

def _bnb_api_secret(db: Database) -> str:
    return db.get_setting("binance_api_secret", "").strip()


def _stars_amounts_kb(min_usd: float, rate: float) -> InlineKeyboardMarkup:
    all_amounts = [1, 2, 5, 10, 20, 50]
    amounts = [a for a in all_amounts if a >= min_usd]
    rows = []
    for i in range(0, len(amounts), 2):
        row = []
        for a in amounts[i:i+2]:
            stars = int(a * rate)
            row.append(InlineKeyboardButton(
                "💵 ${} — ⭐ {:,}".format(a, stars),
                callback_data="stars_buy_{}".format(a)
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ مبلغ مخصص", callback_data="stars_custom")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="deposit")])
    return InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════════
#  ⭐ Stars — عرض الصفحة
# ══════════════════════════════════════════════════════════

async def charge_stars_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    db: Database = context.bot_data["db"]

    if db.get_setting("pay_stars", "0") != "1":
        await safe_answer(query, "⭐ نجوم تيليغرام غير مفعّلة حالياً.", show_alert=True)
        return

    rate    = _stars_rate(db)
    min_usd = _stars_min_usd(db)
    context.user_data.pop("stars_state", None)

    await safe_edit(
        query,
        "⭐ <b>شحن بـ Telegram Stars</b>\n\n"
        "💱 السعر: <b>{} نجمة = $1</b>\n"
        "💰 الحد الأدنى: <b>${:.0f}</b>\n\n"
        "اختر المبلغ:".format(int(rate), min_usd),
        reply_markup=_stars_amounts_kb(min_usd, rate),
        parse_mode="HTML"
    )


async def stars_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    db: Database = context.bot_data["db"]
    try:
        usd = float(query.data.replace("stars_buy_", ""))
    except ValueError:
        return
    await _send_stars_invoice(update, context, db, usd)


async def stars_custom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    db: Database = context.bot_data["db"]
    rate    = _stars_rate(db)
    min_usd = _stars_min_usd(db)
    context.user_data["stars_state"] = "waiting_amount"
    await safe_edit(
        query,
        "⭐ <b>مبلغ مخصص</b>\n\n"
        "💱 السعر: <b>{} نجمة = $1</b>\n"
        "💰 الحد الأدنى: <b>${:.0f}</b>\n\n"
        "📝 أرسل المبلغ بالدولار:".format(int(rate), min_usd),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="charge_stars")]
        ]),
        parse_mode="HTML"
    )


async def stars_amount_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("stars_state") != "waiting_amount":
        return False

    db: Database = context.bot_data["db"]
    try:
        usd = float((update.message.text or "").strip().replace(",", "."))
        if usd <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ أرسل رقماً صحيحاً، مثال: <code>5</code>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="charge_stars")
            ]]),
            parse_mode="HTML"
        )
        return True

    min_usd = _stars_min_usd(db)
    if usd < min_usd:
        await update.message.reply_text(
            "❌ الحد الأدنى هو <b>${:.0f}</b>".format(min_usd),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="charge_stars")
            ]]),
            parse_mode="HTML"
        )
        return True

    if usd > 10000:
        await update.message.reply_text("❌ الحد الأقصى $10,000")
        return True

    context.user_data.pop("stars_state", None)
    await _send_stars_invoice(update, context, db, usd)
    return True


async def _send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               db: Database, usd: float):
    rate       = _stars_rate(db)
    stars_need = max(1, int(usd * rate))
    try:
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title="شحن ${:.0f} رصيد".format(usd),
            description="دفع {:,} نجمة مقابل إضافة ${:.2f} لرصيدك.".format(stars_need, usd),
            payload="stars_{}_{}".format(update.effective_user.id, usd),
            currency="XTR",
            prices=[LabeledPrice(
                label="⭐ {:,} نجمة  ←  ${:.2f}".format(stars_need, usd),
                amount=stars_need,
            )],
        )
    except TelegramError as e:
        logger.error("[STARS] فشل الفاتورة: {}".format(e))
        msg = "❌ حدث خطأ، حاول مرة أخرى."
        if hasattr(update, "callback_query") and update.callback_query:
            await safe_answer(update.callback_query, msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=back_to_main_kb())


async def successful_payment_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    if not payload.startswith("stars_"):
        return

    db: Database = context.bot_data["db"]
    parts = payload.split("_", 2)
    try:
        uid       = int(parts[1])
        usd_asked = float(parts[2])
    except (IndexError, ValueError):
        return

    stars_paid = payment.total_amount
    rate       = _stars_rate(db)
    credit     = round(stars_paid / rate, 4)

    db.add_balance(uid, credit)
    balance = db.get_balance(uid)

    await update.message.reply_text(
        "✅ <b>تم شحن رصيدك!</b>\n\n"
        "⭐ النجوم: <b>{:,}</b>\n"
        "💰 أضيف: <b>${:.4f}</b>\n"
        "💳 رصيدك الآن: <b>${:.4f}</b>".format(stars_paid, credit, balance),
        parse_mode="HTML",
        reply_markup=back_to_main_kb()
    )

    user     = update.effective_user
    username = "@{}".format(user.username) if user.username else "#{}".format(uid)
    notif = (
        "⭐ <b>شحن نجوم ناجح</b>\n\n"
        "👤 {} (<code>{}</code>)\n"
        "⭐ نجوم: <b>{:,}</b>\n"
        "💰 أضيف: <b>${:.4f}</b>\n"
        "💳 الرصيد: <b>${:.4f}</b>".format(username, uid, stars_paid, credit, balance)
    )
    try:
        ch = db.get_setting("deposit_channel", "").strip()
        if ch and ch not in ("", "0"):
            await context.bot.send_message(chat_id=int(ch), text=notif, parse_mode="HTML")
        admin = _admin_id(db)
        if admin:
            await context.bot.send_message(chat_id=admin, text=notif, parse_mode="HTML")
    except TelegramError:
        pass


# ══════════════════════════════════════════════════════════
#  💛 Binance Pay
# ══════════════════════════════════════════════════════════

async def charge_binance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    db: Database = context.bot_data["db"]

    if db.get_setting("pay_binance", "0") != "1":
        await safe_answer(query, "💛 Binance Pay غير مفعّل حالياً.", show_alert=True)
        return

    pay_id = _bnb_pay_id(db)
    if not pay_id:
        await safe_answer(query, "⚠️ لم يُحدَّد Binance Pay ID بعد. تواصل مع الأدمن.", show_alert=True)
        return

    min_usd = _bnb_min_usd(db)
    context.user_data["binance_state"] = "waiting_order_id"

    await safe_edit(
        query,
        "🟡 <b>طريقة الإيداع عبر بينانس</b>\n\n"
        "✅ الحد الأدنى للإيداع: <b>${}</b>\n"
        "📝 يمكنك إيداع أي مبلغ من <b>${}</b> فما فوق\n\n"
        "1. قم بنسخ معرف التحويل أدناه\n"
        "2. اذهب إلى تطبيق <b>Binance</b>\n"
        "3. أرسل أي مبلغ تريده (من ${})\n"
        "4. أرسل معرف المعاملة (Transaction ID)\n\n"
        "📋 <b>ايدي التحويل:</b>\n"
        "<code>{}</code>\n\n"
        "⚠️ <b>ملاحظات هامة:</b>\n"
        "• يجب أن يكون التحويل من نفس اليوم\n"
        "• لا يمكن استخدام نفس المعرف مرتين\n"
        "• سيتم إضافة المبلغ بالضبط كما أرسلته".format(
            min_usd, min_usd, min_usd, pay_id),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("• كيف تودع ❓", url="https://t.me/Deposit_bot_Method")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="deposit")],
        ]),
        parse_mode="HTML"
    )


async def binance_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("binance_state") != "waiting_order_id":
        return False

    db: Database = context.bot_data["db"]
    order_id = (update.message.text or "").strip()

    if not order_id or not order_id.isdigit() or len(order_id) < 10:
        await update.message.reply_text(
            "❌ <b>Order ID غير صحيح</b>\n\n"
            "أرسل الرقم كما يظهر في تطبيق Binance.\n"
            "مثال: <code>429587669106335744</code>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="deposit")
            ]]),
            parse_mode="HTML"
        )
        return True

    # تحقق من الاستخدام المسبق
    used = db.get_setting("bnb_used_{}".format(order_id), "")
    if used == "1":
        await update.message.reply_text(
            "⛔ <b>هذا Order ID تم استخدامه مسبقاً.</b>",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML"
        )
        return True

    context.user_data.pop("binance_state", None)

    api_key    = _bnb_api_key(db)
    api_secret = _bnb_api_secret(db)
    uid        = update.effective_user.id
    user       = update.effective_user
    username   = "@{}".format(user.username) if user.username else "#{}".format(uid)

    if api_key and api_secret:
        # وضع تلقائي
        checking = await update.message.reply_text(
            "🔍 <b>جارٍ التحقق من المعاملة...</b>",
            parse_mode="HTML"
        )
        amount = await _verify_binance_order(api_key, api_secret, order_id)

        if amount is None:
            await context.bot.edit_message_text(
                chat_id=checking.chat.id,
                message_id=checking.message_id,
                text=(
                    "❌ <b>لم يتم العثور على التحويل</b>\n\n"
                    "تأكد من:\n"
                    "• صحة Order ID\n"
                    "• اكتمال التحويل في تطبيق Binance\n"
                    "• أن التحويل تم اليوم\n\n"
                    "يمكنك المحاولة مرة أخرى."
                ),
                parse_mode="HTML",
                reply_markup=back_to_main_kb()
            )
            return True

        min_usd = _bnb_min_usd(db)
        if amount < min_usd:
            await context.bot.edit_message_text(
                chat_id=checking.chat.id,
                message_id=checking.message_id,
                text="⚠️ <b>المبلغ أقل من الحد الأدنى!</b>\n\nالمُرسَل: <b>${:.4f}</b>\nالأدنى: <b>${}</b>".format(amount, min_usd),
                parse_mode="HTML",
                reply_markup=back_to_main_kb()
            )
            return True

        db.set_setting("bnb_used_{}".format(order_id), "1")
        db.add_balance(uid, amount)
        balance = db.get_balance(uid)

        await context.bot.edit_message_text(
            chat_id=checking.chat.id,
            message_id=checking.message_id,
            text=(
                "✅ <b>تم الشحن!</b>\n\n"
                "🆔 Order ID: <code>{}</code>\n"
                "💰 أضيف: <b>${:.4f}</b>\n"
                "💳 رصيدك: <b>${:.4f}</b>".format(order_id, amount, balance)
            ),
            parse_mode="HTML",
            reply_markup=back_to_main_kb()
        )

        notif = (
            "🟡 <b>شحن Binance Pay تلقائي ✅</b>\n\n"
            "👤 {} (<code>{}</code>)\n"
            "🆔 Order ID: <code>{}</code>\n"
            "💰 أضيف: <b>${:.4f}</b>\n"
            "💳 الرصيد: <b>${:.4f}</b>".format(username, uid, order_id, amount, balance)
        )
        try:
            ch = db.get_setting("deposit_channel", "").strip()
            if ch and ch not in ("", "0"):
                await context.bot.send_message(chat_id=int(ch), text=notif, parse_mode="HTML")
            admin = _admin_id(db)
            if admin:
                await context.bot.send_message(chat_id=admin, text=notif, parse_mode="HTML")
        except TelegramError:
            pass

    else:
        # وضع يدوي — يرسل للأدمن للمراجعة
        db.set_setting("bnb_used_{}".format(order_id), "pending")

        try:
            admin = _admin_id(db)
            if admin:
                await context.bot.send_message(
                    chat_id=admin,
                    text=(
                        "🟡 <b>طلب شحن Binance Pay (يدوي)</b>\n\n"
                        "👤 {} (<code>{}</code>)\n"
                        "🆔 Order ID: <code>{}</code>".format(username, uid, order_id)
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ قبول", callback_data="binance_approve_{}_{}".format(order_id, uid)),
                            InlineKeyboardButton("❌ رفض",  callback_data="binance_reject_{}_{}".format(order_id, uid)),
                        ]
                    ])
                )
        except TelegramError as e:
            logger.warning("[BINANCE] فشل إشعار الأدمن: {}".format(e))

        await update.message.reply_text(
            "✅ <b>تم إرسال طلبك للمراجعة</b>\n\n"
            "🆔 Order ID: <code>{}</code>\n"
            "⏳ سيتم إضافة رصيدك بعد المراجعة.".format(order_id),
            parse_mode="HTML",
            reply_markup=back_to_main_kb()
        )

    logger.info("[BINANCE] uid={} order_id={}".format(uid, order_id))
    return True


async def _verify_binance_order(api_key: str, api_secret: str, order_id: str):
    """يتحقق من Order ID عبر Binance Pay API ويرجع المبلغ أو None"""
    try:
        now_ms   = int(time.time() * 1000)
        start_ms = now_ms - (30 * 24 * 60 * 60 * 1000)

        query = (
            "timestamp={}"
            "&startTime={}"
            "&endTime={}"
            "&limit=100".format(now_ms, start_ms, now_ms)
        )

        sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = "https://api.binance.com/sapi/v1/pay/transactions?{}&signature={}".format(query, sig)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"X-MBX-APIKEY": api_key},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json(content_type=None)

        if not data.get("success"):
            logger.error("[BINANCE] API فشل: {}".format(data))
            return None

        clean = "".join(filter(str.isdigit, order_id))
        for tx in data.get("data", []):
            api_id = str(tx.get("orderId", "")).strip()
            digits = "".join(filter(str.isdigit, api_id))
            if api_id == order_id or digits == clean or clean in digits:
                amount = float(tx.get("amount", 0))
                if amount > 0:
                    return amount
        return None

    except Exception as e:
        logger.error("[BINANCE ERROR] {}".format(e))
        return None


# ══════════════════════════════════════════════════════════
#  أدمن: قبول/رفض Binance يدوي
# ══════════════════════════════════════════════════════════

async def binance_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    db: Database = context.bot_data["db"]
    if update.effective_user.id != _admin_id(db):
        return

    parts    = query.data.split("_")   # binance_approve_<order>_<uid>
    order_id = parts[2]
    uid      = parts[3]

    context.user_data["bnb_approve_order"] = order_id
    context.user_data["bnb_approve_uid"]   = int(uid)
    context.user_data["bnb_admin_state"]   = "waiting_amount"

    await safe_edit(
        query,
        "🟡 <b>قبول طلب Binance Pay</b>\n\n"
        "🆔 Order ID: <code>{}</code>\n"
        "👤 المستخدم: <code>{}</code>\n\n"
        "📝 أرسل المبلغ بالدولار:".format(order_id, uid),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ إلغاء", callback_data="adm_main")
        ]])
    )


async def binance_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    db: Database = context.bot_data["db"]
    if update.effective_user.id != _admin_id(db):
        return

    parts    = query.data.split("_")
    order_id = parts[2]
    uid      = int(parts[3])

    db.set_setting("bnb_used_{}".format(order_id), "rejected")

    try:
        await context.bot.send_message(
            chat_id=uid,
            text="❌ <b>تم رفض طلب Binance Pay</b>\n🆔 Order ID: <code>{}</code>".format(order_id),
            parse_mode="HTML"
        )
    except TelegramError:
        pass

    await safe_edit(query, "❌ تم رفض الطلب: <code>{}</code>".format(order_id), parse_mode="HTML")


async def binance_admin_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("bnb_admin_state") != "waiting_amount":
        return False
    db: Database = context.bot_data["db"]
    if update.effective_user.id != _admin_id(db):
        return False

    try:
        amount = float((update.message.text or "").strip().replace(",", "."))
        assert amount > 0
    except Exception:
        await update.message.reply_text("❌ أرسل رقماً صحيحاً مثل: <code>5.00</code>", parse_mode="HTML")
        return True

    order_id = context.user_data.pop("bnb_approve_order", "")
    uid      = context.user_data.pop("bnb_approve_uid", 0)
    context.user_data.pop("bnb_admin_state", None)

    if db.get_setting("bnb_used_{}".format(order_id), "") == "1":
        await update.message.reply_text("⚠️ هذا Order ID أُضيف بالفعل.")
        return True

    db.set_setting("bnb_used_{}".format(order_id), "1")
    db.add_balance(uid, amount)
    balance = db.get_balance(uid)

    try:
        await context.bot.send_message(
            chat_id=uid,
            text=(
                "✅ <b>تم إضافة رصيدك!</b>\n\n"
                "🆔 Order ID: <code>{}</code>\n"
                "💰 أضيف: <b>${:.4f}</b>\n"
                "💳 رصيدك: <b>${:.4f}</b>".format(order_id, amount, balance)
            ),
            parse_mode="HTML",
            reply_markup=back_to_main_kb()
        )
    except TelegramError:
        pass

    await update.message.reply_text(
        "✅ تم إضافة <b>${:.4f}</b> للمستخدم <code>{}</code>".format(amount, uid),
        parse_mode="HTML"
    )
    return True
