"""
🚫 handlers/sms_actions.py
أزرار "إلغاء الرقم" و"حظر الرقم" تحت رسالة انتظار كود SMS.
- لا تُفعَّل الأزرار إلا بعد 30 ثانية من وقت الشراء.
- كلاهما: يرجّع الرصيد، يحرّر الرقم للمخزون، ويستبعد هذا الرقم
  عن هذا المستخدم تحديداً (إلا لو كان آخر رقم متاح للدولة/النوع).
- "حظر الرقم" يزيد أيضاً عداد فشل الرقم (نفس آلية انتهاء المهلة)،
  فإذا وصل لـ 3 يُحذف الرقم نهائياً ويُبلَّغ الأدمن.
"""

import logging
import datetime
from telegram import Update
from telegram.ext import ContextTypes

from sms_handler import SMS_ACTION_WAIT, _build_sms_expired_msg

logger = logging.getLogger(__name__)


def _elapsed_seconds(created_at) -> float:
    """يحسب عدد الثواني المنقضية منذ created_at (string أو datetime)"""
    if not created_at:
        return 999999
    if isinstance(created_at, str):
        try:
            created_at = datetime.datetime.fromisoformat(created_at)
        except Exception:
            try:
                created_at = datetime.datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return 999999
    now = datetime.datetime.utcnow()
    if created_at.tzinfo:
        now = now.replace(tzinfo=created_at.tzinfo)
    return (now - created_at).total_seconds()


async def _handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    q    = update.callback_query
    db   = context.bot_data["db"]
    poller = context.bot_data.get("sms_poller")
    user = update.effective_user

    prefix   = "sms_cancel_" if action == "cancel" else "sms_block_"
    order_id = int(q.data.replace(prefix, "", 1))

    order = db.get_sms_order(order_id)
    if not order:
        await q.answer("❌ الطلب غير موجود", show_alert=True)
        return

    if order["user_tg_id"] != user.id:
        await q.answer("🚫 هذا الطلب ليس لك", show_alert=True)
        return

    if order["status"] != "pending":
        await q.answer("⚠️ تم التعامل مع هذا الطلب بالفعل", show_alert=True)
        return

    elapsed = _elapsed_seconds(order.get("created_at"))
    if elapsed < SMS_ACTION_WAIT:
        remaining = int(SMS_ACTION_WAIT - elapsed) + 1
        await q.answer(
            "⏳ انتظر {} ثانية بعد الشراء قبل استخدام هذا الزر".format(remaining),
            show_alert=True
        )
        return

    # ── أوقف الـ polling ────────────────────────────────
    if poller:
        poller.cancel(order_id)

    sms_num_id = order["sms_num_id"]
    phone      = order["phone"]
    country    = order["country"]
    cost       = order["cost"]

    # ── أرجع الرصيد وحرّر الرقم ─────────────────────────
    db.cancel_sms_order(order_id)
    db.add_balance(user.id, cost)
    db.release_sms_number(sms_num_id)

    # ── استبعد هذا الرقم عن هذا المستخدم مستقبلاً ──────
    db.add_sms_exclusion(user.id, phone, reason=action)

    extra = ""
    if action == "block":
        # نفس آلية فشل المهلة: 3 مرات → حذف الرقم + إبلاغ الأدمن
        info = db.increment_sms_fail(sms_num_id)
        fail_count = info.get("fail_count", 0)
        if fail_count >= 3:
            db.delete_sms_number(sms_num_id)
            extra = "\n⚠️ <i>تم حذف هذا الرقم نهائياً من النظام (تكرار الحظر)</i>"

    title = "❌ <b>تم إلغاء الرقم</b>" if action == "cancel" else "🚫 <b>تم حظر الرقم</b>"
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "{title}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📞 <b>الرقم:</b> <code>{phone}</code>\n"
        "🌍 <b>الدولة:</b> {country}\n\n"
        "💰 <b>تم إرجاع رصيدك: ${cost:.3f}</b>{extra}"
    ).format(title=title, phone=phone, country=country, cost=cost, extra=extra)

    try:
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=None)
    except Exception as e:
        logger.warning("sms_actions edit error: %s", e)

    await q.answer(
        "✅ تم الإلغاء وإرجاع الرصيد" if action == "cancel" else "✅ تم الحظر وإرجاع الرصيد"
    )


async def sms_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_action(update, context, "cancel")


async def sms_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_action(update, context, "block")
