"""
🤖 main.py
"""
import asyncio
import logging
import sys
import os

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, PreCheckoutQueryHandler, filters,
    ContextTypes
)
from telegram.error import BadRequest, TelegramError

import config
from database import Database
from otp_listener import OtpListener
from crypto_pay import CryptoPayHandler
from ton_trx_pay import TonTrxPayHandler
from vodafone_auto import VodafoneAutoHandler

os.makedirs("data", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  Error Handler
# ══════════════════════════════════════════════════════════

async def error_handler(update, context):
    err = context.error
    if isinstance(err, BadRequest) and "not modified" in str(err).lower():
        return  # تجاهل — رسالة لم تتغير
    if isinstance(err, TelegramError) and "query is too old" in str(err).lower():
        return  # تجاهل — callback قديم
    logger.error("Update {} caused error: {}".format(update, err), exc_info=err)


# ══════════════════════════════════════════════════════════
#  Message Router
# ══════════════════════════════════════════════════════════

async def message_router(update: Update, context):
    from handlers.admin.panel import (
        adm_file_handler, adm_price_msg_handler,
        adm_sms_file_handler, adm_sms_price_msg_handler,
        adm_force_channel_msg_handler,
        adm_new_category_msg_handler,
        adm_num_del_phone_msg_handler,
        adm_search_number_msg_handler,
        adm_instructions_msg_handler,
        adm_links_msg_handler,
        adm_coupon_create_msg_handler,
        adm_discount_add_msg_handler,
        adm_ref_msg_handler,
        adm_report_ch_msg_handler,
    )
    from handlers.coupon import coupon_msg_handler
    from handlers.stars_binance_pay import (
        stars_amount_message_handler,
        binance_message_handler,
        binance_admin_amount_handler,
    )

    if not update.message:
        return

    uid = update.effective_user.id if update.effective_user else None

    # ① ملفات الأدمن (session أو TXT لأرقام SMS)
    if update.message.document:
        # نجرب SMS txt أولاً لأن adm_file_handler يتجاهل غير session
        if await adm_sms_file_handler(update, context):
            return
        await adm_file_handler(update, context)
        return

    if not (update.message.text or update.message.photo):
        return

    # ② Stars مبلغ مخصص
    if await stars_amount_message_handler(update, context):
        return

    # ③ Binance Order ID
    if await binance_message_handler(update, context):
        return

    # ④ Binance أدمن يدخل المبلغ
    if await binance_admin_amount_handler(update, context):
        return

    # ⑤ Crypto TXID (BEP20 / TRC20 / TON / TRX)
    for key in ("cph", "ttp"):
        h = context.bot_data.get(key)
        if h and uid and h.in_session(uid):
            if await h.handle_txid_message(update.message):
                return

    # ⑥ فودافون كاش
    vah = context.bot_data.get("vah")
    if vah and uid and vah.in_session(uid):
        if await vah.handle_message(update.message):
            return

    # ⑦ سعر SMS
    if await adm_sms_price_msg_handler(update, context):
        return

    # ⑧ فئة رفع جديدة
    if await adm_new_category_msg_handler(update, context):
        return

    # ⑧.5 حذف رقم جاهز واحد
    if await adm_num_del_phone_msg_handler(update, context):
        return

    # ⑧.6 بحث عن رقم (أدمن)
    if await adm_search_number_msg_handler(update, context):
        return

    # ⑨ قناة اشتراك إجباري
    if await adm_force_channel_msg_handler(update, context):
        return

    # ⑨ التعليمات
    if await adm_instructions_msg_handler(update, context):
        return

    # ⑩ روابط القنوات والدعم
    if await adm_links_msg_handler(update, context):
        return

    # ⑪ كوبونات الأدمن
    if await adm_coupon_create_msg_handler(update, context):
        return

    # ⑫ الخصومات التلقائية
    if await adm_discount_add_msg_handler(update, context):
        return

    # ⑬ إعدادات الإحالة
    if await adm_ref_msg_handler(update, context):
        return

    # ⑭ قناة التقارير + استعادة نسخة
    if await adm_report_ch_msg_handler(update, context):
        return

    # ⑮ كوبون المستخدم
    if await coupon_msg_handler(update, context):
        return

    # ⑯ إعدادات الأدمن (آخر شيء)
    await adm_price_msg_handler(update, context)


# ══════════════════════════════════════════════════════════
#  Commands
# ══════════════════════════════════════════════════════════

async def start_cmd(update: Update, context):
    from handlers.user import start_callback
    db   = context.bot_data["db"]
    args = context.args or []
    user = update.effective_user
    # معالجة رابط الإحالة
    if args and args[0].startswith("ref"):
        try:
            referrer_id = int(args[0][3:])
            db.ensure_user(user.id, user.username, user.first_name)
            db.set_referrer(user.id, referrer_id)
        except Exception:
            pass
    await start_callback(update, context)


async def admin_cmd(update: Update, context):
    db = context.bot_data["db"]
    if update.effective_user.id != int(db.get_setting("admin_id", "0")):
        await update.message.reply_text("❌ غير مصرح")
        return
    from handlers.admin.panel import admin_main_kb
    stats = db.get_stats()
    pend  = len(db.get_pending_deposits())
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>لوحة التحكم</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 المستخدمين: <b>{users}</b>  🚫 محظور: <b>{banned}</b>\n"
        "📱 الأرقام: ✅ <b>{available}</b> متاح | 🛒 <b>{sold}</b> مباع\n"
        "📦 الطلبات: <b>{orders}</b>  🌟 اليوم: <b>{today}</b>\n"
        "💰 الإيرادات: <b>${revenue:.2f}</b>\n"
        "⏳ شحن معلق: <b>{pend}</b>".format(pend=pend, **stats),
        reply_markup=admin_main_kb(),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════
#  تسجيل الـ Handlers
# ══════════════════════════════════════════════════════════

def register_handlers(app: Application):

    # ── User ──────────────────────────────────────────────
    from handlers.user import (
        start_callback, my_account_callback,
        buy_country_callback, buy_number_callback,
        confirm_buy_callback, get_otp_callback,
        my_orders_callback, deposit_callback,
        otp_history_callback, toggle_favorite_callback,
        charge_usdt_menu_callback,
        sms_countries_callback, sms_buy_callback, sms_app_callback,
        check_sub_callback,
        choose_language_callback, set_lang_callback,
        instructions_callback,
    )

    # ── Admin ─────────────────────────────────────────────
    from handlers.admin.panel import (
        admin_callback, adm_numbers_callback, adm_num_cc_callback,
        adm_num_delete_menu_callback, adm_num_del_country_list_callback,
        adm_num_delcountry_callback, adm_num_del_single_callback,
        adm_num_clear_all_callback, adm_num_clear_all_confirm_callback,
        adm_num_del_phone_msg_handler,
        adm_upload_callback, adm_upload_normal_callback, adm_upload_newcat_callback,
        adm_upload_cat_callback, adm_new_category_msg_handler,
        adm_prices_callback, adm_setprice_callback,
        adm_orders_callback, adm_deposits_callback,
        adm_dep_ok_callback, adm_dep_no_callback,
        adm_broadcast_callback, adm_settings_callback, adm_set_key_callback,
        adm_zip_callback, adm_del_sold_callback,
        adm_cfg_stars_callback, adm_cfg_binance_callback,
        adm_cfg_bep20_callback, adm_cfg_trc20_callback,
        adm_cfg_ton_callback, adm_cfg_trx_callback,
        adm_cfg_vod_callback,
        adm_cfg_channels_callback, adm_clear_channels_callback,
        adm_cfg_notify_callback, adm_clear_notify_callback,
        adm_toggle_callback, adm_set_key_callback,
        adm_stats_callback,
        adm_users_callback, adm_ban_callback, adm_unban_callback,
        adm_addbal_callback, adm_subbal_callback, adm_setbal_callback,
        adm_sms_callback, adm_sms_upload_wa_callback, adm_sms_upload_tg_callback,
        adm_sms_price_callback, adm_sms_list_callback,
        adm_sms_clear_callback, adm_sms_clear_wa_callback, adm_sms_clear_tg_callback,
        adm_sms_country_price_callback, adm_sms_setcp_callback,
        adm_sms_delete_menu_callback, adm_sms_del_country_wa_callback,
        adm_sms_del_country_tg_callback, adm_sms_delcountry_callback,
        adm_sms_del_single_callback,
        adm_sms_app_labels_callback, adm_sms_set_wa_label_callback, adm_sms_set_tg_label_callback,
        adm_cfg_force_sub_callback, adm_force_add_callback,
        adm_force_del_callback, adm_force_delone_callback, adm_force_clear_callback,
        adm_cfg_instructions_callback,
        adm_set_instructions_ar_callback, adm_set_instructions_en_callback,
        adm_cfg_links_callback,
        adm_set_link_activation_callback, adm_set_link_main_callback, adm_set_link_support_callback,
    )

    # ── Stars / Binance ───────────────────────────────────
    from handlers.stars_binance_pay import (
        charge_stars_callback, stars_preset_callback, stars_custom_callback,
        successful_payment_stars,
        charge_binance_callback,
        binance_approve_callback, binance_reject_callback,
    )

    # ━━━━━━━━━━━━━━━━━━━━━━ Commands ━━━━━━━━━━━━━━━━━━━━━━
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))

    # ━━━━━━━━━━━━━━━━━━━━━━ User ━━━━━━━━━━━━━━━━━━━━━━━━━━
    app.add_handler(CallbackQueryHandler(start_callback,            pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(my_account_callback,       pattern="^my_account$"))
    app.add_handler(CallbackQueryHandler(buy_country_callback,      pattern="^buy_country$"))
    app.add_handler(CallbackQueryHandler(buy_number_callback,       pattern=r"^buy_num_.+$"))
    app.add_handler(CallbackQueryHandler(confirm_buy_callback,      pattern=r"^confirm_buy_.+$"))
    app.add_handler(CallbackQueryHandler(get_otp_callback,          pattern=r"^get_otp_\d+$"))
    app.add_handler(CallbackQueryHandler(my_orders_callback,        pattern="^my_orders$"))
    app.add_handler(CallbackQueryHandler(otp_history_callback,      pattern="^otp_history$"))
    app.add_handler(CallbackQueryHandler(toggle_favorite_callback,  pattern=r"^toggle_fav_.+$"))
    app.add_handler(CallbackQueryHandler(deposit_callback,          pattern="^deposit$"))
    app.add_handler(CallbackQueryHandler(charge_usdt_menu_callback, pattern="^charge_usdt_menu$"))
    app.add_handler(CallbackQueryHandler(check_sub_callback,        pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(choose_language_callback,  pattern="^choose_language$"))
    app.add_handler(CallbackQueryHandler(set_lang_callback,         pattern=r"^set_lang_(ar|en)_.+$"))
    app.add_handler(CallbackQueryHandler(instructions_callback,     pattern="^instructions$"))

    # ━━━━━━━━━━━━━━━━━━━━━━ SMS ━━━━━━━━━━━━━━━━━━━━━━━━━━━
    app.add_handler(CallbackQueryHandler(sms_countries_callback, pattern="^sms_countries$"))
    app.add_handler(CallbackQueryHandler(sms_app_callback,       pattern=r"^sms_app_(whatsapp|telegram)$"))
    app.add_handler(CallbackQueryHandler(sms_buy_callback,       pattern=r"^sms_buy_.+$"))

    # User — أزرار إلغاء/حظر رقم SMS
    from handlers.sms_actions import sms_cancel_callback, sms_block_callback
    app.add_handler(CallbackQueryHandler(sms_cancel_callback, pattern=r"^sms_cancel_\d+$"))
    app.add_handler(CallbackQueryHandler(sms_block_callback,  pattern=r"^sms_block_\d+$"))

    # ━━━━━━━━━━━━━━━━━━━━━━ Stars ━━━━━━━━━━━━━━━━━━━━━━━━━
    app.add_handler(CallbackQueryHandler(charge_stars_callback, pattern="^charge_stars$"))
    app.add_handler(CallbackQueryHandler(stars_preset_callback, pattern=r"^stars_buy_\d+(\.\d+)?$"))
    app.add_handler(CallbackQueryHandler(stars_custom_callback, pattern="^stars_custom$"))
    async def _precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.pre_checkout_query.answer(ok=True)

    app.add_handler(PreCheckoutQueryHandler(_precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_stars))

    # ━━━━━━━━━━━━━━━━━━━━━━ Binance ━━━━━━━━━━━━━━━━━━━━━━━
    app.add_handler(CallbackQueryHandler(charge_binance_callback,  pattern="^charge_binance$"))
    app.add_handler(CallbackQueryHandler(binance_approve_callback, pattern=r"^binance_approve_.+$"))
    app.add_handler(CallbackQueryHandler(binance_reject_callback,  pattern=r"^binance_reject_.+$"))

    # ━━━━━━━━━━━━━━━━━━━━━━ Crypto (BEP20/TRC20/TON/TRX) ━━
    async def _charge_bep20(u, c):
        await u.callback_query.answer()
        h = c.bot_data.get("cph")
        if h: await h.show_pay_page(u.effective_chat.id, "bep20")

    async def _charge_trc20(u, c):
        await u.callback_query.answer()
        h = c.bot_data.get("cph")
        if h: await h.show_pay_page(u.effective_chat.id, "trc20")

    async def _charge_ton(u, c):
        await u.callback_query.answer()
        h = c.bot_data.get("ttp")
        if h: await h.show_pay_page(u.effective_chat.id, "ton")

    async def _charge_trx(u, c):
        await u.callback_query.answer()
        h = c.bot_data.get("ttp")
        if h: await h.show_pay_page(u.effective_chat.id, "trx")

    async def _charge_vod(u, c):
        await u.callback_query.answer()
        h = c.bot_data.get("vah")
        if h: await h.show_pay_page(u.effective_chat.id, u.effective_user.id)

    app.add_handler(CallbackQueryHandler(_charge_bep20, pattern="^charge_bep20$"))
    app.add_handler(CallbackQueryHandler(_charge_trc20, pattern="^charge_trc20$"))
    app.add_handler(CallbackQueryHandler(_charge_ton,   pattern="^charge_ton$"))
    app.add_handler(CallbackQueryHandler(_charge_trx,   pattern="^charge_trx$"))
    app.add_handler(CallbackQueryHandler(_charge_vod,   pattern="^charge_vodafone$"))

    # ━━━━━━━━━━━━━━━━━━━━━━ Crypto callbacks ━━━━━━━━━━━━━━━
    async def _crypto_sent(u, c):
        net = u.callback_query.data.replace("crypto_sent_", "")
        await u.callback_query.answer()
        h = c.bot_data.get("cph")
        if h: await h.prompt_txid(u.effective_chat.id, u.effective_user.id, net)

    async def _crypto_copy(u, c):
        net = u.callback_query.data.replace("crypto_copy_", "")
        await u.callback_query.answer()
        h = c.bot_data.get("cph")
        if h: await h.handle_copy(u.effective_chat.id, net)

    async def _tontrx_sent(u, c):
        net = u.callback_query.data.replace("tontrx_sent_", "")
        await u.callback_query.answer()
        h = c.bot_data.get("ttp")
        if h: await h.prompt_txid(u.effective_chat.id, u.effective_user.id, net)

    async def _tontrx_copy(u, c):
        net = u.callback_query.data.replace("tontrx_copy_", "")
        await u.callback_query.answer()
        h = c.bot_data.get("ttp")
        if h: await h.handle_copy(u.effective_chat.id, net)

    async def _charge_back(u, c):
        await u.callback_query.answer()
        await deposit_callback(u, c)

    app.add_handler(CallbackQueryHandler(_crypto_sent,  pattern=r"^crypto_sent_.+$"))
    app.add_handler(CallbackQueryHandler(_crypto_copy,  pattern=r"^crypto_copy_.+$"))
    app.add_handler(CallbackQueryHandler(_tontrx_sent,  pattern=r"^tontrx_sent_.+$"))
    app.add_handler(CallbackQueryHandler(_tontrx_copy,  pattern=r"^tontrx_copy_.+$"))
    app.add_handler(CallbackQueryHandler(_charge_back,  pattern="^charge_back$"))
    app.add_handler(CallbackQueryHandler(_charge_back,  pattern="^charge_cancel$"))

    # ━━━━━━━━━━━━━━━━━━━━━━ Admin ━━━━━━━━━━━━━━━━━━━━━━━━━━
    app.add_handler(CallbackQueryHandler(admin_callback,         pattern="^adm_main$"))
    app.add_handler(CallbackQueryHandler(adm_stats_callback,     pattern="^adm_stats$"))
    app.add_handler(CallbackQueryHandler(adm_numbers_callback,   pattern="^adm_numbers$"))
    app.add_handler(CallbackQueryHandler(adm_num_cc_callback,    pattern=r"^adm_num_cc_.+$"))
    app.add_handler(CallbackQueryHandler(adm_num_delete_menu_callback,        pattern="^adm_num_delete_menu$"))
    app.add_handler(CallbackQueryHandler(adm_num_del_country_list_callback,   pattern="^adm_num_del_country_list$"))
    app.add_handler(CallbackQueryHandler(adm_num_delcountry_callback,         pattern=r"^adm_num_delcountry_.+$"))
    app.add_handler(CallbackQueryHandler(adm_num_del_single_callback,         pattern="^adm_num_del_single$"))
    app.add_handler(CallbackQueryHandler(adm_num_clear_all_callback,          pattern="^adm_num_clear_all$"))
    app.add_handler(CallbackQueryHandler(adm_num_clear_all_confirm_callback,  pattern="^adm_num_clear_all_confirm$"))
    app.add_handler(CallbackQueryHandler(adm_upload_callback,        pattern="^adm_upload$"))
    app.add_handler(CallbackQueryHandler(adm_upload_normal_callback, pattern="^adm_upload_normal$"))
    app.add_handler(CallbackQueryHandler(adm_upload_newcat_callback, pattern="^adm_upload_newcat$"))
    app.add_handler(CallbackQueryHandler(adm_upload_cat_callback,    pattern=r"^adm_upload_cat_.+$"))
    app.add_handler(CallbackQueryHandler(adm_prices_callback,    pattern="^adm_prices$"))
    app.add_handler(CallbackQueryHandler(adm_setprice_callback,  pattern=r"^adm_setprice_.+$"))
    app.add_handler(CallbackQueryHandler(adm_orders_callback,    pattern="^adm_orders$"))
    app.add_handler(CallbackQueryHandler(adm_deposits_callback,  pattern="^adm_deposits$"))
    app.add_handler(CallbackQueryHandler(adm_dep_ok_callback,    pattern=r"^adm_dep_ok_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_dep_no_callback,    pattern=r"^adm_dep_no_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_broadcast_callback, pattern="^adm_broadcast$"))
    app.add_handler(CallbackQueryHandler(adm_settings_callback,  pattern="^adm_settings$"))

    # Admin — قنوات
    app.add_handler(CallbackQueryHandler(adm_cfg_channels_callback,   pattern="^adm_cfg_channels$"))
    app.add_handler(CallbackQueryHandler(adm_clear_channels_callback, pattern="^adm_clear_channels$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_notify_callback,     pattern="^adm_cfg_notify$"))
    app.add_handler(CallbackQueryHandler(adm_clear_notify_callback,   pattern="^adm_clear_notify$"))

    # Admin — طرق الدفع
    app.add_handler(CallbackQueryHandler(adm_cfg_stars_callback,   pattern="^adm_cfg_stars$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_binance_callback, pattern="^adm_cfg_binance$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_bep20_callback,   pattern="^adm_cfg_bep20$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_trc20_callback,   pattern="^adm_cfg_trc20$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_ton_callback,     pattern="^adm_cfg_ton$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_trx_callback,     pattern="^adm_cfg_trx$"))
    app.add_handler(CallbackQueryHandler(adm_cfg_vod_callback,     pattern="^adm_cfg_vod$"))
    app.add_handler(CallbackQueryHandler(adm_toggle_callback,      pattern=r"^adm_toggle_.+$"))

    # Admin — إدارة المستخدمين
    app.add_handler(CallbackQueryHandler(adm_users_callback,  pattern="^adm_users$"))
    app.add_handler(CallbackQueryHandler(adm_ban_callback,    pattern=r"^adm_ban_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_unban_callback,  pattern=r"^adm_unban_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_addbal_callback, pattern=r"^adm_addbal_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_subbal_callback, pattern=r"^adm_subbal_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_setbal_callback, pattern=r"^adm_setbal_\d+$"))

    # Admin — متنوع
    app.add_handler(CallbackQueryHandler(adm_zip_callback,      pattern=r"^adm_zip"))
    app.add_handler(CallbackQueryHandler(adm_del_sold_callback, pattern=r"^adm_del_sold_.+$"))

    # Admin — SMS
    app.add_handler(CallbackQueryHandler(adm_sms_callback,              pattern="^adm_sms$"))
    app.add_handler(CallbackQueryHandler(adm_sms_upload_wa_callback,    pattern="^adm_sms_upload_wa$"))
    app.add_handler(CallbackQueryHandler(adm_sms_upload_tg_callback,    pattern="^adm_sms_upload_tg$"))
    app.add_handler(CallbackQueryHandler(adm_sms_price_callback,        pattern="^adm_sms_price$"))
    app.add_handler(CallbackQueryHandler(adm_sms_country_price_callback,pattern="^adm_sms_country_price$"))
    app.add_handler(CallbackQueryHandler(adm_sms_setcp_callback,        pattern=r"^adm_sms_setcp_.+$"))
    app.add_handler(CallbackQueryHandler(adm_sms_list_callback,         pattern="^adm_sms_list$"))
    app.add_handler(CallbackQueryHandler(adm_sms_delete_menu_callback,  pattern="^adm_sms_delete_menu$"))
    app.add_handler(CallbackQueryHandler(adm_sms_del_country_wa_callback,pattern="^adm_sms_del_country_wa$"))
    app.add_handler(CallbackQueryHandler(adm_sms_del_country_tg_callback,pattern="^adm_sms_del_country_tg$"))
    app.add_handler(CallbackQueryHandler(adm_sms_delcountry_callback,   pattern=r"^adm_sms_delcountry_.+$"))
    app.add_handler(CallbackQueryHandler(adm_sms_del_single_callback,   pattern="^adm_sms_del_single$"))
    app.add_handler(CallbackQueryHandler(adm_sms_clear_wa_callback,     pattern="^adm_sms_clear_wa$"))
    app.add_handler(CallbackQueryHandler(adm_sms_clear_tg_callback,     pattern="^adm_sms_clear_tg$"))
    app.add_handler(CallbackQueryHandler(adm_sms_clear_callback,        pattern="^adm_sms_clear_all$"))
    app.add_handler(CallbackQueryHandler(adm_sms_app_labels_callback,   pattern="^adm_sms_app_labels$"))
    app.add_handler(CallbackQueryHandler(adm_sms_set_wa_label_callback, pattern="^adm_sms_set_wa_label$"))
    app.add_handler(CallbackQueryHandler(adm_sms_set_tg_label_callback, pattern="^adm_sms_set_tg_label$"))

    # Admin — اشتراك إجباري
    app.add_handler(CallbackQueryHandler(adm_cfg_force_sub_callback, pattern="^adm_cfg_force_sub$"))
    app.add_handler(CallbackQueryHandler(adm_force_add_callback,     pattern="^adm_force_add$"))
    app.add_handler(CallbackQueryHandler(adm_force_del_callback,     pattern="^adm_force_del$"))
    app.add_handler(CallbackQueryHandler(adm_force_delone_callback,  pattern=r"^adm_force_delone_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_force_clear_callback,   pattern="^adm_force_clear$"))

    # Admin — التعليمات
    app.add_handler(CallbackQueryHandler(adm_cfg_instructions_callback,    pattern="^adm_cfg_instructions$"))
    app.add_handler(CallbackQueryHandler(adm_set_instructions_ar_callback, pattern="^adm_set_instructions_ar$"))
    app.add_handler(CallbackQueryHandler(adm_set_instructions_en_callback, pattern="^adm_set_instructions_en$"))

    # Admin — روابط
    app.add_handler(CallbackQueryHandler(adm_cfg_links_callback,           pattern="^adm_cfg_links$"))
    app.add_handler(CallbackQueryHandler(adm_set_link_activation_callback, pattern="^adm_set_link_activation$"))
    app.add_handler(CallbackQueryHandler(adm_set_link_main_callback,       pattern="^adm_set_link_main$"))
    app.add_handler(CallbackQueryHandler(adm_set_link_support_callback,    pattern="^adm_set_link_support$"))

    # Admin — كوبونات
    from handlers.admin.panel import (
        adm_coupons_callback, adm_coupon_create_callback, adm_coupon_del_callback,
        adm_coupon_delone_callback, adm_discounts_callback, adm_discount_add_callback,
        adm_discount_clear_callback, adm_referral_settings_callback,
        adm_ref_set_pct_callback, adm_ref_set_min_callback,
        adm_report_settings_callback, adm_set_report_ch_callback,
        adm_send_report_now_callback, adm_backup_now_callback, adm_restore_backup_callback,
    )
    app.add_handler(CallbackQueryHandler(adm_coupons_callback,          pattern="^adm_coupons$"))
    app.add_handler(CallbackQueryHandler(adm_coupon_create_callback,    pattern="^adm_coupon_create$"))
    app.add_handler(CallbackQueryHandler(adm_coupon_del_callback,       pattern="^adm_coupon_del$"))
    app.add_handler(CallbackQueryHandler(adm_coupon_delone_callback,    pattern=r"^adm_coupon_delone_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_discounts_callback,        pattern="^adm_discounts$"))
    app.add_handler(CallbackQueryHandler(adm_discount_add_callback,     pattern="^adm_discount_add$"))
    app.add_handler(CallbackQueryHandler(adm_discount_clear_callback,   pattern="^adm_discount_clear$"))
    app.add_handler(CallbackQueryHandler(adm_referral_settings_callback,pattern="^adm_referral_settings$"))
    app.add_handler(CallbackQueryHandler(adm_ref_set_pct_callback,      pattern="^adm_ref_set_pct$"))
    app.add_handler(CallbackQueryHandler(adm_ref_set_min_callback,      pattern="^adm_ref_set_min$"))
    app.add_handler(CallbackQueryHandler(adm_report_settings_callback,  pattern="^adm_report_settings$"))
    app.add_handler(CallbackQueryHandler(adm_set_report_ch_callback,    pattern="^adm_set_report_ch$"))
    app.add_handler(CallbackQueryHandler(adm_send_report_now_callback,  pattern="^adm_send_report_now$"))
    app.add_handler(CallbackQueryHandler(adm_backup_now_callback,       pattern="^adm_backup_now$"))
    app.add_handler(CallbackQueryHandler(adm_restore_backup_callback,   pattern="^adm_restore_backup$"))

    # Admin — أداء الدول / تنبيه المخزون / بحث رقم / سجل عمليات
    from handlers.admin.panel import (
        adm_performance_callback, adm_low_stock_callback,
        adm_search_number_callback, adm_search_number_msg_handler,
        adm_audit_log_callback,
    )
    app.add_handler(CallbackQueryHandler(adm_performance_callback,    pattern="^adm_performance$"))
    app.add_handler(CallbackQueryHandler(adm_low_stock_callback,      pattern="^adm_low_stock$"))
    app.add_handler(CallbackQueryHandler(adm_search_number_callback,  pattern="^adm_search_number$"))
    app.add_handler(CallbackQueryHandler(adm_audit_log_callback,      pattern="^adm_audit_log$"))

    # User — إحالة
    from handlers.referral import referral_callback, referral_withdraw_callback, referral_noop_callback
    app.add_handler(CallbackQueryHandler(referral_callback,          pattern="^referral_menu$"))
    app.add_handler(CallbackQueryHandler(referral_withdraw_callback, pattern="^referral_withdraw$"))
    app.add_handler(CallbackQueryHandler(referral_noop_callback,     pattern="^referral_noop$"))

    # User — كوبون شحن
    from handlers.coupon import coupon_callback
    app.add_handler(CallbackQueryHandler(coupon_callback, pattern="^use_coupon$"))

    # Admin — السعر الافتراضي
    async def _adm_default_price(u, c):
        c.user_data["adm_state"] = "waiting_default_price"
        await u.callback_query.edit_message_text(
            "💰 أرسل السعر الافتراضي الجديد (مثال: <code>0.5</code>):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="adm_prices")
            ]]),
            parse_mode="HTML"
        )
    app.add_handler(CallbackQueryHandler(_adm_default_price, pattern="^adm_default_price$"))

    # adm_set_* — يجب أن يكون آخر شيء في admin
    app.add_handler(CallbackQueryHandler(adm_set_key_callback, pattern=r"^adm_set_.+$"))

    # ━━━━━━━━━━━━━━━━━━━━━━ Message Router ━━━━━━━━━━━━━━━━━
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
        message_router
    ))

    # ━━━━━━━━━━━━━━━━━━━━━━ Error Handler ━━━━━━━━━━━━━━━━━━
    app.add_error_handler(error_handler)


# ══════════════════════════════════════════════════════════
#  main
# ══════════════════════════════════════════════════════════

async def main():
    os.makedirs("data",     exist_ok=True)
    os.makedirs("sessions", exist_ok=True)

    db = Database(config.DATABASE_PATH)

    # إعدادات أساسية من config — بس لو مش موجودة في DB
    db.set_setting("admin_id", str(config.ADMIN_ID))

    def _set_if_empty(key, val):
        if val and not db.get_setting(key, ""):
            db.set_setting(key, str(val))

    _set_if_empty("notify_channel",     getattr(config, "CHANNEL_ID",          ""))
    _set_if_empty("deposit_channel",    getattr(config, "DEPOSIT_CHANNEL_ID",  ""))
    _set_if_empty("newuser_channel",    getattr(config, "NEWUSER_CHANNEL_ID",  ""))
    _set_if_empty("bep20_address",      getattr(config, "BEP20_ADDRESS",       ""))
    _set_if_empty("trc20_address",      getattr(config, "TRC20_ADDRESS",       ""))
    _set_if_empty("ton_address",        getattr(config, "TON_ADDRESS",         ""))
    _set_if_empty("vodafone_number",    getattr(config, "VODAFONE_NUMBER",     ""))
    _set_if_empty("binance_api_key",    getattr(config, "BINANCE_API_KEY",     ""))
    _set_if_empty("binance_api_secret", getattr(config, "BINANCE_API_SECRET",  ""))
    _set_if_empty("binance_pay_id",     getattr(config, "BINANCE_PAY_ID",      ""))
    _set_if_empty("default_price",      "0.5")
    _set_if_empty("stars_rate",         "85")
    _set_if_empty("stars_min_usd",      "1")
    _set_if_empty("binance_min_usd",    "0.01")
    _set_if_empty("bep20_min_usdt",     "1")
    _set_if_empty("trc20_min_usdt",     "1")
    _set_if_empty("ton_min_amount",     "1")
    _set_if_empty("trx_min_amount",     "10")
    _set_if_empty("vod_auto_min_egp",   "50")

    app = Application.builder().token(config.BOT_TOKEN).build()

    cph = CryptoPayHandler(db=db, bot=app.bot)
    ttp = TonTrxPayHandler(db=db, bot=app.bot)
    vah = VodafoneAutoHandler(db=db, bot=app.bot)

    from sms_handler import SmsPoller
    sms_poller = SmsPoller(db=db, bot=app.bot)

    app.bot_data.update({
        "db":         db,
        "cph":        cph,
        "ttp":        ttp,
        "vah":        vah,
        "otp_listener": None,
        "sms_poller": sms_poller,
    })

    # OTP Listener
    if getattr(config, "TG_API_ID", None) and getattr(config, "TG_API_HASH", None):
        otp_listener = OtpListener(
            db=db, bot=app.bot,
            api_id=config.TG_API_ID,
            api_hash=config.TG_API_HASH
        )
        app.bot_data["otp_listener"] = otp_listener
        await otp_listener.start()
    else:
        logger.warning("[MAIN] TG_API_ID/HASH غير محدد — OTP listener معطّل")

    register_handlers(app)

    logger.info("[MAIN] ✅ البوت شغال")
    async with app:
        await app.start()
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        # Background loops
        from features import daily_report_loop, backup_loop
        from handlers.admin.panel import low_stock_check_loop
        asyncio.create_task(daily_report_loop(app.bot, db))
        asyncio.create_task(backup_loop(app.bot, db))
        asyncio.create_task(low_stock_check_loop(app.bot, db))

        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
