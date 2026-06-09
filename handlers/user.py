"""
👤 handlers/user.py
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from otp_listener import _build_waiting_msg, build_order_msg

logger = logging.getLogger(__name__)

# ══ لوحة القائمة الرئيسية ══════════════════════════════════

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 شراء رقم تيليجرام", callback_data="buy_country")],
        [InlineKeyboardButton("📱 أرقام SMS",           callback_data="sms_countries")],
        [
            InlineKeyboardButton("💰 شحن رصيد", callback_data="deposit"),
            InlineKeyboardButton("👤 حسابي",     callback_data="my_account"),
        ],
        [InlineKeyboardButton("📋 طلباتي",       callback_data="my_orders")],
    ])

def _back_kb(cb="main_menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=cb)]])

async def _answer(q, text="", alert=False):
    try: await q.answer(text, show_alert=alert)
    except Exception: pass

async def _edit(q, text, kb=None, mode="HTML"):
    try: await q.edit_message_text(text, reply_markup=kb, parse_mode=mode)
    except BadRequest as e:
        if "not modified" not in str(e).lower(): logger.warning(f"edit: {e}")


# ══ /start ══════════════════════════════════════════════════

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db   = context.bot_data["db"]
    user = update.effective_user
    is_new = db.ensure_user(user.id, user.username, user.first_name)

    if db.is_banned(user.id):
        await update.effective_message.reply_text(
            "🚫 <b>حسابك محظور.</b>\nتواصل مع الدعم للاستفسار.",
            parse_mode="HTML"
        )
        return

    bal  = db.get_balance(user.id)
    name = user.first_name or "صديق"

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📲 <b>بوت أرقام تيليجرام</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👋 أهلاً <b>{}</b>!\n\n"
        "💳 رصيدك الحالي: <b>${:.3f}</b>\n\n"
        "⬇️ اختر من القائمة:".format(name, bal)
    )

    # لو callback query → عدّل الرسالة الحالية بدل ما تبعت جديدة
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=main_menu_kb(),
                parse_mode="HTML"
            )
        except Exception:
            await update.effective_message.reply_text(
                text, reply_markup=main_menu_kb(), parse_mode="HTML"
            )
    else:
        await update.effective_message.reply_text(
            text, reply_markup=main_menu_kb(), parse_mode="HTML"
        )

    if is_new:
        try:
            ch = db.get_setting("newuser_channel", "").strip()
            if ch and ch != "0":
                uname = "@" + user.username if user.username else "لا يوجد"
                await context.bot.send_message(
                    chat_id=int(ch),
                    text=(
                        "🆕 <b>مستخدم جديد انضم</b>\n\n"
                        "🆔 ID: <code>{}</code>\n"
                        "👤 الاسم: {}\n"
                        "📛 يوزر: {}".format(user.id, name, uname)
                    ),
                    parse_mode="HTML"
                )
        except Exception: pass


# ══ حسابي ════════════════════════════════════════════════════

async def my_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    await _answer(q)

    if db.is_banned(user.id):
        await _answer(q, "🚫 حسابك محظور", True); return

    bal    = db.get_balance(user.id)
    orders = db.get_orders_by_user(user.id, limit=50)
    done   = sum(1 for o in orders if o["status"] == "completed")
    spent  = sum(o["cost"] for o in orders if o["status"] == "completed")
    uname  = "@" + user.username if user.username else "لا يوجد"

    await _edit(q,
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>حسابي</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🆔 المعرف: <code>{}</code>\n"
        "📛 يوزر: {}\n\n"
        "💳 الرصيد: <b>${:.3f}</b>\n"
        "📦 الطلبات: <b>{}</b> طلب\n"
        "✅ مكتملة: <b>{}</b>\n"
        "💸 إجمالي الإنفاق: <b>${:.3f}</b>".format(
            user.id, uname, bal, len(orders), done, spent),
        InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 شحن رصيد", callback_data="deposit")],
            [InlineKeyboardButton("📋 طلباتي",   callback_data="my_orders")],
            [InlineKeyboardButton("🔙 رجوع",      callback_data="main_menu")],
        ])
    )


# ══ اختيار الدولة ════════════════════════════════════════════

async def buy_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    await _answer(q)
    db.ensure_user(user.id, user.username, user.first_name)

    if db.is_banned(user.id):
        await _answer(q, "🚫 حسابك محظور", True); return

    countries = db.get_available_countries()
    if not countries:
        await _edit(q,
            "😔 <b>لا توجد أرقام متاحة حالياً</b>\n\nحاول لاحقاً.",
            _back_kb()
        ); return

    bal = db.get_balance(user.id)
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            price = db.get_price(c["country_code"])
            can   = "✅" if bal >= price else "💳"
            row.append(InlineKeyboardButton(
                "{} {} {} — ${:.2f} ({})".format(
                    can, c["country_flag"], c["country_name"], price, c["available"]),
                callback_data="buy_num_{}".format(c["country_code"])
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])

    await _edit(q,
        "🛒 <b>اختر الدولة</b>\n\n"
        "💳 رصيدك: <b>${:.3f}</b>\n"
        "✅ = يمكنك الشراء  |  💳 = رصيد غير كافٍ".format(bal),
        InlineKeyboardMarkup(rows)
    )


# ══ تفاصيل الدولة ════════════════════════════════════════════

async def buy_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
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
        await _edit(q,
            "😔 <b>نفدت أرقام {} {}</b>\n\nحاول دولة أخرى.".format(flag, cname),
            _back_kb("buy_country")
        ); return

    bal_bar = "🟩" * min(can, 5) + "⬜" * max(0, 5 - min(can, 5))

    await _edit(q,
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "{} <b>{}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 سعر الرقم: <b>${:.3f}</b>\n"
        "📦 المتاح الآن: <b>{}</b> رقم\n\n"
        "💳 رصيدك: <b>${:.3f}</b>\n"
        "🛒 يمكنك شراء: <b>{}</b> رقم\n"
        "{}".format(flag, cname, price, avail, bal, can, bal_bar),
        InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✅ شراء رقم الآن" if can > 0 else "💰 شحن رصيد أولاً",
                callback_data="confirm_buy_{}".format(cc) if can > 0 else "deposit"
            )],
            [InlineKeyboardButton("🔙 رجوع", callback_data="buy_country")],
        ])
    )


# ══ تأكيد الشراء ══════════════════════════════════════════════

async def confirm_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    db    = context.bot_data["db"]
    otp_l = context.bot_data.get("otp_listener")
    user  = update.effective_user
    cc    = q.data.replace("confirm_buy_", "")
    await _answer(q)

    if db.is_banned(user.id):
        await _answer(q, "🚫 حسابك محظور", True); return

    price = db.get_price(cc)
    num   = db.get_available_number(cc)

    if not num:
        await _answer(q, "😔 نفدت الأرقام! جرب دولة أخرى.", True); return

    if not db.deduct_balance(user.id, price):
        await _answer(q, "💳 رصيدك غير كافٍ للشراء.", True); return

    db.mark_number_sold(num["id"], user.id)
    order_id = db.create_order(
        user_tg_id=user.id,
        number_id=num["id"],
        phone=num["phone"],
        country_code=cc,
        cost=price,
        twofa=num.get("twofa")
    )

    # جيب بيانات الدولة من الـ DB
    c_list  = db.get_available_countries()
    c_map   = {c["country_code"]: c for c in c_list}
    cc_data = c_map.get(cc, {})
    flag    = num.get("country_flag") or cc_data.get("country_flag", "🌍")
    cname   = num.get("country_name") or cc_data.get("country_name", cc)

    try:
        msg = await q.edit_message_text(
            _build_waiting_msg(num["phone"]),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 طلب الكود يدوياً", callback_data="get_otp_{}".format(order_id))]
            ])
        )
        msg_id = msg.message_id
    except Exception:
        msg_id = q.message.message_id

    db.set_order_msg_id(order_id, msg_id)

    if otp_l:
        await otp_l.attach_order(num["phone"], order_id)

    # إشعار قناة التفعيلات
    try:
        ch = db.get_setting("notify_channel", "").strip()
        if ch and ch != "0":
            phone_str = num["phone"]
            v = max(1, len(phone_str) // 3)
            masked = phone_str[:v] + "★" * (len(phone_str) - v * 2) + phone_str[-v:]
            await context.bot.send_message(
                chat_id=int(ch),
                text=(
                    "🛒 <b>طلب شراء جديد</b>\n\n"
                    "🌍 الدولة: {} {}\n"
                    "📞 الرقم: <code>+{}</code>\n"
                    "👤 المستخدم: <code>{}</code>\n"
                    "💰 السعر: <b>${:.3f}</b>\n"
                    "🆔 الطلب: <b>#{}</b>".format(
                        flag, cname, masked, user.id, price, order_id)
                ),
                parse_mode="HTML"
            )
    except Exception: pass


# ══ طلب الكود يدوياً ══════════════════════════════════════════

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
        # نجيب twofa من order أولاً، وإلا من numbers كـ fallback
        twofa = order.get("twofa")
        if not twofa and order.get("number_id"):
            num   = db.get_number(order["number_id"])
            twofa = num.get("twofa") if num else None
        try:
            await q.edit_message_text(
                build_order_msg(order["phone"], code, twofa=twofa),
                parse_mode="HTML",
                reply_markup=None
            )
        except Exception: pass
    else:
        await _answer(q, "⏳ لم يصل كود بعد، انتظر قليلاً وحاول مجدداً.", True)


# ══ طلباتي ════════════════════════════════════════════════════

async def my_orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    db     = context.bot_data["db"]
    user   = update.effective_user
    orders = db.get_orders_by_user(user.id, limit=10)
    await _answer(q)

    if not orders:
        await _edit(q,
            "📋 <b>طلباتي</b>\n\n"
            "لم تقم بأي طلبات بعد.\n"
            "اضغط «شراء رقم» للبدء! 🛒",
            _back_kb()
        ); return

    text = "📋 <b>آخر {} طلبات</b>\n\n".format(len(orders))
    for o in orders:
        raw = o.get("otp_code") or ""
        if raw.startswith("cancelled"):
            code   = "❌ ملغي"
            status = "❌"
        elif raw:
            code   = "<code>{}</code>".format(raw)
            status = "✅"
        else:
            code   = "⏳ في الانتظار"
            status = "⏳"
        text += "{} <code>+{}</code>\n    🔑 {}\n\n".format(status, o["phone"], code)

    await _edit(q, text.strip(), _back_kb())


# ══ شحن الرصيد ════════════════════════════════════════════════

async def deposit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    db  = context.bot_data["db"]
    cph = context.bot_data.get("cph")
    ttp = context.bot_data.get("ttp")
    vah = context.bot_data.get("vah")
    await _answer(q)

    stars_on   = db.get_setting("pay_stars",  "0") == "1"
    binance_on = db.get_setting("pay_binance", "0") == "1" and bool(db.get_setting("binance_pay_id","").strip())
    usdt_on    = (cph.is_bep20_enabled() or cph.is_trc20_enabled()) if cph else False
    trx_on     = ttp.is_trx_enabled() if ttp else False
    ton_on     = ttp.is_ton_enabled()  if ttp else False
    vod_on     = vah.is_enabled()      if vah else False
    bal        = db.get_balance(update.effective_user.id)

    rows = []
    if stars_on:   rows.append([InlineKeyboardButton("⭐  نجوم تيليجرام",     callback_data="charge_stars")])
    if binance_on: rows.append([InlineKeyboardButton("🟡  باينانس ( تلقائي )", callback_data="charge_binance")])
    if usdt_on:    rows.append([InlineKeyboardButton("💎  USDT عملات رقمية",   callback_data="charge_usdt_menu")])
    if trx_on:     rows.append([InlineKeyboardButton("🔴  TRX — ترون",          callback_data="charge_trx")])
    if ton_on:     rows.append([InlineKeyboardButton("💎  TON — تون كوين",      callback_data="charge_ton")])
    if vod_on:     rows.append([InlineKeyboardButton("📱  فودافون كاش",         callback_data="charge_vodafone")])

    if not rows:
        rows.append([InlineKeyboardButton("⚠️ لا توجد طرق دفع متاحة حالياً", callback_data="main_menu")])

    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])

    await _edit(q,
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 <b>شحن الرصيد</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 رصيدك الحالي: <b>${:.4f}</b>\n\n"
        "🔽 اختر طريقة الدفع:".format(bal),
        InlineKeyboardMarkup(rows)
    )


# ══ قائمة شبكات USDT ══════════════════════════════════════════

async def charge_usdt_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    db  = context.bot_data["db"]
    cph = context.bot_data.get("cph")
    await _answer(q)

    bep20_on = cph.is_bep20_enabled() if cph else False
    trc20_on = cph.is_trc20_enabled() if cph else False

    rows = []
    if trc20_on: rows.append([InlineKeyboardButton("🌐  TRC20 (TRON)", callback_data="charge_trc20")])
    if bep20_on: rows.append([InlineKeyboardButton("🌐  BEP20 (BSC)",  callback_data="charge_bep20")])
    if not rows: rows.append([InlineKeyboardButton("⚠️ غير متاح", callback_data="deposit")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="deposit")])

    await _edit(q,
        "💎 <b>العملة: USDT — دولار</b>\n\n"
        "📡 اختر الشبكة المناسبة:\n\n"
        "⚠️ <b>تنبيه:</b> تأكد من الشبكة الصحيحة\n"
        "لتجنب فقدان الأموال",
        InlineKeyboardMarkup(rows)
    )


# ══ أرقام SMS — اختيار الدولة ════════════════════════════

async def sms_countries_callback(update, context):
    q    = update.callback_query
    db   = context.bot_data["db"]
    user = update.effective_user
    await _answer(q)
    db.ensure_user(user.id, user.username, user.first_name)

    if db.is_banned(user.id):
        await _answer(q, "🚫 حسابك محظور", True); return

    countries = db.get_sms_countries()
    if not countries:
        await _edit(q,
            "😔 <b>لا توجد أرقام SMS متاحة حالياً</b>\n\nحاول لاحقاً.",
            _back_kb()
        ); return

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
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])

    await _edit(q,
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📱 <b>أرقام SMS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💳 رصيدك: <b>${:.3f}</b>\n\n"
        "✅ = يمكنك الشراء  |  💳 = رصيد غير كافٍ\n\n"
        "🌍 اختر الدولة:".format(bal),
        InlineKeyboardMarkup(rows)
    )


async def sms_buy_callback(update, context):
    q       = update.callback_query
    db      = context.bot_data["db"]
    poller  = context.bot_data.get("sms_poller")
    user    = update.effective_user
    country = q.data.replace("sms_buy_", "", 1)
    await _answer(q)

    if db.is_banned(user.id):
        await _answer(q, "🚫 حسابك محظور", True); return

    price_str = db.get_setting("sms_price", "0.5")
    try:
        price = db.get_sms_price(country)
    except Exception:
        try:
            price = float(price_str)
        except ValueError:
            price = 0.5

    # تحقق من الرصيد
    if not db.deduct_balance(user.id, price):
        await _answer(q, "💳 رصيدك غير كافٍ للشراء.", True); return

    # احجز رقم
    num = db.lock_sms_number(country, user.id)
    if not num:
        # ما لقاش رقم — ارجع الرصيد
        db.add_balance(user.id, price)
        await _answer(q, "😔 نفدت الأرقام! جرب دولة أخرى.", True); return

    order_id = db.create_sms_order(
        user_tg_id=user.id,
        sms_num_id=num["id"],
        phone=num["phone"],
        country=country,
        cost=price
    )

    from sms_handler import _build_sms_waiting_msg
    await _answer(q)
    msg = await context.bot.send_message(
        chat_id=user.id,
        text=_build_sms_waiting_msg(num["phone"], country),
        parse_mode="HTML"
    )
    msg_id = msg.message_id

    db.set_sms_order_msg_id(order_id, msg_id)

    if poller:
        poller.start_polling(
            order_id=order_id,
            user_tg_id=user.id,
            chat_id=user.id,
            msg_id=msg_id,
            phone=num["phone"],
            country=country,
            api_url=num["api_url"],
            cost=price,
            sms_num_id=num["id"]
        )
