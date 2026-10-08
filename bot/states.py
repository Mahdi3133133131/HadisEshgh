"""
وضعیت‌های گفت‌وگو.

چرا ConversationHandler به کار نرفت: صفحه‌کلید زیرین همیشه بر پرده
است و کاربر هر لحظه می‌تواند از میانهٔ یک جریان بیرون بپرد.
ConversationHandler با این رفتار سازگار نیست و به «کاربر در وضعیتی
گیر کرده» می‌انجامد — ایرادی که کاربر خودش نمی‌فهمد و تنها می‌بیند
ربات پاسخ نمی‌دهد.

به جایش یک کلید ساده در context.user_data گذاشته‌ایم که هر دکمهٔ
منو آن را پاک می‌کند. پس بیرون آمدن، همیشه با یک ضربه شدنی است.
"""

from __future__ import annotations

from typing import Any

STATE_KEY = "state"
DATA_KEY = "state_data"

# ── کاربر ────────────────────────────────────────────────────
AWAITING_SUBMISSION_FILE = "awaiting_submission_file"
AWAITING_SUBMISSION_MADAH = "awaiting_submission_madah"
AWAITING_SUBMISSION_STYLE = "awaiting_submission_style"
AWAITING_SUBMISSION_TITLE = "awaiting_submission_title"

# ویرایش یک بخش از پیشکش. هم همراه در گفتگوی خصوصی به آن
# می‌رسد و هم گرداننده در گروه، پس در GROUP_ONLY_STATES نیست؛
# به جایش شناسهٔ گفتگو در دادهٔ وضعیت نگه داشته می‌شود تا پیامِ
# گفتگوی دیگر به اشتباه ویرایش شمرده نشود.
AWAITING_EDIT_VALUE = "awaiting_edit_value"
AWAITING_FEEDBACK = "awaiting_feedback"
AWAITING_SEARCH_INPUT = "awaiting_search_input"

# پرسش «نام مداح را می‌دانید؟» — پیش از جست‌وجو پرسیده می‌شود و
# اگر کاربر ندانست، پس از ناکامی دگربار.
AWAITING_SEARCH_HINT = "awaiting_search_hint"
AWAITING_HINT_AFTER_FAIL = "awaiting_hint_after_fail"

# ── گرداننده ─────────────────────────────────────────────────
AWAITING_BROADCAST = "awaiting_broadcast"
AWAITING_ADMIN_REPLY = "awaiting_admin_reply"

# افزودن انبوه در گروه مداحی
AWAITING_BULK_AUDIO = "awaiting_bulk_audio"

# برداشتن نوا از گنجینه، در گروه مداحی
AWAITING_DELETE_QUERY = "awaiting_delete_query"

# پاسخِ گرداننده به «شناسه و پیوند کانال را بفرستید».
# یک وضعیت برای هر دو فهرست (عضویت اجباری و منبع)؛ کدامشان در
# دادهٔ وضعیت می‌نشیند، تا دو وضعیتِ همسان نداشته باشیم.
AWAITING_CHANNEL_INPUT = "awaiting_channel_input"

# ویرایش شناسنامهٔ نوایی که از پیش در گنجینه نشسته — از زیر خودِ
# فایل، در گروه بایگانی. جدا از ویرایشِ پیشکش است، چون آنجا هنوز
# چیزی در گنجینه ننشسته و اینجا نشسته و فایلش هم باید از نو
# برچسب بخورد.
AWAITING_TRACK_EDIT = "awaiting_track_edit"

# پرکردن یک بازجویی ناکام: تنها گامِ گرفتنِ خودِ نوا اینجاست؛
# پرسیدن مداح و سبک و نام، از آن پس کارِ «دفتر پذیرش» است.
AWAITING_FILL_AUDIO = "awaiting_fill_audio"

# بازیابی پایگاه داده از فایل پشتیبان — تنها در گروه مداحی و تنها
# پس از `/restore`. بی این وضعیت، سندِ `.db` در گروه بی‌اعتبار است.
AWAITING_RESTORE_FILE = "awaiting_restore_file"

# دفتر پذیرش — یک جریان یگانه برای هر نوایی که گرداننده می‌افزاید:
# افزودن انبوه، نوای بازفرستاده، و پر کردن بازجویی ناکام، هر سه از
# همین وضعیت‌ها می‌گذرند. پیش از این هر کدام جریان جدای خود را
# داشت و هیچ‌کدام دکمهٔ تأیید و ویرایش نداشت.
AWAITING_INTAKE_MADAH = "awaiting_intake_madah"
AWAITING_INTAKE_STYLE = "awaiting_intake_style"
AWAITING_INTAKE_TITLE = "awaiting_intake_title"
AWAITING_INTAKE_EDIT = "awaiting_intake_edit"

# کارت شناسنامه بر پرده است و ربات چشم‌به‌راه نواختن است، نه
# نوشتار. وضعیت جدایی می‌خواهد: بی آن، هر سخنی که گرداننده در گروه
# می‌گفت به چشم «نام تازهٔ نوا» می‌آمد.
# غربالِ پیش از پرسش‌ها: «این را از پیش داریم، درست است؟»
AWAITING_INTAKE_SCREEN = "awaiting_intake_screen"
AWAITING_INTAKE_CARD = "awaiting_intake_card"

# همهٔ وضعیت‌های دفتر پذیرش، یک‌جا — تا مسیریاب ناگزیر نباشد
# چهار نام را در دو جا بشمارد و روزی یکی را جا بیندازد.
INTAKE_STATES = frozenset(
    {
        AWAITING_INTAKE_MADAH,
        AWAITING_INTAKE_STYLE,
        AWAITING_INTAKE_TITLE,
        AWAITING_INTAKE_EDIT,
        AWAITING_INTAKE_CARD,
        AWAITING_INTAKE_SCREEN,
    }
)

# وضعیت‌هایی که تنها در گروه گردانندگان معنا دارند.
#
# چرا این فهرست لازم است: user_data در تلگرام برای هر **کاربر** یکی
# است، نه برای هر گفتگو. پس گرداننده‌ای که در گروه «افزودن انبوه» را
# آغاز کرده و سپس در گفتگوی خصوصی آوایی می‌فرستد، همان وضعیت را با
# خود می‌آورد — و آن آوا به چشم «نوای دسته» می‌آمد، حال آنکه او
# می‌خواست بازجویی کند. در گفتگوی خصوصی پاک می‌شوند.
GROUP_ONLY_STATES = frozenset(
    {
        AWAITING_BROADCAST,
        AWAITING_ADMIN_REPLY,
        AWAITING_BULK_AUDIO,
        AWAITING_DELETE_QUERY,
        AWAITING_FILL_AUDIO,
        AWAITING_RESTORE_FILE,
    }
)

# وضعیت‌های دفتر پذیرش عمداً در فهرست بالا نیستند: پذیرش هم در
# گروه می‌گذرد و هم — برای نوای بازفرستاده — در گفتگوی خصوصی. به
# جای پاک کردن بر پایهٔ گونهٔ گفتگو، خودِ گرداننده‌اش شناسهٔ گفتگو را
# می‌سنجد؛ دقیق‌تر است و پذیرشِ نیمه‌کاره را نمی‌پراند.

# سبک‌هایی که هنگام پیشکش پیشنهاد می‌شوند.
# داشتن این برچسب‌ها از همین امروز، دیتاست مرحلهٔ هفت (تشخیص خودکار
# سبک) را می‌سازد؛ وگرنه بعداً باید هزاران نوا را دستی برچسب زد.
STYLES = ("شور", "واحد", "زمینه", "تک", "لطمه", "روضه", "مناجات", "دیگر")


def set_state(user_data: dict[str, Any], state: str | None, **data: Any) -> None:
    if state is None:
        user_data.pop(STATE_KEY, None)
        user_data.pop(DATA_KEY, None)
        return
    user_data[STATE_KEY] = state
    # بی‌کلید بودن یعنی «این وضعیت داده‌ای ندارد» — پس دادهٔ وضعیتِ
    # پیشین باید برداشته شود. پیش‌تر جا می‌ماند و وضعیت تازه، دادهٔ
    # کهنهٔ کارِ دیگری را به ارث می‌برد.
    if data:
        user_data[DATA_KEY] = data
    else:
        user_data.pop(DATA_KEY, None)


def get_state(user_data: dict[str, Any]) -> str | None:
    return user_data.get(STATE_KEY)


def get_data(user_data: dict[str, Any]) -> dict[str, Any]:
    return user_data.get(DATA_KEY, {})


def clear_state(user_data: dict[str, Any]) -> None:
    set_state(user_data, None)


def clear_state_here(user_data: dict[str, Any], chat_id: int | None) -> None:
    """
    وضعیت را پاک می‌کند، مگر آنکه به گفتگوی دیگری تعلق داشته باشد.

    ## چرا این جدایی لازم شد

    user_data در تلگرام برای هر **کاربر** یکی است، نه برای هر
    گفتگو. پس گرداننده‌ای که پذیرشی نیمه‌کاره در گروه مداحی داشت و
    سپس در گفتگوی خصوصی «منو» را می‌زد، همان یک زدن، پذیرشِ گروه را
    از میان می‌برد — و از آن پس هر دکمه‌ای در گروه می‌گفت «پذیرشی
    در جریان نیست».

    اکنون تنها وضعیتی پاک می‌شود که به همین گفتگو تعلق دارد.
    """
    data = get_data(user_data)
    owner = data.get("chat_id")
    if owner is not None and chat_id is not None and int(owner) != int(chat_id):
        return
    clear_state(user_data)
