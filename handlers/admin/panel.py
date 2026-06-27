"""
👑 handlers/admin/panel.py — لوحة تحكم الأدمن
"""
import os, io, zipfile, logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from country_codes import detect_country, COUNTRY_DATA
import config

logger = logging.getLogger(__name__)


def is_admin(update: Update, context) -> bool:
    admin_id = int(context.bot_data["db"].get_setting("admin_id", "0"))
    return update.effective_user.id == admin_id


def _yn(v): return "✅" if v == "1" else "❌"
def _short(v, n=18):
    if not v or not v.strip(): return "غير محدد"
    return v[:n] + "…" if len(v) > n else v


# ══════════════════════════════════════════════════════════
#  لوحة رئيسية
# ══════════════════════════════════════════════════════════

def admin_main_kb():
    return InlineKeyboardMarkup([
        # ── المخزون ──────────────────────────
        [
            InlineKeyboardButton("📱 أرقام تيليجرام", callback_data="adm_numbers"),
            InlineKeyboardButton("💬 أرقام SMS",       callback_data="adm_sms"),
        ],
        # ── المال والطلبات ───────────────────
        [
            InlineKeyboardButton("💰 الأسعار",         callback_data="adm_prices"),
            InlineKeyboardButton("📋 الطلبات",         callback_data="adm_orders"),
        ],
        [
            InlineKeyboardButton("💳 الشحن",           callback_data="adm_deposits"),
            InlineKeyboardButton("📊 الإحصائيات",      callback_data="adm_stats"),
        ],
        # ── المستخدمون والتواصل ──────────────
        [
            InlineKeyboardButton("👥 المستخدمون",      callback_data="adm_users"),
            InlineKeyboardButton("📢 إشعار جماعي",    callback_data="adm_broadcast"),
        ],
        # ── التحليل والمراقبة ─────────────────
        [
            InlineKeyboardButton("📈 أداء الدول",       callback_data="adm_performance"),
            InlineKeyboardButton("⚠️ تنبيه المخزون",   callback_data="adm_low_stock"),
        ],
        [
            InlineKeyboardButton("🔍 بحث عن رقم",      callback_data="adm_search_number"),
            InlineKeyboardButton("📜 سجل العمليات",    callback_data="adm_audit_log"),
        ],
        # ── الإعدادات والخروج ────────────────
        [InlineKeyboardButton("⚙️ الإعدادات",          callback_data="adm_settings")],
        [InlineKeyboardButton("🏠 الرجوع للقائمة",     callback_data="main_menu")],
    ])


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        await update.callback_query.answer("❌ غير مصرح", show_alert=True)
        return
    db    = context.bot_data["db"]
    stats = db.get_stats()
    pend  = len(db.get_pending_deposits())
    total_revenue = stats["revenue"] + stats.get("sms_revenue", 0)
    total_orders  = stats["orders"]  + stats.get("sms_orders",  0)
    total_today   = stats["today"]   + stats.get("sms_today",   0)
    await update.callback_query.edit_message_text(
        "👑 <b>لوحة التحكم</b>\n\n"
        "👥 <b>المستخدمون:</b>  <b>{users}</b>  •  🚫 محظور: <b>{banned}</b>\n\n"
        "📱 TG:   ✅ <b>{available}</b> متاح  |  🛒 <b>{sold}</b> مباع\n"
        "💬 SMS:  ✅ <b>{sms_avail}</b> متاح\n\n"
        "📦 <b>الطلبات:</b>  <b>{orders}</b>  •  🌟 اليوم: <b>{today}</b>\n"
        "💰 <b>الإيرادات:</b>  <b>${revenue:.2f}</b>\n"
        "⏳ <b>شحن معلق:</b>  <b>{pend}</b>".format(
            pend=pend,
            sms_avail=stats.get("sms_avail", 0),
            orders=total_orders, today=total_today,
            revenue=total_revenue,
            **{k: stats[k] for k in ("users","banned","available","sold")}
        ),
        reply_markup=admin_main_kb(),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  إحصائيات تفصيلية
# ══════════════════════════════════════════════════════════

async def adm_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db    = context.bot_data["db"]
    stats = db.get_stats()
    with db._conn() as conn:
        revenue_week = conn.execute(
            "SELECT COALESCE(SUM(cost),0) FROM orders WHERE status='completed' AND created_at >= date('now','-7 days')"
        ).fetchone()[0]
        revenue_month = conn.execute(
            "SELECT COALESCE(SUM(cost),0) FROM orders WHERE status='completed' AND created_at >= date('now','-30 days')"
        ).fetchone()[0]
        revenue_today = conn.execute(
            "SELECT COALESCE(SUM(cost),0) FROM orders WHERE status='completed' AND date(created_at)=date('now')"
        ).fetchone()[0]
        top_countries = conn.execute("""
            SELECT
                COALESCE(n.country_flag, '🌍') as flag,
                COALESCE(n.country_name, o.country_code) as name,
                COUNT(*) as c
            FROM orders o
            LEFT JOIN numbers n ON n.country_code = o.country_code
            GROUP BY o.country_code
            ORDER BY c DESC LIMIT 5
        """).fetchall()
        # SMS orders
        sms_total = conn.execute(
            "SELECT COUNT(*) FROM sms_orders"
        ).fetchone()[0]
        sms_completed = conn.execute(
            "SELECT COUNT(*) FROM sms_orders WHERE status='completed'"
        ).fetchone()[0]
        sms_revenue = conn.execute(
            "SELECT COALESCE(SUM(cost),0) FROM sms_orders WHERE status='completed'"
        ).fetchone()[0]
        sms_today = conn.execute(
            "SELECT COALESCE(SUM(cost),0) FROM sms_orders WHERE status='completed' AND date(created_at)=date('now')"
        ).fetchone()[0]
        sms_week = conn.execute(
            "SELECT COALESCE(SUM(cost),0) FROM sms_orders WHERE status='completed' AND created_at >= date('now','-7 days')"
        ).fetchone()[0]
        sms_avail = conn.execute(
            "SELECT COUNT(*) FROM sms_numbers WHERE status='available'"
        ).fetchone()[0]

    total_revenue_today = revenue_today + sms_today
    total_revenue_week  = revenue_week  + sms_week
    total_revenue_all   = stats["revenue"] + sms_revenue
    total_users_bal     = db.get_total_users_balance()

    text  = "📊 <b>الإحصائيات</b>\n\n"
    text += "━━━━ 💰 الإيرادات ━━━━\n"
    text += "📅 اليوم:    <b>${:.2f}</b>\n".format(total_revenue_today)
    text += "📆 الأسبوع:  <b>${:.2f}</b>\n".format(total_revenue_week)
    text += "🗂 الإجمالي: <b>${:.2f}</b>\n\n".format(total_revenue_all)
    text += "━━━━ 📦 الطلبات ━━━━\n"
    text += "📱 أرقام TG:  <b>{}</b>\n".format(stats["orders"])
    text += "💬 أرقام SMS: <b>{}</b> (مكتمل: {})\n".format(sms_total, sms_completed)
    text += "📲 SMS متاح:  <b>{}</b>\n\n".format(sms_avail)
    text += "━━━━━ 👥 المستخدمون ━━━━━\n"
    text += "📊 إجمالي: <b>{}</b>\n".format(stats["users"])
    text += "💳 إجمالي رصيد المستخدمين: <b>${:.2f}</b>\n".format(total_users_bal)
    if top_countries:
        text += "\n━━━━ 🏆 أكثر الدول ━━━━\n"
        for r in top_countries:
            text += "  {} {} — <b>{}</b>\n".format(r[0], r[1], r[2])
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  الأرقام
# ══════════════════════════════════════════════════════════

async def adm_numbers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    grouped = db.get_all_numbers_grouped()
    if not grouped:
        await update.callback_query.edit_message_text(
            "📱 <b>الأرقام</b>\n\nلا توجد أرقام بعد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 رفع ملفات", callback_data="adm_upload")],
                [InlineKeyboardButton("🔙 رجوع",       callback_data="adm_main")],
            ]),
            parse_mode="HTML"
        )
        return
    rows = []
    total_avail = 0
    for cc, nums in sorted(grouped.items()):
        avail = sum(1 for n in nums if n["status"] == "available")
        sold  = sum(1 for n in nums if n["status"] == "sold")
        total_avail += avail
        flag  = nums[0]["country_flag"]
        cname = nums[0]["country_name"]
        rows.append([InlineKeyboardButton(
            "{} {} ✅{} 🛒{}".format(flag, cname, avail, sold),
            callback_data="adm_num_cc_{}".format(cc)
        )])
    rows.append([
        InlineKeyboardButton("📤 رفع ملفات", callback_data="adm_upload"),
        InlineKeyboardButton("📦 ZIP الكل",  callback_data="adm_zip_all"),
    ])
    rows.append([
        InlineKeyboardButton("🗑 حذف كل المباعة", callback_data="adm_del_sold_ALL"),
        InlineKeyboardButton("🗑 حذف أرقام",       callback_data="adm_num_delete_menu"),
    ])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")])
    await update.callback_query.edit_message_text(
        "📱 <b>الأرقام</b> — متاح: <b>{}</b>".format(total_avail),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML"
    )


async def adm_num_cc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    cc   = update.callback_query.data.replace("adm_num_cc_", "")
    nums = db.get_numbers_by_country(cc)
    if not nums:
        await update.callback_query.answer("لا توجد أرقام", show_alert=True)
        return
    flag  = nums[0]["country_flag"]
    cname = nums[0]["country_name"]
    avail = sum(1 for n in nums if n["status"] == "available")
    sold  = sum(1 for n in nums if n["status"] == "sold")
    price = db.get_price(cc)
    text  = "{} <b>{}</b>\n\n✅ متاح: {} | 🛒 مباع: {}\n💰 السعر: <b>${:.3f}</b>\n\n<b>الأرقام:</b>\n".format(
        flag, cname, avail, sold, price)
    for n in nums[:15]:
        icon = "✅" if n["status"] == "available" else "🛒"
        text += "{} <code>+{}</code>\n".format(icon, n["phone"])
    if len(nums) > 15:
        text += "... و {} آخرين".format(len(nums) - 15)
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💰 تعديل السعر", callback_data="adm_setprice_{}".format(cc)),
                InlineKeyboardButton("📦 ZIP",          callback_data="adm_zip_{}".format(cc)),
            ],
            [InlineKeyboardButton("🗑 حذف المباعة + ملفاتها", callback_data="adm_del_sold_{}".format(cc))],
            [InlineKeyboardButton("🗑🗑 حذف الدولة كاملة (الكل)", callback_data="adm_num_delcountry_{}".format(cc))],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_numbers")],
        ]),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  حذف الأرقام الجاهزة — قائمة شاملة (دولة/فئة/رقم واحد/الكل)
# ══════════════════════════════════════════════════════════

async def adm_num_delete_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    await update.callback_query.edit_message_text(
        "🗑 <b>حذف الأرقام الجاهزة</b>\n\nاختر طريقة الحذف:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 حذف دولة / فئة",     callback_data="adm_num_del_country_list")],
            [InlineKeyboardButton("🗑 حذف رقم واحد",        callback_data="adm_num_del_single")],
            [InlineKeyboardButton("🗑 حذف كل المباعة",     callback_data="adm_del_sold_ALL")],
            [InlineKeyboardButton("🗑🗑 حذف كل الأرقام (الكل)", callback_data="adm_num_clear_all")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_numbers")],
        ]),
        parse_mode="HTML"
    )


async def adm_num_del_country_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    grouped = db.get_all_numbers_grouped()
    if not grouped:
        await update.callback_query.answer("لا توجد دول/فئات", show_alert=True)
        return
    rows = []
    for cc, nums in sorted(grouped.items()):
        flag  = nums[0]["country_flag"]
        cname = nums[0]["country_name"]
        rows.append([InlineKeyboardButton(
            "🗑 {} {} ({} رقم)".format(flag, cname, len(nums)),
            callback_data="adm_num_delcountry_{}".format(cc)
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_num_delete_menu")])
    await update.callback_query.edit_message_text(
        "اختر الدولة/الفئة للحذف الكامل (متاح + مباع):",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML"
    )


async def adm_num_delcountry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db    = context.bot_data["db"]
    cc    = update.callback_query.data.replace("adm_num_delcountry_", "", 1)
    nums  = db.get_numbers_by_country(cc)
    count = len(nums)
    if cc.startswith("CAT_"):
        flag, cname = "📦", cc[4:]
    else:
        flag, cname = COUNTRY_DATA.get(cc, ("🌍", cc))
    db.delete_numbers_by_country(cc)
    await update.callback_query.answer(
        "✅ تم حذف {} {} ({} رقم)".format(flag, cname, count), show_alert=True
    )
    update.callback_query.data = "adm_numbers"
    await adm_numbers_callback(update, context)


async def adm_num_del_single_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_num_del_phone"
    await update.callback_query.edit_message_text(
        "📞 أرسل رقم الهاتف للحذف:\n<code>+1234567890</code>\n\n"
        "(يحذف الرقم وملف الـ session الخاص به نهائياً)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_num_delete_menu")]]),
        parse_mode="HTML"
    )


async def adm_num_clear_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    await update.callback_query.edit_message_text(
        "⚠️ <b>تأكيد حذف كل الأرقام الجاهزة</b>\n\n"
        "سيتم حذف <b>كل</b> الأرقام (المتاحة والمباعة) مع كل ملفات الـ session نهائياً.\n"
        "هذا الإجراء <b>لا يمكن التراجع عنه</b>.\n\n"
        "هل أنت متأكد؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، حذف الكل نهائياً", callback_data="adm_num_clear_all_confirm")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="adm_num_delete_menu")],
        ]),
        parse_mode="HTML"
    )


async def adm_num_clear_all_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    db.delete_all_numbers()
    db.log_admin_action(update.effective_user.id, "حذف كل الأرقام الجاهزة", "حذف شامل (متاح + مباع)")
    await update.callback_query.answer("✅ تم حذف كل الأرقام الجاهزة", show_alert=True)
    await adm_numbers_callback(update, context)


async def adm_num_del_phone_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("adm_state") != "waiting_num_del_phone":
        return False
    phone = (update.message.text or "").strip()
    context.user_data.pop("adm_state", None)
    db = context.bot_data["db"]
    ok = db.delete_number_by_phone(phone)
    if ok:
        await update.message.reply_text("✅ تم حذف <code>{}</code>".format(phone), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ الرقم غير موجود: <code>{}</code>".format(phone), parse_mode="HTML")
    return True


# ══════════════════════════════════════════════════════════
#  رفع الملفات
# ══════════════════════════════════════════════════════════

async def adm_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_sessions"
    context.user_data.pop("upload_category", None)
    db = context.bot_data["db"]
    cats = db.get_categories()
    rows = []
    for cat in cats:
        rows.append([InlineKeyboardButton(
            "📦 {}".format(cat), callback_data="adm_upload_cat_{}".format(cat)
        )])
    rows.append([InlineKeyboardButton("➕ فئة جديدة", callback_data="adm_upload_newcat")])
    rows.append([InlineKeyboardButton("🌍 رفع عادي (تقسيم حسب الدولة)", callback_data="adm_upload_normal")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_numbers")])
    await update.callback_query.edit_message_text(
        "📤 <b>رفع ملفات الأرقام</b>\n\n"
        "اختر طريقة الرفع:\n\n"
        "🌍 <b>رفع عادي</b>: كل رقم يُصنَّف حسب دولته تلقائياً\n"
        "📦 <b>فئة مخصصة</b>: كل الملفات في الـ ZIP توضع تحت فئة واحدة باسمها، بدون تقسيم على الدول",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML"
    )


async def adm_upload_normal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_sessions"
    context.user_data.pop("upload_category", None)
    await update.callback_query.edit_message_text(
        "📤 <b>رفع ملفات الأرقام — تقسيم حسب الدولة</b>\n\n"
        "أرسل:\n"
        "• ملف <code>.session</code> مباشرة\n"
        "• ملف <code>.zip</code> يحتوي على sessions\n"
        "• ZIP داخل ZIP مدعوم ✅\n"
        "• يقرأ 2FA من JSON تلقائياً ✅\n\n"
        "يمكنك إرسال عدة ملفات متتالية. اضغط رجوع عند الانتهاء:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_upload")]]),
        parse_mode="HTML"
    )


async def adm_upload_newcat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_new_category"
    await update.callback_query.edit_message_text(
        "➕ <b>فئة جديدة</b>\n\n"
        "أرسل اسم الفئة (مثال: <code>أرقام مميزة</code> أو <code>VIP</code>):\n\n"
        "كل الأرقام التي ترفعها لهذه الفئة ستظهر تحت اسمها بدلاً من تقسيمها حسب الدول.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_upload")]]),
        parse_mode="HTML"
    )


async def adm_upload_cat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    cat = update.callback_query.data.replace("adm_upload_cat_", "", 1)
    context.user_data["adm_state"]    = "waiting_sessions"
    context.user_data["upload_category"] = cat
    await update.callback_query.edit_message_text(
        "📤 <b>رفع ملفات للفئة: 📦 {}</b>\n\n"
        "أرسل ملف <code>.session</code> أو <code>.zip</code>.\n"
        "كل الأرقام داخل الملف ستوضع تحت هذه الفئة بدون تقسيم على الدول.\n\n"
        "يمكنك إرسال عدة ملفات متتالية. اضغط رجوع عند الانتهاء:".format(cat),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_upload")]]),
        parse_mode="HTML"
    )


async def adm_new_category_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("adm_state") != "waiting_new_category":
        return False
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("❌ اسم غير صالح."); return True
    context.user_data["adm_state"]       = "waiting_sessions"
    context.user_data["upload_category"] = name
    await update.message.reply_text(
        "✅ <b>تم إنشاء الفئة: 📦 {}</b>\n\n"
        "أرسل ملفات <code>.session</code> أو <code>.zip</code> الآن، "
        "وستوضع جميعها تحت هذه الفئة.\n\n"
        "اضغط /admin للرجوع عند الانتهاء.".format(name),
        parse_mode="HTML"
    )
    return True


def _extract_sessions_recursive(zip_bytes: bytes) -> list:
    """
    يفتح ZIP (مهما كان عمق التداخل: zip في zip في فولدر...)
    ويرجع قائمة (session_bytes, session_filename, extra_files_dict)
    extra_files_dict = {filename: bytes} لكل الملفات المجاورة (json, txt...) في نفس المجلد/الأرشيف
    """
    results = []
    try:
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            for n in names:
                if n.endswith(".session"):
                    sdata  = zf.read(n)
                    sname  = os.path.basename(n)
                    folder = n.rsplit("/", 1)[0] if "/" in n else ""
                    base   = sname[:-len(".session")]  # الاسم بدون الامتداد، للمطابقة
                    extra  = {}
                    for sib in names:
                        if sib == n:
                            continue
                        sib_folder = sib.rsplit("/", 1)[0] if "/" in sib else ""
                        if sib_folder != folder:
                            continue
                        if sib.endswith(".session") or sib.endswith(".zip"):
                            continue
                        sib_base = os.path.basename(sib).rsplit(".", 1)[0]
                        # نأخذ الملفات المطابقة لاسم نفس الرقم، أو ملفات عامة (2fa.txt, info.json...)
                        is_match  = (sib_base == base or sib_base.lstrip("+") == base.lstrip("+"))
                        is_generic = "2fa" in sib_base.lower() or sib_base.lower() in ("info", "data", "config")
                        if is_match or is_generic:
                            try: extra[os.path.basename(sib)] = zf.read(sib)
                            except Exception: pass
                    results.append((sdata, sname, extra))
                elif n.endswith(".zip"):
                    try:
                        inner_data = zf.read(n)
                        results.extend(_extract_sessions_recursive(inner_data))
                    except Exception:
                        pass
    except Exception:
        pass
    return results


async def adm_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("adm_state") != "waiting_sessions":
        return False
    db  = context.bot_data["db"]
    doc = update.message.document
    if not doc:
        return False
    fname    = doc.file_name or ""
    category = context.user_data.get("upload_category")  # None = تقسيم عادي حسب الدولة
    file  = await doc.get_file()
    data  = await file.download_as_bytearray()
    added = 0; skipped = 0; twofa_count = 0

    if fname.endswith(".session"):
        r = _process_session(db, bytes(data), fname, category=category)
        added += r["added"]; skipped += r["skipped"]
        twofa_count += int(r.get("twofa", False))

    elif fname.endswith(".zip"):
        try:
            sessions = _extract_sessions_recursive(bytes(data))
        except Exception as e:
            await update.message.reply_text("❌ خطأ في ZIP: {}".format(e))
            return True
        for sdata, sname, extra in sessions:
            r = _process_session(db, sdata, sname, extra_files=extra, category=category)
            added += r["added"]; skipped += r["skipped"]
            twofa_count += int(r.get("twofa", False))

    cat_line = "📦 الفئة: <b>{}</b>\n".format(category) if category else ""
    await update.message.reply_text(
        "✅ <b>تمت المعالجة</b>\n\n"
        "{}"
        "➕ أُضيف: <b>{}</b>\n"
        "🔐 منهم 2FA: <b>{}</b>\n"
        "⏭ موجود مسبقاً: <b>{}</b>".format(cat_line, added, twofa_count, skipped),
        parse_mode="HTML"
    )
    return True


def _process_session(db, data: bytes, filename: str, extra_files: dict = None, category: str = None) -> dict:
    import sqlite3 as sq, json as _json
    phone        = filename.replace(".session", "").split("/")[-1].split("\\")[-1]
    phone        = phone.lstrip("+")  # توحيد الصيغة: بدون + في التخزين (يُضاف عند العرض)
    sessions_dir = "sessions"
    os.makedirs(sessions_dir, exist_ok=True)
    session_path = os.path.join(sessions_dir, "{}.session".format(phone))

    # لو موجود بالفعل — نحدث الـ DB بس (add_number بتعمل UPDATE)
    skipped = 1 if os.path.exists(session_path) else 0
    with open(session_path, "wb") as f:
        f.write(data)

    twofa = None

    def _find_twofa(obj):
        """يبحث عن قيمة 2FA في أي مستوى من JSON بأي اسم حقل معروف"""
        keys = (
            "twoFA", "twofa", "two_fa", "TwoFA", "2fa", "2FA",
            "password", "Password", "cloud_password", "cloudPassword",
            "twoFaPass", "2fa_password", "2faPassword"
        )
        if isinstance(obj, dict):
            for k in keys:
                v = obj.get(k)
                if v and str(v).strip():
                    return str(v).strip()
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    r = _find_twofa(v)
                    if r: return r
        elif isinstance(obj, list):
            for item in obj:
                r = _find_twofa(item)
                if r: return r
        return None

    if extra_files:
        for fname, fdata in extra_files.items():
            if fname.endswith(".json"):
                try:
                    jdata = _json.loads(fdata.decode("utf-8", errors="ignore"))
                    twofa = _find_twofa(jdata)
                    if twofa: break
                except Exception: pass
        if not twofa:
            for fname, fdata in extra_files.items():
                if "2fa" in fname.lower() and fname.endswith(".txt"):
                    val = fdata.decode("utf-8", errors="ignore").strip()
                    if val:
                        twofa = val
                        break

    # إصلاح ترتيب أعمدة session — Telethon المثبت يتوقع 5 أعمدة فقط
    # (dc_id, server_address, port, auth_key, takeout_id) بدون tmp_auth_key
    try:
        fix = sq.connect(session_path)
        cols = [r[1] for r in fix.execute("PRAGMA table_info(sessions)").fetchall()]
        if len(cols) == 6 and "tmp_auth_key" in cols:
            fix.execute("ALTER TABLE sessions RENAME TO sessions_old")
            fix.execute("CREATE TABLE sessions (dc_id integer primary key, server_address text, port integer, auth_key blob, takeout_id integer)")
            fix.execute("INSERT INTO sessions(dc_id,server_address,port,auth_key,takeout_id) "
                        "SELECT dc_id,server_address,port,auth_key,takeout_id FROM sessions_old")
            fix.execute("DROP TABLE sessions_old")
            fix.commit()
        fix.close()
    except Exception: pass

    if category:
        # فئة مخصصة — لا يتم تقسيمها حسب الدولة
        cc, flag, cname = "CAT_{}".format(category), "📦", category
    else:
        cc, flag, cname = detect_country(phone)

    db.add_number(phone, cc, cname, flag, session_path, twofa=twofa)
    return {"added": 1, "skipped": skipped, "twofa": bool(twofa)}


# ══════════════════════════════════════════════════════════
#  الأسعار
# ══════════════════════════════════════════════════════════

async def adm_prices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    grouped = db.get_all_numbers_grouped()
    prices  = db.get_all_prices()
    default = db.get_setting("default_price", "0.5")
    text    = "💰 <b>الأسعار</b>\n\nافتراضي: <b>${}</b>\n\n".format(default)
    rows    = []
    for cc, nums in sorted(grouped.items()):
        flag  = nums[0]["country_flag"]
        cname = nums[0]["country_name"]
        price = prices.get(cc, float(default))
        avail = sum(1 for n in nums if n["status"] == "available")
        text += "{} {} — <b>${:.3f}</b> ({} متاح)\n".format(flag, cname, price, avail)
        rows.append([InlineKeyboardButton(
            "{} {} — ${:.3f}".format(flag, cname, price),
            callback_data="adm_setprice_{}".format(cc)
        )])
    rows.append([InlineKeyboardButton("💰 السعر الافتراضي", callback_data="adm_default_price")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")


async def adm_setprice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    cc   = update.callback_query.data.replace("adm_setprice_", "")
    if cc.startswith("CAT_"):
        flag, cname = "📦", cc[4:]
    else:
        flag, cname = COUNTRY_DATA.get(cc, ("🌍", cc))
    context.user_data["adm_state"]    = "waiting_price"
    context.user_data["adm_price_cc"] = cc
    await update.callback_query.edit_message_text(
        "{} <b>{}</b>\n\nأرسل السعر الجديد (مثال: <code>0.5</code>):".format(flag, cname),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_prices")]]),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  ZIP تحميل
# ══════════════════════════════════════════════════════════

async def adm_zip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    data = update.callback_query.data
    if data == "adm_zip_all":
        nums    = [n for ns in db.get_all_numbers_grouped().values() for n in ns]
        label   = "all_sessions"
        caption = "📦 كل الأرقام — {} ملف".format(len(nums))
    else:
        cc      = data.replace("adm_zip_", "")
        nums    = db.get_numbers_by_country(cc)
        if cc.startswith("CAT_"):
            flag, cname = "📦", cc[4:]
        else:
            flag, cname = COUNTRY_DATA.get(cc, ("🌍", cc))
        label   = "sessions_{}".format(cc)
        caption = "📦 {} {} — {} ملف".format(flag, cname, len(nums))
    if not nums:
        await update.callback_query.answer("لا توجد ملفات", show_alert=True)
        return
    await update.callback_query.answer("📦 جارٍ الإنشاء...")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in nums:
            path = n["session_path"]
            if os.path.exists(path):
                zf.write(path, arcname="{}.session".format(n["phone"]))
    buf.seek(0)
    await update.effective_message.reply_document(
        document=buf, filename="{}.zip".format(label), caption=caption
    )


# ══════════════════════════════════════════════════════════
#  الطلبات
# ══════════════════════════════════════════════════════════

async def adm_orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db     = context.bot_data["db"]
    orders = db.get_recent_orders(limit=15)
    if not orders:
        text = "📋 <b>الطلبات</b>\n\nلا توجد طلبات."
    else:
        text = "📋 <b>آخر {} طلبات</b>\n\n".format(len(orders))
        for o in orders:
            code   = o.get("otp_code") or "⏳"
            status = {"completed": "✅", "pending": "⏳", "cancelled": "❌"}.get(o["status"], "❓")
            text  += "{} #{} | <code>+{}</code> | {} | ${:.2f}\n".format(
                status, o["id"], o["phone"], code, o["cost"])
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  الشحن
# ══════════════════════════════════════════════════════════

async def adm_deposits_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    deps = db.get_pending_deposits()
    if not deps:
        text = "💳 <b>الشحن</b>\n\nلا توجد طلبات معلقة."
        kb   = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]])
    else:
        text = "💳 <b>طلبات شحن معلقة</b> ({})\n\n".format(len(deps))
        rows = []
        for d in deps:
            text += "#{} | {} | <code>{}</code> | ${:.2f}\n".format(
                d["id"], d["method"], d["txid"] or "—", d["amount"])
            rows.append([
                InlineKeyboardButton("✅ #{}".format(d["id"]), callback_data="adm_dep_ok_{}".format(d["id"])),
                InlineKeyboardButton("❌ #{}".format(d["id"]), callback_data="adm_dep_no_{}".format(d["id"])),
            ])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")])
        kb = InlineKeyboardMarkup(rows)
    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")


async def adm_dep_ok_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db     = context.bot_data["db"]
    dep_id = int(update.callback_query.data.replace("adm_dep_ok_", ""))
    dep    = db.get_deposit(dep_id)
    if not dep:
        await update.callback_query.answer("❌ غير موجود", show_alert=True); return
    db.approve_deposit(dep_id)
    await update.callback_query.answer("✅ تم القبول", show_alert=True)
    # إشعار قناة الشحن
    ch = db.get_setting("deposit_channel", "")
    if ch and ch.strip() not in ("", "0"):
        try:
            await context.bot.send_message(
                chat_id=int(ch),
                text="✅ <b>شحن مقبول</b>\n\n👤 المستخدم: <code>{}</code>\n💰 المبلغ: <b>${:.3f}</b>\n💳 الطريقة: {}".format(
                    dep["user_tg_id"], dep["amount"], dep["method"]),
                parse_mode="HTML"
            )
        except Exception: pass
    try:
        await context.bot.send_message(
            chat_id=dep["user_tg_id"],
            text="✅ <b>تم إضافة رصيدك</b>\n\nالمبلغ: <b>${:.3f}</b>\nطريقة الدفع: {}".format(
                dep["amount"], dep["method"]),
            parse_mode="HTML"
        )
    except Exception: pass


async def adm_dep_no_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db     = context.bot_data["db"]
    dep_id = int(update.callback_query.data.replace("adm_dep_no_", ""))
    dep    = db.get_deposit(dep_id)
    if not dep:
        await update.callback_query.answer("❌ غير موجود", show_alert=True); return
    db.reject_deposit(dep_id)
    await update.callback_query.answer("❌ تم الرفض", show_alert=True)
    try:
        await context.bot.send_message(
            chat_id=dep["user_tg_id"],
            text="❌ <b>تم رفض طلب الشحن</b>\n\nتواصل مع الدعم لمزيد من المعلومات.",
            parse_mode="HTML"
        )
    except Exception: pass


# ══════════════════════════════════════════════════════════
#  إدارة المستخدمين — رصيد / حظر
# ══════════════════════════════════════════════════════════

async def adm_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    await update.callback_query.edit_message_text(
        "👥 <b>إدارة المستخدمين</b>\n\nأرسل ID المستخدم أو @username للبحث:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]
        ]),
        parse_mode="HTML"
    )
    context.user_data["adm_state"] = "waiting_user_search"


async def _show_user_panel(update, context, user: dict):
    """يعرض لوحة التحكم الخاصة بمستخدم"""
    uid    = user["tg_id"]
    uname  = "@" + user["username"] if user.get("username") else "—"
    fname  = user.get("first_name") or "—"
    bal    = user["balance"]
    banned = bool(user.get("is_banned"))
    ban_btn = "🔓 إلغاء الحظر" if banned else "🚫 حظر"
    ban_cb  = "adm_unban_{}".format(uid) if banned else "adm_ban_{}".format(uid)
    await update.effective_message.reply_text(
        "👤 <b>بيانات المستخدم</b>\n\n"
        "🆔 ID: <code>{}</code>\n"
        "👤 الاسم: {}\n"
        "📛 يوزر: {}\n"
        "💰 الرصيد: <b>${:.3f}</b>\n"
        "🚫 محظور: <b>{}</b>".format(uid, fname, uname, bal, "نعم" if banned else "لا"),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ إضافة رصيد",  callback_data="adm_addbal_{}".format(uid)),
                InlineKeyboardButton("➖ خصم رصيد",   callback_data="adm_subbal_{}".format(uid)),
            ],
            [
                InlineKeyboardButton("💰 تعيين رصيد",  callback_data="adm_setbal_{}".format(uid)),
                InlineKeyboardButton(ban_btn,           callback_data=ban_cb),
            ],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_users")],
        ]),
        parse_mode="HTML"
    )


async def adm_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db  = context.bot_data["db"]
    uid = int(update.callback_query.data.replace("adm_ban_", ""))
    db.ban_user(uid)
    db.log_admin_action(update.effective_user.id, "حظر مستخدم", "UID: {}".format(uid))
    await update.callback_query.answer("🚫 تم الحظر", show_alert=True)
    try:
        await context.bot.send_message(uid, "🚫 <b>تم حظر حسابك.</b>\nتواصل مع الدعم.", parse_mode="HTML")
    except Exception: pass
    user = db.get_user(uid)
    if user: await _show_user_panel(update, context, user)


async def adm_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db  = context.bot_data["db"]
    uid = int(update.callback_query.data.replace("adm_unban_", ""))
    db.unban_user(uid)
    db.log_admin_action(update.effective_user.id, "رفع حظر مستخدم", "UID: {}".format(uid))
    await update.callback_query.answer("✅ تم رفع الحظر", show_alert=True)
    try:
        await context.bot.send_message(uid, "✅ <b>تم رفع الحظر عن حسابك.</b>", parse_mode="HTML")
    except Exception: pass
    user = db.get_user(uid)
    if user: await _show_user_panel(update, context, user)


async def adm_addbal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    uid = int(update.callback_query.data.replace("adm_addbal_", ""))
    context.user_data["adm_state"]      = "waiting_addbal"
    context.user_data["adm_target_uid"] = uid
    await update.callback_query.edit_message_text(
        "➕ <b>إضافة رصيد</b>\n\nللمستخدم: <code>{}</code>\nأرسل المبلغ:".format(uid),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users")]]),
        parse_mode="HTML"
    )


async def adm_subbal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    uid = int(update.callback_query.data.replace("adm_subbal_", ""))
    context.user_data["adm_state"]      = "waiting_subbal"
    context.user_data["adm_target_uid"] = uid
    await update.callback_query.edit_message_text(
        "➖ <b>خصم رصيد</b>\n\nللمستخدم: <code>{}</code>\nأرسل المبلغ:".format(uid),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users")]]),
        parse_mode="HTML"
    )


async def adm_setbal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    uid = int(update.callback_query.data.replace("adm_setbal_", ""))
    context.user_data["adm_state"]      = "waiting_setbal"
    context.user_data["adm_target_uid"] = uid
    await update.callback_query.edit_message_text(
        "💰 <b>تعيين رصيد</b>\n\nللمستخدم: <code>{}</code>\nأرسل الرصيد الجديد:".format(uid),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users")]]),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  إشعار جماعي
# ══════════════════════════════════════════════════════════

async def adm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_broadcast"
    await update.callback_query.edit_message_text(
        "📢 <b>إشعار جماعي</b>\n\nأرسل نص الرسالة (يدعم HTML):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  Message handler — كل states
# ══════════════════════════════════════════════════════════

ADMIN_STATES = (
    "waiting_price", "waiting_default_price", "waiting_broadcast",
    "waiting_setting_val", "waiting_user_search",
    "waiting_addbal", "waiting_subbal", "waiting_setbal",
    "waiting_sms_txt", "waiting_sms_price", "waiting_sms_country_price", "waiting_sms_del_phone", "waiting_new_category", "waiting_num_del_phone", "waiting_search_number",
    "waiting_sms_wa_label", "waiting_sms_tg_label",
    "waiting_force_channel",
    "waiting_instructions_ar", "waiting_instructions_en",
    "waiting_link_activation", "waiting_link_main", "waiting_link_support",
    "waiting_coupon_create",
    "waiting_discount_add",
    "waiting_ref_pct", "waiting_ref_min",
    "waiting_report_ch", "waiting_restore_backup",
)


async def adm_price_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("adm_state")
    if state not in ADMIN_STATES:
        return False

    db   = context.bot_data["db"]
    text = (update.message.text or "").strip()

    # ── سعر دولة ──────────────────────────────────────────
    if state == "waiting_price":
        cc = context.user_data.get("adm_price_cc")
        try:
            price = float(text.replace(",", "."))
            if price <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ أرسل رقم صحيح"); return True
        db.set_price(cc, price)
        if cc.startswith("CAT_"):
            flag, cname = "📦", cc[4:]
        else:
            flag, cname = COUNTRY_DATA.get(cc, ("🌍", cc))
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("{} {} → <b>${:.4f}</b> ✅".format(flag, cname, price), parse_mode="HTML")

    # ── سعر افتراضي ──────────────────────────────────────
    elif state == "waiting_default_price":
        try:
            price = float(text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("❌ أرسل رقم صحيح"); return True
        db.set_setting("default_price", str(price))
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("✅ السعر الافتراضي: <b>${:.4f}</b>".format(price), parse_mode="HTML")

    # ── إشعار جماعي ──────────────────────────────────────
    elif state == "waiting_broadcast":
        users  = db.get_all_users()
        sent   = 0; failed = 0
        for u in users:
            if u.get("is_banned"): continue
            try:
                await context.bot.send_message(u["tg_id"], text, parse_mode="HTML")
                sent += 1
            except Exception:
                failed += 1
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("📢 أُرسل\n✅ {}\n❌ {}".format(sent, failed))

    # ── إعداد عام ─────────────────────────────────────────
    elif state == "waiting_setting_val":
        key = context.user_data.pop("adm_setting_key", None)
        if key:
            db.set_setting(key, text)
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("✅ تم الحفظ")

    # ── اسم التطبيق الأول (واتساب) ───────────────────────
    elif state == "waiting_sms_wa_label":
        if not text:
            await update.message.reply_text("❌ أرسل اسماً صحيحاً"); return True
        db.set_setting("sms_wa_label", text)
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("✅ اسم التطبيق الأول: <b>{}</b>".format(text), parse_mode="HTML")

    # ── اسم التطبيق الثاني (تيليجرام) ───────────────────
    elif state == "waiting_sms_tg_label":
        if not text:
            await update.message.reply_text("❌ أرسل اسماً صحيحاً"); return True
        db.set_setting("sms_tg_label", text)
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("✅ اسم التطبيق الثاني: <b>{}</b>".format(text), parse_mode="HTML")

    # ── بحث مستخدم ───────────────────────────────────────
    elif state == "waiting_user_search":
        user = db.search_user(text)
        if not user:
            await update.message.reply_text("❌ المستخدم غير موجود")
            return True
        context.user_data.pop("adm_state", None)
        await _show_user_panel(update, context, user)

    # ── إضافة رصيد ───────────────────────────────────────
    elif state == "waiting_addbal":
        uid = context.user_data.pop("adm_target_uid", None)
        context.user_data.pop("adm_state", None)
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ أرسل رقم صحيح"); return True
        db.add_balance(uid, amount)
        new_bal = db.get_balance(uid)
        db.log_admin_action(update.effective_user.id, "إضافة رصيد",
                             "UID: {} | +${:.3f} | الرصيد الجديد: ${:.3f}".format(uid, amount, new_bal))
        await update.message.reply_text(
            "✅ أُضيف <b>${:.3f}</b> للمستخدم <code>{}</code>\nالرصيد الجديد: <b>${:.3f}</b>".format(
                amount, uid, new_bal), parse_mode="HTML")
        try:
            await context.bot.send_message(
                uid, "✅ <b>تم إضافة ${:.3f} لرصيدك</b>\nرصيدك الحالي: <b>${:.3f}</b>".format(
                    amount, new_bal), parse_mode="HTML")
        except Exception: pass

    # ── خصم رصيد ─────────────────────────────────────────
    elif state == "waiting_subbal":
        uid = context.user_data.pop("adm_target_uid", None)
        context.user_data.pop("adm_state", None)
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ أرسل رقم صحيح"); return True
        db.add_balance(uid, -amount)
        new_bal = db.get_balance(uid)
        db.log_admin_action(update.effective_user.id, "خصم رصيد",
                             "UID: {} | -${:.3f} | الرصيد الجديد: ${:.3f}".format(uid, amount, new_bal))
        await update.message.reply_text(
            "✅ خُصم <b>${:.3f}</b> من المستخدم <code>{}</code>\nالرصيد الجديد: <b>${:.3f}</b>".format(
                amount, uid, new_bal), parse_mode="HTML")

    # ── تعيين رصيد ───────────────────────────────────────
    elif state == "waiting_setbal":
        uid = context.user_data.pop("adm_target_uid", None)
        context.user_data.pop("adm_state", None)
        try:
            amount = float(text.replace(",", "."))
            if amount < 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ أرسل رقم صحيح"); return True
        db.set_balance(uid, amount)
        db.log_admin_action(update.effective_user.id, "تعيين رصيد",
                             "UID: {} | الرصيد = ${:.3f}".format(uid, amount))
        await update.message.reply_text(
            "✅ رصيد <code>{}</code> = <b>${:.3f}</b>".format(uid, amount), parse_mode="HTML")

    return True


# ══════════════════════════════════════════════════════════
#  الإعدادات
# ══════════════════════════════════════════════════════════

async def adm_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    await update.callback_query.edit_message_text(
        "⚙️ <b>الإعدادات</b>\n\nاختر القسم:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ نجوم تيليجرام",    callback_data="adm_cfg_stars")],
            [InlineKeyboardButton("🟡 Binance Pay",       callback_data="adm_cfg_binance")],
            [InlineKeyboardButton("💎 BEP20 (USDT)",     callback_data="adm_cfg_bep20")],
            [InlineKeyboardButton("💎 TRC20 (USDT)",     callback_data="adm_cfg_trc20")],
            [InlineKeyboardButton("💎 TON",               callback_data="adm_cfg_ton")],
            [InlineKeyboardButton("💎 TRX",               callback_data="adm_cfg_trx")],
            [InlineKeyboardButton("📱 فودافون كاش",      callback_data="adm_cfg_vod")],
            [InlineKeyboardButton("📢 قنوات الإشعارات",  callback_data="adm_cfg_channels")],
            [InlineKeyboardButton("📌 اشتراك إجباري",    callback_data="adm_cfg_force_sub")],
            [InlineKeyboardButton("📖 التعليمات",         callback_data="adm_cfg_instructions")],
            [InlineKeyboardButton("🔗 روابط وقنوات",     callback_data="adm_cfg_links")],
            [InlineKeyboardButton("🎟️ الكوبونات",        callback_data="adm_coupons")],
            [InlineKeyboardButton("🏷️ الخصم التلقائي",   callback_data="adm_discounts")],
            [InlineKeyboardButton("🤝 الإحالة",           callback_data="adm_referral_settings")],
            [InlineKeyboardButton("📊 التقارير والبكاب",  callback_data="adm_report_settings")],
            [InlineKeyboardButton("🔙 رجوع",              callback_data="adm_main")],
        ]),
        parse_mode="HTML"
    )


async def adm_cfg_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعداد القنوات الثلاث"""
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    notify  = db.get_setting("notify_channel",  "") or "غير محدد"
    deposit = db.get_setting("deposit_channel", "") or "غير محدد"
    newuser = db.get_setting("newuser_channel", "") or "غير محدد"
    await update.callback_query.edit_message_text(
        "📢 <b>القنوات</b>\n\n"
        "🔔 <b>قناة التفعيلات:</b> <code>{}</code>\n"
        "💳 <b>قناة تقارير الشحن:</b> <code>{}</code>\n"
        "👤 <b>قناة المستخدمين الجدد:</b> <code>{}</code>\n\n"
        "أرسل ID القناة بالشكل: <code>-1001234567890</code>".format(notify, deposit, newuser),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ قناة التفعيلات",        callback_data="adm_set_notify_channel")],
            [InlineKeyboardButton("✏️ قناة تقارير الشحن",     callback_data="adm_set_deposit_channel")],
            [InlineKeyboardButton("✏️ قناة المستخدمين الجدد", callback_data="adm_set_newuser_channel")],
            [InlineKeyboardButton("🗑 مسح الكل", callback_data="adm_clear_channels")],
            [InlineKeyboardButton("🔙 رجوع",    callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_clear_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    db.set_setting("notify_channel", "")
    db.set_setting("deposit_channel", "")
    db.set_setting("newuser_channel", "")
    await update.callback_query.answer("🗑 تم مسح كل القنوات", show_alert=True)
    update.callback_query.data = "adm_cfg_channels"
    await adm_cfg_channels_callback(update, context)


async def adm_cfg_stars_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    on = db.get_setting("pay_stars", "0")
    rate = db.get_setting("stars_rate", "85")
    min_usd = db.get_setting("stars_min_usd", "1")
    await update.callback_query.edit_message_text(
        "⭐ <b>نجوم تيليجرام</b>\n\n"
        "الحالة: <b>{}</b>\n"
        "💱 نجمة بالدولار: <b>{} نجمة = $1</b>\n"
        "💰 حد أدنى: <b>${}</b>".format(_yn(on), rate, min_usd),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل" if on=="1" else "🟢 تفعيل", callback_data="adm_toggle_pay_stars")],
            [InlineKeyboardButton("✏️ نجمة/$", callback_data="adm_set_stars_rate")],
            [InlineKeyboardButton("✏️ حد أدنى $", callback_data="adm_set_stars_min_usd")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_cfg_binance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    on     = db.get_setting("pay_binance", "0")
    pay_id = db.get_setting("binance_pay_id", "")
    ak     = db.get_setting("binance_api_key", "")
    asc    = db.get_setting("binance_api_secret", "")
    min_v  = db.get_setting("binance_min_usd", "0.01")
    await update.callback_query.edit_message_text(
        "🟡 <b>Binance Pay</b>\n\n"
        "الحالة: <b>{}</b>\n"
        "💰 الحد الأدنى: <b>${}</b>\n\n"
        "📋 <b>Pay ID (UID):</b> <code>{}</code>\n"
        "<i>هذا هو المعرف اللي المستخدم يحول عليه</i>\n\n"
        "🔑 <b>API Key:</b> <code>{}</code>\n"
        "🔒 <b>API Secret:</b> <code>{}</code>\n"
        "<i>للتحقق التلقائي — اختياري</i>".format(
            _yn(on), min_v, pay_id or "غير محدد", _short(ak), _short(asc)),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل" if on=="1" else "🟢 تفعيل", callback_data="adm_toggle_pay_binance")],
            [InlineKeyboardButton("✏️ Pay ID (UID)",  callback_data="adm_set_binance_pay_id"),
             InlineKeyboardButton("💰 حد أدنى $",     callback_data="adm_set_binance_min_usd")],
            [InlineKeyboardButton("✏️ API Key",        callback_data="adm_set_binance_api_key"),
             InlineKeyboardButton("✏️ API Secret",     callback_data="adm_set_binance_api_secret")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_cfg_bep20_callback(update, context):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    on   = db.get_setting("pay_bep20", "0")
    addr = db.get_setting("bep20_address", "")
    min_v = db.get_setting("bep20_min_usdt", "1")
    await update.callback_query.edit_message_text(
        "💎 <b>BEP20 (USDT)</b>\n\n"
        "الحالة: <b>{}</b>\n"
        "💰 الحد الأدنى: <b>${} USDT</b>\n"
        "📋 العنوان: <code>{}</code>".format(_yn(on), min_v, addr or "غير محدد"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل" if on=="1" else "🟢 تفعيل", callback_data="adm_toggle_pay_bep20")],
            [InlineKeyboardButton("✏️ عنوان المحفظة", callback_data="adm_set_bep20_address"),
             InlineKeyboardButton("💰 حد أدنى $",     callback_data="adm_set_bep20_min_usdt")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_cfg_trc20_callback(update, context):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    on   = db.get_setting("pay_trc20", "0")
    addr = db.get_setting("trc20_address", "")
    ak   = db.get_setting("trc20_api_key", "")
    min_v = db.get_setting("trc20_min_usdt", "1")
    await update.callback_query.edit_message_text(
        "💎 <b>TRC20 (USDT)</b>\n\n"
        "الحالة: <b>{}</b>\n"
        "💰 الحد الأدنى: <b>${} USDT</b>\n"
        "📋 العنوان: <code>{}</code>\n"
        "🔑 API Key: <code>{}</code>".format(_yn(on), min_v, addr or "غير محدد", _short(ak)),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل" if on=="1" else "🟢 تفعيل", callback_data="adm_toggle_pay_trc20")],
            [InlineKeyboardButton("✏️ عنوان المحفظة",    callback_data="adm_set_trc20_address"),
             InlineKeyboardButton("💰 حد أدنى $",         callback_data="adm_set_trc20_min_usdt")],
            [InlineKeyboardButton("✏️ Trongrid API Key", callback_data="adm_set_trc20_api_key")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_cfg_ton_callback(update, context):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    on   = db.get_setting("pay_ton", "0")
    addr = db.get_setting("ton_address", "")
    min_v = db.get_setting("ton_min_amount", "1")
    await update.callback_query.edit_message_text(
        "💎 <b>TON</b>\n\n"
        "الحالة: <b>{}</b>\n"
        "💰 الحد الأدنى: <b>{} TON</b>\n"
        "📋 العنوان: <code>{}</code>".format(_yn(on), min_v, addr or "غير محدد"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل" if on=="1" else "🟢 تفعيل", callback_data="adm_toggle_pay_ton")],
            [InlineKeyboardButton("✏️ عنوان المحفظة", callback_data="adm_set_ton_address"),
             InlineKeyboardButton("💰 حد أدنى TON",   callback_data="adm_set_ton_min_amount")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_cfg_trx_callback(update, context):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    on   = db.get_setting("pay_trx", "0")
    addr = db.get_setting("trx_address", "")
    min_v = db.get_setting("trx_min_amount", "10")
    await update.callback_query.edit_message_text(
        "🔴 <b>TRX</b>\n\n"
        "الحالة: <b>{}</b>\n"
        "💰 الحد الأدنى: <b>{} TRX</b>\n"
        "📋 العنوان: <code>{}</code>".format(_yn(on), min_v, addr or "غير محدد"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل" if on=="1" else "🟢 تفعيل", callback_data="adm_toggle_pay_trx")],
            [InlineKeyboardButton("✏️ عنوان المحفظة", callback_data="adm_set_trx_address"),
             InlineKeyboardButton("💰 حد أدنى TRX",   callback_data="adm_set_trx_min_amount")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_cfg_vod_callback(update, context):
    if not is_admin(update, context): return
    db    = context.bot_data["db"]
    on    = db.get_setting("pay_vodafone_auto", "0")
    phone = db.get_setting("vodafone_number", "")
    uid   = db.get_setting("autocash_user_id", "")
    pid   = db.get_setting("autocash_panel_id", "")
    min_v = db.get_setting("vod_auto_min_egp", "50")
    await update.callback_query.edit_message_text(
        "📱 <b>فودافون كاش</b>\n\n"
        "الحالة: <b>{}</b>\n"
        "💰 الحد الأدنى: <b>{} جنيه</b>\n"
        "📞 الرقم: <b>{}</b>\n"
        "🆔 User ID: <b>{}</b>\n"
        "🆔 Panel ID: <b>{}</b>".format(
            _yn(on), min_v, phone or "غير محدد", uid or "غير محدد", pid or "غير محدد"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل" if on=="1" else "🟢 تفعيل", callback_data="adm_toggle_pay_vodafone_auto")],
            [InlineKeyboardButton("✏️ رقم الاستلام",     callback_data="adm_set_vodafone_number"),
             InlineKeyboardButton("💰 حد أدنى جنيه",     callback_data="adm_set_vod_auto_min_egp")],
            [InlineKeyboardButton("✏️ AutoCash User ID",  callback_data="adm_set_autocash_user_id"),
             InlineKeyboardButton("✏️ AutoCash Panel ID", callback_data="adm_set_autocash_panel_id")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


# قناة الإشعارات (للتوافق مع الكود القديم)
async def adm_cfg_notify_callback(update, context):
    update.callback_query.data = "adm_cfg_channels"
    await adm_cfg_channels_callback(update, context)


# ── Toggle ─────────────────────────────────────────────────
_TOGGLE_GUARDS = {
    "pay_stars":         lambda db: True,
    "pay_binance":       lambda db: bool(db.get_setting("binance_pay_id","").strip()),
    "pay_bep20":         lambda db: bool(db.get_setting("bep20_address","").strip()),
    "pay_trc20":         lambda db: bool(db.get_setting("trc20_address","").strip()) and bool(db.get_setting("trc20_api_key","").strip()),
    "pay_ton":           lambda db: bool(db.get_setting("ton_address","").strip()),
    "pay_trx":           lambda db: bool(db.get_setting("trx_address","").strip()),
    "pay_vodafone_auto": lambda db: (bool(db.get_setting("vodafone_number","").strip())
                                     and bool(db.get_setting("autocash_user_id","").strip())
                                     and bool(db.get_setting("autocash_panel_id","").strip())),
}
_TOGGLE_BACK = {
    "pay_stars":         "adm_cfg_stars",
    "pay_binance":       "adm_cfg_binance",
    "pay_bep20":         "adm_cfg_bep20",
    "pay_trc20":         "adm_cfg_trc20",
    "pay_ton":           "adm_cfg_ton",
    "pay_trx":           "adm_cfg_trx",
    "pay_vodafone_auto": "adm_cfg_vod",
}
_BACK_HANDLER = {}


async def adm_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db  = context.bot_data["db"]
    key = update.callback_query.data.replace("adm_toggle_", "")
    cur = db.get_setting(key, "0")
    if cur != "1":
        guard = _TOGGLE_GUARDS.get(key, lambda db: True)
        if not guard(db):
            await update.callback_query.answer("⚠️ أكمل الإعدادات المطلوبة أولاً", show_alert=True)
            return
        db.set_setting(key, "1")
        await update.callback_query.answer("✅ تم التفعيل", show_alert=True)
    else:
        db.set_setting(key, "0")
        await update.callback_query.answer("🔴 تم التعطيل", show_alert=True)
    back_cb = _TOGGLE_BACK.get(key, "adm_settings")
    update.callback_query.data = back_cb
    handler = _BACK_HANDLER.get(back_cb)
    if handler:
        await handler(update, context)


async def adm_clear_notify_callback(update, context):
    if not is_admin(update, context): return
    context.bot_data["db"].set_setting("notify_channel", "")
    await update.callback_query.answer("🗑 تم المسح", show_alert=True)
    update.callback_query.data = "adm_cfg_channels"
    await adm_cfg_channels_callback(update, context)


async def adm_set_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    key = update.callback_query.data.replace("adm_set_", "")
    context.user_data["adm_state"]       = "waiting_setting_val"
    context.user_data["adm_setting_key"] = key
    await update.callback_query.edit_message_text(
        "⚙️ أرسل القيمة الجديدة لـ <b>{}</b>:".format(key),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_settings")]]),
        parse_mode="HTML"
    )


_BACK_HANDLER.update({
    "adm_cfg_stars":   adm_cfg_stars_callback,
    "adm_cfg_binance": adm_cfg_binance_callback,
    "adm_cfg_bep20":   adm_cfg_bep20_callback,
    "adm_cfg_trc20":   adm_cfg_trc20_callback,
    "adm_cfg_ton":     adm_cfg_ton_callback,
    "adm_cfg_trx":     adm_cfg_trx_callback,
    "adm_cfg_vod":     adm_cfg_vod_callback,
})


# ══════════════════════════════════════════════════════════
#  حذف المباعة (+ ملفات الـ session من القرص)
# ══════════════════════════════════════════════════════════

async def adm_del_sold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db  = context.bot_data["db"]
    raw = update.callback_query.data.replace("adm_del_sold_", "")

    if raw == "ALL":
        # حذف كل المباعة من جميع الدول
        grouped = db.get_all_numbers_grouped()
        count = 0
        for cc, nums in grouped.items():
            for n in nums:
                if n["status"] == "sold":
                    db.delete_number(n["id"])  # يحذف الملف أيضاً
                    count += 1
        await update.callback_query.answer("🗑 حُذف {} رقم مباع من كل الدول".format(count), show_alert=True)
        update.callback_query.data = "adm_numbers"
        await adm_numbers_callback(update, context)
    else:
        cc   = raw
        nums = db.get_numbers_by_country(cc)
        count = 0
        for n in nums:
            if n["status"] == "sold":
                db.delete_number(n["id"])
                count += 1
        await update.callback_query.answer("🗑 حُذف {} رقم + ملفاتهم".format(count), show_alert=True)
        update.callback_query.data = "adm_num_cc_{}".format(cc)
        await adm_num_cc_callback(update, context)


# ══════════════════════════════════════════════════════════
#  قسم أرقام SMS
# ══════════════════════════════════════════════════════════

async def adm_sms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    wa_total  = db.get_sms_total_available("whatsapp")
    tg_total  = db.get_sms_total_available("telegram")
    default   = db.get_setting("sms_price", "0.5")
    wa_label  = db.get_setting("sms_wa_label", "واتساب")
    tg_label  = db.get_setting("sms_tg_label", "تيليجرام")
    await update.callback_query.edit_message_text(
        "📱 <b>إدارة أرقام SMS</b>\n\n"
        "💬 {} متاح: <b>{}</b>\n"
        "✈️ {} متاح: <b>{}</b>\n"
        "💰 السعر الافتراضي: <b>${}</b>".format(wa_label, wa_total, tg_label, tg_total, default),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 رفع ملف {}".format(wa_label),  callback_data="adm_sms_upload_wa")],
            [InlineKeyboardButton("📤 رفع ملف {}".format(tg_label),  callback_data="adm_sms_upload_tg")],
            [InlineKeyboardButton("💰 السعر الافتراضي",              callback_data="adm_sms_price")],
            [InlineKeyboardButton("🌍 سعر دولة محددة",               callback_data="adm_sms_country_price")],
            [InlineKeyboardButton("✏️ تغيير أسماء التطبيقات",        callback_data="adm_sms_app_labels")],
            [InlineKeyboardButton("📋 عرض الأرقام",                  callback_data="adm_sms_list")],
            [InlineKeyboardButton("🗑 حذف أرقام",                    callback_data="adm_sms_delete_menu")],
            [InlineKeyboardButton("🔙 رجوع",                         callback_data="adm_main")],
        ]),
        parse_mode="HTML"
    )


async def adm_sms_upload_wa_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"]    = "waiting_sms_txt"
    context.user_data["sms_app_type"] = "whatsapp"
    await update.callback_query.edit_message_text(
        "📤 <b>رفع ملف أرقام واتساب</b>\n\n"
        "أرسل ملف <code>.txt</code>:\n"
        "<code>+13347795283|https://api.example.com?token=xxx</code>\n"
        "<code>+13673243007----https://smsjs.top/api/sms/record?key=xxx</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms")]]),
        parse_mode="HTML"
    )


async def adm_sms_upload_tg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"]    = "waiting_sms_txt"
    context.user_data["sms_app_type"] = "telegram"
    await update.callback_query.edit_message_text(
        "📤 <b>رفع ملف أرقام تيليجرام SMS</b>\n\n"
        "أرسل ملف <code>.txt</code>:\n"
        "<code>+13347795283|https://api.example.com?token=xxx</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms")]]),
        parse_mode="HTML"
    )


async def adm_sms_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_sms_price"
    current = context.bot_data["db"].get_setting("sms_price", "0.5")
    await update.callback_query.edit_message_text(
        "💰 <b>السعر الافتراضي لأرقام SMS</b>\n\n"
        "السعر الحالي: <b>${}</b>\n\n"
        "أرسل السعر الجديد:".format(current),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms")]]),
        parse_mode="HTML"
    )


async def adm_sms_app_labels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض وتغيير أسماء التطبيقين"""
    if not is_admin(update, context): return
    db       = context.bot_data["db"]
    wa_label = db.get_setting("sms_wa_label", "واتساب")
    tg_label = db.get_setting("sms_tg_label", "تيليجرام")
    await update.callback_query.edit_message_text(
        "✏️ <b>أسماء التطبيقات</b>\n\n"
        "💬 التطبيق الأول (واتساب): <b>{}</b>\n"
        "✈️ التطبيق الثاني (تيليجرام): <b>{}</b>\n\n"
        "اختر التطبيق الذي تريد تغيير اسمه:".format(wa_label, tg_label),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 تغيير اسم التطبيق الأول", callback_data="adm_sms_set_wa_label")],
            [InlineKeyboardButton("✈️ تغيير اسم التطبيق الثاني", callback_data="adm_sms_set_tg_label")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms")],
        ]),
        parse_mode="HTML"
    )


async def adm_sms_set_wa_label_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    current = db.get_setting("sms_wa_label", "واتساب")
    context.user_data["adm_state"] = "waiting_sms_wa_label"
    await update.callback_query.edit_message_text(
        "💬 <b>اسم التطبيق الأول</b>\n\n"
        "الاسم الحالي: <b>{}</b>\n\n"
        "أرسل الاسم الجديد:".format(current),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms_app_labels")]]),
        parse_mode="HTML"
    )


async def adm_sms_set_tg_label_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    current = db.get_setting("sms_tg_label", "تيليجرام")
    context.user_data["adm_state"] = "waiting_sms_tg_label"
    await update.callback_query.edit_message_text(
        "✈️ <b>اسم التطبيق الثاني</b>\n\n"
        "الاسم الحالي: <b>{}</b>\n\n"
        "أرسل الاسم الجديد:".format(current),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms_app_labels")]]),
        parse_mode="HTML"
    )


async def adm_sms_country_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    wa_label     = db.get_setting("sms_wa_label", "واتساب")
    tg_label     = db.get_setting("sms_tg_label", "تيليجرام")
    wa_countries = db.get_sms_countries("whatsapp")
    tg_countries = db.get_sms_countries("telegram")
    all_countries = wa_countries + tg_countries
    if not all_countries:
        await update.callback_query.answer("لا توجد دول مضافة بعد", show_alert=True); return
    rows = []
    for c in all_countries:
        app_name = wa_label if c["app_type"] == "whatsapp" else tg_label
        icon     = "💬" if c["app_type"] == "whatsapp" else "✈️"
        rows.append([InlineKeyboardButton(
            "{} {} | {} — ${:.2f}".format(icon, app_name, c["country"], float(c.get("price", 0.5))),
            callback_data="adm_sms_setcp_{}_{}".format(c["app_type"], c["country"])
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms")])
    await update.callback_query.edit_message_text(
        "🌍 <b>تحديد سعر دولة</b>\n\nاختر الدولة والتطبيق لتعديل سعره:",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML"
    )


async def adm_sms_setcp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db       = context.bot_data["db"]
    data     = update.callback_query.data.replace("adm_sms_setcp_", "", 1)
    parts    = data.split("_", 1)
    app_type = parts[0]
    country  = parts[1] if len(parts) > 1 else ""
    context.user_data["adm_state"]       = "waiting_sms_country_price"
    context.user_data["adm_sms_country"] = country
    context.user_data["adm_sms_app"]     = app_type
    current  = db.get_sms_price(country, app_type)
    app_name = db.get_setting("sms_wa_label", "واتساب") if app_type == "whatsapp" else db.get_setting("sms_tg_label", "تيليجرام")
    icon     = "💬" if app_type == "whatsapp" else "✈️"
    await update.callback_query.edit_message_text(
        "💰 {} <b>{}</b> — <b>{}</b>\n"
        "السعر الحالي: <b>${:.2f}</b>\n\n"
        "أرسل السعر الجديد:".format(icon, app_name, country, current),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms_country_price")]]),
        parse_mode="HTML"
    )


async def adm_sms_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db       = context.bot_data["db"]
    wa_label = db.get_setting("sms_wa_label", "واتساب")
    tg_label = db.get_setting("sms_tg_label", "تيليجرام")
    wa = db.get_sms_countries("whatsapp")
    tg = db.get_sms_countries("telegram")
    text = "📋 <b>أرقام SMS المتاحة</b>\n\n"
    if wa:
        text += "💬 <b>{}:</b>\n".format(wa_label)
        for c in wa:
            text += "  • {} — {} متاح — ${:.2f}\n".format(c["country"], c["available"], float(c.get("price",0.5)))
        text += "\n"
    if tg:
        text += "✈️ <b>{}:</b>\n".format(tg_label)
        for c in tg:
            text += "  • {} — {} متاح — ${:.2f}\n".format(c["country"], c["available"], float(c.get("price",0.5)))
    if not wa and not tg:
        text += "لا توجد أرقام متاحة."
    await update.callback_query.edit_message_text(
        text.strip(),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms")]]),
        parse_mode="HTML"
    )


async def adm_sms_delete_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    await update.callback_query.edit_message_text(
        "🗑 <b>حذف أرقام SMS</b>\n\nاختر طريقة الحذف:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 حذف دولة (واتساب)",   callback_data="adm_sms_del_country_wa")],
            [InlineKeyboardButton("🗑 حذف دولة (تيليجرام)", callback_data="adm_sms_del_country_tg")],
            [InlineKeyboardButton("🗑 حذف رقم واحد",        callback_data="adm_sms_del_single")],
            [InlineKeyboardButton("🗑 حذف كل واتساب",      callback_data="adm_sms_clear_wa")],
            [InlineKeyboardButton("🗑 حذف كل تيليجرام",    callback_data="adm_sms_clear_tg")],
            [InlineKeyboardButton("🗑 حذف الكل",            callback_data="adm_sms_clear_all")],
            [InlineKeyboardButton("🔙 رجوع",                callback_data="adm_sms")],
        ]),
        parse_mode="HTML"
    )


async def adm_sms_del_country_wa_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    countries = db.get_sms_countries("whatsapp")
    if not countries:
        await update.callback_query.answer("لا توجد دول واتساب", show_alert=True); return
    rows = [[InlineKeyboardButton("🗑 {}".format(c["country"]),
             callback_data="adm_sms_delcountry_wa_{}".format(c["country"]))] for c in countries]
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms_delete_menu")])
    await update.callback_query.edit_message_text(
        "اختر الدولة للحذف (واتساب):", reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML"
    )


async def adm_sms_del_country_tg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    countries = db.get_sms_countries("telegram")
    if not countries:
        await update.callback_query.answer("لا توجد دول تيليجرام", show_alert=True); return
    rows = [[InlineKeyboardButton("🗑 {}".format(c["country"]),
             callback_data="adm_sms_delcountry_tg_{}".format(c["country"]))] for c in countries]
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms_delete_menu")])
    await update.callback_query.edit_message_text(
        "اختر الدولة للحذف (تيليجرام):", reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML"
    )


async def adm_sms_delcountry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    data = update.callback_query.data.replace("adm_sms_delcountry_", "")
    parts = data.split("_", 1)
    app_type = parts[0]
    country  = parts[1] if len(parts) > 1 else ""
    context.bot_data["db"].delete_sms_by_country(country, app_type)
    await update.callback_query.answer("✅ تم حذف {}".format(country), show_alert=True)
    update.callback_query.data = "adm_sms_delete_menu"
    await adm_sms_delete_menu_callback(update, context)


async def adm_sms_del_single_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_sms_del_phone"
    await update.callback_query.edit_message_text(
        "📞 أرسل رقم الهاتف للحذف:\n<code>+1234567890</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_sms_delete_menu")]]),
        parse_mode="HTML"
    )


async def adm_sms_clear_wa_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.bot_data["db"].delete_all_sms_numbers("whatsapp")
    await update.callback_query.answer("✅ تم حذف كل أرقام واتساب", show_alert=True)
    await adm_sms_callback(update, context)


async def adm_sms_clear_tg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.bot_data["db"].delete_all_sms_numbers("telegram")
    await update.callback_query.answer("✅ تم حذف كل أرقام تيليجرام", show_alert=True)
    await adm_sms_callback(update, context)


async def adm_sms_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    db.delete_all_sms_numbers()
    db.log_admin_action(update.effective_user.id, "حذف كل أرقام SMS", "حذف شامل")
    await update.callback_query.answer("✅ تم حذف كل أرقام SMS", show_alert=True)
    await adm_sms_callback(update, context)


async def adm_sms_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("adm_state") != "waiting_sms_txt":
        return False
    doc = update.message.document
    if not doc:
        return False
    fname = doc.file_name or ""
    if not fname.endswith(".txt"):
        await update.message.reply_text("❌ يجب أن يكون الملف بصيغة .txt")
        return True
    app_type = context.user_data.pop("sms_app_type", "whatsapp")
    file    = await doc.get_file()
    data    = await file.download_as_bytearray()
    content = bytes(data).decode("utf-8", errors="ignore")
    from sms_handler import parse_sms_txt
    numbers = parse_sms_txt(content, app_type)
    if not numbers:
        await update.message.reply_text("❌ لم يُعثر على أرقام صالحة في الملف.")
        return True
    added = context.bot_data["db"].add_sms_numbers_bulk(numbers)
    icon  = "💬" if app_type == "whatsapp" else "✈️"
    await update.message.reply_text(
        "✅ {} <b>تمت المعالجة</b>\n\n📋 الملف: <b>{}</b> سطر\n➕ أُضيف: <b>{}</b> رقم".format(
            icon, len(numbers), added),
        parse_mode="HTML"
    )
    return True


async def adm_sms_price_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("adm_state")
    if state == "waiting_sms_del_phone":
        phone = (update.message.text or "").strip()
        context.user_data.pop("adm_state", None)
        context.bot_data["db"].delete_sms_by_phone(phone)
        await update.message.reply_text("✅ تم حذف <code>{}</code>".format(phone), parse_mode="HTML")
        return True
    if state not in ("waiting_sms_price", "waiting_sms_country_price"):
        return False
    text = (update.message.text or "").strip()
    try:
        price = float(text.replace(",", "."))
        if price <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أرسل رقم صحيح موجب"); return True
    db = context.bot_data["db"]
    if state == "waiting_sms_price":
        db.set_setting("sms_price", str(price))
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("✅ السعر الافتراضي = <b>${:.4f}</b>".format(price), parse_mode="HTML")
    else:
        country  = context.user_data.pop("adm_sms_country", "")
        app_type = context.user_data.pop("adm_sms_app", "whatsapp")
        context.user_data.pop("adm_state", None)
        if country:
            db.set_sms_country_price(country, price, app_type)
            icon = "💬" if app_type == "whatsapp" else "✈️"
            await update.message.reply_text(
                "✅ {} <b>{}</b> = <b>${:.4f}</b>".format(icon, country, price), parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ خطأ: لم يتم تحديد الدولة")
    return True


def _force_sub_text(channels: list) -> str:
    if not channels:
        return "📌 <b>الاشتراك الإجباري</b>\n\n⭕ لا توجد قنوات إجبارية حالياً."
    lines = "📌 <b>الاشتراك الإجباري</b>\n\n<b>القنوات المضافة:</b>\n\n"
    for i, ch in enumerate(channels, 1):
        name = ch.get("name", "بدون اسم")
        link = ch.get("link", "—")
        cid  = ch.get("id", "—")
        lines += "{}. <b>{}</b>\n   🆔 <code>{}</code>\n   🔗 {}\n\n".format(i, name, cid, link)
    return lines.strip()


async def adm_cfg_force_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db       = context.bot_data["db"]
    channels = db.get_force_channels()
    rows = [
        [InlineKeyboardButton("➕ إضافة قناة / جروب",   callback_data="adm_force_add")],
        [InlineKeyboardButton("🗑 حذف قناة",             callback_data="adm_force_del")],
        [InlineKeyboardButton("❌ مسح الكل",             callback_data="adm_force_clear")],
        [InlineKeyboardButton("🔙 رجوع",                 callback_data="adm_settings")],
    ]
    await update.callback_query.edit_message_text(
        _force_sub_text(channels),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML"
    )


async def adm_force_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_force_channel"
    await update.callback_query.edit_message_text(
        "📌 <b>إضافة قناة اشتراك إجباري</b>\n\n"
        "أرسل بيانات القناة بالصيغة:\n\n"
        "<code>CHANNEL_ID | اسم القناة | رابط القناة</code>\n\n"
        "<b>مثال:</b>\n"
        "<code>-1001234567890 | قناة الدعم | https://t.me/mychannel</code>\n\n"
        "📝 <b>ملاحظات:</b>\n"
        "• CHANNEL_ID يبدأ بـ <code>-100</code>\n"
        "• اجعل البوت أدمن في القناة أولاً\n"
        "• الرابط اختياري (اتركه فارغاً لو ما فيش)\n\n"
        "<b>صيغة بدون رابط:</b>\n"
        "<code>-1001234567890 | اسم القناة</code>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 رجوع", callback_data="adm_cfg_force_sub")
        ]]),
        parse_mode="HTML"
    )


async def adm_force_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db       = context.bot_data["db"]
    channels = db.get_force_channels()
    if not channels:
        await update.callback_query.answer("لا توجد قنوات للحذف", show_alert=True)
        return
    rows = []
    for i, ch in enumerate(channels):
        name = ch.get("name", "قناة {}".format(i+1))
        rows.append([InlineKeyboardButton(
            "🗑 {}".format(name),
            callback_data="adm_force_delone_{}".format(i)
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_cfg_force_sub")])
    await update.callback_query.edit_message_text(
        "🗑 <b>اختر القناة للحذف:</b>",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML"
    )


async def adm_force_delone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    idx = int(update.callback_query.data.replace("adm_force_delone_", ""))
    db       = context.bot_data["db"]
    channels = db.get_force_channels()
    if 0 <= idx < len(channels):
        removed = channels.pop(idx)
        db.set_force_channels(channels)
        await update.callback_query.answer(
            "🗑 تم حذف: {}".format(removed.get("name", "")), show_alert=True
        )
    update.callback_query.data = "adm_cfg_force_sub"
    await adm_cfg_force_sub_callback(update, context)


async def adm_force_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.bot_data["db"].set_force_channels([])
    await update.callback_query.answer("✅ تم مسح كل القنوات الإجبارية", show_alert=True)
    update.callback_query.data = "adm_cfg_force_sub"
    await adm_cfg_force_sub_callback(update, context)


async def adm_force_channel_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """يعالج رسالة إضافة قناة إجبارية"""
    if context.user_data.get("adm_state") != "waiting_force_channel":
        return False
    text = (update.message.text or "").strip()
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ الصيغة غير صحيحة.\n"
            "مثال: <code>-1001234567890 | اسم القناة | https://t.me/link</code>",
            parse_mode="HTML"
        )
        return True

    try:
        ch_id = int(parts[0])
    except ValueError:
        await update.message.reply_text("❌ ID القناة غير صحيح، يجب أن يكون رقماً.")
        return True

    name = parts[1] if len(parts) > 1 else "قناة"
    link = parts[2] if len(parts) > 2 else ""

    db       = context.bot_data["db"]
    channels = db.get_force_channels()

    # تحقق من عدم التكرار
    if any(ch["id"] == ch_id for ch in channels):
        await update.message.reply_text("⚠️ هذه القناة مضافة بالفعل.")
        return True

    channels.append({"id": ch_id, "name": name, "link": link})
    db.set_force_channels(channels)
    context.user_data.pop("adm_state", None)

    await update.message.reply_text(
        "✅ <b>تمت الإضافة!</b>\n\n"
        "📢 <b>الاسم:</b> {}\n"
        "🆔 <b>ID:</b> <code>{}</code>\n"
        "🔗 <b>الرابط:</b> {}".format(name, ch_id, link or "—"),
        parse_mode="HTML"
    )
    return True


# ══════════════════════════════════════════════════════════
#  التعليمات
# ══════════════════════════════════════════════════════════

async def adm_cfg_instructions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    ar   = db.get_setting("instructions_ar", "").strip() or "لم يتم التعيين"
    en   = db.get_setting("instructions_en", "").strip() or "Not set"
    await update.callback_query.edit_message_text(
        "📖 <b>التعليمات</b>\n\n"
        "🇸🇦 <b>العربية (الحالية):</b>\n{ar}\n\n"
        "🇬🇧 <b>English (current):</b>\n{en}".format(
            ar=ar[:300] + ("..." if len(ar) > 300 else ""),
            en=en[:300] + ("..." if len(en) > 300 else ""),
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تعديل العربية",  callback_data="adm_set_instructions_ar")],
            [InlineKeyboardButton("✏️ Edit English",   callback_data="adm_set_instructions_en")],
            [InlineKeyboardButton("🔙 رجوع",            callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_set_instructions_ar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_instructions_ar"
    await update.callback_query.edit_message_text(
        "✏️ أرسل نص التعليمات <b>بالعربية</b>:\n\n"
        "<i>يدعم تنسيق HTML: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;</i>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 رجوع", callback_data="adm_cfg_instructions")
        ]]),
        parse_mode="HTML"
    )


async def adm_set_instructions_en_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_instructions_en"
    await update.callback_query.edit_message_text(
        "✏️ Send the <b>English</b> instructions text:\n\n"
        "<i>HTML formatting supported: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;</i>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 رجوع", callback_data="adm_cfg_instructions")
        ]]),
        parse_mode="HTML"
    )


async def adm_instructions_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("adm_state")
    if state not in ("waiting_instructions_ar", "waiting_instructions_en"):
        return False
    text = update.message.text or ""
    lang_key = "instructions_ar" if state == "waiting_instructions_ar" else "instructions_en"
    context.bot_data["db"].set_setting(lang_key, text)
    context.user_data.pop("adm_state", None)
    lang_name = "العربية" if "ar" in lang_key else "English"
    await update.message.reply_text(
        "✅ تم حفظ التعليمات ({}).".format(lang_name),
        parse_mode="HTML"
    )
    return True


# ══════════════════════════════════════════════════════════
#  روابط القنوات والدعم
# ══════════════════════════════════════════════════════════

async def adm_cfg_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    act     = db.get_setting("activation_channel_link", "").strip() or "—"
    main_ch = db.get_setting("main_channel_link",       "").strip() or "—"
    sup     = db.get_setting("support_link",             "").strip() or "—"
    await update.callback_query.edit_message_text(
        "🔗 <b>روابط القنوات والدعم</b>\n\n"
        "📢 قناة التفعيلات: <code>{act}</code>\n"
        "📣 القناة الرئيسية: <code>{main}</code>\n"
        "🆘 الدعم الفني: <code>{sup}</code>".format(act=act, main=main_ch, sup=sup),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 رابط قناة التفعيلات",  callback_data="adm_set_link_activation")],
            [InlineKeyboardButton("📣 رابط القناة الرئيسية", callback_data="adm_set_link_main")],
            [InlineKeyboardButton("🆘 رابط الدعم الفني",    callback_data="adm_set_link_support")],
            [InlineKeyboardButton("🔙 رجوع",                 callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_set_link_activation_callback(update, context):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_link_activation"
    await update.callback_query.edit_message_text(
        "📢 أرسل رابط <b>قناة التفعيلات</b>:\nمثال: <code>https://t.me/mychannel</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_cfg_links")]]),
        parse_mode="HTML"
    )

async def adm_set_link_main_callback(update, context):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_link_main"
    await update.callback_query.edit_message_text(
        "📣 أرسل رابط <b>القناة الرئيسية</b>:\nمثال: <code>https://t.me/mychannel</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_cfg_links")]]),
        parse_mode="HTML"
    )

async def adm_set_link_support_callback(update, context):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_link_support"
    await update.callback_query.edit_message_text(
        "🆘 أرسل <b>رابط أو يوزر الدعم الفني</b>:\nمثال: <code>https://t.me/support</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_cfg_links")]]),
        parse_mode="HTML"
    )


async def adm_links_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("adm_state")
    mapping = {
        "waiting_link_activation": ("activation_channel_link", "قناة التفعيلات"),
        "waiting_link_main":       ("main_channel_link",       "القناة الرئيسية"),
        "waiting_link_support":    ("support_link",            "الدعم الفني"),
    }
    if state not in mapping:
        return False
    key, label = mapping[state]
    text = (update.message.text or "").strip()
    if not text.startswith("http") and not text.startswith("@"):
        await update.message.reply_text("❌ الرابط غير صحيح. يجب أن يبدأ بـ https:// أو @")
        return True
    context.bot_data["db"].set_setting(key, text)
    context.user_data.pop("adm_state", None)
    await update.message.reply_text("✅ تم حفظ رابط <b>{}</b>.".format(label), parse_mode="HTML")
    return True


# ══════════════════════════════════════════════════════════
#  الكوبونات — لوحة الأدمن
# ══════════════════════════════════════════════════════════

async def adm_coupons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    coupons = db.get_all_coupons()
    text    = "🎟️ <b>الكوبونات</b>\n\n"
    if not coupons:
        text += "لا توجد كوبونات بعد.\n"
    for c in coupons[:10]:
        status = "✅" if c["is_active"] else "❌"
        t_type = "{}%".format(c["value"]) if c["type"] == "percent" else "${:.2f}".format(c["value"])
        exp    = c["expires_at"] or "∞"
        text  += "{} <code>{}</code> — {} — {}/{} استخدام — ينتهي: {}\n".format(
            status, c["code"], t_type, c["used_count"], c["max_uses"], exp
        )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إنشاء كوبون",    callback_data="adm_coupon_create")],
            [InlineKeyboardButton("🗑 حذف كوبون",      callback_data="adm_coupon_del")],
            [InlineKeyboardButton("🔙 رجوع",            callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_coupon_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_coupon_create"
    await update.callback_query.edit_message_text(
        "➕ <b>إنشاء كوبون جديد</b>\n\n"
        "أرسل البيانات بالصيغة:\n\n"
        "<code>الكود | النوع | القيمة | عدد الاستخدامات | تاريخ الانتهاء</code>\n\n"
        "<b>أمثلة:</b>\n"
        "<code>SAVE20 | percent | 20 | 100 | 2026-12-31</code>\n"
        "<code>GIFT5 | fixed | 5 | 1 | -</code>\n\n"
        "• النوع: <b>percent</b> (نسبة) أو <b>fixed</b> (مبلغ ثابت)\n"
        "• تاريخ الانتهاء: YYYY-MM-DD أو - بدون انتهاء",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_coupons")]]),
        parse_mode="HTML"
    )


async def adm_coupon_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    coupons = [c for c in db.get_all_coupons()]
    if not coupons:
        await update.callback_query.answer("لا توجد كوبونات", show_alert=True)
        return
    rows = [[InlineKeyboardButton(
        "🗑 {} — {}".format(c["code"], "✅" if c["is_active"] else "❌"),
        callback_data="adm_coupon_delone_{}".format(c["id"])
    )] for c in coupons[:15]]
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_coupons")])
    await update.callback_query.edit_message_text(
        "🗑 اختر الكوبون للحذف:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML"
    )


async def adm_coupon_delone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    cid = int(update.callback_query.data.replace("adm_coupon_delone_", ""))
    context.bot_data["db"].delete_coupon(cid)
    await update.callback_query.answer("✅ تم الحذف", show_alert=True)
    update.callback_query.data = "adm_coupons"
    await adm_coupons_callback(update, context)


async def adm_coupon_create_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("adm_state") != "waiting_coupon_create":
        return False
    context.user_data.pop("adm_state", None)
    parts = [p.strip() for p in (update.message.text or "").split("|")]
    if len(parts) < 4:
        await update.message.reply_text("❌ الصيغة غير صحيحة.")
        return True
    code     = parts[0].upper()
    type_    = parts[1].lower()
    try:    value = float(parts[2])
    except: await update.message.reply_text("❌ القيمة غير صحيحة."); return True
    try:    max_uses = int(parts[3])
    except: max_uses = 1
    expires = parts[4] if len(parts) > 4 and parts[4] != "-" else None
    if type_ not in ("percent", "fixed"):
        await update.message.reply_text("❌ النوع يجب أن يكون percent أو fixed.")
        return True
    ok = context.bot_data["db"].create_coupon(code, type_, value, max_uses, expires)
    if ok:
        await update.message.reply_text(
            "✅ تم إنشاء الكوبون <code>{}</code>".format(code), parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ الكوبون موجود بالفعل.")
    return True


# ══════════════════════════════════════════════════════════
#  نظام الخصم التلقائي — لوحة الأدمن
# ══════════════════════════════════════════════════════════

async def adm_discounts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db        = context.bot_data["db"]
    discounts = db.get_discounts()
    text      = "🏷️ <b>نظام الخصم التلقائي</b>\n\n"
    text     += "يُطبَّق خصم تلقائي بناءً على عدد طلبات المستخدم:\n\n"
    if not discounts:
        text += "لا توجد خصومات مضافة بعد.\n"
    for d in discounts:
        text += "• بعد <b>{}</b> طلب → خصم <b>{}%</b>\n".format(d["orders"], d["percent"])
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة خصم",  callback_data="adm_discount_add")],
            [InlineKeyboardButton("🗑 مسح الكل",   callback_data="adm_discount_clear")],
            [InlineKeyboardButton("🔙 رجوع",        callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_discount_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_discount_add"
    await update.callback_query.edit_message_text(
        "➕ <b>إضافة خصم تلقائي</b>\n\n"
        "أرسل:\n<code>عدد الطلبات | نسبة الخصم%</code>\n\n"
        "مثال: <code>10 | 5</code> ← خصم 5% بعد 10 طلبات",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_discounts")]]),
        parse_mode="HTML"
    )


async def adm_discount_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.bot_data["db"].set_discounts([])
    await update.callback_query.answer("✅ تم مسح الخصومات", show_alert=True)
    update.callback_query.data = "adm_discounts"
    await adm_discounts_callback(update, context)


async def adm_discount_add_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("adm_state") != "waiting_discount_add":
        return False
    context.user_data.pop("adm_state", None)
    parts = [p.strip() for p in (update.message.text or "").split("|")]
    try:
        orders  = int(parts[0])
        percent = float(parts[1])
    except Exception:
        await update.message.reply_text("❌ الصيغة غير صحيحة."); return True
    db        = context.bot_data["db"]
    discounts = db.get_discounts()
    discounts = [d for d in discounts if d["orders"] != orders]
    discounts.append({"orders": orders, "percent": percent})
    db.set_discounts(discounts)
    await update.message.reply_text(
        "✅ خصم {}% بعد {} طلب".format(percent, orders)
    )
    return True


# ══════════════════════════════════════════════════════════
#  الإحالة — لوحة الأدمن
# ══════════════════════════════════════════════════════════

async def adm_referral_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    pct     = db.get_setting("referral_percent",     "10")
    min_wd  = db.get_setting("referral_min_withdraw", "1.0")
    await update.callback_query.edit_message_text(
        "🤝 <b>إعدادات الإحالة</b>\n\n"
        "💰 نسبة الكسب: <b>{}%</b>\n"
        "💳 الحد الأدنى للسحب: <b>${}</b>".format(pct, min_wd),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تغيير النسبة",        callback_data="adm_ref_set_pct")],
            [InlineKeyboardButton("✏️ تغيير الحد الأدنى",   callback_data="adm_ref_set_min")],
            [InlineKeyboardButton("🔙 رجوع",                 callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_ref_set_pct_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_ref_pct"
    await update.callback_query.edit_message_text(
        "أرسل نسبة الإحالة (مثال: <code>10</code> = 10%)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_referral_settings")]]),
        parse_mode="HTML"
    )


async def adm_ref_set_min_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_ref_min"
    await update.callback_query.edit_message_text(
        "أرسل الحد الأدنى للسحب (مثال: <code>1.0</code>)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_referral_settings")]]),
        parse_mode="HTML"
    )


async def adm_ref_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("adm_state")
    if state not in ("waiting_ref_pct", "waiting_ref_min"):
        return False
    val = (update.message.text or "").strip().replace(",", ".")
    try:    num = float(val)
    except: await update.message.reply_text("❌ أرسل رقم صحيح."); return True
    db = context.bot_data["db"]
    if state == "waiting_ref_pct":
        db.set_setting("referral_percent", str(num))
        await update.message.reply_text("✅ نسبة الإحالة = {}%".format(num))
    else:
        db.set_setting("referral_min_withdraw", str(num))
        await update.message.reply_text("✅ الحد الأدنى للسحب = ${}".format(num))
    context.user_data.pop("adm_state", None)
    return True


# ══════════════════════════════════════════════════════════
#  قناة التقارير اليومية + النسخ الاحتياطي — لوحة الأدمن
# ══════════════════════════════════════════════════════════

async def adm_report_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db      = context.bot_data["db"]
    ch      = db.get_setting("admin_report_channel", "").strip() or "غير محدد"
    await update.callback_query.edit_message_text(
        "📊 <b>التقارير والنسخ الاحتياطي</b>\n\n"
        "📢 قناة التقارير: <code>{}</code>\n\n"
        "• التقرير اليومي يُرسَل تلقائياً الساعة 12 منتصف الليل\n"
        "• النسخ الاحتياطي كل 6 ساعات".format(ch),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 تعيين قناة التقارير",   callback_data="adm_set_report_ch")],
            [InlineKeyboardButton("📊 إرسال تقرير الآن",      callback_data="adm_send_report_now")],
            [InlineKeyboardButton("💾 نسخة احتياطية الآن",   callback_data="adm_backup_now")],
            [InlineKeyboardButton("📤 رفع نسخة احتياطية",    callback_data="adm_restore_backup")],
            [InlineKeyboardButton("🔙 رجوع",                   callback_data="adm_settings")],
        ]),
        parse_mode="HTML"
    )


async def adm_set_report_ch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_report_ch"
    await update.callback_query.edit_message_text(
        "أرسل <b>ID قناة التقارير</b> (مثال: <code>-1001234567890</code>)\n"
        "تأكد إن البوت أدمن فيها.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_report_settings")]]),
        parse_mode="HTML"
    )


async def adm_send_report_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    from features import send_daily_report
    await update.callback_query.answer("📊 جارٍ الإرسال...", show_alert=False)
    await send_daily_report(context.bot, context.bot_data["db"])
    await update.callback_query.answer("✅ تم إرسال التقرير", show_alert=True)


async def adm_backup_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    from features import make_backup
    import datetime
    await update.callback_query.answer("💾 جارٍ النسخ...", show_alert=False)
    try:
        db   = context.bot_data["db"]
        path = make_backup(db._path)
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=open(path, "rb"),
            filename="backup_{}.db".format(datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")),
            caption="💾 <b>نسخة احتياطية يدوية</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.callback_query.answer("❌ {}".format(e), show_alert=True)


async def adm_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_restore_backup"
    await update.callback_query.edit_message_text(
        "📤 <b>رفع نسخة احتياطية</b>\n\n"
        "أرسل ملف <code>.db</code> وسيتم استبدال قاعدة البيانات الحالية.\n\n"
        "⚠️ <b>تحذير:</b> سيتم إيقاف البوت وإعادة تشغيله بعد الاستعادة.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_report_settings")]]),
        parse_mode="HTML"
    )


async def adm_report_ch_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("adm_state")
    if state == "waiting_report_ch":
        val = (update.message.text or "").strip()
        try:    int(val)
        except: await update.message.reply_text("❌ ID غير صحيح."); return True
        context.bot_data["db"].set_setting("admin_report_channel", val)
        context.user_data.pop("adm_state", None)
        await update.message.reply_text("✅ تم تعيين قناة التقارير.")
        return True
    if state == "waiting_restore_backup":
        doc = update.message.document
        if not doc or not (doc.file_name or "").endswith(".db"):
            await update.message.reply_text("❌ يجب أن يكون الملف بصيغة .db")
            return True
        import shutil, os
        context.user_data.pop("adm_state", None)
        db   = context.bot_data["db"]
        file = await doc.get_file()
        data = await file.download_as_bytearray()
        # نسخة احتياطية للحالية قبل الاستبدال
        from features import make_backup
        make_backup(db._path)
        with open(db._path, "wb") as f:
            f.write(bytes(data))
        await update.message.reply_text(
            "✅ <b>تم استعادة قاعدة البيانات!</b>\n\n"
            "⚡ يرجى إعادة تشغيل البوت يدوياً.",
            parse_mode="HTML"
        )
        return True
    return False


# ══════════════════════════════════════════════════════════
#  📈 أداء الدول
# ══════════════════════════════════════════════════════════

async def adm_performance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db   = context.bot_data["db"]
    perf = db.get_country_performance(limit=10)
    if not perf:
        await update.callback_query.edit_message_text(
            "📈 <b>أداء الدول</b>\n\nلا توجد طلبات بعد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
            parse_mode="HTML"
        )
        return
    text = "📈 <b>أداء الدول (تيليجرام)</b>\n\n"
    for p in perf:
        cc = p["country_code"]
        if cc.startswith("CAT_"):
            flag, cname = "📦", cc[4:]
        else:
            flag, cname = COUNTRY_DATA.get(cc, ("🌍", cc))
        bar_len = int(p["success_rate"] / 10)
        bar = "🟩" * bar_len + "⬜" * (10 - bar_len)
        text += (
            "{flag} <b>{cname}</b>\n"
            "  📦 إجمالي: {total} | ✅ ناجح: {completed} | ❌ ملغي: {cancelled}\n"
            "  {bar} {rate}%\n\n"
        ).format(flag=flag, cname=cname, total=p["total"], completed=p["completed"],
                 cancelled=p["cancelled"], bar=bar, rate=p["success_rate"])
    await update.callback_query.edit_message_text(
        text.strip(),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  ⚠️ تنبيه نفاد المخزون
# ══════════════════════════════════════════════════════════

async def adm_low_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db = context.bot_data["db"]
    threshold = 3
    tg_low  = db.get_low_stock_countries(threshold)
    sms_low = db.get_low_stock_sms(threshold)

    text = "⚠️ <b>تنبيه المخزون</b> (الحد: {} أو أقل)\n\n".format(threshold)
    if not tg_low and not sms_low:
        text += "✅ كل المخزون في حالة جيدة، لا توجد دول قاربت على النفاد."
    else:
        if tg_low:
            text += "📱 <b>تيليجرام:</b>\n"
            for c in tg_low:
                flag = c["country_flag"] or ("📦" if c["country_code"].startswith("CAT_") else "🌍")
                name = c["country_name"] or c["country_code"]
                text += "  {} {} — متاح: <b>{}</b>\n".format(flag, name, c["available"])
            text += "\n"
        if sms_low:
            text += "💬 <b>SMS:</b>\n"
            for c in sms_low:
                icon = "💬" if c["app_type"] == "whatsapp" else "✈️"
                text += "  {} {} — متاح: <b>{}</b>\n".format(icon, c["country"], c["available"])

    await update.callback_query.edit_message_text(
        text.strip(),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
        parse_mode="HTML"
    )


async def low_stock_check_loop(bot, db, interval_seconds: int = 3600, threshold: int = 3):
    """يفحص المخزون بشكل دوري ويبعت تنبيه تلقائي للأدمن لو فيه دول قاربت على النفاد"""
    import asyncio
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            admin_id = int(db.get_setting("admin_id", "0"))
            if not admin_id:
                continue
            tg_low  = db.get_low_stock_countries(threshold)
            sms_low = db.get_low_stock_sms(threshold)
            if not tg_low and not sms_low:
                continue
            text = "🔔 <b>تنبيه: مخزون منخفض!</b>\n\n"
            if tg_low:
                text += "📱 <b>تيليجرام:</b>\n"
                for c in tg_low:
                    flag = c["country_flag"] or "🌍"
                    name = c["country_name"] or c["country_code"]
                    text += "  {} {} — متاح: <b>{}</b>\n".format(flag, name, c["available"])
                text += "\n"
            if sms_low:
                text += "💬 <b>SMS:</b>\n"
                for c in sms_low:
                    icon = "💬" if c["app_type"] == "whatsapp" else "✈️"
                    text += "  {} {} — متاح: <b>{}</b>\n".format(icon, c["country"], c["available"])
            await bot.send_message(chat_id=admin_id, text=text.strip(), parse_mode="HTML")
        except Exception as e:
            logger.warning("low_stock_check_loop error: %s", e)


# ══════════════════════════════════════════════════════════
#  🔍 بحث عن رقم
# ══════════════════════════════════════════════════════════

async def adm_search_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    context.user_data["adm_state"] = "waiting_search_number"
    await update.callback_query.edit_message_text(
        "🔍 <b>بحث عن رقم</b>\n\nأرسل رقم الهاتف للبحث:\n<code>+1234567890</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
        parse_mode="HTML"
    )


async def adm_search_number_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("adm_state") != "waiting_search_number":
        return False
    context.user_data.pop("adm_state", None)
    db    = context.bot_data["db"]
    phone = (update.message.text or "").strip()
    result = db.search_number(phone)

    if not result:
        await update.message.reply_text(
            "❌ لم يُعثر على الرقم <code>{}</code>".format(phone), parse_mode="HTML"
        )
        return True

    order = result.get("order")
    if result["kind"] == "ready":
        status_icon = {"available": "✅ متاح", "sold": "🛒 مباع"}.get(result["status"], result["status"])
        text = (
            "🔍 <b>نتيجة البحث — رقم جاهز</b>\n\n"
            "📞 الرقم: <code>{phone}</code>\n"
            "🌍 الدولة: {flag} {cname}\n"
            "📊 الحالة: {status}\n"
        ).format(phone=result["phone"], flag=result["country_flag"],
                 cname=result["country_name"], status=status_icon)
        if result.get("twofa"):
            text += "🔐 2FA: <code>{}</code>\n".format(result["twofa"])
        if order:
            text += (
                "\n📦 <b>آخر طلب:</b>\n"
                "👤 المستخدم: <code>{uid}</code>\n"
                "💰 السعر: ${cost:.3f}\n"
                "🔑 الكود: <code>{code}</code>\n"
                "📅 التاريخ: {date}\n"
            ).format(uid=order["user_tg_id"], cost=order["cost"],
                     code=order.get("otp_code") or "—", date=order["created_at"])
    else:
        status_icon = {"available": "✅ متاح", "locked": "🔒 محجوز"}.get(result["status"], result["status"])
        text = (
            "🔍 <b>نتيجة البحث — رقم SMS</b>\n\n"
            "📞 الرقم: <code>{phone}</code>\n"
            "🌍 الدولة: {country}\n"
            "🌐 التطبيق: {app}\n"
            "📊 الحالة: {status}\n"
            "⚠️ عداد الفشل: {fail}\n"
        ).format(phone=result["phone"], country=result["country"],
                 app="💬 واتساب" if result["app_type"] == "whatsapp" else "✈️ تيليجرام",
                 status=status_icon, fail=result.get("fail_count", 0))
        if order:
            text += (
                "\n📦 <b>آخر طلب:</b>\n"
                "👤 المستخدم: <code>{uid}</code>\n"
                "💰 السعر: ${cost:.3f}\n"
                "🔑 الكود: <code>{code}</code>\n"
                "📅 التاريخ: {date}\n"
            ).format(uid=order["user_tg_id"], cost=order["cost"],
                     code=order.get("otp_code") or "—", date=order["created_at"])

    await update.message.reply_text(text, parse_mode="HTML")
    return True


# ══════════════════════════════════════════════════════════
#  📜 سجل العمليات الحساسة
# ══════════════════════════════════════════════════════════

async def adm_audit_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context): return
    db  = context.bot_data["db"]
    log = db.get_audit_log(limit=20)
    if not log:
        text = "📜 <b>سجل العمليات</b>\n\nلا توجد عمليات مسجَّلة بعد."
    else:
        text = "📜 <b>آخر {} عملية حساسة</b>\n\n".format(len(log))
        for entry in log:
            text += "🔸 <b>{action}</b>\n   {details}\n   🕐 {date}\n\n".format(
                action=entry["action"],
                details=entry.get("details") or "—",
                date=entry["created_at"]
            )
    await update.callback_query.edit_message_text(
        text.strip()[:4000],
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_main")]]),
        parse_mode="HTML"
    )
