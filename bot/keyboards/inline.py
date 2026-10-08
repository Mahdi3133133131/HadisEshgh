"""
دکمه‌های درون‌خطی.

## نکتهٔ مهم دربارهٔ دکمهٔ صفحهٔ اینستاگرام

سند خواسته بود چون سنجیدن دنبال‌کنندگان اینستاگرام از توان ربات
بیرون است، دست‌کم «نواختن بر دکمهٔ صفحه» شرط ورود باشد.

ولی دکمهٔ پیوند (url) در تلگرام هیچ خبری به ربات نمی‌دهد؛ کاربر
می‌نوازد، مرورگر گشوده می‌شود، و ربات هرگز آگاه نمی‌گردد. پس آن شرط
به شکل خواسته‌شده اصلاً سنجیدنی نیست.

چاره‌ای که به کار بسته‌ایم: دکمه از گونهٔ callback است. با نواخته
شدن، ربات آن را ثبت می‌کند و همان دکمه در جا به پیوند راستین
دگرگون می‌شود تا کاربر بتواند صفحه را بگشاید. یک نواخت افزون‌تر،
ولی شرط، سنجیدنی می‌گردد.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import config
from core import texts
from core.normalize import to_persian_digits

# ── پیشوندهای دادهٔ فراخوان ──────────────────────────────────
GATE_INSTAGRAM = "gate:ig"
GATE_CHECK = "gate:check"

SUB_APPROVE = "sub:ok"
SUB_REJECT = "sub:no"
SUB_TRUST = "sub:trust"

# جریان بازبینی و ویرایش — هم سوی همراه، هم سوی گرداننده
SUB_SEND = "sub:send"        # همراه: بفرست به گروه
SUB_DROP = "sub:drop"        # همراه: بی‌خیال شو
SUB_EDIT = "sub:edit"        # هر دو سو: فهرست بخش‌ها
SUB_FIELD = "sub:field"      # هر دو سو: این بخش را می‌خواهم
SUB_BACK = "sub:back"        # بازگشت به شناسنامه

# دفتر پذیرش — نوایی که گرداننده می‌افزاید. هر دکمه شمارهٔ کارت را
# با خود دارد تا نواختن بر کارتِ کهنه، نوای امروز را دگرگون نکند.
IN_OK = "in:ok"
IN_NO = "in:no"
IN_EDIT = "in:edit"
IN_FIELD = "in:field"
IN_BACK = "in:back"
# غربال: «همین است که داریم» / «نه، تازه است»
IN_DUP = "in:dup"
IN_NEW = "in:new"
IN_STYLE = "in:style"
IN_SKIP = "in:skip"

# یافته‌های تارنماها. شمارهٔ ردیف در دادهٔ فراخوان می‌رود، نه
# نشانی — نشانی صفحه بلندتر از سقف ۶۴ بایتیِ تلگرام است.
SITE_PICK = "site:get"

# داوری کاربر بر پیش‌نمایش سی‌ثانیه‌ای هر یافته
SITE_OK = "site:ok"
SITE_NO = "site:no"

# دکمه‌های زیر نسخهٔ آراسته در گروه بایگانی. شمارهٔ نوا در خودِ
# دادهٔ فراخوان است، پس این دکمه‌ها ماه‌ها بعد هم کار می‌کنند.
BROKEN_RETRY = "brk:retry"
ORN_EDIT = "orn:edit"
ORN_FIELD = "orn:field"
ORN_BACK = "orn:back"
ORN_DEL = "orn:del"
ORN_YES = "orn:yes"

FB_REPLY = "fb:reply"
FB_RELEASE = "fb:release"

BROADCAST_CANCEL = "bc:cancel"


def gate(instagram_tapped: bool = False) -> InlineKeyboardMarkup:
    """
    آستانهٔ ورود: هم‌نشینی در کانال، نواختن بر صفحه، و سنجش.

    اگر صفحه پیش‌تر نواخته شده باشد، دکمه‌اش به پیوند راستین با
    نشان ✅ دگرگون می‌شود.
    """
    # یک دکمه به ازای هر کانالِ اجباری. پیش‌تر تنها یکی بود و
    # شناسه‌اش در .env سفت شده بود.
    from core.db import channels

    rows = []
    required = channels.required_all()
    for channel in required:
        if not channel.get("url"):
            continue
        label = texts.btn("join_channel")
        if len(required) > 1:
            label = f"{label} — {channel['title']}"
        rows.append([InlineKeyboardButton(label[:64], url=channel["url"])])

    if not rows:
        rows.append(
            [InlineKeyboardButton(texts.btn("join_channel"), url=config.channel_url)]
        )

    # ── چرا دو دکمه، و نه یکی ───────────────────────────────
    #
    # خواسته این بود که زدنِ دکمه راستی کاربر را به اینستاگرام
    # ببرد، نه اینکه تنها تأیید باشد. ولی تلگرام اجازه نمی‌دهد
    # یک دکمه هم‌زمان `url` و `callback_data` داشته باشد: دکمهٔ
    # لینک هیچ خبری به ربات نمی‌دهد، و دکمهٔ بازخوردی جایی
    # نمی‌برد.
    #
    # پس دو تا، کنار هم: یکی می‌بَرَد، یکی تأیید می‌کند. پیش‌تر
    # همین دو کار در **یک** دکمه بود که با تپِ نخست به لینک بدل
    # می‌شد — و کاربر نمی‌فهمید چرا بارِ اول جایی نرفت.
    if instagram_tapped:
        rows.append(
            [
                InlineKeyboardButton(
                    f"{texts.btn('open_instagram')} ✅", url=config.instagram_url
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    texts.btn("open_instagram"), url=config.instagram_url
                ),
                InlineKeyboardButton(
                    texts.btn("instagram_done"), callback_data=GATE_INSTAGRAM
                ),
            ]
        )

    rows.append(
        [InlineKeyboardButton(texts.btn("check_membership"), callback_data=GATE_CHECK)]
    )
    return InlineKeyboardMarkup(rows)


def submission_summary(submission_id: int) -> InlineKeyboardMarkup:
    """
    شناسنامهٔ پیشکش، پیش از فرستادن به گروه — سوی همراه.

    چیدمان همان است که خواسته شد: تأیید و لغو کنار هم، ویرایش
    زیرشان. کاربر بیش از همه «تأیید» را می‌زند، پس همان بالا و در
    دسترسِ انگشت است.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("confirm"), callback_data=f"{SUB_SEND}:{submission_id}"
                ),
                InlineKeyboardButton(
                    texts.btn("cancel"), callback_data=f"{SUB_DROP}:{submission_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    texts.btn("edit"), callback_data=f"{SUB_EDIT}:{submission_id}"
                )
            ],
        ]
    )


def submission_fields(submission_id: int, side: str) -> InlineKeyboardMarkup:
    """
    «کدام بخش را می‌خواهید اصلاح کنید؟»

    سه بخش، هر کدام در سطر خودش — چون نامشان درازند و کنار هم به
    «…» می‌روند. تأیید و لغو زیرشان و کنار هم، همان‌گونه که خواسته
    شد.

    `side` می‌گوید تأییدِ پایانی چه معنایی دارد: برای همراه یعنی
    «بفرست به گروه»، برای گرداننده یعنی «بپذیر و به گنجینه ببر».
    """
    confirm = SUB_SEND if side == "user" else SUB_APPROVE
    cancel = SUB_DROP if side == "user" else SUB_REJECT
    # نوشتار هم باید راست بگوید: همراه «چشم‌پوشی» می‌کند، گرداننده
    # «رد» می‌کند. یک واژه برای هر دو، معنای کارِ گرداننده را
    # می‌پوشاند.
    cancel_label = "cancel" if side == "user" else "reject"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("field_madah"),
                    callback_data=f"{SUB_FIELD}:{submission_id}:madah",
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("field_style"),
                    callback_data=f"{SUB_FIELD}:{submission_id}:style",
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("field_title"),
                    callback_data=f"{SUB_FIELD}:{submission_id}:title",
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("confirm"), callback_data=f"{confirm}:{submission_id}"
                ),
                InlineKeyboardButton(
                    texts.btn(cancel_label), callback_data=f"{cancel}:{submission_id}"
                ),
            ],
        ]
    )


def submission_back(submission_id: int) -> InlineKeyboardMarkup:
    """
    تنها یک دکمهٔ بازگشت — هنگامی که ربات چشم‌به‌راه نوشتار است.

    بی این، کاربری که دکمهٔ ویرایش را به اشتباه زده در حالتی گیر
    می‌کرد که تنها راه بیرون آمدنش نوشتن چیزی بود.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("back"), callback_data=f"{SUB_BACK}:{submission_id}"
                )
            ]
        ]
    )


def submission_review(submission_id: int) -> InlineKeyboardMarkup:
    """
    دکمه‌های داوری پیشکش، در گروه گردانندگان.

    دکمهٔ «اعتماد» راه آسانِ همان کاری است که /trust با شناسهٔ عددی
    می‌کند: یک نواخت روی همان پیشکشی که پیش چشم است، و از آن پس
    پیشکش‌های آن همراه بی داوری به گنجینه می‌روند.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("approve"), callback_data=f"{SUB_APPROVE}:{submission_id}"
                ),
                InlineKeyboardButton(
                    texts.btn("reject"), callback_data=f"{SUB_REJECT}:{submission_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    texts.btn("edit"), callback_data=f"{SUB_EDIT}:{submission_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("trust_user"), callback_data=f"{SUB_TRUST}:{submission_id}"
                )
            ],
        ]
    )


def feedback_reply(feedback_id: int, locked: bool = False) -> InlineKeyboardMarkup:
    """
    دکمهٔ پاسخ‌گویی به انتقاد.

    هنگام در دست بودن قفل، دکمهٔ رهاکردن هم افزوده می‌شود تا اگر
    گرداننده‌ای کار را نیمه رها کرد، دیگری بتواند دستی آزادش کند و
    چشم‌به‌راه سرآمدن مهلت نماند.
    """
    rows = [
        [
            InlineKeyboardButton(
                texts.btn("reply_to_user"), callback_data=f"{FB_REPLY}:{feedback_id}"
            )
        ]
    ]
    if locked:
        rows.append(
            [
                InlineKeyboardButton(
                    texts.btn("release_lock"),
                    callback_data=f"{FB_RELEASE}:{feedback_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def broadcast_cancel(broadcast_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("cancel"), callback_data=f"{BROADCAST_CANCEL}:{broadcast_id}"
                )
            ]
        ]
    )


# ── بازجویی نوا ─────────────────────────────────────────────
SEARCH_CORRECT = "srch:ok"
SEARCH_WRONG = "srch:no"
SEARCH_SEND_FULL = "srch:full"

# میان‌بر «شروع جست‌وجو» — زیر پیام راهنمایی که وقتی کاربر بی‌مقدمه
# فایلی می‌فرستد نشان داده می‌شود. بی این، تنها راه، رفتن به منو
# بود و همان یک گام اضافه، سخت‌گیری تازه را آزاردهنده می‌کرد.
SEARCH_BEGIN = "srch:begin"

# «بی‌خیال» شمارهٔ جست‌وجو را با خود می‌برد، چون پس از زدنش باید
# صوت همان ویدیو فرستاده شود و بی شماره، نمی‌دانیم کدام.
SEARCH_CANCEL = "srch:cancel"
SEARCH_NOTIFY = "srch:notify"

# «بی‌خیال»ِ فهرست سایت‌ها کار دیگری می‌کند (تنها بستن فهرست)، پس
# فراخوان جدا دارد. پیش‌تر هر دو یکی بودند و همین، فرستادن صوت را
# ناممکن می‌کرد.
SITE_CANCEL = "site:cancel"


def search_result(search_id: int) -> InlineKeyboardMarkup:
    """
    دکمه‌های زیر نوای یافته‌شده.

    «این آن نیست» تنها بازخورد نیست؛ توکن کاربر را هم بازمی‌گرداند،
    چون خطا از ما بوده است.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("result_correct"),
                    callback_data=f"{SEARCH_CORRECT}:{search_id}",
                ),
                InlineKeyboardButton(
                    texts.btn("result_wrong"),
                    callback_data=f"{SEARCH_WRONG}:{search_id}",
                ),
            ]
        ]
    )


SIM_PLAY = "sim:play"
HINT_SKIP = "hint:skip"
FAIL_FILL = "fail:fill"
BULK_END = "bulk:end"
DEL_PICK = "del:pick"
DEL_YES = "del:yes"
DEL_CANCEL = "del:no"


def similar_offer(candidates: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """
    گمانهٔ نواهای همانند — یک دکمه برای هر نامزد.

    **هرگز خودکار فایل فرستاده نمی‌شود.** پیش‌تر چنین بود و
    نتیجه‌اش این که کاربرِ یک بازجویی ناکام، چند نوای نامربوط
    می‌گرفت. گمانه باید پیشنهاد بماند، نه فرستاده شود؛ گزینش با
    خودِ اوست.

    candidates: فهرست (شناسهٔ نوا، نوشتار دکمه)
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"{SIM_PLAY}:{track_id}")]
            for track_id, label in candidates
        ]
    )


def hint_skip() -> InlineKeyboardMarkup:
    """«نمی‌دانم» — تا پرسشِ نام مداح، بن‌بست نشود."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.btn("hint_unknown"), callback_data=HINT_SKIP)]]
    )


def failure_fill(search_id: int) -> InlineKeyboardMarkup:
    """
    در گروه گردانندگان، زیر بازجویی ناکام.

    گرداننده‌ای که نسخهٔ کامل را دارد می‌نوازد، نوا را می‌فرستد، و
    ربات هم آن را به گنجینه می‌افزاید و هم برای همان جوینده
    می‌فرستد.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("fill_request"), callback_data=f"{FAIL_FILL}:{search_id}"
                )
            ]
        ]
    )


def delete_candidates(rows) -> InlineKeyboardMarkup:
    """
    فهرست نواهای یافته، برای برگزیدن یکی.

    هر دکمه در سطر خودش می‌نشیند: نام نوا دراز است و دو دکمه در یک
    سطر، هر دو را به «…» می‌برد.
    """
    buttons = []
    for row in rows:
        label = f"{row['madah'] or 'نامعلوم'} — {row['title'] or 'بی‌نام'}"
        buttons.append(
            [
                InlineKeyboardButton(
                    label[:60], callback_data=f"{DEL_PICK}:{row['id']}"
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton(texts.btn("cancel"), callback_data=DEL_CANCEL)]
    )
    return InlineKeyboardMarkup(buttons)


def delete_confirm(track_id: int) -> InlineKeyboardMarkup:
    """واپسین پرسش پیش از برداشتن. برداشتن برگشت‌ناپذیر است."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("delete_yes"), callback_data=f"{DEL_YES}:{track_id}"
                ),
                InlineKeyboardButton(texts.btn("cancel"), callback_data=DEL_CANCEL),
            ]
        ]
    )


def bulk_finish() -> InlineKeyboardMarkup:
    """پایان دادن به افزودن انبوه."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.btn("bulk_end"), callback_data=BULK_END)]]
    )


def not_found_actions(search_id: int | None = None) -> InlineKeyboardMarkup:
    """
    هنگامی که چیزی یافت نشد.

    سند خواسته بود کاربری که خودش نسخهٔ کامل را یافته، بتواند
    برایمان بفرستد تا دیگران هم بهره ببرند.

    شمارهٔ جست‌وجو در دکمهٔ «بی‌خیال» می‌رود: پس از زدنش صوتِ همان
    ویدیو فرستاده می‌شود تا کاربر دست‌خالی نرود، و بی این شماره
    نمی‌دانیم صوتِ کدام جست‌وجو را بفرستیم.
    """
    suffix = "" if search_id is None else f":{search_id}"
    rows = [
        [
            InlineKeyboardButton(
                texts.btn("send_full"),
                callback_data=f"{SEARCH_SEND_FULL}{suffix}",
            )
        ],
    ]
    # «خبرم کن» تنها آنگاه معنا دارد که شمارهٔ بازجویی در دست
    # باشد؛ بی آن، نمی‌دانیم خبر را برای که و بابت چه بفرستیم.
    if search_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    texts.btn("notify_me"),
                    callback_data=f"{SEARCH_NOTIFY}{suffix}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                texts.btn("cancel"), callback_data=f"{SEARCH_CANCEL}{suffix}"
            )
        ]
    )
    return InlineKeyboardMarkup(
        rows
    )


# فهرست محبوب‌ترین‌ها. شمارهٔ نوا در خودِ فراخوان است، پس این
# دکمه‌ها ماه‌ها بعد هم کار می‌کنند.
POPULAR_PICK = "pop:get"
POPULAR_PAGE = "pop:pg"


# ── چرا برچسبِ دکمه‌ها تنها شماره است ────────────────────────
#
# چهار نامِ فارسی در یک ردیف جا نمی‌شود: «کربلایی محمدرضا
# جدیدوند» در ربعِ عرضِ صفحه به سه نقطه می‌رسد و خوانده نمی‌شود.
# پس نام‌ها در متنِ بالای پیام می‌آیند — شماره‌گذاری‌شده — و دکمه
# تنها همان شماره را می‌گیرد.
COLUMNS = 4
ROWS = 8
PER_PAGE = COLUMNS * ROWS


def _grid(rows, prefix: str, columns: int = COLUMNS) -> list[list]:
    """دکمه‌های شماره‌ای را در شبکه‌ای می‌چیند."""
    keys: list[list] = []
    for start in range(0, len(rows), columns):
        keys.append(
            [
                InlineKeyboardButton(
                    to_persian_digits(str(number)),
                    callback_data=f"{prefix}:{item_id}",
                )
                for number, item_id in rows[start : start + columns]
            ]
        )
    return keys


def popular_list(
    rows: list[tuple[int, str]], page: int = 0, pages: int = 1
) -> InlineKeyboardMarkup:
    """
    هر نوا یک دکمه در ستونی یگانه؛ گزینش با کاربر است.

    اینجا برخلاف فهرست مداحان، نامِ کامل روی دکمه می‌نشیند: یک
    ستون است و عرضِ کامل را دارد.
    """
    keys = [
        [InlineKeyboardButton(label[:60], callback_data=f"{POPULAR_PICK}:{track_id}")]
        for track_id, label in rows
    ]
    keys.extend(_pager(POPULAR_PAGE, page, pages))
    return InlineKeyboardMarkup(keys)


# ── گشت‌وگذار در مداحان ─────────────────────────────────────
#
# ## چرا شناسهٔ یک نوا، و نه نامِ مداح، در فراخوان می‌نشیند
#
# تلگرام `callback_data` را تا ۶۴ بایت می‌پذیرد. نامِ هنجارشدهٔ
# مداح فارسی است و هر حرفش دو بایت می‌گیرد؛ «کربلایی محمدرضا
# جدیدوند» به‌تنهایی از سقف می‌گذرد و دکمه ساخته نمی‌شود.
#
# پس شناسهٔ یکی از نواهای همان مداح می‌نشیند — عددی کوچک — و
# گرداننده از روی آن به `madah_norm` می‌رسد. هم جا می‌شود و هم
# با رشدِ گنجینه جابه‌جا نمی‌شود (برخلاف شمارهٔ ردیف).
MADAH_PICK = "mdh:one"
MADAH_PAGE = "mdh:pg"
MADAH_TRACK = "mdh:tr"
MADAH_TRACK_PAGE = "mdh:trpg"
MADAH_BACK = "mdh:back"


def _pager(prefix: str, page: int, pages: int, suffix: str = "") -> list:
    """
    یک ردیف دکمهٔ ورق زدن، یا ردیفی تهی اگر یک برگه بیشتر نیست.

    شمارهٔ برگه در خودِ فراخوان است نه در وضعیتِ گفتگو: این
    فهرست‌ها شاید ساعت‌ها بعد ورق بخورند و وضعیتِ حافظه تا آن وقت
    نمانده است.
    """
    if pages <= 1:
        return []
    tail = f":{suffix}" if suffix else ""
    row = []
    if page > 0:
        row.append(
            InlineKeyboardButton("‹ پیشین", callback_data=f"{prefix}:{page - 1}{tail}")
        )
    row.append(
        InlineKeyboardButton(
            f"{to_persian_digits(str(page + 1))}/{to_persian_digits(str(pages))}",
            callback_data="noop",
        )
    )
    if page + 1 < pages:
        row.append(
            InlineKeyboardButton("پسین ›", callback_data=f"{prefix}:{page + 1}{tail}")
        )
    return [row]


def madah_list(rows: list[tuple[int, int]], page: int, pages: int) -> InlineKeyboardMarkup:
    """
    فهرست مداحان در شبکهٔ چهارستونی.

    `rows` جفت‌های (شماره، شناسهٔ نوای لنگر) است — نه نام. نام‌ها
    در متنِ پیام‌اند؛ اینجا تنها شماره می‌نشیند.
    """
    keys = _grid(rows, MADAH_PICK)
    keys.extend(_pager(MADAH_PAGE, page, pages))
    return InlineKeyboardMarkup(keys)


def madah_tracks(
    rows: list[tuple[int, str]], anchor_id: int, page: int, pages: int
) -> InlineKeyboardMarkup:
    """نواهای یک مداح؛ هر کدام یک دکمه."""
    keys = _grid(rows, MADAH_TRACK)
    keys.extend(_pager(MADAH_TRACK_PAGE, page, pages, suffix=str(anchor_id)))
    keys.append(
        [InlineKeyboardButton("‹ فهرست مداحان", callback_data=f"{MADAH_BACK}:0")]
    )
    return InlineKeyboardMarkup(keys)


def start_search() -> InlineKeyboardMarkup:
    """میان‌بر آغاز جست‌وجو، زیر پیام راهنما."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.btn("menu_search"), callback_data=SEARCH_BEGIN)]]
    )


# ═════════════════════════════════════════════════════════════
#  دفتر پذیرش
#
#  چرا دکمهٔ درون‌خطی و نه صفحه‌کلید زیرین: پذیرش بیشتر در گروه
#  می‌گذرد، و صفحه‌کلید زیرین در گروه برای **همه** پدیدار می‌شود —
#  حتی برای کسی که کاری با پذیرش ندارد.
# ═════════════════════════════════════════════════════════════

def intake_styles(seq: int) -> InlineKeyboardMarkup:
    """سبک‌ها، سه‌تا در هر سطر."""
    from bot.states import STYLES

    rows = []
    for start in range(0, len(STYLES), 3):
        rows.append(
            [
                InlineKeyboardButton(
                    name, callback_data=f"{IN_STYLE}:{seq}:{index}"
                )
                for index, name in enumerate(STYLES[start : start + 3], start=start)
            ]
        )
    return InlineKeyboardMarkup(rows)


def intake_skip(seq: int) -> InlineKeyboardMarkup:
    """گامی که می‌توان از آن گذشت."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.btn("skip_title"), callback_data=f"{IN_SKIP}:{seq}")]]
    )


def intake_screen(seq: int) -> InlineKeyboardMarkup:
    """
    داوریِ غربال: آیا این همان نوایی است که از پیش داریم؟

    تأیید یعنی از صف بیرون برود و هیچ پرسشی دربارهٔ آن پرسیده
    نشود؛ رد یعنی تازه است و جریانِ پذیرش دربارهٔ آن ادامه یابد.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("screen_duplicate"),
                    callback_data=f"{IN_DUP}:{seq}",
                ),
                InlineKeyboardButton(
                    texts.btn("screen_new"),
                    callback_data=f"{IN_NEW}:{seq}",
                ),
            ]
        ]
    )


def intake_card(seq: int) -> InlineKeyboardMarkup:
    """
    شناسنامهٔ نوا پیش از نشستن در گنجینه.

    همان چیدمانی که در پیشکشِ همراهان هست: تأیید و لغو کنار هم،
    ویرایش زیرشان.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(texts.btn("confirm"), callback_data=f"{IN_OK}:{seq}"),
                InlineKeyboardButton(texts.btn("cancel"), callback_data=f"{IN_NO}:{seq}"),
            ],
            [InlineKeyboardButton(texts.btn("edit"), callback_data=f"{IN_EDIT}:{seq}")],
        ]
    )


# ── داوریِ نوایی که ربات خودش یافته ─────────────────────────
HARVEST_OK = "hv:ok"
HARVEST_NO = "hv:no"


def harvest_card(queue_id: int) -> InlineKeyboardMarkup:
    """
    زیرِ نوایی که خودِ ربات از تارنمایی یافته است.

    شمارهٔ صف در خودِ فراخوان است، نه در وضعیتِ گفتگو: این کارت‌ها
    شبانه می‌آیند و شاید روزها بعد داوری شوند، و وضعیتِ حافظه تا
    آن وقت نمانده است.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("confirm"), callback_data=f"{HARVEST_OK}:{queue_id}"
                ),
                InlineKeyboardButton(
                    texts.btn("cancel"), callback_data=f"{HARVEST_NO}:{queue_id}"
                ),
            ]
        ]
    )


def intake_fields(seq: int) -> InlineKeyboardMarkup:
    """«کدام بخش را می‌خواهید اصلاح کنید؟»"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("field_madah"), callback_data=f"{IN_FIELD}:{seq}:madah"
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("field_style"), callback_data=f"{IN_FIELD}:{seq}:style"
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("field_title"), callback_data=f"{IN_FIELD}:{seq}:title"
                )
            ],
            [
                InlineKeyboardButton(texts.btn("confirm"), callback_data=f"{IN_OK}:{seq}"),
                InlineKeyboardButton(texts.btn("cancel"), callback_data=f"{IN_NO}:{seq}"),
            ],
        ]
    )


def intake_back(seq: int) -> InlineKeyboardMarkup:
    """تنها بازگشت — هنگامی که ربات چشم‌به‌راه نوشتار است."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.btn("back"), callback_data=f"{IN_BACK}:{seq}")]]
    )


# ── نوای بازفرستاده: افزودن یا بازجویی؟ ─────────────────────
ARC_ADD = "arc:add"
ARC_SEEK = "arc:seek"


def forwarded_choice() -> InlineKeyboardMarkup:
    """
    گرداننده نوایی بازفرستاده؛ خواستش روشن نیست.

    پیش‌تر خودکار به گنجینه می‌رفت، و همان یک تصمیمِ نانوشته،
    جریان پیشکش را از میان برمی‌داشت: گرداننده‌ای که «پیشکش نوا» را
    زده بود و سپس نوایی بازفرستاد، هرگز پرسش‌ها و دکمهٔ تأیید را
    نمی‌دید. اکنون پرسیده می‌شود.
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(texts.btn("forward_add"), callback_data=ARC_ADD)],
            [InlineKeyboardButton(texts.btn("forward_seek"), callback_data=ARC_SEEK)],
        ]
    )


def site_results(rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """
    یافته‌های تارنماها، هر کدام یک دکمه.

    هیچ فایلی خودکار فرستاده نمی‌شود؛ گزینش با کاربر است. این همان
    درسی است که از «ربات هر چه در گنجینه داشت را می‌فرستاد» گرفتیم.
    """
    keys = [
        [InlineKeyboardButton(label[:60], callback_data=f"{SITE_PICK}:{index}")]
        for index, label in rows
    ]
    keys.append(
        [InlineKeyboardButton(texts.btn("cancel"), callback_data=SITE_CANCEL)]
    )
    return InlineKeyboardMarkup(keys)


def site_preview(index: int) -> InlineKeyboardMarkup:
    """
    زیر هر پیش‌نمایش سی‌ثانیه‌ای: خودش هست یا نیست.

    تأیید، نسخهٔ کامل را می‌آورد و سکه می‌سوزاند؛ رد، تنها همین
    پیش‌نمایش را می‌بندد و چیزی نمی‌ستاند. پس گشتن رایگان است و
    تنها یافتن بهاست.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("preview_yes"), callback_data=f"{SITE_OK}:{index}"
                ),
                InlineKeyboardButton(
                    texts.btn("preview_no"), callback_data=f"{SITE_NO}:{index}"
                ),
            ]
        ]
    )


# ═════════════════════════════════════════════════════════════
#  نسخهٔ آراسته در گروه بایگانی
# ═════════════════════════════════════════════════════════════

def broken_actions(track_id: int) -> InlineKeyboardMarkup:
    """
    دکمه‌های زیر نوایی که نمایه نشد.

    حذف، همان جریانِ آزمودهٔ آراسته را می‌رود (`ORN_DEL`) که خودش
    پلهٔ تأیید دارد — دوباره‌نویسی‌اش یعنی روزی یکی عوض شود و
    دیگری نه.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("broken_retry"),
                    callback_data=f"{BROKEN_RETRY}:{track_id}",
                ),
                InlineKeyboardButton(
                    texts.btn("ornate_delete"),
                    callback_data=f"{ORN_DEL}:{track_id}",
                ),
            ]
        ]
    )


def ornate_actions(track_id: int) -> InlineKeyboardMarkup:
    """
    ویرایش و حذف، زیر هر نوایی که در گروه بایگانی می‌نشیند.

    چرا زیر خودِ فایل و نه در فرمانی جدا: ماه‌ها بعد که کسی
    بایگانی را ورق می‌زند و می‌بیند نام مداحی غلط است، همان‌جا و
    با یک نواخت می‌تواند درستش کند — بی آنکه شمارهٔ نوا را
    بجوید و فرمانی به یاد بیاورد.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("edit"), callback_data=f"{ORN_EDIT}:{track_id}"
                ),
                InlineKeyboardButton(
                    texts.btn("ornate_delete"), callback_data=f"{ORN_DEL}:{track_id}"
                ),
            ]
        ]
    )


def ornate_fields(track_id: int) -> InlineKeyboardMarkup:
    """کدام بخش ویرایش شود."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("field_madah"),
                    callback_data=f"{ORN_FIELD}:{track_id}:madah",
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("field_style"),
                    callback_data=f"{ORN_FIELD}:{track_id}:style",
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("field_title"),
                    callback_data=f"{ORN_FIELD}:{track_id}:title",
                )
            ],
            [
                InlineKeyboardButton(
                    texts.btn("back"), callback_data=f"{ORN_BACK}:{track_id}"
                )
            ],
        ]
    )


def ornate_confirm_delete(track_id: int) -> InlineKeyboardMarkup:
    """پرسش واپسین پیش از برداشتن — برگشت‌ناپذیر است."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    texts.btn("delete_yes"), callback_data=f"{ORN_YES}:{track_id}"
                ),
                InlineKeyboardButton(
                    texts.btn("cancel"), callback_data=f"{ORN_BACK}:{track_id}"
                ),
            ]
        ]
    )
