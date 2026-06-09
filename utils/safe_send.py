"""
🛡️ utils/safe_send.py
دوال مساعدة آمنة تلتهم أخطاء Telegram الشائعة بدون crash
"""

import logging
from telegram import Update, InlineKeyboardMarkup
from telegram.error import BadRequest, TimedOut, NetworkError

logger = logging.getLogger(__name__)

_IGNORED = (
    "message is not modified",
    "query is too old",
    "query id is invalid",
    "message to edit not found",
    "message can't be edited",
)


def _is_ignorable(err: Exception) -> bool:
    return any(s in str(err).lower() for s in _IGNORED)


async def safe_answer(query, text: str = None, show_alert: bool = False):
    """query.answer() لا تكسر البوت لو انتهى الوقت."""
    try:
        if text:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
    except (BadRequest, TimedOut, NetworkError) as e:
        if not _is_ignorable(e):
            logger.warning(f"[SAFE] answer: {e}")


async def safe_edit(query, text: str, reply_markup=None,
                    parse_mode: str = "HTML", **kwargs):
    """query.edit_message_text() لا تكسر البوت لو الرسالة لم تتغير."""
    try:
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            **kwargs,
        )
    except (BadRequest, TimedOut, NetworkError) as e:
        if not _is_ignorable(e):
            logger.warning(f"[SAFE] edit: {e}")


async def safe_send(bot, chat_id, text: str, reply_markup=None,
                    parse_mode: str = "HTML", **kwargs):
    """bot.send_message() لا تكسر البوت."""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            **kwargs,
        )
    except (BadRequest, TimedOut, NetworkError) as e:
        logger.warning(f"[SAFE] send to {chat_id}: {e}")
        return None
