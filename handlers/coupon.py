"""
🎟️ handlers/coupon.py — نظام الكوبونات للمستخدمين
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest

logger = logging.getLogger(__name__)


async def coupon_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض شاشة إدخال الكوبون"""
    q = update.callback_query
    await q.answer()
    context.user_data["waiting_coupon"] = True
    await q.edit_message_text(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎟️ <b>استخدام كوبون</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "أرسل كود الكوبون:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 رجوع", callback_data="deposit")
        ]]),
        parse_mode="HTML"
    )


async def coupon_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not context.user_data.get("waiting_coupon"):
        return False
    context.user_data.pop("waiting_coupon", None)

    db   = context.bot_data["db"]
    user = update.effective_user
    code = (update.message.text or "").strip()

    if not code:
        await update.message.reply_text("❌ كود فارغ.")
        return True

    # نتحقق إن الكوبون صالح أولاً
    coupon = db.get_coupon(code)
    if not coupon:
        await update.message.reply_text("❌ الكوبون غير موجود أو منتهي الصلاحية.")
        return True

    # نحتاج مبلغ شحن — هنا نطبق الكوبون كإضافة رصيد مباشرة
    ok, val = db.use_coupon(code, user.id, 0)
    if not ok:
        await update.message.reply_text("❌ {}".format(val))
        return True

    # val = الخصم أو القيمة المضافة
    if coupon["type"] == "fixed":
        db.add_balance(user.id, val)
        msg = "✅ <b>تم تفعيل الكوبون!</b>\n\n💰 أُضيف <b>${:.3f}</b> لرصيدك.".format(val)
    else:
        db.add_balance(user.id, val)
        msg = "✅ <b>تم تفعيل الكوبون!</b>\n\n🎁 أُضيف <b>{:.1f}%</b> = <b>${:.3f}</b> لرصيدك.".format(
            coupon["value"], val
        )

    bal = db.get_balance(user.id)
    await update.message.reply_text(
        msg + "\n💳 رصيدك الحالي: <b>${:.3f}</b>".format(bal),
        parse_mode="HTML"
    )
    return True
