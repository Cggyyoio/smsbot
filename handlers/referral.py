"""
🤝 handlers/referral.py — نظام الإحالة
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest

logger = logging.getLogger(__name__)


async def _edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("referral edit: %s", e)


async def referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    await q.answer()

    bot_me   = await context.bot.get_me()
    ref_link = "https://t.me/{}?start=ref{}".format(bot_me.username, user.id)
    stats    = db.get_referral_stats(user.id)
    min_wd   = float(db.get_setting("referral_min_withdraw", "1.0"))
    pct      = float(db.get_setting("referral_percent", "10"))

    can_withdraw = stats["pending"] >= min_wd

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 <b>ربح رصيد — الإحالة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔗 <b>رابط الإحالة:</b>\n"
        "<code>{link}</code>\n\n"
        "📊 <b>إحصائياتك:</b>\n"
        "👥 من أحضرت: <b>{count}</b> مستخدم\n"
        "💵 إجمالي الأرباح: <b>${earned:.3f}</b>\n"
        "⏳ رصيد معلّق: <b>${pending:.3f}</b>\n\n"
        "📌 تكسب <b>{pct:.0f}%</b> من قيمة كل طلب يعمله من تحيله\n"
        "💳 الحد الأدنى للسحب: <b>${min:.2f}</b>"
    ).format(
        link=ref_link, count=stats["count"],
        earned=stats["earned"], pending=stats["pending"],
        pct=pct, min=min_wd
    )

    rows = []
    if can_withdraw:
        rows.append([InlineKeyboardButton(
            "💸 سحب ${:.3f} للرصيد".format(stats["pending"]),
            callback_data="referral_withdraw"
        )])
    else:
        rows.append([InlineKeyboardButton(
            "🔒 الرصيد المعلّق أقل من الحد الأدنى",
            callback_data="referral_noop"
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])

    await _edit(q, text, InlineKeyboardMarkup(rows))


async def referral_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    await q.answer()

    amount = db.withdraw_referral(user.id)
    if amount > 0:
        await q.answer(
            "✅ تم تحويل ${:.3f} إلى رصيدك!".format(amount),
            show_alert=True
        )
    else:
        min_wd = float(db.get_setting("referral_min_withdraw", "1.0"))
        await q.answer(
            "❌ الرصيد المعلّق أقل من الحد الأدنى ${:.2f}".format(min_wd),
            show_alert=True
        )
    await referral_callback(update, context)


async def referral_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
