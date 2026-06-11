"""
👤 handlers/user.py — with i18n (AR / EN)
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from otp_listener import _build_waiting_msg, build_order_msg
from i18n import t

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
#  helpers
# ──────────────────────────────────────────────────────────

def _back_kb(cb="main_menu", lang="ar"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_back", lang), callback_data=cb)]])

async def _answer(q, text="", alert=False):
    try: await q.answer(text, show_alert=alert)
    except Exception: pass

async def _edit(q, text, kb=None, mode="HTML"):
    try: await q.edit_message_text(text, reply_markup=kb, parse_mode=mode)
    except BadRequest as e:
        if "not modified" not in str(e).lower(): logger.warning("edit: %s", e)

def _lang(db, uid: int) -> str:
    return db.get_user_lang(uid)

# ──────────────────────────────────────────────────────────
#  إشعار قناة التفعيلات (موحّد)
# ──────────────────────────────────────────────────────────

def _apply_referral_earning(db, user_id: int, order_cost: float):
    """يضيف أرباح للمُحيل عند كل طلب"""
    try:
        referrer = db.get_referrer(user_id)
        if not referrer:
            return
        pct     = float(db.get_setting("referral_percent", "10"))
        earning = round(order_cost * pct / 100, 4)
        if earning > 0:
            db.add_referral_earning(referrer, earning)
    except Exception:
        pass


def _mask_phone(phone: str) -> str:
    digits = str(phone).lstrip("+")
    return "+" + digits[:4] + "★★★"

def _mask_code(code: str) -> str:
    return "".join(ch if i % 2 == 0 else "★" for i, ch in enumerate(str(code)))

def _mask_uid(uid) -> str:
    return str(uid)[:3] + "★★★"

async def _send_notify(bot, db, *, app_type: str, flag: str, country: str,
                       phone: str, code=None, uid, price: float,
                       status: str = "تم التفعيل ⚡"):
    try:
        ch = db.get_setting("notify_channel", "").strip()
        if not ch or ch == "0":
            return
        bot_me       = await bot.get_me()
        bot_username = "@" + bot_me.username
        code_line    = _mask_code(code) if code else "⏳ في الانتظار"
        text = (
            "✅ <b>تم شراء رقم جديد</b>\n\n"
            "🌐 <b>التطبيق:</b> {app}\n"
            "🌍 <b>الدولة:</b> {flag} {country}\n"
            "📞 <b>الرقم:</b> <code>{phone}</code>\n"
            "🔑 <b>الكود:</b> <code>{code}</code>\n"
            "👤 <b>المستخدم:</b> <code>{uid}</code>\n"
            "⚡ <b>الحالة:</b> {status}\n"
            "💰 <b>السعر:</b> ${price:.3f}\n"
            "🤖 <b>للشراء:</b> {bot}"
        ).format(
            app=app_type, flag=flag, country=country,
            phone=_mask_phone(phone), code=code_line,
            uid=_mask_uid(uid), status=status,
            price=float(price), bot=bot_username
        )
        await bot.send_message(chat_id=int(ch), text=text, parse_mode="HTML")
    except Exception as e:
        logger.warning("notify_channel error: %s", e)

# ──────────────────────────────────────────────────────────
#  القائمة الرئيسية
# ──────────────────────────────────────────────────────────

def main_menu_kb(lang="ar", db=None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(t("btn_buy_tg",  lang), callback_data="buy_country"),
            InlineKeyboardButton(t("btn_sms",     lang), callback_data="sms_countries"),
        ],
        [
            InlineKeyboardButton(t("btn_deposit", lang), callback_data="deposit"),
            InlineKeyboardButton(t("btn_account", lang), callback_data="my_account"),
        ],
        [
            InlineKeyboardButton(t("btn_orders",       lang), callback_data="my_orders"),
            InlineKeyboardButton(t("btn_instructions", lang), callback_data="instructions"),
        ],
        [
            InlineKeyboardButton("💰 ربح رصيد" if lang == "ar" else "💰 Earn Balance",
                                 callback_data="referral_menu"),
            InlineKeyboardButton("🌐 تغيير اللغة" if lang == "ar" else "🌐 Language",
                                 callback_data="choose_language"),
        ],
    ]
    if db:
        act_link  = db.get_setting("activation_channel_link", "").strip()
        main_link = db.get_setting("main_channel_link", "").strip()
        sup_link  = db.get_setting("support_link", "").strip()
        ch_row = []
        if act_link:  ch_row.append(InlineKeyboardButton(t("btn_activation_ch", lang), url=act_link))
        if main_link: ch_row.append(InlineKeyboardButton(t("btn_main_ch",       lang), url=main_link))
        if ch_row: rows.append(ch_row)
        if sup_link:  rows.append([InlineKeyboardButton(t("btn_support", lang), url=sup_link)])
    return InlineKeyboardMarkup(rows)

# ──────────────────────────────────────────────────────────
#  Forced Subscription
# ──────────────────────────────────────────────────────────

async def check_subscription(user_id: int, channels: list, bot) -> list:
    not_joined = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                not_joined.append(ch)
        except Exception:
            not_joined.append(ch)
    return not_joined

def _not_joined_msg(not_joined: list, lang="ar") -> tuple:
    text = t("force_sub_title", lang)
    rows = []
    for i, ch in enumerate(not_joined, 1):
        name = ch.get("name") or ch.get("link") or str(ch["id"])
        link = ch.get("link", "")
        text += "{}️⃣  <b>{}</b>\n".format(i, name)
        if link:
            rows.append([InlineKeyboardButton("📢 {}".format(name), url=link)])
    text += t("force_sub_after", lang)
    rows.append([InlineKeyboardButton(t("force_sub_btn_check", lang), callback_data="check_sub")])
    return text, InlineKeyboardMarkup(rows)

# ──────────────────────────────────────────────────────────
#  اختيار اللغة
# ──────────────────────────────────────────────────────────

def _lang_kb(next_step="main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇸🇦 العربية", callback_data="set_lang_ar_{}".format(next_step)),
        InlineKeyboardButton("🇬🇧 English", callback_data="set_lang_en_{}".format(next_step)),
    ]])

async def choose_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _answer(q)
    await _edit(q, t("choose_lang", "ar"), _lang_kb("main_menu"))

async def set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q         = update.callback_query
    db        = context.bot_data["db"]
    parts     = q.data.replace("set_lang_", "").split("_", 1)
    lang      = parts[0]
    next_step = parts[1] if len(parts) > 1 else "main_menu"
    db.set_user_lang(update.effective_user.id, lang)
    await _answer(q, t("lang_set", lang))
    if next_step == "force_sub":
        await _do_force_sub_or_menu(update, context, lang)
    else:
        await start_callback(update, context)

# ──────────────────────────────────────────────────────────
#  /start
# ──────────────────────────────────────────────────────────

async def _send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    db    = context.bot_data["db"]
    user  = update.effective_user
    bal   = db.get_balance(user.id)
    name  = user.first_name or ("صديق" if lang == "ar" else "Friend")
    uname = "@" + user.username if user.username else ("بدون يوزر" if lang == "ar" else "No username")
    text  = t("welcome", lang, name=name, uname=uname, uid=user.id, bal=bal)
    kb    = main_menu_kb(lang=lang, db=db)
    if update.callback_query:
        try:    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except: await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def _do_force_sub_or_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    db       = context.bot_data["db"]
    user     = update.effective_user
    channels = db.get_force_channels()
    if channels:
        not_joined = await check_subscription(user.id, channels, context.bot)
        if not_joined:
            text, kb = _not_joined_msg(not_joined, lang)
            if update.callback_query:
                try:    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
                except: await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
            else:
                await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
            return
    db.set_onboarded(user.id)
    await _send_main_menu(update, context, lang)

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db     = context.bot_data["db"]
    user   = update.effective_user
    bot    = context.bot
    is_new = db.ensure_user(user.id, user.username, user.first_name)

    if db.is_banned(user.id):
        txt = t("banned", "ar")
        if update.callback_query:
            try:    await update.callback_query.edit_message_text(txt, parse_mode="HTML")
            except: await update.effective_message.reply_text(txt, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(txt, parse_mode="HTML")
        return

    # إشعار المستخدم الجديد
    if is_new:
        try:
            ch    = db.get_setting("newuser_channel", "").strip()
            uname = "@" + user.username if user.username else "بدون يوزر"
            name  = user.first_name or "صديق"
            if ch and ch not in ("", "0"):
                await bot.send_message(
                    chat_id=int(ch),
                    text="🆕 <b>مستخدم جديد</b>\n\n👤 <b>{name}</b>\n📛 {uname}\n🆔 <code>{uid}</code>".format(
                        name=name, uname=uname, uid=user.id),
                    parse_mode="HTML"
                )
        except Exception:
            pass

    lang = _lang(db, user.id)

    if not db.is_onboarded(user.id):
        msg = t("choose_lang", "ar")
        if update.callback_query:
            try:    await update.callback_query.edit_message_text(msg, reply_markup=_lang_kb("force_sub"), parse_mode="HTML")
            except: await update.effective_message.reply_text(msg, reply_markup=_lang_kb("force_sub"), parse_mode="HTML")
        else:
            await update.effective_message.reply_text(msg, reply_markup=_lang_kb("force_sub"), parse_mode="HTML")
        return

    await _do_force_sub_or_menu(update, context, lang)

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("🔄", show_alert=False)
    db   = context.bot_data["db"]
    lang = _lang(db, update.effective_user.id)
    await _do_force_sub_or_menu(update, context, lang)

# ──────────────────────────────────────────────────────────
#  التعليمات
# ──────────────────────────────────────────────────────────

async def instructions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    lang = _lang(db, update.effective_user.id)
    await _answer(q)
    if lang == "en":
        text = db.get_setting("instructions_en", "").strip() or t("instructions_default", "en")
    else:
        text = db.get_setting("instructions_ar", "").strip() or t("instructions_default", "ar")
    await _edit(q, text, _back_kb("main_menu", lang))

# ──────────────────────────────────────────────────────────
#  حسابي
# ──────────────────────────────────────────────────────────

async def my_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    lang = _lang(db, user.id)
    await _answer(q)

    if db.is_banned(user.id):
        await _answer(q, t("banned_short", lang), True); return

    bal        = db.get_balance(user.id)
    orders     = db.get_orders_by_user(user.id, limit=500)
    sms_orders = db.get_sms_orders_by_user(user.id, limit=500)
    done       = sum(1 for o in orders     if o["status"] == "completed")
    sms_done   = sum(1 for o in sms_orders if o["status"] == "completed")
    spent      = sum(o["cost"] for o in orders     if o["status"] == "completed")
    sms_spent  = sum(o["cost"] for o in sms_orders if o["status"] == "completed")
    uname      = "@" + user.username if user.username else ("لا يوجد" if lang == "ar" else "None")

    await _edit(q,
        t("account_title", lang,
          uid=user.id, uname=uname, bal=bal,
          orders=len(orders) + len(sms_orders),
          done=done + sms_done,
          spent=spent + sms_spent),
        InlineKeyboardMarkup([
            [InlineKeyboardButton(t("btn_deposit2", lang), callback_data="deposit")],
            [InlineKeyboardButton(t("btn_orders2",  lang), callback_data="my_orders")],
            [InlineKeyboardButton(t("btn_back",     lang), callback_data="main_menu")],
        ])
    )

# ──────────────────────────────────────────────────────────
#  اختيار الدولة
# ──────────────────────────────────────────────────────────

async def buy_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    lang = _lang(db, user.id)
    await _answer(q)
    db.ensure_user(user.id, user.username, user.first_name)

    if db.is_banned(user.id):
        await _answer(q, t("banned_short", lang), True); return

    countries = db.get_available_countries()
    if not countries:
        await _edit(q, t("no_numbers", lang), _back_kb(lang=lang)); return

    bal  = db.get_balance(user.id)
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            price = db.get_price(c["country_code"])
            can   = "✅" if bal >= price else "💳"
            row.append(InlineKeyboardButton(
                "{} {} {} — ${:.2f} ({})".format(can, c["country_flag"], c["country_name"], price, c["available"]),
                callback_data="buy_num_{}".format(c["country_code"])
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")])
    await _edit(q, t("buy_country_title", lang, bal=bal), InlineKeyboardMarkup(rows))

# ──────────────────────────────────────────────────────────
#  تفاصيل الدولة
# ──────────────────────────────────────────────────────────

async def buy_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    lang = _lang(db, user.id)
    cc   = q.data.replace("buy_num_", "")
    await _answer(q)

    avail = db.count_available(cc)
    price = db.get_price(cc)
    bal   = db.get_balance(user.id)
    can   = int(bal // price) if price > 0 else 0

    c_list = db.get_available_countries()
    c_map  = {c["country_code"]: c for c in c_list}
    c      = c_map.get(cc, {})
    flag   = c.get("country_flag", "🌍")
    cname  = c.get("country_name", cc)

    if avail == 0:
        await _edit(q, t("sold_out", lang, flag=flag, name=cname), _back_kb("buy_country", lang))
        return

    bar = "🟩" * min(can, 5) + "⬜" * max(0, 5 - min(can, 5))
    await _edit(q,
        t("country_detail", lang, flag=flag, name=cname, price=price, avail=avail, bal=bal, can=can, bar=bar),
        InlineKeyboardMarkup([
            [InlineKeyboardButton(
                t("btn_buy_now", lang) if can > 0 else t("btn_top_up", lang),
                callback_data="confirm_buy_{}".format(cc) if can > 0 else "deposit"
            )],
            [InlineKeyboardButton(t("btn_back", lang), callback_data="buy_country")],
        ])
    )

# ──────────────────────────────────────────────────────────
#  تأكيد الشراء
# ──────────────────────────────────────────────────────────

async def confirm_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    db    = context.bot_data["db"]
    otp_l = context.bot_data.get("otp_listener")
    user  = update.effective_user
    lang  = _lang(db, user.id)
    cc    = q.data.replace("confirm_buy_", "")
    await _answer(q)

    if db.is_banned(user.id):
        await _answer(q, t("banned_short", lang), True); return

    price = db.get_price(cc)

    # خصم تلقائي بناءً على عدد الطلبات
    disc_pct = db.get_user_discount(user.id)
    if disc_pct > 0:
        price = round(price * (1 - disc_pct / 100), 4)

    num = db.get_available_number(cc)

    if not num:
        await _answer(q, t("sold_out", lang, flag="", name="").strip(), True); return

    if not db.deduct_balance(user.id, price):
        await _answer(q, t("sms_insufficient", lang), True); return

    db.mark_number_sold(num["id"], user.id)
    order_id = db.create_order(
        user_tg_id=user.id,
        number_id=num["id"],
        phone=num["phone"],
        country_code=cc,
        cost=price,
        twofa=num.get("twofa")
    )

    c_list  = db.get_available_countries()
    c_map   = {c["country_code"]: c for c in c_list}
    cc_data = c_map.get(cc, {})
    flag    = num.get("country_flag") or cc_data.get("country_flag", "🌍")
    cname   = num.get("country_name") or cc_data.get("country_name", cc)

    try:
        msg = await q.edit_message_text(
            _build_waiting_msg(num["phone"]),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔄 طلب الكود يدوياً" if lang == "ar" else "🔄 Request Code Manually",
                    callback_data="get_otp_{}".format(order_id)
                )
            ]])
        )
        msg_id = msg.message_id
    except Exception:
        msg_id = q.message.message_id

    db.set_order_msg_id(order_id, msg_id)
    if otp_l:
        await otp_l.attach_order(num["phone"], order_id)

    # إشعار المُحيل
    _apply_referral_earning(db, user.id, price)

    # إشعار القناة عند الشراء
    await _send_notify(
        context.bot, db,
        app_type="تيليجرام",
        flag=flag, country=cname,
        phone=num["phone"],
        code=None,
        uid=user.id,
        price=price,
        status="تم الشراء ⏳"
    )

# ──────────────────────────────────────────────────────────
#  طلب الكود يدوياً
# ──────────────────────────────────────────────────────────

async def get_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q        = update.callback_query
    db       = context.bot_data["db"]
    otp_l    = context.bot_data.get("otp_listener")
    order_id = int(q.data.replace("get_otp_", ""))
    await _answer(q, "🔄 جارٍ جلب الكود...")

    order = db.get_order(order_id)
    if not order:
        await _answer(q, "❌ الطلب غير موجود", True); return

    code = order.get("otp_code") or ""
    if code and not code.startswith("cancelled"):
        await _answer(q, "✅ الكود: {}".format(code), True); return

    if otp_l:
        code = await otp_l.fetch_otp_now(order["phone"], order_id)

    if code:
        db.set_order_otp(order_id, code)
        twofa = order.get("twofa")
        if not twofa and order.get("number_id"):
            num   = db.get_number(order["number_id"])
            twofa = num.get("twofa") if num else None
        try:
            await q.edit_message_text(
                build_order_msg(order["phone"], code, twofa=twofa),
                parse_mode="HTML", reply_markup=None
            )
        except Exception:
            pass
    else:
        lang = _lang(db, update.effective_user.id)
        await _answer(q, "⏳ لم يصل كود بعد، انتظر قليلاً." if lang == "ar" else "⏳ No code yet, wait a moment.", True)

# ──────────────────────────────────────────────────────────
#  طلباتي
# ──────────────────────────────────────────────────────────

async def my_orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    db     = context.bot_data["db"]
    user   = update.effective_user
    lang   = _lang(db, user.id)
    orders = db.get_orders_by_user(user.id, limit=10)
    await _answer(q)

    if not orders:
        await _edit(q, t("no_orders", lang), _back_kb(lang=lang)); return

    text = t("orders_title", lang).format(len(orders))
    for o in orders:
        raw = o.get("otp_code") or ""
        if raw.startswith("cancelled"):
            code   = t("code_cancelled", lang)
            status = t("status_cancel",  lang)
        elif raw:
            code   = "<code>{}</code>".format(raw)
            status = t("status_done",    lang)
        else:
            code   = t("code_waiting",   lang)
            status = t("status_pending", lang)
        text += "{} <code>+{}</code>\n    🔑 {}\n\n".format(status, o["phone"], code)

    await _edit(q, text.strip(), _back_kb(lang=lang))

# ──────────────────────────────────────────────────────────
#  شحن الرصيد
# ──────────────────────────────────────────────────────────

async def deposit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    cph  = context.bot_data.get("cph")
    ttp  = context.bot_data.get("ttp")
    vah  = context.bot_data.get("vah")
    lang = _lang(db, update.effective_user.id)
    await _answer(q)

    stars_on   = db.get_setting("pay_stars",  "0") == "1"
    binance_on = db.get_setting("pay_binance", "0") == "1" and bool(db.get_setting("binance_pay_id", "").strip())
    usdt_on    = (cph.is_bep20_enabled() or cph.is_trc20_enabled()) if cph else False
    trx_on     = ttp.is_trx_enabled() if ttp else False
    ton_on     = ttp.is_ton_enabled()  if ttp else False
    vod_on     = vah.is_enabled()      if vah else False
    bal        = db.get_balance(update.effective_user.id)

    rows = []
    if stars_on:   rows.append([InlineKeyboardButton(t("btn_stars",   lang), callback_data="charge_stars")])
    if binance_on: rows.append([InlineKeyboardButton(t("btn_binance", lang), callback_data="charge_binance")])
    if usdt_on:    rows.append([InlineKeyboardButton(t("btn_usdt",    lang), callback_data="charge_usdt_menu")])
    if trx_on:     rows.append([InlineKeyboardButton(t("btn_trx",     lang), callback_data="charge_trx")])
    if ton_on:     rows.append([InlineKeyboardButton(t("btn_ton",     lang), callback_data="charge_ton")])
    if vod_on:     rows.append([InlineKeyboardButton(t("btn_vod",     lang), callback_data="charge_vodafone")])
    if not rows:   rows.append([InlineKeyboardButton(t("no_payment",  lang), callback_data="main_menu")])
    rows.append([InlineKeyboardButton(
        "🎟️ استخدام كوبون" if lang == "ar" else "🎟️ Use Coupon",
        callback_data="use_coupon"
    )])
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")])

    await _edit(q, t("deposit_title", lang, bal=bal), InlineKeyboardMarkup(rows))

async def charge_usdt_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    cph  = context.bot_data.get("cph")
    lang = _lang(db, update.effective_user.id)
    await _answer(q)

    bep20_on = cph.is_bep20_enabled() if cph else False
    trc20_on = cph.is_trc20_enabled() if cph else False

    rows = []
    if trc20_on: rows.append([InlineKeyboardButton("🌐 TRC20 (TRON)", callback_data="charge_trc20")])
    if bep20_on: rows.append([InlineKeyboardButton("🌐 BEP20 (BSC)",  callback_data="charge_bep20")])
    if not rows: rows.append([InlineKeyboardButton(t("usdt_unavailable", lang), callback_data="deposit")])
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="deposit")])

    await _edit(q, t("usdt_title", lang), InlineKeyboardMarkup(rows))

# ──────────────────────────────────────────────────────────
#  أرقام SMS
# ──────────────────────────────────────────────────────────

async def sms_countries_callback(update, context):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    lang = _lang(db, user.id)
    await _answer(q)
    db.ensure_user(user.id, user.username, user.first_name)

    if db.is_banned(user.id):
        await _answer(q, t("banned_short", lang), True); return

    countries = db.get_sms_countries()
    if not countries:
        await _edit(q, t("sms_no_numbers", lang), _back_kb(lang=lang)); return

    bal  = db.get_balance(user.id)
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            price = float(c.get("price", 0.5))
            can   = "✅" if bal >= price else "💳"
            row.append(InlineKeyboardButton(
                "{} {} — ${:.2f} ({})".format(can, c["country"], price, c["available"]),
                callback_data="sms_buy_{}".format(c["country"])
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")])
    await _edit(q, t("sms_title", lang, bal=bal), InlineKeyboardMarkup(rows))

async def sms_buy_callback(update, context):
    q       = update.callback_query
    db      = context.bot_data["db"]
    poller  = context.bot_data.get("sms_poller")
    user    = update.effective_user
    lang    = _lang(db, user.id)
    country = q.data.replace("sms_buy_", "", 1)
    await _answer(q)

    if db.is_banned(user.id):
        await _answer(q, t("banned_short", lang), True); return

    try:
        price = db.get_sms_price(country)
    except Exception:
        price = 0.5

    # خصم تلقائي
    disc_pct = db.get_user_discount(user.id)
    if disc_pct > 0:
        price = round(price * (1 - disc_pct / 100), 4)

    if not db.deduct_balance(user.id, price):
        await _answer(q, t("sms_insufficient", lang), True); return

    num = db.lock_sms_number(country, user.id)
    if not num:
        db.add_balance(user.id, price)
        await _answer(q, t("sms_sold_out", lang), True); return

    order_id = db.create_sms_order(
        user_tg_id=user.id, sms_num_id=num["id"],
        phone=num["phone"], country=country, cost=price
    )

    from sms_handler import _build_sms_waiting_msg
    msg = await context.bot.send_message(
        chat_id=user.id, text=_build_sms_waiting_msg(num["phone"], country), parse_mode="HTML"
    )
    db.set_sms_order_msg_id(order_id, msg.message_id)

    if poller:
        poller.start_polling(
            order_id=order_id, user_tg_id=user.id, chat_id=user.id,
            msg_id=msg.message_id, phone=num["phone"], country=country,
            api_url=num["api_url"], cost=price, sms_num_id=num["id"]
        )

    # إشعار المُحيل
    _apply_referral_earning(db, user.id, price)
