"""
utils/keyboards.py — keyboards مشتركة لبوت الأرقام
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ])


def cancel_kb(cb: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ إلغاء", callback_data=cb)]
    ])
