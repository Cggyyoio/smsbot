"""
🌐 i18n.py — نظام الترجمة (عربي / English)
"""

STRINGS = {
    # ── القائمة الرئيسية ──────────────────────────────────
    "welcome": {
        "ar": "👋 أهلاً <b>{name}</b>\n\n👤 {uname}\n🆔 <code>{uid}</code>\n💳 <b>${bal:.3f}</b>",
        "en": "👋 Hello <b>{name}</b>\n\n👤 {uname}\n🆔 <code>{uid}</code>\n💳 <b>${bal:.3f}</b>",
    },
    "btn_buy_tg":       {"ar": "🛒 شراء رقم تيليجرام",     "en": "🛒 Buy Telegram Number"},
    "btn_sms":          {"ar": "📱 أرقام SMS",              "en": "📱 SMS Numbers"},
    "btn_deposit":      {"ar": "💰 شحن رصيد",               "en": "💰 Deposit"},
    "btn_account":      {"ar": "👤 حسابي",                  "en": "👤 My Account"},
    "btn_orders":       {"ar": "📋 طلباتي",                 "en": "📋 My Orders"},
    "btn_instructions": {"ar": "📖 التعليمات",              "en": "📖 Instructions"},
    "btn_language":     {"ar": "🌐 تغيير اللغة",            "en": "🌐 Change Language"},
    "btn_activation_ch":{"ar": "📢 قناة التفعيلات",         "en": "📢 Activation Channel"},
    "btn_main_ch":      {"ar": "📣 القناة الرئيسية",        "en": "📣 Main Channel"},
    "btn_support":      {"ar": "🆘 الدعم الفني",            "en": "🆘 Support"},
    "btn_back":         {"ar": "🔙 رجوع",                   "en": "🔙 Back"},

    # ── اختيار اللغة ──────────────────────────────────────
    "choose_lang": {
        "ar": "🌐 <b>اختر لغتك</b>\n\nChoose your language:",
        "en": "🌐 <b>Choose your language</b>\n\nاختر لغتك:",
    },
    "lang_set": {
        "ar": "✅ تم تعيين اللغة: <b>العربية</b>",
        "en": "✅ Language set to: <b>English</b>",
    },

    # ── الاشتراك الإجباري ─────────────────────────────────
    "force_sub_title": {
        "ar": "🔐 <b>اشتراك إجباري</b>\n\nيجب الاشتراك في القنوات التالية أولاً:\n\n",
        "en": "🔐 <b>Subscription Required</b>\n\nPlease join the following channels first:\n\n",
    },
    "force_sub_btn_check": {
        "ar": "✅ تحققت من اشتراكي",
        "en": "✅ I have joined",
    },
    "force_sub_after": {
        "ar": "\nبعد الاشتراك اضغط الزر أدناه ✅",
        "en": "\nAfter joining, press the button below ✅",
    },

    # ── محظور ─────────────────────────────────────────────
    "banned": {
        "ar": "🚫 <b>حسابك محظور</b>\nتواصل مع الدعم للاستفسار.",
        "en": "🚫 <b>Your account is banned</b>\nContact support for more info.",
    },

    # ── التعليمات ─────────────────────────────────────────
    "instructions_default": {
        "ar": "📖 <b>التعليمات</b>\n\nلم يتم تعيين أي تعليمات بعد.\nتواصل مع الأدمن.",
        "en": "📖 <b>Instructions</b>\n\nNo instructions have been set yet.\nContact the admin.",
    },

    # ── شحن الرصيد ────────────────────────────────────────
    "deposit_title": {
        "ar": "━━━━━━━━━━━━━━━━━━━━━━\n💳 <b>شحن الرصيد</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n💰 رصيدك الحالي: <b>${bal:.4f}</b>\n\n🔽 اختر طريقة الدفع:",
        "en": "━━━━━━━━━━━━━━━━━━━━━━\n💳 <b>Deposit</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n💰 Current balance: <b>${bal:.4f}</b>\n\n🔽 Choose payment method:",
    },
    "no_payment":  {"ar": "⚠️ لا توجد طرق دفع متاحة حالياً", "en": "⚠️ No payment methods available"},
    "btn_stars":   {"ar": "⭐ نجوم تيليجرام",     "en": "⭐ Telegram Stars"},
    "btn_binance": {"ar": "🟡 باينانس (تلقائي)",  "en": "🟡 Binance Pay (Auto)"},
    "btn_usdt":    {"ar": "💎 USDT عملات رقمية",  "en": "💎 USDT Crypto"},
    "btn_trx":     {"ar": "🔴 TRX — ترون",        "en": "🔴 TRX — Tron"},
    "btn_ton":     {"ar": "💎 TON — تون كوين",    "en": "💎 TON Coin"},
    "btn_vod":     {"ar": "📱 فودافون كاش",       "en": "📱 Vodafone Cash"},

    # ── حسابي ─────────────────────────────────────────────
    "account_title": {
        "ar": "━━━━━━━━━━━━━━━━━━━━━━\n👤 <b>حسابي</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n🆔 المعرف: <code>{uid}</code>\n📛 يوزر: {uname}\n\n💳 الرصيد: <b>${bal:.3f}</b>\n📦 الطلبات: <b>{orders}</b> طلب\n✅ مكتملة: <b>{done}</b>\n💸 إجمالي الإنفاق: <b>${spent:.3f}</b>",
        "en": "━━━━━━━━━━━━━━━━━━━━━━\n👤 <b>My Account</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n🆔 ID: <code>{uid}</code>\n📛 Username: {uname}\n\n💳 Balance: <b>${bal:.3f}</b>\n📦 Orders: <b>{orders}</b>\n✅ Completed: <b>{done}</b>\n💸 Total Spent: <b>${spent:.3f}</b>",
    },
    "btn_deposit2": {"ar": "💰 شحن رصيد", "en": "💰 Deposit"},
    "btn_orders2":  {"ar": "📋 طلباتي",   "en": "📋 My Orders"},

    # ── اختيار الدولة ─────────────────────────────────────
    "buy_country_title": {
        "ar": "🛒 <b>اختر الدولة</b>\n\n💳 رصيدك: <b>${bal:.3f}</b>\n✅ = يمكنك الشراء  |  💳 = رصيد غير كافٍ",
        "en": "🛒 <b>Choose Country</b>\n\n💳 Balance: <b>${bal:.3f}</b>\n✅ = Can buy  |  💳 = Insufficient balance",
    },
    "no_numbers": {
        "ar": "😔 <b>لا توجد أرقام متاحة حالياً</b>\n\nحاول لاحقاً.",
        "en": "😔 <b>No numbers available right now</b>\n\nTry later.",
    },

    # ── تفاصيل الدولة ─────────────────────────────────────
    "country_detail": {
        "ar": "━━━━━━━━━━━━━━━━━━━━━━\n{flag} <b>{name}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n💰 سعر الرقم: <b>${price:.3f}</b>\n📦 المتاح الآن: <b>{avail}</b> رقم\n\n💳 رصيدك: <b>${bal:.3f}</b>\n🛒 يمكنك شراء: <b>{can}</b> رقم\n{bar}",
        "en": "━━━━━━━━━━━━━━━━━━━━━━\n{flag} <b>{name}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n💰 Price: <b>${price:.3f}</b>\n📦 Available: <b>{avail}</b>\n\n💳 Balance: <b>${bal:.3f}</b>\n🛒 You can buy: <b>{can}</b>\n{bar}",
    },
    "sold_out": {
        "ar": "😔 <b>نفدت أرقام {flag} {name}</b>\n\nحاول دولة أخرى.",
        "en": "😔 <b>No numbers for {flag} {name}</b>\n\nTry another country.",
    },
    "btn_buy_now":   {"ar": "✅ شراء رقم الآن",    "en": "✅ Buy Now"},
    "btn_top_up":    {"ar": "💰 شحن رصيد أولاً",   "en": "💰 Top Up First"},

    # ── طلباتي ────────────────────────────────────────────
    "orders_title":   {"ar": "📋 <b>آخر {} طلبات</b>\n\n", "en": "📋 <b>Last {} orders</b>\n\n"},
    "no_orders": {
        "ar": "📋 <b>طلباتي</b>\n\nلم تقم بأي طلبات بعد.\nاضغط «شراء رقم» للبدء! 🛒",
        "en": "📋 <b>My Orders</b>\n\nNo orders yet.\nPress 'Buy Number' to start! 🛒",
    },
    "status_done":    {"ar": "✅",  "en": "✅"},
    "status_pending": {"ar": "⏳", "en": "⏳"},
    "status_cancel":  {"ar": "❌", "en": "❌"},
    "code_waiting":   {"ar": "⏳ في الانتظار", "en": "⏳ Waiting"},
    "code_cancelled": {"ar": "❌ ملغي",        "en": "❌ Cancelled"},

    # ── أرقام SMS ─────────────────────────────────────────
    "sms_title": {
        "ar": "━━━━━━━━━━━━━━━━━━━━━━\n📱 <b>أرقام SMS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n💳 رصيدك: <b>${bal:.3f}</b>\n\n✅ = يمكنك الشراء  |  💳 = رصيد غير كافٍ\n\n🌍 اختر الدولة:",
        "en": "━━━━━━━━━━━━━━━━━━━━━━\n📱 <b>SMS Numbers</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n💳 Balance: <b>${bal:.3f}</b>\n\n✅ = Can buy  |  💳 = Insufficient balance\n\n🌍 Choose country:",
    },
    "sms_no_numbers": {
        "ar": "😔 <b>لا توجد أرقام SMS متاحة حالياً</b>\n\nحاول لاحقاً.",
        "en": "😔 <b>No SMS numbers available right now</b>\n\nTry later.",
    },
    "sms_insufficient": {"ar": "💳 رصيدك غير كافٍ للشراء.", "en": "💳 Insufficient balance."},
    "sms_sold_out":     {"ar": "😔 نفدت الأرقام! جرب دولة أخرى.", "en": "😔 Out of stock! Try another country."},
    "banned_short":     {"ar": "🚫 حسابك محظور", "en": "🚫 Your account is banned"},

    # ── USDT menu ─────────────────────────────────────────
    "usdt_title": {
        "ar": "💎 <b>العملة: USDT — دولار</b>\n\n📡 اختر الشبكة المناسبة:\n\n⚠️ <b>تنبيه:</b> تأكد من الشبكة الصحيحة\nلتجنب فقدان الأموال",
        "en": "💎 <b>Currency: USDT</b>\n\n📡 Choose the correct network:\n\n⚠️ <b>Warning:</b> Make sure you pick the right network\nto avoid losing funds",
    },
    "usdt_unavailable": {"ar": "⚠️ غير متاح", "en": "⚠️ Unavailable"},
}


def t(key: str, lang: str = "ar", **kwargs) -> str:
    """يرجع النص المترجم للمفتاح المطلوب"""
    entry = STRINGS.get(key, {})
    text  = entry.get(lang) or entry.get("ar") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text
