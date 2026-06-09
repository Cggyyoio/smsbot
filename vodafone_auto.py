"""
╔══════════════════════════════════════════════════════════════╗
║   📱 فودافون كاش التلقائي — vodafone_auto.py                 ║
║                                                              ║
║  • يستخدم مكتبة autocash للتحقق الفوري من التحويلات         ║
║  • المستخدم يدخل المبلغ بالجنيه + رقم هاتفه                ║
║  • البوت يتحقق تلقائياً ويحوّل لدولار بسعر autocash        ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import time

from telegram import Bot

logger = logging.getLogger(__name__)

SESSION_TIMEOUT = 300   # 5 دقائق
RATE_CACHE_TTL  = 300   # 5 دقائق

# ── جلسات الدفع المفتوحة ───────────────────────────────────
_VOD_AUTO_SESSIONS: dict[int, dict] = {}

# ── قفل لمنع معالجة طلبين من نفس المستخدم في نفس الوقت ───
_VOD_PENDING: set[int] = set()


class VodafoneAutoHandler:
    """
    المُدير الرئيسي لفودافون كاش التلقائي.

    التدفق:
      1. show_pay_page()      → يعرض الرقم ويطلب المبلغ بالجنيه
      2. handle_message()     → step=waiting_amount  → يحفظ المبلغ ويطلب الرقم
      3. handle_message()     → step=waiting_phone   → يتحقق عبر autocash ويشحن
    """

    def __init__(self, db, bot: Bot):
        self.db  = db
        self.bot = bot

    # ── تحقق من التفعيل ──────────────────────────────────────

    def is_enabled(self) -> bool:
        return (
            self.db.get_setting("pay_vodafone_auto", "0") == "1"
            and bool(self.db.get_setting("autocash_user_id",  "").strip())
            and bool(self.db.get_setting("autocash_panel_id", "").strip())
            and bool(self.db.get_setting("vodafone_number",   "").strip())
        )

    # ── إدارة الجلسات ────────────────────────────────────────

    def in_session(self, uid: int) -> bool:
        s = _VOD_AUTO_SESSIONS.get(uid)
        if not s:
            return False
        if time.time() - s["started"] > SESSION_TIMEOUT:
            _VOD_AUTO_SESSIONS.pop(uid, None)
            return False
        return True

    def _start_session(self, uid: int, step: str, **kwargs):
        _VOD_AUTO_SESSIONS[uid] = {
            "step": step, "started": time.time(), **kwargs
        }

    def _get_session(self, uid: int) -> dict | None:
        s = _VOD_AUTO_SESSIONS.get(uid)
        if not s:
            return None
        if time.time() - s["started"] > SESSION_TIMEOUT:
            _VOD_AUTO_SESSIONS.pop(uid, None)
            return None
        return s

    def _clear_session(self, uid: int):
        _VOD_AUTO_SESSIONS.pop(uid, None)

    # ── صفحة الدفع ───────────────────────────────────────────

    async def show_pay_page(self, chat_id: int, user_id: int):
        """عرض رقم فودافون والتعليمات وطلب المبلغ بالجنيه."""
        vod_number = self.db.get_setting("vodafone_number", "")
        min_egp    = float(self.db.get_setting("vod_auto_min_egp", "50"))
        rate_egp   = await self._get_rate()

        rate_line  = (
            f"💱 سعر الصرف: <b>{rate_egp:.2f} جنيه = $1</b>\n"
            if rate_egp > 0 else ""
        )

        self._start_session(user_id, "waiting_amount")

        from utils.keyboards import cancel_kb
        await self.bot.send_message(
            chat_id=chat_id,
            text=(
                f"📱 <b>شحن فودافون كاش (تلقائي)</b>\n\n"
                f"📞 حوّل على الرقم:\n"
                f"<code>{vod_number}</code>\n\n"
                f"{rate_line}"
                f"📉 الحد الأدنى: <b>{min_egp:.0f} جنيه</b>\n\n"
                f"✉️ بعد التحويل أرسل <b>المبلغ بالجنيه</b>:"
            ),
            reply_markup=cancel_kb("charge_back"),
            parse_mode="HTML",
        )

    # ── معالجة رسائل المستخدم ────────────────────────────────

    async def handle_message(self, message) -> bool:
        uid  = message.from_user.id
        sess = self._get_session(uid)
        if not sess:
            return False

        step = sess["step"]
        cid  = message.chat.id
        text = (message.text or "").strip()

        from utils.keyboards import cancel_kb, back_to_main_kb

        # ════ الخطوة 1: المبلغ بالجنيه ════════════════════════
        if step == "waiting_amount":
            if not text:
                return False
            try:
                amount_egp = float(text.replace(",", "."))
                assert amount_egp > 0
            except Exception:
                await message.reply_text(
                    "❌ أرسل رقماً صحيحاً، مثال: <code>100</code>",
                    reply_markup=cancel_kb("charge_back"),
                    parse_mode="HTML",
                )
                return True

            min_egp = float(self.db.get_setting("vod_auto_min_egp", "50"))
            if amount_egp < min_egp:
                await message.reply_text(
                    f"❌ الحد الأدنى للشحن: <b>{min_egp:.0f} جنيه</b>",
                    reply_markup=cancel_kb("charge_back"),
                    parse_mode="HTML",
                )
                return True

            self._start_session(uid, "waiting_phone", amount_egp=amount_egp)
            await message.reply_text(
                f"✅ المبلغ: <b>{amount_egp:.0f} جنيه</b>\n\n"
                f"📞 أرسل <b>رقم هاتفك</b> المحوّل منه:\n"
                f"مثال: <code>01012345678</code>",
                reply_markup=cancel_kb("charge_back"),
                parse_mode="HTML",
            )
            return True

        # ════ الخطوة 2: رقم الهاتف والتحقق ════════════════════
        if step == "waiting_phone":
            if not text:
                return False

            # تنظيف الرقم
            phone = (
                text.strip()
                .replace("+20", "0")
                .replace("+2",  "0")
                .replace("-",   "")
                .replace(" ",   "")
            )
            if len(phone) < 10 or not phone.isdigit():
                await message.reply_text(
                    "❌ أرسل رقم هاتف صحيح، مثال: <code>01012345678</code>",
                    reply_markup=cancel_kb("charge_back"),
                    parse_mode="HTML",
                )
                return True

            amount_egp = sess.get("amount_egp", 0)
            self._clear_session(uid)

            # ── منع Race Condition: مستخدم يضغط مرتين بسرعة ──
            if uid in _VOD_PENDING:
                await message.reply_text("⏳ طلبك قيد المعالجة، انتظر لحظة...")
                return True
            _VOD_PENDING.add(uid)

            # رسالة الانتظار
            wait_msg = await message.reply_text(
                "🔍 <b>جارٍ التحقق من التحويل...</b>\n"
                "<i>قد يستغرق 10–20 ثانية</i>",
                parse_mode="HTML",
            )

            try:
                # ── التحقق عبر autocash (مع extra لحجز العملية) ──
                result = await self._verify_payment(phone, amount_egp, uid)

                # ⚠️ autocash يرجع status كـ string 'fail' أو boolean True
                # لذلك لازم نتحقق إن status == True بالضبط وليس أي truthy value
                status = result.get("status")
                success = (status is True) or (str(status).lower() in ("true", "1", "success"))

                if not success:
                    err_msg = result.get("message", "")
                    await self.bot.edit_message_text(
                        chat_id=cid,
                        message_id=wait_msg.message_id,
                        text=(
                            f"❌ <b>لم يتم التحقق من التحويل!</b>\n\n"
                            f"تأكد من:\n"
                            f"• المبلغ صحيح: <b>{amount_egp:.0f} جنيه</b>\n"
                            f"• رقم هاتفك صحيح: <code>{phone}</code>\n"
                            f"• التحويل اكتمل (مش معلق)\n\n"
                            + (f"💡 {err_msg}" if err_msg else "")
                        ),
                        parse_mode="HTML",
                    )
                    return True

                # ── طبقة حماية ثانية: التحقق من الـ key في DB ──
                # autocash يمنع التكرار عبر extra، لكن نحفظ key كضمان إضافي
                txkey = str(result.get("key", "")).strip()
                if txkey:
                    already = self.db.get_setting(f"vod_txkey_{txkey}", "")
                    if already:
                        await self.bot.edit_message_text(
                            chat_id=cid, message_id=wait_msg.message_id,
                            text=(
                                "⛔ <b>هذا التحويل مستخدم مسبقاً!</b>\n"
                                "كل تحويل يُقبل مرة واحدة فقط."
                            ),
                            parse_mode="HTML",
                        )
                        return True
                    # احجز الـ key فوراً قبل أي عملية
                    self.db.set_setting(f"vod_txkey_{txkey}", str(uid))

                # ── احسب الرصيد بالدولار ──
                rate_egp = await self._get_rate()
                if rate_egp <= 0:
                    if txkey:
                        self.db.set_setting(f"vod_txkey_{txkey}", "")
                    await self.bot.edit_message_text(
                        chat_id=cid, message_id=wait_msg.message_id,
                        text=(
                            "⚠️ <b>تعذّر جلب سعر الصرف!</b>\n"
                            "تواصل مع الأدمن لإضافة رصيدك يدوياً."
                        ),
                        parse_mode="HTML",
                    )
                    return True

                usd_credit = round(amount_egp / rate_egp, 4)

                # ── إضافة الرصيد ──
                self.db.add_balance(uid, usd_credit)
                new_bal = self.db.get_balance(uid)

                await self.bot.edit_message_text(
                    chat_id=cid, message_id=wait_msg.message_id,
                    text=(
                        f"✅ <b>تم شحن رصيدك بنجاح!</b>\n\n"
                        f"📱 فودافون كاش\n"
                        f"📞 رقمك: <code>{phone}</code>\n"
                        f"💵 مبلغ التحويل: <b>{amount_egp:.0f} جنيه</b>\n"
                        f"💱 سعر الصرف: <b>{rate_egp:.2f} جنيه = $1</b>\n"
                        f"💰 رصيد مضاف: <code>${usd_credit:.4f}</code>\n"
                        f"💳 رصيدك الحالي: <code>${new_bal:.4f}</code>"
                    ),
                    reply_markup=back_to_main_kb(),
                    parse_mode="HTML",
                )

                # ── إشعار القناة/الأدمن ──
                from config import ADMIN_ID
                notif = self.db.get_setting("checker_channel", "") or str(ADMIN_ID)
                try:
                    await self.bot.send_message(
                        chat_id=notif,
                        text=(
                            f"📱 <b>فودافون كاش تلقائي ✅</b>\n\n"
                            f"👤 المستخدم: <code>{uid}</code>\n"
                            f"📞 رقم: <code>{phone}</code>\n"
                            f"💵 المبلغ: <b>{amount_egp:.0f} جنيه</b>\n"
                            f"💰 مضاف: <code>${usd_credit:.4f}</code>\n"
                            f"🔑 المرجع: <code>{txkey or 'N/A'}</code>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

                logger.info(
                    f"[VOD AUTO] ✅ uid={uid} phone={phone} "
                    f"egp={amount_egp} rate={rate_egp} usd=${usd_credit} key={txkey}"
                )

            finally:
                # دايماً نفك القفل بعد الانتهاء
                _VOD_PENDING.discard(uid)

            return True

        return False

    # ── autocash: التحقق (sync في executor) ─────────────────

    async def _verify_payment(self, phone: str, amount_egp: float, uid: int) -> dict:
        """
        يستدعي autocash.check_payment() مع extra=uid لحجز العملية.

        ⚠️ الـ extra هو المفتاح الجوهري لمنع التكرار:
        - autocash يبحث عن تحويل بنفس الرقم والمبلغ
        - يضع extra على العملية ويضع taken=true
        - أي طلب لاحق لنفس العملية يُرفض من autocash تلقائياً
        """
        user_id_cfg  = self.db.get_setting("autocash_user_id",  "")
        panel_id_cfg = self.db.get_setting("autocash_panel_id", "")
        extra        = f"uid{uid}"   # معرف فريد لربط العملية بالمستخدم

        def _sync():
            from autocash import AutoCash
            ac = AutoCash(user_id_cfg, panel_id_cfg)
            result = ac.check_payment(phone=phone, amount=int(amount_egp), extra=extra)
            logger.warning(f"[VODAFONE API RESPONSE] {result}")
            return result

        try:
            loop   = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _sync)
            logger.info(f"[VOD AUTO] check_payment result: {result}")
            return result
        except Exception as e:
            logger.error(f"[VOD AUTO] check_payment error: {e}")
            return {"status": False, "message": str(e)}

    # ── autocash: سعر الصرف مع cache ────────────────────────

    async def _get_rate(self) -> float:
        """
        يجلب سعر الصرف (جنيه/$) من autocash.get_info()
        مع cache لمدة 5 دقائق لتقليل الطلبات.
        """
        cached    = self.db.get_setting("vod_auto_rate_cache", "")
        cache_ts  = float(self.db.get_setting("vod_auto_rate_ts", "0"))
        if cached and (time.time() - cache_ts) < RATE_CACHE_TTL:
            return float(cached)

        user_id_cfg  = self.db.get_setting("autocash_user_id",  "")
        panel_id_cfg = self.db.get_setting("autocash_panel_id", "")

        if not user_id_cfg or not panel_id_cfg:
            # fallback للسعر اليدوي
            manual = self.db.get_setting("vod_auto_rate_manual", "0")
            return float(manual) if manual else 0.0

        def _sync():
            from autocash import AutoCash
            ac = AutoCash(user_id_cfg, panel_id_cfg)
            return ac.get_info()

        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, _sync)
            rate = float(info.get("rate", 0))
            if rate > 0:
                self.db.set_setting("vod_auto_rate_cache", str(rate))
                self.db.set_setting("vod_auto_rate_ts",    str(time.time()))
            return rate
        except Exception as e:
            logger.error(f"[VOD AUTO] get_info error: {e}")
            # إرجاع السعر المخزن أو اليدوي
            if cached:
                return float(cached)
            manual = self.db.get_setting("vod_auto_rate_manual", "0")
            return float(manual) if manual else 0.0
