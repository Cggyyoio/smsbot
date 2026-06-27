"""
📩 otp_listener.py — يستمع لرسائل OTP من +42777
• يستخدم 2FA من DB إن وُجد
• يخفي الرقم على المستخدم حتى وصول الكود
• بعد 5 دقايق بدون كود → يرجع الرصيد + يحرر الرقم
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

logger = logging.getLogger(__name__)

SESSIONS_DIR  = "sessions"
OTP_SENDER    = "+42777"
OTP_SENDER_ID = 777000       # Telegram system messages
OTP_TIMEOUT   = 5 * 60       # 5 دقايق بالثواني


def _build_waiting_msg(phone: str) -> str:
    return (
        "⚡ <b>تم الشراء!</b>\n\n"
        "📞 <b>الرقم:</b>  <code>+{phone}</code>\n"
        "🔑 <b>الكود:</b>  ⏳ <i>في انتظار الرسالة...</i>\n\n"
        "⏰ <i>سيصل خلال دقائق</i>"
    ).format(phone=phone)


def build_order_msg(phone: str, code: str, twofa: str = None) -> str:
    msg = (
        "✅ <b>الكود وصل!</b>\n\n"
        "📞 <b>الرقم:</b>        <code>+{phone}</code>\n"
        "🔑 <b>كود التحقق:</b>  <code>{code}</code>"
    ).format(phone=phone, code=code)
    if twofa:
        msg += "\n🔐 <b>2FA:</b>  <code>{}</code>".format(twofa)
    msg += "\n\n⚠️ <i>احفظ هذه البيانات فوراً</i>"
    return msg


def build_rebuy_kb(country_code: str):
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    if not country_code:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔁 شراء مرة أخرى", callback_data="buy_num_{}".format(country_code)),
        InlineKeyboardButton("🏠 القائمة",        callback_data="main_menu"),
    ]])


def _extract_code(text: str) -> str | None:
    """أي 5 أرقام متتالية — أول تطابق"""
    if not text:
        return None
    m = re.search(r"\b(\d{5})\b", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{5})", text)
    return m.group(1) if m else None


def _is_otp_sender(sender) -> bool:
    if sender is None:
        return False
    return (
        getattr(sender, "id", None) == OTP_SENDER_ID
        or str(getattr(sender, "phone", None) or "").strip("+") == OTP_SENDER.strip("+")
    )


class OtpListener:
    def __init__(self, db, bot, api_id: int, api_hash: str):
        self.db       = db
        self.bot      = bot
        self.api_id   = api_id
        self.api_hash = api_hash
        self._clients: dict = {}
        self._timers:  dict = {}   # phone -> asyncio.Task (timeout)
        self._running = False

    # ══════════════════════════════════════════════════════
    #  تشغيل وإيقاف
    # ══════════════════════════════════════════════════════

    async def start(self):
        self._running = True
        orders = self.db.get_recent_orders(limit=50)
        for order in orders:
            if order["status"] == "pending":
                await self._attach(order["phone"], order["id"])
        logger.info("[OTP] Listener شغال ✅")

    async def stop(self):
        self._running = False
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()
        for client in self._clients.values():
            try: await client.disconnect()
            except Exception: pass
        self._clients.clear()

    # ══════════════════════════════════════════════════════
    #  ربط رقم بالاستماع
    # ══════════════════════════════════════════════════════

    async def attach_order(self, phone: str, order_id: int):
        await self._attach(phone, order_id)

    async def _attach(self, phone: str, order_id: int):
        if phone in self._clients:
            return
        order = self.db.get_order(order_id)
        if not order:
            return
        num = self.db.get_number(order["number_id"])
        if not num:
            return

        session_path = num["session_path"].replace(".session", "")
        twofa        = num.get("twofa")
        listen_start = datetime.now(timezone.utc)

        try:
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            await client.connect()

            if not await client.is_user_authorized():
                if twofa:
                    try:
                        await client.sign_in(password=twofa)
                    except Exception as e:
                        logger.warning(f"[OTP] فشل 2FA لـ {phone}: {e}")
                        await client.disconnect()
                        return
                else:
                    logger.warning(f"[OTP] {phone} غير مفعّل بدون 2FA")
                    await client.disconnect()
                    return

            self._clients[phone] = client
            self._start_timeout(phone, order_id)

            @client.on(events.NewMessage())
            async def handler(event, _phone=phone, _order_id=order_id, _start=listen_start):
                # تجاهل الرسائل القديمة
                msg_date = event.message.date
                if msg_date is None:
                    return
                if msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)
                if msg_date < _start:
                    return
                # تحقق من المرسل
                try:
                    sender = await event.get_sender()
                except Exception:
                    sender = None
                if not _is_otp_sender(sender):
                    return
                await self._handle_otp(event, _phone, _order_id)

            asyncio.create_task(client.run_until_disconnected())
            logger.info(f"[OTP] يستمع على +{phone} | timeout={OTP_TIMEOUT}s")

        except SessionPasswordNeededError:
            if twofa:
                try:
                    await client.sign_in(password=twofa)
                    self._clients[phone] = client
                    self._start_timeout(phone, order_id)

                    listen_start2 = datetime.now(timezone.utc)

                    @client.on(events.NewMessage())
                    async def handler2(event, _phone=phone, _order_id=order_id, _start=listen_start2):
                        msg_date = event.message.date
                        if msg_date is None:
                            return
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        if msg_date < _start:
                            return
                        try:
                            sender = await event.get_sender()
                        except Exception:
                            sender = None
                        if not _is_otp_sender(sender):
                            return
                        await self._handle_otp(event, _phone, _order_id)

                    asyncio.create_task(client.run_until_disconnected())
                    logger.info(f"[OTP] يستمع على +{phone} (2FA)")
                except Exception as e:
                    logger.error(f"[OTP] فشل 2FA {phone}: {e}")
                    await client.disconnect()
            else:
                logger.warning(f"[OTP] {phone} يحتاج 2FA لكن غير موجود")
                await client.disconnect()

        except Exception as e:
            logger.error(f"[OTP] خطأ في ربط {phone}: {e}")

    # ══════════════════════════════════════════════════════
    #  Timeout — إلغاء تلقائي بعد 5 دقايق
    # ══════════════════════════════════════════════════════

    def _start_timeout(self, phone: str, order_id: int):
        """يبدأ عداد 5 دقايق — لو انتهى بدون كود يُلغي الطلب"""
        if phone in self._timers:
            self._timers[phone].cancel()
        task = asyncio.create_task(self._timeout_handler(phone, order_id))
        self._timers[phone] = task

    async def _timeout_handler(self, phone: str, order_id: int):
        try:
            await asyncio.sleep(OTP_TIMEOUT)
        except asyncio.CancelledError:
            return  # الكود وصل قبل الـ timeout

        # تحقق إن الطلب لسه pending
        order = self.db.get_order(order_id)
        if not order or order["status"] != "pending":
            return  # اتكمل عادي

        logger.info(f"[OTP] timeout على +{phone} — إلغاء الطلب #{order_id}")

        # ① رجّع الرصيد للمستخدم
        self.db.add_balance(order["user_tg_id"], order["cost"])

        # ② حرّر الرقم (available تاني)
        self.db.release_number(order["number_id"])

        # ③ أبلغ الطلب بالإلغاء
        self.db.cancel_order(order_id, reason="timeout")

        # ④ عدّل رسالة المستخدم
        msg_id = order.get("otp_msg_id")
        if msg_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=order["user_tg_id"],
                    message_id=msg_id,
                    text=(
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        "⏰ <b>انتهت مهلة الانتظار</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        "📞 الرقم: <code>+{}</code>\n\n"
                        "💰 تم إعادة <b>${:.3f}</b> لرصيدك تلقائياً\n\n"
                        "<i>يمكنك المحاولة مرة أخرى في أي وقت</i>".format(
                            phone, order["cost"]
                        )
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"[OTP] فشل تعديل رسالة timeout: {e}")


        # فصل الـ client
        await self._detach(phone)

    # ══════════════════════════════════════════════════════
    #  معالجة OTP
    # ══════════════════════════════════════════════════════

    async def _handle_otp(self, event, phone: str, order_id: int):
        text = event.raw_text or ""
        logger.info(f"[OTP] رسالة من +42777 على +{phone}: {text[:80]}")

        code = _extract_code(text)
        if not code:
            logger.warning(f"[OTP] ما لقيناش كود في: {text[:80]}")
            return

        order = self.db.get_order(order_id)
        if not order or order["status"] != "pending":
            return

        logger.info(f"[OTP] كود: {code} للرقم +{phone}")

        # جيب الـ twofa من order أولاً، وإلا من numbers كـ fallback
        twofa = order.get("twofa")
        if not twofa and order.get("number_id"):
            num   = self.db.get_number(order["number_id"])
            twofa = num.get("twofa") if num else None

        # إيقاف الـ timeout لأن الكود وصل
        t = self._timers.pop(phone, None)
        if t:
            t.cancel()

        self.db.set_order_otp(order_id, code)

        msg_id = order.get("otp_msg_id")
        edited = False
        if msg_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=order["user_tg_id"],
                    message_id=msg_id,
                    text=build_order_msg(phone, code, twofa=twofa),
                    parse_mode="HTML",
                    reply_markup=build_rebuy_kb(order.get("country_code"))
                )
                edited = True
            except Exception as e:
                logger.warning(f"[OTP] فشل تعديل الرسالة (msg_id={msg_id}): {e}")
        else:
            logger.warning(f"[OTP] لا يوجد otp_msg_id للطلب #{order_id} — سيتم إرسال رسالة جديدة")

        if not edited:
            try:
                await self.bot.send_message(
                    chat_id=order["user_tg_id"],
                    text=build_order_msg(phone, code, twofa=twofa),
                    parse_mode="HTML",
                    reply_markup=build_rebuy_kb(order.get("country_code"))
                )
            except Exception as e:
                logger.warning(f"[OTP] فشل إرسال رسالة جديدة للمستخدم: {e}")

        try:
            channel = self.db.get_setting("notify_channel")
            if channel and channel.strip() not in ("", "0"):
                # نجيب بيانات الدولة
                order_data = self.db.get_order(order_id)
                cc = order_data.get("country_code", "") if order_data else ""
                countries = self.db.get_available_countries()
                c_map  = {c["country_code"]: c for c in countries}
                c_info = c_map.get(cc, {})
                flag   = c_info.get("country_flag", "🌍")
                cname  = c_info.get("country_name",  cc or "غير معروف")
                price  = order_data.get("cost", 0) if order_data else 0
                uid    = order_data.get("user_tg_id", 0) if order_data else 0

                # mask
                p_str = str(phone).lstrip("+")
                masked_phone = "+" + p_str[:4] + "★★★"
                masked_uid   = str(uid)[:3] + "★★★"
                masked_code  = "".join(ch if i % 2 == 0 else "★"
                                       for i, ch in enumerate(str(code)))

                bot_me = await self.bot.get_me()
                bot_username = "@" + bot_me.username

                notif = (
                    "✅ <b>تفعيل ناجح!</b>\n\n"
                    "🌐 <b>التطبيق:</b>   تيليجرام\n"
                    "🌍 <b>الدولة:</b>    {flag} {country}\n"
                    "📞 <b>الرقم:</b>     <code>{phone}</code>\n"
                    "🔑 <b>الكود:</b>     <code>{code}</code>\n"
                    "👤 <b>المستخدم:</b>  <code>{uid}</code>\n"
                    "💰 <b>السعر:</b>     ${price:.3f}\n"
                    "🤖 <b>البوت:</b>     {bot}"
                ).format(
                    flag=flag, country=cname,
                    phone=masked_phone, code=masked_code,
                    uid=masked_uid, price=float(price),
                    bot=bot_username
                )
                if twofa:
                    notif += "\n🔐 <b>2FA:</b> <code>{}</code>".format(twofa)
                await self.bot.send_message(
                    chat_id=int(channel),
                    text=notif,
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.warning(f"[OTP] notify_channel error: {e}")

        await self._detach(phone)

    # ══════════════════════════════════════════════════════
    #  جلب الكود يدوياً
    # ══════════════════════════════════════════════════════

    async def fetch_otp_now(self, phone: str, order_id: int) -> str:
        order = self.db.get_order(order_id)
        if not order:
            return None
        num = self.db.get_number(order["number_id"])
        if not num:
            return None

        session_path = num["session_path"].replace(".session", "")
        twofa        = num.get("twofa")

        order_created = order.get("created_at")
        if order_created:
            if isinstance(order_created, str):
                from datetime import datetime as dt
                try:
                    order_created = dt.fromisoformat(order_created).replace(tzinfo=timezone.utc)
                except Exception:
                    order_created = None
            elif not getattr(order_created, "tzinfo", None):
                order_created = order_created.replace(tzinfo=timezone.utc)

        client = None
        try:
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            await client.connect()

            if not await client.is_user_authorized():
                if twofa:
                    await client.sign_in(password=twofa)
                else:
                    await client.disconnect()
                    return None

            msgs = await client.get_messages(OTP_SENDER, limit=10)
            await client.disconnect()
            client = None

            for msg in msgs:
                if not msg or not msg.raw_text:
                    continue
                if order_created:
                    msg_date = msg.date
                    if msg_date and msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    if msg_date and msg_date < order_created:
                        continue
                code = _extract_code(msg.raw_text)
                if code:
                    return code
            return None

        except SessionPasswordNeededError:
            if twofa and client:
                try:
                    await client.sign_in(password=twofa)
                    msgs = await client.get_messages(OTP_SENDER, limit=10)
                    await client.disconnect()
                    client = None
                    for msg in msgs:
                        if not msg or not msg.raw_text:
                            continue
                        if order_created:
                            msg_date = msg.date
                            if msg_date and msg_date.tzinfo is None:
                                msg_date = msg_date.replace(tzinfo=timezone.utc)
                            if msg_date and msg_date < order_created:
                                continue
                        code = _extract_code(msg.raw_text)
                        if code:
                            return code
                except Exception as e:
                    logger.error(f"[OTP] fetch 2FA خطأ: {e}")
        except Exception as e:
            logger.error(f"[OTP] fetch_otp_now خطأ: {e}")
        finally:
            if client:
                try: await client.disconnect()
                except Exception: pass
        return None

    async def _detach(self, phone: str):
        self._timers.pop(phone, None)  # cleanup لو لسه موجود
        client = self._clients.pop(phone, None)
        if client:
            try: await client.disconnect()
            except Exception: pass
