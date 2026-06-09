"""
╔══════════════════════════════════════════════════════════════╗
║   💎 نظام دفع TON & TRX — ton_trx_pay.py                    ║
║                                                              ║
║  • يجلب سعر الصرف اللحظي من CoinGecko تلقائياً              ║
║  • يتحقق من المعاملة على blockchain مباشرة                   ║
║  • المستخدم يحوّل أي مبلغ والبوت يحسب الدولار               ║
║  • يدعم TON (The Open Network) و TRX (TRON)                  ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import time
import aiohttp

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Bot

logger = logging.getLogger(__name__)

API_TIMEOUT     = 20
SESSION_TIMEOUT = 600   # 10 دقائق
PRICE_CACHE_TTL = 120   # تحديث السعر كل دقيقتين

# ── Cache أسعار الصرف ───────────────────────────────────────
_price_cache: dict[str, tuple[float, float]] = {}  # coin → (price_usd, timestamp)

# ── جلسات الدفع المفتوحة ────────────────────────────────────
_TON_TRX_SESSIONS: dict[int, dict] = {}


# ══════════════════════════════════════════════════════════════
#  جلب سعر الصرف من CoinGecko
# ══════════════════════════════════════════════════════════════

COINGECKO_IDS = {
    "ton": "the-open-network",
    "trx": "tron",
}


async def get_live_price(coin: str) -> float:
    """
    يُعيد سعر العملة بالدولار.
    يستخدم cache لتجنب الطلبات الزائدة.
    coin: "ton" أو "trx"
    """
    coin = coin.lower()
    now  = time.time()

    cached = _price_cache.get(coin)
    if cached and (now - cached[1]) < PRICE_CACHE_TTL:
        return cached[0]

    cg_id = COINGECKO_IDS.get(coin, coin)
    url   = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={cg_id}&vs_currencies=usd"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                headers={"User-Agent": "SMM-Bot/1.0"},
            ) as resp:
                data = await resp.json()
        price = float(data[cg_id]["usd"])
        _price_cache[coin] = (price, now)
        logger.info(f"[PRICE] {coin.upper()} = ${price}")
        return price
    except Exception as e:
        logger.error(f"[PRICE] فشل جلب سعر {coin}: {e}")
        # رجوع للسعر القديم لو موجود
        if cached:
            logger.warning(f"[PRICE] استخدام سعر مخزن للـ {coin}: ${cached[0]}")
            return cached[0]
        return 0.0


# ══════════════════════════════════════════════════════════════
#  TON Blockchain Client
# ══════════════════════════════════════════════════════════════

TONAPI_BASE = "https://tonapi.io/v2"


class TONClient:
    """
    يتحقق من معاملة TON عبر TONAPI (مجاني بدون API key للاستخدام العادي).
    المستخدم يرسل رقم المعاملة (tx hash) أو BOC.
    """

    def __init__(self, wallet: str, min_confirms: int = 3):
        self.wallet       = wallet.strip()
        self.min_confirms = min_confirms

    async def verify(self, tx_hash: str) -> dict:
        """
        يتحقق من معاملة TON ويُعيد:
        {"success": True, "amount": <TON amount>, "network": "ton"}
        أو {"success": False, "error": "رسالة"}
        """
        tx_hash = tx_hash.strip()

        # TON tx hash يكون 64 hex
        if len(tx_hash) < 40:
            return {"success": False,
                    "error": "❌ Hash غير صحيح\nمثال: <code>3a9f2b...</code> (64 حرف)"}

        try:
            url = f"{TONAPI_BASE}/blockchain/transactions/{tx_hash}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                    headers={"Accept": "application/json"},
                ) as resp:
                    if resp.status == 404:
                        return {"success": False,
                                "error": "❌ المعاملة غير موجودة بعد\nانتظر دقيقة وحاول مجدداً"}
                    data = await resp.json()

            # فحص الوجهة
            out_msgs = data.get("out_msgs", [])
            in_msg   = data.get("in_msg", {})

            # نبحث عن تحويل لمحفظة الاستقبال
            amount_nano = 0

            # TON transfers قد تكون in_msg أو out_msgs
            dest = (in_msg.get("destination", {}) or {})
            dest_addr = dest.get("address", "") or dest.get("name", "")

            if self._addr_match(dest_addr):
                amount_nano = int(in_msg.get("value", 0))
            else:
                for msg in out_msgs:
                    d = (msg.get("destination", {}) or {})
                    d_addr = d.get("address", "") or d.get("name", "")
                    if self._addr_match(d_addr):
                        amount_nano += int(msg.get("value", 0))

            if amount_nano == 0:
                return {"success": False,
                        "error": (
                            f"❌ لم يتم العثور على تحويل لمحفظتك\n"
                            f"تأكد أن المحفظة الصحيحة هي:\n"
                            f"<code>{self.wallet}</code>"
                        )}

            # TON = nanotons / 1e9
            amount_ton = amount_nano / 1e9
            return {"success": True, "amount": round(amount_ton, 6), "network": "ton"}

        except Exception as e:
            logger.error(f"[TON] verify error: {e}")
            return {"success": False, "error": f"❌ خطأ في التحقق: {e}"}

    @staticmethod
    def _extract_account_id(addr: str) -> str:
        """
        يستخرج الـ 64-char hex account ID من أي صيغة لعنوان TON:
        - صيغة raw:           "0:abc123..."  → "abc123..."
        - صيغة user-friendly: "EQxxx" / "UQxxx" (base64url) → hex(bytes[2:34])
        """
        import base64 as _b64
        addr = addr.strip()
        if not addr:
            return ""
        # صيغة raw: "workchain:hexstring"
        if ":" in addr:
            return addr.split(":", 1)[1].lower()
        # صيغة user-friendly base64url (48 حرف)
        try:
            # نضيف padding لو ناقص
            padded = addr + "=" * ((4 - len(addr) % 4) % 4)
            decoded = _b64.urlsafe_b64decode(padded)
            # الهيكل: [flags(1)] [workchain(1)] [account_id(32)] [crc16(2)]
            if len(decoded) >= 34:
                return decoded[2:34].hex().lower()
        except Exception:
            pass
        return addr.lower()

    def _addr_match(self, addr: str) -> bool:
        """
        مطابقة عناوين TON بصرف النظر عن الصيغة:
        TONAPI يرجع raw (0:hex) لكن المحفظة مخزنة كـ user-friendly (EQ.../UQ...)
        نحوّل الاثنين لـ hex account ID ثم نقارن.
        """
        if not addr or not self.wallet:
            return False
        try:
            a_id = self._extract_account_id(addr)
            w_id = self._extract_account_id(self.wallet)
            if a_id and w_id:
                return a_id == w_id
        except Exception:
            pass
        # fallback: مقارنة نصية عادية
        a = addr.strip().lower()
        w = self.wallet.strip().lower()
        return a == w


# ══════════════════════════════════════════════════════════════
#  TRX Blockchain Client
# ══════════════════════════════════════════════════════════════

TRONSCAN_API = "https://apilist.tronscanapi.com/api"


class TRXClient:
    """
    يتحقق من معاملة TRX عبر TronScan API.
    المستخدم يرسل TXID.
    """

    def __init__(self, wallet: str, min_confirms: int = 10):
        self.wallet       = wallet.strip()
        self.min_confirms = min_confirms

    async def verify(self, txid: str) -> dict:
        txid = txid.strip()

        if len(txid) != 64:
            return {"success": False,
                    "error": "❌ TXID غير صحيح\nيجب أن يكون 64 حرفاً"}

        try:
            url = f"{TRONSCAN_API}/transaction-info?hash={txid}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                    headers={"User-Agent": "SMM-Bot/1.0"},
                ) as resp:
                    data = await resp.json()

            if not data or data.get("contractRet") is None:
                return {"success": False,
                        "error": "❌ المعاملة غير موجودة\nانتظر دقيقة وحاول مجدداً"}

            if data.get("contractRet") != "SUCCESS":
                return {"success": False,
                        "error": f"❌ المعاملة فاشلة: {data.get('contractRet')}"}

            # فحص الوجهة والمبلغ
            contracts = data.get("contractData", {})
            to_addr   = (contracts.get("to_address") or
                         contracts.get("toAddress", "")).strip()

            # TrxTransfer
            amount_sun = int(contracts.get("amount", 0))

            if not self._addr_match(to_addr):
                return {"success": False,
                        "error": (
                            f"❌ المعاملة موجهة لعنوان مختلف\n"
                            f"العنوان الصحيح:\n<code>{self.wallet}</code>"
                        )}

            if amount_sun == 0:
                return {"success": False,
                        "error": "❌ المبلغ المُرسل صفر"}

            amount_trx = amount_sun / 1_000_000   # sun → TRX
            return {"success": True, "amount": round(amount_trx, 6), "network": "trx"}

        except Exception as e:
            logger.error(f"[TRX] verify error: {e}")
            return {"success": False, "error": f"❌ خطأ في التحقق: {e}"}

    def _addr_match(self, addr: str) -> bool:
        if not addr or not self.wallet:
            return False
        return addr.strip().lower() == self.wallet.strip().lower()


# ══════════════════════════════════════════════════════════════
#  TonTrxPayHandler — المُدير الرئيسي
# ══════════════════════════════════════════════════════════════

class TonTrxPayHandler:

    LABELS = {
        "ton": "💎 TON (The Open Network)",
        "trx": "🔴 TRX (TRON)",
    }

    def __init__(self, db, bot: Bot):
        self.db  = db
        self.bot = bot

    # ── حالة الجلسة ──────────────────────────────────────────

    def in_session(self, uid: int) -> bool:
        s = _TON_TRX_SESSIONS.get(uid)
        if not s:
            return False
        if time.time() - s["started"] > SESSION_TIMEOUT:
            _TON_TRX_SESSIONS.pop(uid, None)
            return False
        return True

    def _start_session(self, uid: int, network: str):
        _TON_TRX_SESSIONS[uid] = {
            "network": network,
            "started": time.time(),
        }

    def _clear_session(self, uid: int):
        _TON_TRX_SESSIONS.pop(uid, None)

    def _get_session(self, uid: int) -> dict | None:
        s = _TON_TRX_SESSIONS.get(uid)
        if not s:
            return None
        if time.time() - s["started"] > SESSION_TIMEOUT:
            _TON_TRX_SESSIONS.pop(uid, None)
            return None
        return s

    # ── تفعيل ────────────────────────────────────────────────

    def is_ton_enabled(self) -> bool:
        return (self.db.get_setting("pay_ton", "0") == "1" and
                bool(self.db.get_setting("ton_address", "").strip()))

    def is_trx_enabled(self) -> bool:
        return (self.db.get_setting("pay_trx", "0") == "1" and
                bool(self.db.get_setting("trx_address", "").strip()))

    # ── صفحة الدفع ───────────────────────────────────────────

    async def show_pay_page(self, chat_id: int, network: str):
        if network == "ton":
            if not self.is_ton_enabled():
                await self.bot.send_message(chat_id=chat_id, text="⛔ TON متوقف حالياً.")
                return
            address   = self.db.get_setting("ton_address", "")
            min_coin  = float(self.db.get_setting("ton_min_amount", "1"))
            net_label = "TON (The Open Network)"
            coin_sym  = "TON"
            emoji     = "💎"

        elif network == "trx":
            if not self.is_trx_enabled():
                await self.bot.send_message(chat_id=chat_id, text="⛔ TRX متوقف حالياً.")
                return
            address   = self.db.get_setting("trx_address", "")
            min_coin  = float(self.db.get_setting("trx_min_amount", "10"))
            net_label = "TRX (TRON)"
            coin_sym  = "TRX"
            emoji     = "🔴"
        else:
            return

        # جلب السعر الحالي
        live_price = await get_live_price(network)
        price_str  = f"${live_price:.4f}" if live_price else "جارٍ التحميل..."

        text = (
            f"{emoji} <b>شحن الرصيد عبر {net_label}</b>\n\n"
            f"أرسل <b>{coin_sym}</b> إلى العنوان:\n"
            f"<code>{address}</code>\n\n"
            f"📊 سعر الصرف الحالي: <b>1 {coin_sym} = {price_str}</b>\n"
            f"📉 الحد الأدنى: <b>{min_coin} {coin_sym}</b>\n\n"
            f"<b>مثال:</b> إرسال 10 {coin_sym} "
            f"{'≈ $' + str(round(10 * live_price, 2)) if live_price else ''}\n\n"
            f"✅ بعد التحويل اضغط <b>«أرسلت المبلغ»</b>\n"
            f"ثم أرسل رقم المعاملة (Tx Hash / TXID)"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ أرسلت المبلغ",
                                  callback_data=f"tontrx_sent_{network}")],
            [InlineKeyboardButton("📋 نسخ العنوان",
                                  callback_data=f"tontrx_copy_{network}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="charge_back")],
        ])
        await self.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML"
        )


    async def handle_copy(self, chat_id: int, network: str):
        addr_key = "ton_address" if network == "ton" else "trx_address"
        sym      = "TON" if network == "ton" else "TRX"
        address  = self.db.get_setting(addr_key, "")
        await self.bot.send_message(
            chat_id=chat_id,
            text=(f"📋 <b>عنوان {sym}:</b>\n\n"
                  f"<code>{address}</code>\n\n"
                  f"<i>اضغط على العنوان لنسخه</i>"),
            parse_mode="HTML",
        )

    # ── طلب Tx Hash ──────────────────────────────────────────

    async def prompt_txid(self, chat_id: int, user_id: int, network: str):
        self._start_session(user_id, network)
        sym = "TON" if network == "ton" else "TRX"

        from utils.keyboards import cancel_kb
        await self.bot.send_message(
            chat_id=chat_id,
            text=(
                f"📨 <b>أرسل Tx Hash (رقم المعاملة)</b>\n\n"
                f"• افتح محفظتك وابحث عن المعاملة\n"
                f"• انسخ الـ Transaction Hash / ID\n"
                f"• أرسله هنا\n\n"
                f"⏳ المهلة: 10 دقائق"
            ),
            reply_markup=cancel_kb("charge_back"),
            parse_mode="HTML",
        )

    # ── نسخ العنوان ──────────────────────────────────────────

    async def copy_address(self, chat_id: int, network: str):
        addr_key = "ton_address" if network == "ton" else "trx_address"
        address  = self.db.get_setting(addr_key, "")
        sym      = "TON" if network == "ton" else "TRX"
        if address:
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"📋 <b>عنوان {sym}:</b>\n<code>{address}</code>",
                parse_mode="HTML",
            )

    # ── معالجة Tx Hash ───────────────────────────────────────

    async def handle_txid_message(self, message) -> bool:
        uid   = message.from_user.id
        state = self._get_session(uid)
        if not state:
            return False

        network = state["network"]
        self._clear_session(uid)

        txid = (message.text or "").strip()
        cid  = message.chat.id

        check_msg = await self.bot.send_message(
            chat_id=cid,
            text="🔍 <b>جارٍ التحقق من المعاملة...</b>\n<i>قد يستغرق 15–30 ثانية</i>",
            parse_mode="HTML",
        )

        # ── جلب العميل المناسب ──
        client = self._get_client(network)
        if not client:
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text="❌ <b>النظام غير مضبوط!</b>\nتواصل مع الأدمن.",
                parse_mode="HTML",
            )
            return True

        # ── التحقق من المعاملة ──
        result = await client.verify(txid)
        if not result.get("success"):
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text=result.get("error", "❌ خطأ غير معروف"),
                parse_mode="HTML",
            )
            return True

        coin_amount = result["amount"]
        sym         = "TON" if network == "ton" else "TRX"

        # ── الحد الأدنى ──
        min_key  = "ton_min_amount" if network == "ton" else "trx_min_amount"
        min_coin = float(self.db.get_setting(min_key, "1" if network == "ton" else "10"))

        if coin_amount < min_coin:
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text=(
                    f"⚠️ <b>المبلغ أقل من الحد الأدنى!</b>\n\n"
                    f"المُرسَل: <b>{coin_amount} {sym}</b>\n"
                    f"الأدنى:  <b>{min_coin} {sym}</b>"
                ),
                parse_mode="HTML",
            )
            return True

        # ── جلب سعر الصرف الحالي ──
        live_price = await get_live_price(network)
        if live_price <= 0:
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text=(
                    "⚠️ <b>تعذّر جلب سعر الصرف حالياً!</b>\n"
                    "حاول مرة أخرى بعد دقيقة."
                ),
                parse_mode="HTML",
            )
            return True

        # ── حساب الدولار ──
        usd_value = round(coin_amount * live_price, 4)

        # ── منع تكرار الـ TXID ──
        already = self.db.get_setting(f"tontrx_used_{txid[:40]}", "")
        if already:
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text="⛔ <b>هذا الـ TXID مستخدم مسبقاً!</b>\nكل معاملة تُقبل مرة واحدة فقط.",
                parse_mode="HTML",
            )
            return True

        # ── حفظ في DB وإضافة الرصيد ──
        self.db.set_setting(f"tontrx_used_{txid[:40]}", f"{uid}:{usd_value}")
        self.db.add_balance(uid, usd_value)
        new_bal = self.db.get_balance(uid)
        label   = self.LABELS.get(network, network.upper())

        await self.bot.edit_message_text(
            chat_id=cid, message_id=check_msg.message_id,
            text=(
                f"✅ <b>تم شحن رصيدك بنجاح!</b>\n\n"
                f"{label}\n"
                f"🪙 المُرسَل:        <b>{coin_amount} {sym}</b>\n"
                f"📊 سعر الصرف:      <b>1 {sym} = ${live_price:.4f}</b>\n"
                f"💰 رصيد مضاف:      <code>${usd_value:.4f}</code>\n"
                f"💳 رصيدك الحالي:   <code>${new_bal:.4f}</code>"
            ),
            parse_mode="HTML",
        )

        # ── إشعار الأدمن / قناة ──
        from config import ADMIN_ID
        notif_target = self.db.get_setting("checker_channel", "") or ADMIN_ID
        try:
            await self.bot.send_message(
                chat_id=notif_target,
                text=(
                    f"{label}\n\n"
                    f"👤 المستخدم: <code>{uid}</code>\n"
                    f"🪙 المُرسَل: <b>{coin_amount} {sym}</b>\n"
                    f"📊 السعر: <b>${live_price:.4f}</b>\n"
                    f"💰 مضاف: <code>${usd_value:.4f}</code>\n"
                    f"🔗 TXID: <code>{txid[:40]}</code>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

        logger.info(
            f"[TON/TRX] ✅ uid={uid} net={network} "
            f"amount={coin_amount} price=${live_price} credit=${usd_value}"
        )
        return True

    def _get_client(self, network: str):
        if network == "ton":
            addr = self.db.get_setting("ton_address", "").strip()
            conf = int(self.db.get_setting("ton_confirmations", "3"))
            return TONClient(addr, conf) if addr else None
        elif network == "trx":
            addr = self.db.get_setting("trx_address", "").strip()
            conf = int(self.db.get_setting("trx_confirmations", "10"))
            return TRXClient(addr, conf) if addr else None
        return None
