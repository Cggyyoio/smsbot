"""
📱 sms_handler.py — منطق شراء أرقام SMS
• يقرأ ملفات TXT برفعها الأدمن (يدعم | و ----)
• المستخدم يختار الدولة → يشتري → البوت يبدأ polling على API كل 5 ثواني
• لما يصل الكود → يعدّل الرسالة ويحذف الرقم من قاعدة البيانات
• بعد 10 دقائق بدون كود → يرجع الرصيد ويحرر الرقم
"""

import asyncio
import logging
import re
import json
import os
import random
import aiohttp
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

SMS_TIMEOUT     = 10 * 60   # 10 دقائق
POLL_INTERVAL   = 5          # كل 5 ثواني
SMS_ACTION_WAIT = 30         # ثواني قبل تفعيل أزرار إلغاء/حظر الرقم

NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "names.txt")


def get_random_name() -> str:
    """يرجع اسماً عشوائياً من ملف names.txt"""
    try:
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            names = [n.strip() for n in f.readlines() if n.strip()]
        if names:
            return random.choice(names)
    except Exception:
        pass
    return "Alex Morgan"


# ──────────────────────────────────────────────────────────
#  استخراج الكود من الـ API response
# ──────────────────────────────────────────────────────────

CODE_RE = re.compile(r'\d{5,6}')   # 5-6 أرقام متتالية بدون فواصل أو مسافات


def _extract_code(raw_text: str):
    """
    يبحث عن كود OTP في أي نص — JSON أو plain text.
    يرجع (code, full_text) أو (None, None)

    أمثلة:
      {"ok": false, "error": "code not found"}   → (None, None)
      {"ok": true, "code": "12345"}               → ("12345", ...)
      yes|Telegram code: 17320 ...                → ("17320", ...)
    """
    if not raw_text:
        return None, None

    clean = raw_text.strip()

    # ── نص فارغ أو صريح "لسه مجاش" ──────────────────────
    lower = clean.lower()
    NO_CODE_PHRASES = ("code not found", "not found", "wait", "no sms", "empty")
    if clean in ("", "no", "false", "null"):
        return None, None

    # ── حاول parse كـ JSON ───────────────────────────────
    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            # صريح: ok=false + error يحتوي على "not found"
            if not data.get("ok", True):
                err = str(data.get("error", "")).lower()
                if any(p in err for p in NO_CODE_PHRASES):
                    return None, None
        flat = _flatten_json(data)
    except Exception:
        # مش JSON — استخدم النص كما هو
        flat = clean

    # ── ابحث عن 5-6 أرقام متتالية ──────────────────────
    # نتجاهل الأرقام اللي في URLs (مثل /login/17320)
    # بنأخذ أول كود مسبوق بـ "code:" أو ":" أو مسافة
    # أولوية: كود بعد "code" أو ":" أو نقطتين
    priority = re.search(r'(?:code|كود)[:\s#]+(\d{4,8})', flat, re.IGNORECASE)
    if priority:
        code = priority.group(1)
        display = flat.replace("<", "&lt;").replace(">", "&gt;")
        return code, display

    # fallback: أي 5-6 أرقام متتالية
    m = CODE_RE.search(flat)
    if not m:
        return None, None

    code = m.group(0)
    display = flat.replace("<", "&lt;").replace(">", "&gt;")
    return code, display


def _flatten_json(obj, sep=" | ") -> str:
    """يحوّل JSON لسلسلة نصية مقروءة"""
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            parts.append("{}: {}".format(k, _flatten_json(v)))
        return sep.join(parts)
    if isinstance(obj, list):
        return sep.join(_flatten_json(i) for i in obj)
    return str(obj)


# ──────────────────────────────────────────────────────────
#  رسائل الحالة
# ──────────────────────────────────────────────────────────

def _build_sms_waiting_msg(phone: str, country: str) -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎉 <b>تم الشراء بنجاح!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 <b>الدولة:</b> {country}\n"
        "📞 <b>الرقم:</b> <code>{phone}</code>\n"
        "🔑 <b>الكود:</b> ⏳ في انتظار الرسالة...\n\n"
        "⏰ <i>سيصل الكود تلقائياً، الانتظار حتى 10 دقائق</i>"
    ).format(country=country, phone=phone)


def _sms_waiting_kb(order_id: int):
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ إلغاء الرقم", callback_data="sms_cancel_{}".format(order_id)),
        InlineKeyboardButton("🚫 حظر الرقم",  callback_data="sms_block_{}".format(order_id)),
    ]])


def _build_sms_done_msg(phone: str, country: str, code: str, full_response: str) -> str:
    msg = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>تم استلام الكود!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 <b>الدولة:</b> {country}\n"
        "📞 <b>الرقم:</b> <code>{phone}</code>\n"
        "🔑 <b>كود التحقق:</b> <code>{code}</code>\n"
    ).format(country=country, phone=phone, code=code)

    # أضف الرد الكامل من الـ API (مفيد لو في نص SMS كامل)
    if full_response and full_response.strip() != code:
        # اختصره لو طويل
        display = full_response[:800] + ("..." if len(full_response) > 800 else "")
        msg += "\n📩 <b>الرسالة الكاملة:</b>\n<code>{}</code>\n".format(display)

    suggested_name = get_random_name()
    msg += "\n📝 <b>اسم مقترح:</b> <code>{}</code>\n".format(suggested_name)
    msg += "\n<i>✅ احفظ هذه البيانات في مكان آمن</i>"
    return msg


def _build_sms_expired_msg(phone: str, country: str) -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏰ <b>انتهت مهلة الانتظار</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 <b>الدولة:</b> {country}\n"
        "📞 <b>الرقم:</b> <code>{phone}</code>\n\n"
        "❌ لم يصل أي كود خلال 10 دقائق.\n"
        "💰 <b>تم إرجاع رصيدك كاملاً.</b>"
    ).format(country=country, phone=phone)


# ──────────────────────────────────────────────────────────
#  SmsPoller — يدير polling لطلبات SMS النشطة
# ──────────────────────────────────────────────────────────

class SmsPoller:
    def __init__(self, db, bot):
        self.db    = db
        self.bot   = bot
        self._tasks: dict[int, asyncio.Task] = {}

    def start_polling(self, order_id: int, user_tg_id: int,
                      chat_id: int, msg_id: int,
                      phone: str, country: str, api_url: str,
                      cost: float, sms_num_id: int):
        if order_id in self._tasks:
            return
        task = asyncio.create_task(
            self._poll(order_id, user_tg_id, chat_id, msg_id,
                       phone, country, api_url, cost, sms_num_id)
        )
        self._tasks[order_id] = task

    async def _poll(self, order_id, user_tg_id, chat_id, msg_id,
                    phone, country, api_url, cost, sms_num_id):
        elapsed = 0
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            timeout   = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                while elapsed < SMS_TIMEOUT:
                    await asyncio.sleep(POLL_INTERVAL)
                    elapsed += POLL_INTERVAL

                    try:
                        async with session.get(api_url, allow_redirects=True) as resp:
                            raw = await resp.text(encoding="utf-8", errors="replace")
                            logger.info("sms poll [%s] status=%s raw=%r", phone, resp.status, raw[:300])
                            code, full_text = _extract_code(raw)
                            if code:
                                # ✅ وصل الكود
                                self.db.complete_sms_order(order_id, code)
                                self.db.delete_sms_number(sms_num_id)
                                done_text = _build_sms_done_msg(phone, country, code, full_text)
                                try:
                                    await self.bot.edit_message_text(
                                        chat_id=chat_id,
                                        message_id=msg_id,
                                        text=done_text,
                                        parse_mode="HTML",
                                        reply_markup=None
                                    )
                                except BadRequest as e:
                                    if "not modified" not in str(e).lower():
                                        logger.warning("edit sms done: %s", e)
                                # إشعار قناة التفعيلات
                                try:
                                    ch = self.db.get_setting("notify_channel", "").strip()
                                    if ch and ch not in ("", "0"):
                                        p_str      = str(phone).lstrip("+")
                                        m_phone    = "+" + p_str[:4] + "★★★"
                                        m_code     = "".join(c if i % 2 == 0 else "★"
                                                             for i, c in enumerate(str(code)))
                                        m_uid      = str(user_tg_id)[:3] + "★★★"
                                        bot_me     = await self.bot.get_me()
                                        bot_uname  = "@" + bot_me.username
                                        notif = (
                                            "✅ <b>تم شراء رقم جديد</b>\n\n"
                                            "🌐 <b>التطبيق:</b> SMS\n"
                                            "🌍 <b>الدولة:</b> {country}\n"
                                            "📞 <b>الرقم:</b> <code>{phone}</code>\n"
                                            "🔑 <b>الكود:</b> <code>{code}</code>\n"
                                            "👤 <b>المستخدم:</b> <code>{uid}</code>\n"
                                            "⚡ <b>الحالة:</b> تم التفعيل ⚡\n"
                                            "💰 <b>السعر:</b> ${price:.3f}\n"
                                            "🤖 <b>للشراء:</b> {bot}"
                                        ).format(
                                            country=country, phone=m_phone,
                                            code=m_code, uid=m_uid,
                                            price=float(cost), bot=bot_uname
                                        )
                                        await self.bot.send_message(
                                            chat_id=int(ch), text=notif, parse_mode="HTML"
                                        )
                                except Exception as e:
                                    logger.warning("sms notify_channel error: %s", e)
                                return
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.debug("sms poll error: %s", e)

            # ❌ انتهى الوقت بدون كود — زوّد عداد الفشل
            self.db.cancel_sms_order(order_id)
            self.db.add_balance(user_tg_id, cost)

            info = self.db.increment_sms_fail(sms_num_id)
            fail_count = info.get("fail_count", 0)

            if fail_count >= 3:
                # حذف الرقم وإبلاغ الأدمن
                self.db.delete_sms_number(sms_num_id)
                await self._notify_admin_bad_number(phone, api_url, fail_count)
                expired_extra = "\n⚠️ <i>تم حذف هذا الرقم تلقائياً (فشل 3 مرات)</i>"
            else:
                # إرجاع الرقم للمخزون
                self.db.release_sms_number(sms_num_id)
                expired_extra = ""

            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=_build_sms_expired_msg(phone, country) + expired_extra,
                    parse_mode="HTML",
                    reply_markup=None
                )
            except BadRequest:
                pass

        except asyncio.CancelledError:
            pass
        finally:
            self._tasks.pop(order_id, None)

    async def _notify_admin_bad_number(self, phone: str, api_url: str, fail_count: int):
        """يبلّغ الأدمن برقم فشل 3 مرات"""
        try:
            admin_id = self.db.get_setting("admin_id", "")
            if not admin_id:
                return
            await self.bot.send_message(
                chat_id=int(admin_id),
                text=(
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚠️ <b>رقم SMS محذوف تلقائياً</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "📞 <b>الرقم:</b> <code>{phone}</code>\n"
                    "❌ <b>عدد الفشل:</b> {fail} مرات بدون كود\n\n"
                    "🔗 <b>رابط API:</b>\n"
                    "<code>{api}</code>"
                ).format(phone=phone, fail=fail_count, api=api_url),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning("notify admin bad number: %s", e)

    def cancel(self, order_id: int):
        t = self._tasks.pop(order_id, None)
        if t:
            t.cancel()


# ──────────────────────────────────────────────────────────
#  parse_sms_txt — يدعم | و ----
# ──────────────────────────────────────────────────────────

def parse_sms_txt(content: str, app_type: str = "whatsapp") -> list[dict]:
    """
    الصيغ المدعومة:
      +13347795283|https://feizi.shop?token=xxx
      +13673243007----https://smsjs.top/api/sms/record?key=xxx
    يرجع قائمة {phone, api_url, country, app_type}
    """
    from country_codes import detect_country
    SEP_RE = re.compile(r'\||-{2,}|\t')
    numbers = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = SEP_RE.split(line, 1)
        if len(parts) != 2:
            continue
        phone   = parts[0].strip()
        api_url = parts[1].strip()
        if not phone or not api_url:
            continue
        if not phone.startswith("+"):
            phone = "+" + phone
        cc, flag, cname = detect_country(phone)
        numbers.append({
            "phone":    phone,
            "api_url":  api_url,
            "country":  "{} {}".format(flag, cname),
            "app_type": app_type,
        })
    return numbers
