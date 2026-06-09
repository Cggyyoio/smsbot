"""
╔══════════════════════════════════════════════════════════╗
║   نظام الدفع — crypto_pay.py  (مُعدَّل لـ PTB v20)      ║
║   BEP20 + TRC20 | منع مضاعفة الرصيد عبر TXID           ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import time

import aiohttp
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Bot

logger = logging.getLogger(__name__)

API_TIMEOUT     = 20
SESSION_TIMEOUT = 600   # 10 دقائق

# BEP20
BSC_RPC_NODES = [
    "https://rpc.ankr.com/bsc",
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.binance.org/",
]
USDT_BEP20     = "0x55d398326f99059ff775485246999027b3197955"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# TRC20
TRONGRID_API   = "https://api.trongrid.io"
USDT_TRC20     = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# جلسات انتظار TXID (uid → session_data)
_SESSIONS: dict[int, dict] = {}


def _session_start(uid: int, network: str):
    _SESSIONS[uid] = {
        "step":    "waiting_txid",
        "network": network,
        "started": time.time(),
        "task":    None,
    }


def _session_get(uid: int):
    s = _SESSIONS.get(uid)
    if not s:
        return None
    if time.time() - s["started"] > SESSION_TIMEOUT:
        _session_clear(uid)
        return None
    return s


def _session_clear(uid: int):
    s = _SESSIONS.pop(uid, None)
    if s and s.get("task"):
        s["task"].cancel()


# ══════════════════════════════════════════════════════════
#  BEP20 Client
# ══════════════════════════════════════════════════════════

class BEP20Client:
    def __init__(self, wallet: str, min_confirms: int = 3):
        self.wallet       = wallet.strip().lower()
        self.min_confirms = min_confirms

    async def _rpc(self, method: str, params: list) -> dict:
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        for node in BSC_RPC_NODES:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        node, json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                    ) as r:
                        data = await r.json(content_type=None)
                if "result" in data:
                    return data
            except Exception as e:
                logger.warning(f"[BEP20] {node} failed: {e}")
        return {"result": None}

    async def verify(self, txid: str) -> dict:
        txid = txid.strip().lower()
        if not txid.startswith("0x") or len(txid) != 66:
            return {"success": False, "error": "❌ TXID خاطئ\nيجب أن يبدأ بـ 0x ويكون 66 حرفاً"}

        receipt_data = await self._rpc("eth_getTransactionReceipt", [txid])
        result = receipt_data.get("result")

        if result is None or not isinstance(result, dict):
            return {"success": False, "error": "❌ TXID غير موجود على الشبكة\nانتظر دقيقة أو تأكد من النسخ"}

        if result.get("status") != "0x1":
            return {"success": False, "error": "❌ المعاملة فاشلة على الشبكة"}

        block_hex = result.get("blockNumber", "0x0") or "0x0"
        tx_block  = int(block_hex, 16) if block_hex != "0x0" else 0

        latest_data  = await self._rpc("eth_blockNumber", [])
        try:
            latest_block = int(latest_data.get("result", "0x0"), 16)
        except Exception:
            latest_block = tx_block

        confirms = max(0, latest_block - tx_block)
        if confirms < self.min_confirms:
            return {"success": False,
                    "error": f"⏳ التأكيدات غير كافية ({confirms}/{self.min_confirms})\nانتظر دقيقة وأعد المحاولة"}

        logs = result.get("logs", [])
        usdt_logs = [
            lg for lg in logs
            if lg.get("address", "").lower() == USDT_BEP20
            and len(lg.get("topics", [])) >= 3
            and lg["topics"][0].lower() == TRANSFER_TOPIC
        ]

        if not usdt_logs:
            return {"success": False, "error": "❌ لا يوجد تحويل USDT BEP20 في هذه المعاملة"}

        lg     = usdt_logs[0]
        to_raw = lg["topics"][2]
        to_addr = "0x" + to_raw[-40:]

        if to_addr.lower() != self.wallet:
            return {"success": False, "error": "❌ المعاملة لم تُرسَل إلى العنوان الصحيح"}

        try:
            amount = int(lg.get("data", "0x0"), 16) / (10 ** 18)
        except Exception:
            return {"success": False, "error": "❌ تعذّر قراءة المبلغ"}

        if amount <= 0:
            return {"success": False, "error": "❌ مبلغ المعاملة صفر"}

        return {"success": True, "amount": round(amount, 6),
                "confirms": confirms, "network": "BEP20"}


# ══════════════════════════════════════════════════════════
#  TRC20 Client
# ══════════════════════════════════════════════════════════

class TRC20Client:
    def __init__(self, api_key: str, wallet: str, min_confirms: int = 19):
        self.api_key      = api_key.strip()
        self.wallet       = wallet.strip()
        self.min_confirms = min_confirms

    def _headers(self) -> dict:
        return {
            "Content-Type":     "application/json",
            "TRON-PRO-API-KEY": self.api_key,
        }

    async def _post(self, endpoint: str, body: dict) -> dict:
        url = f"{TRONGRID_API}{endpoint}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    url, json=body, headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                ) as r:
                    return await r.json(content_type=None)
        except Exception as e:
            logger.error(f"[TRC20] {endpoint}: {e}")
            return {}

    async def verify(self, txid: str) -> dict:
        txid = txid.strip()
        if txid.startswith(("0x", "0X")):
            txid = txid[2:]
        if not txid:
            return {"success": False, "error": "❌ TXID فارغ"}

        tx_data = await self._post("/wallet/gettransactionbyid",
                                   {"value": txid, "visible": True})
        if not tx_data or "txID" not in tx_data:
            return {"success": False, "error": "❌ TXID غير موجود\nتأكد من النسخ أو انتظر دقيقة"}

        ret_list     = tx_data.get("ret", [{}])
        contract_ret = ret_list[0].get("contractRet", "") if ret_list else ""
        if contract_ret != "SUCCESS":
            return {"success": False, "error": f"❌ المعاملة فاشلة ({contract_ret})"}

        info_data = await self._post("/wallet/gettransactioninfobyid",
                                     {"value": txid, "visible": True})
        if not info_data or "id" not in info_data:
            return {"success": False, "error": "❌ تعذّر جلب تفاصيل المعاملة"}

        if info_data.get("contract_address", "") != USDT_TRC20:
            return {"success": False, "error": "❌ هذه ليست معاملة USDT TRC20"}

        block_number = info_data.get("blockNumber", 0)
        confirms     = await self._get_confirmations(block_number)
        if confirms < self.min_confirms:
            return {"success": False,
                    "error": f"⏳ التأكيدات غير كافية ({confirms}/{self.min_confirms})"}

        logs = info_data.get("log", [])
        usdt_log = None
        for lg in logs:
            topics = lg.get("topics", [])
            if (len(topics) >= 3 and
                    topics[0].lower() ==
                    "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"):
                usdt_log = lg
                break

        if not usdt_log:
            return {"success": False, "error": "❌ لا يوجد تحويل USDT في هذه المعاملة"}

        to_hex  = "41" + usdt_log["topics"][2][-40:]
        to_b58  = self._hex_to_base58(to_hex)
        if to_b58 != self.wallet:
            return {"success": False, "error": "❌ المعاملة لم تُرسَل إلى العنوان الصحيح"}

        try:
            amount = int(usdt_log.get("data", "0"), 16) / (10 ** 6)
        except Exception:
            return {"success": False, "error": "❌ تعذّر قراءة المبلغ"}

        if amount <= 0:
            return {"success": False, "error": "❌ مبلغ المعاملة صفر"}

        return {"success": True, "amount": round(amount, 6),
                "confirms": confirms, "network": "TRC20"}

    async def _get_confirmations(self, block_number: int) -> int:
        if not block_number:
            return 0
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    "https://api.trongrid.io/wallet/getnowblock",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                ) as r:
                    data = await r.json()
            latest = (data.get("block_header", {})
                      .get("raw_data", {}).get("number", block_number))
            return max(0, latest - block_number)
        except Exception:
            return 0

    @staticmethod
    def _hex_to_base58(hex_str: str) -> str:
        import hashlib
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        try:
            payload  = bytes.fromhex(hex_str)
            checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
            full     = payload + checksum
            n        = int.from_bytes(full, "big")
            result   = ""
            while n:
                result = alphabet[n % 58] + result
                n //= 58
            for byte in full:
                if byte == 0:
                    result = "1" + result
                else:
                    break
            return result
        except Exception:
            return ""


# ══════════════════════════════════════════════════════════
#  CryptoPayHandler (يعمل مع PTB v20)
# ══════════════════════════════════════════════════════════

class CryptoPayHandler:
    LABELS = {
        "bep20": "💎 USDT BEP20 (BSC)",
        "trc20": "🟣 USDT TRC20 (TRON)",
    }

    def __init__(self, db, bot: Bot):
        self.db  = db
        self.bot = bot

    # ── نشاط جلسة المستخدم ──────────────────────────────

    def in_session(self, uid: int) -> bool:
        return _session_get(uid) is not None

    # ── صفحة عرض الدفع ──────────────────────────────────

    async def show_pay_page(self, chat_id: int, network: str):
        if network == "bep20":
            if not self.is_bep20_enabled():
                await self.bot.send_message(chat_id=chat_id, text="⛔ BEP20 متوقف حالياً.")
                return
            address   = self.db.get_setting("bep20_address", "")
            min_u     = float(self.db.get_setting("bep20_min_usdt", "1.00"))
            rate      = float(self.db.get_setting("bep20_usdt_rate", "1.00"))
            net_label = "BEP20 (BSC)"
        elif network == "trc20":
            if not self.is_trc20_enabled():
                await self.bot.send_message(chat_id=chat_id, text="⛔ TRC20 متوقف حالياً.")
                return
            address   = self.db.get_setting("trc20_address", "")
            min_u     = float(self.db.get_setting("trc20_min_usdt", "1.00"))
            rate      = float(self.db.get_setting("trc20_usdt_rate", "1.00"))
            net_label = "TRC20 (TRON)"
        else:
            return

        text = (
            f"💳 <b>شحن الرصيد عبر {net_label}</b>\n\n"
            f"أرسل USDT إلى العنوان التالي:\n"
            f"<code>{address}</code>\n\n"
            f"🌐 الشبكة: <b>{net_label}</b>\n"
            f"💵 الحد الأدنى: <b>{min_u} USDT</b>\n"
            f"💱 سعر الصرف: <b>1 USDT = ${rate:.2f}</b>\n\n"
            f"ثم اضغط <b>«أرسلت المبلغ»</b> وأرسل رقم المعاملة (TxID)."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ أرسلت المبلغ", callback_data=f"crypto_sent_{network}")],
            [InlineKeyboardButton("📋 نسخ العنوان",  callback_data=f"crypto_copy_{network}")],
            [InlineKeyboardButton("🔙 رجوع",          callback_data="charge_back")],
        ])
        await self.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML"
        )

    # ── طلب TXID مع عدّاد تنازلي ────────────────────────

    async def prompt_txid(self, chat_id: int, user_id: int, network: str):
        _session_start(user_id, network)

        def _fmt(secs: int) -> str:
            return f"{secs // 60:02d}:{secs % 60:02d}"

        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=(f"📨 أرسل رقم المعاملة (TxID) لـ USDT {network.upper()}.\n\n"
                  f"⏱ الوقت المتبقي: <b>{_fmt(SESSION_TIMEOUT)}</b>"),
            parse_mode="HTML",
        )

        async def _countdown():
            for remaining in range(SESSION_TIMEOUT - 5, 0, -5):
                await asyncio.sleep(5)
                if not _session_get(user_id):
                    return
                try:
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg.message_id,
                        text=(f"📨 أرسل رقم المعاملة (TxID) لـ USDT {network.upper()}.\n\n"
                              f"⏱ الوقت المتبقي: <b>{_fmt(remaining)}</b>"),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            if _session_get(user_id):
                _session_clear(user_id)
                try:
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg.message_id,
                        text="⌛ انتهى الوقت. اضغط «أرسلت المبلغ» مجدداً.",
                    )
                except Exception:
                    pass

        task = asyncio.create_task(_countdown())
        if user_id in _SESSIONS:
            _SESSIONS[user_id]["task"] = task

    # ── نسخ العنوان ─────────────────────────────────────

    async def handle_copy(self, chat_id: int, network: str):
        setting = "bep20_address" if network == "bep20" else "trc20_address"
        label   = "BEP20" if network == "bep20" else "TRC20"
        address = self.db.get_setting(setting, "")
        await self.bot.send_message(
            chat_id=chat_id,
            text=(f"📋 <b>عنوان USDT {label}:</b>\n\n"
                  f"<code>{address}</code>\n\n"
                  f"<i>اضغط على العنوان لنسخه</i>"),
            parse_mode="HTML",
        )

    # ── معالجة رسالة TXID ───────────────────────────────

    async def handle_txid_message(self, message) -> bool:
        uid   = message.from_user.id
        state = _session_get(uid)
        if not state or state.get("step") != "waiting_txid":
            return False
        return await self._verify_and_credit(message, state["network"])

    async def _verify_and_credit(self, message, network: str) -> bool:
        uid  = message.from_user.id
        cid  = message.chat.id
        txid = (message.text or "").strip()
        _session_clear(uid)

        check_msg = await self.bot.send_message(
            chat_id=cid,
            text="🔍 <b>جارٍ التحقق من المعاملة...</b>\n<i>قد يستغرق 10–20 ثانية</i>",
            parse_mode="HTML",
        )

        client = (self._get_bep20_client() if network == "bep20"
                  else self._get_trc20_client())
        if not client:
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text="❌ <b>النظام غير مضبوط!</b>\nتواصل مع الأدمن.",
                parse_mode="HTML",
            )
            return True

        result = await client.verify(txid)
        if not result.get("success"):
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text=result.get("error", "❌ خطأ غير معروف"),
                parse_mode="HTML",
            )
            return True

        paid     = result["amount"]
        net      = result["network"]
        rate_key = "bep20_usdt_rate" if network == "bep20" else "trc20_usdt_rate"
        min_key  = "bep20_min_usdt"  if network == "bep20" else "trc20_min_usdt"
        rate     = float(self.db.get_setting(rate_key, "1.00"))
        min_u    = float(self.db.get_setting(min_key,  "1.00"))

        if paid < min_u:
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text=(f"⚠️ <b>المبلغ أقل من الحد الأدنى!</b>\n\n"
                      f"المُرسَل: <b>{paid} USDT</b>\n"
                      f"الأدنى:  <b>{min_u} USDT</b>"),
                parse_mode="HTML",
            )
            return True

        credit  = round(paid * rate, 4)
        success = self.db.process_crypto_deposit(uid, txid, network, paid, credit)
        if not success:
            await self.bot.edit_message_text(
                chat_id=cid, message_id=check_msg.message_id,
                text="⛔ <b>هذا الـ TXID مستخدم مسبقاً!</b>\nكل معاملة تُقبل مرة واحدة فقط.",
                parse_mode="HTML",
            )
            return True

        new_bal = self.db.get_balance(uid)
        icon    = self.LABELS.get(network, net)

        await self.bot.edit_message_text(
            chat_id=cid, message_id=check_msg.message_id,
            text=(f"✅ <b>تم شحن رصيدك بنجاح!</b>\n\n"
                  f"{icon}\n"
                  f"💵 USDT المُستلَمة: <b>{paid}</b>\n"
                  f"💰 رصيد مضاف:      <code>${credit:.2f}</code>\n"
                  f"💳 رصيدك الحالي:   <code>${new_bal:.2f}</code>"),
            parse_mode="HTML",
        )

        from config import ADMIN_ID
        try:
            await self.bot.send_message(
                chat_id=ADMIN_ID,
                text=(f"{icon}\n\n"
                      f"👤 المستخدم: <code>{uid}</code>\n"
                      f"💵 USDT: <b>{paid}</b>\n"
                      f"💰 رصيد مضاف: <code>${credit:.2f}</code>\n"
                      f"🔗 TXID: <code>{txid}</code>"),
                parse_mode="HTML",
            )
        except Exception:
            pass

        return True

    # ── تحقق من التفعيل ──────────────────────────────────

    def is_bep20_enabled(self) -> bool:
        return (self.db.get_setting("pay_bep20", "0") == "1" and
                bool(self.db.get_setting("bep20_address", "").strip()))

    def is_trc20_enabled(self) -> bool:
        return (self.db.get_setting("pay_trc20", "0") == "1" and
                bool(self.db.get_setting("trc20_api_key", "").strip()) and
                bool(self.db.get_setting("trc20_address", "").strip()))

    def _get_bep20_client(self):
        addr = self.db.get_setting("bep20_address", "").strip()
        conf = int(self.db.get_setting("bep20_confirmations", "3"))
        return BEP20Client(addr, conf) if addr else None

    def _get_trc20_client(self):
        key  = self.db.get_setting("trc20_api_key", "").strip()
        addr = self.db.get_setting("trc20_address", "").strip()
        conf = int(self.db.get_setting("trc20_confirmations", "19"))
        return TRC20Client(key, addr, conf) if (key and addr) else None
