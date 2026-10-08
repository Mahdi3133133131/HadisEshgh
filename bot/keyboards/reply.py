"""
صفحه‌کلید زیرین — همان که سند «کنار سنجاق، عکس چهارخانه» نامیده بود.

آن نشانهٔ چهارخانه، آیکون خودکار تلگرام برای ReplyKeyboard است؛
خودش پدیدار می‌شود و نمی‌توان دگرگونش کرد. کاری که ما می‌کنیم
ساختن همان صفحه‌کلید است تا آن نشانه پدید آید.
"""

from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from core import texts


def main_menu() -> ReplyKeyboardMarkup:
    """
    منوی همیشگی.

    «بازجویی نوا» تنها در سطر خود نشسته، چون کار اصلی ربات همان است
    و باید بی‌درنگ به چشم بیاید.
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(texts.btn("menu_search"))],
            [
                KeyboardButton(texts.btn("menu_popular")),
                KeyboardButton(texts.btn("menu_madahs")),
            ],
            [
                KeyboardButton(texts.btn("menu_submit")),
                KeyboardButton(texts.btn("menu_feedback")),
            ],
            [
                KeyboardButton(texts.btn("menu_tokens")),
                KeyboardButton(texts.btn("menu_help")),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def styles_keyboard() -> ReplyKeyboardMarkup:
    """
    سبک‌های مداحی، سه‌تا در هر سطر.

    از صفحه‌کلید زیرین بهره می‌بریم نه دکمهٔ درون‌خطی، تا کاربر
    بتواند سبکی بیرون از فهرست را هم دستی بنویسد.
    """
    from bot.states import STYLES

    rows = [list(STYLES[i : i + 3]) for i in range(0, len(STYLES), 3)]
    rows.append([texts.btn("cancel")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def skip_keyboard() -> ReplyKeyboardMarkup:
    """
    گامی که می‌توان از آن گذشت.

    دکمهٔ آشکار برای گذشتن لازم است: کاربری که بیت شعر را نمی‌داند
    وگرنه در آن گام می‌ماند و گمان می‌کند ربات پاسخ نمی‌دهد.
    """
    return ReplyKeyboardMarkup(
        [[texts.btn("skip_title")]], resize_keyboard=True, one_time_keyboard=True
    )


def remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
