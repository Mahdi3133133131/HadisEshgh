"""
جست‌وجو در تارنماها — پلهٔ دوم، پس از گنجینه.

## ترتیب کار

    گنجینه  ──یافت نشد──▶  تارنماها  ──برگزید──▶  گنجینه

نخست گنجینهٔ خودمان پرسیده می‌شود؛ تنها اگر آنجا چیزی نبود، سراغ
تارنماها می‌رویم. و آنچه از تارنما آمد و کاربر پسندید، در گنجینه
می‌نشیند — با اثر انگشت. پس هر جست‌وجوی تارنما، دفعهٔ بعد یک
جست‌وجوی گنجینه است. این ربات با کار کردن، بی‌نیاز می‌شود.

## چرا دو سازوکار، نه یکی

چهار تارنما یکسان نیستند و نمی‌شود با یک روش با همه رفتار کرد:

| تارنما | جست‌وجوی زنده | چرا |
|---|---|---|
| kashoob | ✅ `/search?q=` | robots.txt هیچ بندی ندارد |
| pelan3 | ✅ `/?s=` | robots.txt تنها پیشخوان را بسته |
| musicdel | ❌ | **robots.txt خودش جست‌وجو را ناروا دانسته** |
| neynavaplus | ❌ | نتیجه‌ها در خودِ مرورگر ساخته می‌شوند |

برای آن دوِ آخر، تنها راهِ آبرومند سیت‌مپی است که خودشان منتشر
می‌کنند — و سیت‌مپ، درست همان چیزی است که برای خوانده شدن به دست
ماشین ساخته شده. پس نمایه‌ای محلی از آن ساخته می‌شود و جست‌وجوی
کاربر روی همان نمایه انجام می‌گیرد: بی‌درنگ، و بی آنکه کسی را در
لحظهٔ انتظار به تارنما بفرستیم.

## پاس‌داشت حق تارنما

سه چیز، و هر سه بایسته:

  • **robots.txt** پیش از هر نشانی سنجیده می‌شود. برخلاف کرالر
    شبانه، اینجا اگر robots.txt خوانده نشد، نشانی **ناروا** شمرده
    می‌شود؛ در کارِ زنده، گمانِ خوش‌بینانه جای خود را به احتیاط
    می‌دهد.
  • **درنگ میان درخواست‌ها** برای هر میزبان، تا بارِ ما بر آن‌ها
    سنگینی نکند.
  • **نشانِ سرچشمه** بر خودِ فایل: نام تارنما و نشانی صفحه در
    برچسب ID3 می‌نشیند و در زیرنویس تلگرام هم نوشته می‌شود. هرکه
    فایل را بگیرد، می‌داند از کجا آمده.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

USER_AGENT = "HadisEshghBot/1.0 (+telegram archive; respects robots.txt)"

# مهلت هر درخواست تکی.
#
# **باید زیرِ `LIVE_BUDGET` بماند.** پیش‌تر ۲۰ بود و بودجه ۱۲،
# یعنی یک درخواستِ کند تمامِ بودجه را می‌خورد و سایت **همیشه**
# تهی برمی‌گشت — ساختاری، نه اتفاقی. با ۸ ثانیه، دستِ‌کم یک
# درخواستِ دوباره هم در بودجه جا می‌شود.
REQUEST_TIMEOUT = 8

# کلِ زمانی که کاربر برای جست‌وجوی زنده چشم‌به‌راه می‌ماند.
# درازتر از این، انتظار به چشمِ خرابی می‌آید.
LIVE_BUDGET = 12.0

# کمترین فاصله میان دو درخواست به یک میزبان
HOST_GAP = 1.0

MAX_FILE_BYTES = 45 * 1024 * 1024

# بیشترین نشانی که در یک گردشِ سیت‌مپ از هر تارنما برداشته می‌شود
MAX_URLS_PER_RUN = 400

# کمترین همانندیِ نام یافته با آنچه کاربر جسته است.
#
# ## چرا این عدد لازم شد
#
# تا پیش از این، هرچه تارنما برمی‌گرداند همان‌طور خام به کاربر
# می‌رسید: نمایهٔ محلی با یک LIKE و مرتب بر تاریخِ یافتن، و
# جست‌وجوی زنده به ترتیبِ ظاهر شدنِ پیوندها در HTML. نتیجه‌اش
# فهرستی بود از چیزهایی که تنها یک واژه‌شان به پرسش می‌خورد —
# همان که به چشم «ده تا مداحی پیش‌فرض» می‌آمد.
MIN_RELEVANCE = 0.35

# واژه‌هایی که در نام تقریباً هر مداحی هستند و چیزی از هم جدا
# نمی‌کنند؛ در سنجش همانندی به شمار نمی‌آیند.
_STOPWORDS = frozenset(
    {
        "مداحی",
        "نوحه",
        "دانلود",
        "حاج",
        "کربلایی",
        "با",
        "از",
        "و",
        "در",
        "به",
        "نماهنگ",
        "صوت",
        "کلیپ",
    }
)

_WORD_SPLIT = re.compile(r"[^\w\u0600-\u06FF]+")


# ═════════════════════════════════════════════════════════════
#  تارنماها
# ═════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SiteSource:
    """
    یک تارنما و راه‌های رسیدن به نواهایش.

    هر تارنما ساختار خودش را دارد و هیچ دو تایی یکسان نیستند؛ پس
    به جای یک کرالرِ همه‌کاره، هر کدام الگوهای خودش را می‌آورد.
    """

    name: str
    label: str
    home: str
    sitemaps: tuple[str, ...] = ()
    search_url: str | None = None          # قالبی با {q}
    page_pattern: re.Pattern | None = None  # کدام نشانی، صفحهٔ نواست
    enabled: bool = True

    def is_track_page(self, url: str) -> bool:
        if self.page_pattern is None:
            return False
        return bool(self.page_pattern.search(url))


SITES: tuple[SiteSource, ...] = (
    SiteSource(
        name="kashoob",
        label="کاشوب",
        home="https://kashoob.com/",
        sitemaps=("https://kashoob.com/sitemap.xml.gz",),
        search_url="https://kashoob.com/search?q={q}",
        page_pattern=re.compile(r"kashoob\.com/audio/[^/\s\"']+"),
    ),
    SiteSource(
        name="pelan3",
        label="پلن سه",
        home="https://pelan3.com/",
        sitemaps=("https://pelan3.com/sitemap_index.xml",),
        search_url="https://pelan3.com/?s={q}",
        # وردپرس است و نشانی نوشته‌ها یک‌لایه.
        #
        # برگهٔ نتیجهٔ وردپرس کلِ منوی سایت را هم در خود دارد، پس
        # الگوی سست، پیوندهای منو را صفحهٔ نوا می‌شمرد و هر سه جای
        # یافته‌ها را با /madahan/ و /sokhanranan/ پر می‌کرد.
        # لنگر (#) هم کنار گذاشته می‌شود: /#content صفحه نیست.
        page_pattern=re.compile(
            r"pelan3\.com/(?!wp-|category/|tag/|author/|page/|feed|"
            r"madahan|sokhanranan|about|contact|privacy)"
            r"[^/\s\"'#?]{4,}/?$"
        ),
    ),
    SiteSource(
        name="musicdel",
        label="موزیک‌دل",
        home="https://musicdel.ir/",
        sitemaps=("https://musicdel.ir/sitemap_index.xml",),
        # robots.txt این تارنما جست‌وجو را ناروا دانسته است؛
        # پس تنها از راه سیت‌مپ سراغش می‌رویم.
        search_url=None,
        page_pattern=re.compile(r"musicdel\.ir/single-tracks/\d+"),
    ),
    # ── تنها تارنمایی که آزمونِ دروازه را گذراند ────────────
    #
    # سنجش روی ده صفحهٔ نمونه از نقشهٔ سایتش: **هر ده** به نشانیِ
    # mp3 رسیدند. تیترش هم عنوان و نامِ مداح را با هم می‌دهد
    # («دانلود مداحی … از حاج …»)، پس شناسنامهٔ یافته‌ها ناقص
    # نمی‌ماند — که همان نگرانیِ اصلیِ افزودنِ خودکار بود.
    #
    # نامزدهایی که افتادند و چرا:
    #   mahdaviat.ir  — تنها ۱ از ۱۰؛ برگه‌هایش مقاله است نه نوا
    #   shiavoice.com — نقشه‌اش برچسب و نمایه است، و عربی نه فارسی
    #   tekyeh / nohe / radionohe — یکسره پاسخ ندادند
    SiteSource(
        name="madahi",
        label="مداحی",
        home="https://madahi.ir/",
        sitemaps=("https://madahi.ir/sitemap_index.xml",),
        # جست‌وجوی زنده ندارد؛ تنها برای رشدِ خودکار به کار می‌آید.
        search_url=None,
        page_pattern=None,
    ),
    SiteSource(
        name="neynavaplus",
        label="رادیو نینوا پلاس",
        home="https://radio.neynavaplus.com/",
        sitemaps=("https://api.neynavaplus.com/sitemaps/radio.xml",),
        # برگهٔ نتیجه‌هایش در مرورگر ساخته می‌شود و از HTML خام
        # چیزی درنمی‌آید.
        search_url=None,
        page_pattern=re.compile(r"neynavaplus\.com/(audio|radio)/[^\s\"']+"),
    ),
)


def by_name(name: str) -> SiteSource | None:
    for site in SITES:
        if site.name == name:
            return site
    return None


def label_of(name: str) -> str:
    site = by_name(name)
    return site.label if site else name


@dataclass
class Hit:
    """یک نوا که در تارنمایی یافت شده است."""

    site: str
    title: str
    page_url: str
    file_url: str | None = None

    # از برگهٔ خودِ مداح آمده، نه از جست‌وجوی واژگانی.
    #
    # این یافته‌ها نباید با همانندیِ **نام** سنجیده شوند: کاربر
    # «محمود کریمی» جسته و نامِ نوا «نه یاوری نه مسجدی» است —
    # همانندی صفر، حال آنکه یافته بی‌گمان درست است. تارنما خودش
    # گفته این نوا از آنِ اوست، و آن گواهی از هر سنجشِ واژگانی
    # استوارتر است.
    via_person: bool = False

    @property
    def label(self) -> str:
        return label_of(self.site)


# ═════════════════════════════════════════════════════════════
#  ادب شبکه
# ═════════════════════════════════════════════════════════════

# ## چرا `robots` مهلت می‌خواهد
#
# پیش‌تر این حافظه هیچ‌وقت کهنه نمی‌شد. یک ناکامیِ گذرا سرِ
# راه‌اندازی — شبکه هنوز بالا نیامده، یا تارنما لحظه‌ای پاسخ نداد —
# آن دامنه را `None` می‌کرد و `_allowed` تا **پایانِ عمرِ پروسه**
# هر نشانی‌اش را رد می‌کرد. ربات که هفته‌ها بالا می‌ماند، یعنی آن
# سایت برای همیشه مرده بود.
#
# ناکامی زودتر از کامیابی دوباره آزموده می‌شود: بندهای robots
# به‌ندرت عوض می‌شوند، ولی لغزشِ شبکه گذراست.
ROBOTS_TTL_OK = 3600.0
ROBOTS_TTL_FAIL = 300.0

_robots: dict[str, RobotFileParser | None] = {}
_robots_at: dict[str, float] = {}


def _robots_fresh(host: str) -> bool:
    """آیا آنچه دربارهٔ این میزبان می‌دانیم هنوز تازه است."""
    if host not in _robots:
        return False
    age = time.monotonic() - _robots_at.get(host, 0.0)
    ttl = ROBOTS_TTL_FAIL if _robots[host] is None else ROBOTS_TTL_OK
    return age < ttl
_last_call: dict[str, float] = {}
_robots_lock = asyncio.Lock()


# بندهای ستاره‌دارِ هر میزبان، کنارِ تجزیه‌گرِ استاندارد.
_wildcards: dict[str, list[str]] = {}


async def _pace(host: str) -> None:
    """میان دو درخواست به یک میزبان، درنگ می‌گذارد."""
    now = time.monotonic()
    gap = now - _last_call.get(host, 0.0)
    if gap < HOST_GAP:
        await asyncio.sleep(HOST_GAP - gap)
    _last_call[host] = time.monotonic()


def _wildcard_rules(text: str) -> list[str]:
    """
    بندهای Disallow ستاره‌دار را بیرون می‌کشد.

    ## چرا این لازم است

    `RobotFileParser` کتابخانهٔ استاندارد، الگویی که با ستاره
    **آغاز** شود یا ستاره در میانش باشد را درست نمی‌فهمد.
    اندازه‌گیری روی robots.txt راستینِ موزیک‌دل:

        Disallow: *?s=*      ->  can_fetch("/?s=test") = True   ✗
        Disallow: /*?*       ->  can_fetch("/?p=1")    = True   ✗

    یعنی تارنما صریح گفته بود «این نشانی‌ها را مگیر» و ما
    می‌گرفتیم. این ادب را می‌شکند و می‌تواند به مسدود شدنِ
    نشانیِ ما بینجامد.

    تنها بندهای بخشِ `User-agent: *` خوانده می‌شوند — بخشی که
    بر ما هم صدق می‌کند.
    """
    rules: list[str] = []
    applies = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            applies = value == "*"
        elif field == "disallow" and applies and "*" in value:
            rules.append(value)
    return rules


def _blocked_by_wildcard(path: str, rules: list[str]) -> bool:
    """آیا مسیر با یکی از الگوهای ستاره‌دار می‌خواند."""
    for rule in rules:
        pattern = rule
        anchored_end = pattern.endswith("$")
        if anchored_end:
            pattern = pattern[:-1]
        # ستاره یعنی «هر چیزی»؛ بقیهٔ نویسه‌ها همان‌اند که هستند.
        parts = [re.escape(piece) for piece in pattern.split("*")]
        expression = ".*".join(parts)
        expression = "^" + expression + ("$" if anchored_end else "")
        try:
            if re.search(expression, path):
                return True
        except re.error:
            continue
    return False


async def _allowed(session, url: str) -> bool:
    """
    آیا robots.txt این نشانی را روا می‌داند.

    **اینجا برخلاف کرالر شبانه، بدبینانه داوری می‌شود:** اگر
    robots.txt خوانده نشد، نشانی ناروا شمرده می‌شود. کرالر شبانه
    وقت دارد و می‌تواند دوباره بیازماید؛ کارِ زنده وقت ندارد، و
    گمانِ خوش‌بینانه در نبود آگاهی، همان چیزی است که ادب را
    می‌شکند.
    """
    parts = urlparse(url)
    host = parts.netloc
    if not _robots_fresh(host):
        async with _robots_lock:
            if not _robots_fresh(host):
                parser: RobotFileParser | None = None
                try:
                    await _pace(host)
                    robots_url = f"{parts.scheme}://{host}/robots.txt"
                    async with session.get(robots_url, timeout=10) as response:
                        if response.status == 200:
                            body = await response.text()
                            parser = RobotFileParser()
                            parser.parse(body.splitlines())
                            _wildcards[host] = _wildcard_rules(body)
                        elif response.status in (401, 403):
                            parser = None       # ناروا
                        else:
                            # ۴۰۴ یعنی هیچ بندی نیست — استاندارد
                            # می‌گوید همه‌چیز رواست.
                            parser = RobotFileParser()
                            parser.parse([])
                except Exception as exc:  # noqa: BLE001
                    logger.debug("robots.txt %s خوانده نشد: %s", host, exc)
                    parser = None
                _robots[host] = parser
                _robots_at[host] = time.monotonic()

    parser = _robots[host]
    if parser is None:
        return False
    if not parser.can_fetch(USER_AGENT, url):
        return False

    # و آنچه کتابخانهٔ استاندارد از قلم می‌اندازد.
    rules = _wildcards.get(host)
    if rules:
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if _blocked_by_wildcard(path, rules):
            return False
    return True


async def _get_text(session, url: str) -> str | None:
    """یک برگه را می‌گیرد، با سنجش robots و درنگِ ادب."""
    if not await _allowed(session, url):
        logger.debug("robots.txt نشانی %s را ناروا دانست.", url)
        return None
    try:
        await _pace(urlparse(url).netloc)
        async with session.get(url, timeout=REQUEST_TIMEOUT) as response:
            if response.status != 200:
                return None
            raw = await response.read()
            if url.endswith(".gz") or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.debug("گرفتن %s شکست خورد: %s", url, exc)
        return None


def _session():
    import aiohttp

    return aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})


# ═════════════════════════════════════════════════════════════
#  بیرون کشیدن از HTML
# ═════════════════════════════════════════════════════════════

_LINK = re.compile(r'href=[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE = re.compile(
    r'<meta[^>]+property=[\'"]og:title[\'"][^>]+content=[\'"]([^\'"]+)',
    re.IGNORECASE,
)
_MP3 = re.compile(r'[\'"(]?(https?://[^\'"\s<>()]+?\.mp3(?:\?[^\'"\s<>()]*)?)', re.IGNORECASE)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")

# دنبالهٔ نامِ تارنما در سرنویس برگه: «… | کشوب» یا «… - موزیک‌دل»
_TITLE_TAIL = re.compile(r"\s*[|\-–—]\s*[^|\-–—]{1,40}$")


def _site_words() -> frozenset[str]:
    """واژه‌هایی که نامِ خودِ تارنما هستند، نه نامِ نوا."""
    from core.normalize import normalize

    words: set[str] = set()
    for site in SITES:
        words.add(normalize(site.label))
        # `SiteSource` میزبان جدا ندارد؛ از نشانیِ خانه برداشته
        # می‌شود.
        host = urlparse(site.home).netloc.replace("www.", "")
        if host:
            words.add(normalize(host))
            words.add(normalize(host.split(".")[0]))
    words.discard("")
    return frozenset(words)


def _tail_is_a_person(tail: str) -> bool:
    """
    آیا این دنباله نامِ آدم است، نه نامِ تارنما.

    سه نشانه، هر کدام بس است:
      ۱. لقب دارد («حاج محمود کریمی»)
      ۲. مداحی است که در گنجینه می‌شناسیم
      ۳. بیش از یک واژه است — نامِ تارنما تک‌واژه است
         («کاشوب»، «موزیک‌دل»)، نامِ آدم کمتر
    """
    if not tail:
        return False

    from core.normalize import normalize

    try:
        from services.captions import TITLES, known_madahs

        for title in TITLES:
            if tail.startswith(normalize(title) + " ") or tail == normalize(title):
                return True
        if tail in known_madahs():
            return True
    except Exception:  # noqa: BLE001
        logger.debug("سنجشِ آدم‌بودنِ دنباله نشد.", exc_info=True)

    return len(tail.split()) > 1


def _strip_site_tail(text: str) -> str:
    """
    دنبالهٔ «… | نامِ تارنما» را می‌بُرد — ولی نه وقتی نامِ آدم است.

    ## چرا این سنجش لازم شد

    پیش‌تر هر پارهٔ پس از آخرین `|` یا `—` بریده می‌شد. ولی
    عنوانِ رایجِ این تارنماها «نامِ نوا — نامِ مداح» است، و آنچه
    بریده می‌شد دقیقاً **نامِ مداح** بود — همان که کاربر جست‌وجو
    کرده. یعنی سنجهٔ همانندی روی چیزی کار می‌کرد که کلیدواژه‌اش
    را از دست داده بود.

    ## چرا دو قاعده و نه یک فهرست

    فهرستِ نامِ تارنماها بس نبود: خودِ تارنما در سرنویسش هر
    نگارشی می‌تواند بنویسد («کشوب» به جای «کاشوب»). پس اگر در
    فهرست نبود، سنجیده می‌شود که آیا **به آدم می‌مانَد** — و
    تنها آنگاه می‌مانَد.
    """
    from core.normalize import normalize

    match = _TITLE_TAIL.search(text)
    if not match:
        return text.strip()

    tail = normalize(match.group(0).lstrip(" |-\u2013\u2014"))
    if not tail:
        return text.strip()

    known = _site_words()
    if tail in known or any(w in known for w in tail.split()):
        return _TITLE_TAIL.sub("", text).strip()

    if _tail_is_a_person(tail):
        return text.strip()

    return _TITLE_TAIL.sub("", text).strip()


def _clean_title(raw: str) -> str:
    from core.normalize import fix_display

    text = _TAGS.sub(" ", raw)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text).strip()
    # نام تارنما معمولاً به دنبالهٔ سرنویس چسبیده است و در جست‌وجو
    # تنها نویز می‌سازد.
    text = _strip_site_tail(text)
    return fix_display(text)[:200]


def _title_of(html: str) -> str:
    match = _OG_TITLE.search(html) or _TITLE.search(html)
    return _clean_title(match.group(1)) if match else ""


def _title_from_url(url: str) -> str:
    """
    نامی خوانا از خودِ نشانی.

    برای kashoob که نشانی‌اش پارسیِ درصدنویسی‌شده است، این به‌تنهایی
    بس است؛ برای musicdel که نشانی‌اش عدد است، چیزی به دست نمی‌دهد
    و نام باید از خودِ برگه گرفته شود.
    """
    from core.normalize import fix_display

    stem = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    stem = re.sub(r"[-_]+", " ", stem).strip()
    if not stem or stem.isdigit() or not re.search(r"[؀-ۿ]", stem):
        return ""
    return fix_display(stem)[:200]


def _media_in(html: str, page_url: str) -> str | None:
    """نشانی فایل صوتی را در برگه می‌یابد."""
    for match in _MP3.finditer(html):
        return match.group(1)
    # گاه نشانی نسبی است
    for match in _LINK.finditer(html):
        href = match.group(1)
        if ".mp3" in href.lower():
            return urljoin(page_url, href)
    return None


# ═════════════════════════════════════════════════════════════
#  جست‌وجو
# ═════════════════════════════════════════════════════════════

def _words(text: str) -> set[str]:
    """واژه‌های معنادار یک نوشتار، هنجارشده."""
    from core.normalize import normalize

    parts = _WORD_SPLIT.split(normalize(text or ""))
    return {w for w in parts if len(w) > 1 and w not in _STOPWORDS}


def relevance(term: str, title: str) -> float:
    """
    چقدر این نام به آنچه کاربر جسته می‌خورد — عددی میان ۰ و ۱.

    سه چیز با هم: هم‌پوشانیِ واژه‌ها (جاکارد)، آمدنِ کلِ پرسش در
    نام، و بودنِ همهٔ واژه‌های پرسش در نام. دوتای پسین امتیازِ
    افزوده‌اند، چون «محمود کریمی» در «شور محمود کریمی» یقیناً
    همان است، حال آنکه جاکاردِ تنها، به خاطر واژه‌های اضافیِ نام،
    عدد کمی می‌دهد.
    """
    from core.normalize import normalize

    query_words = _words(term)
    title_words = _words(title)
    if not query_words or not title_words:
        return 0.0

    union = query_words | title_words
    score = len(query_words & title_words) / len(union) if union else 0.0

    normal_title = normalize(title or "")
    if normalize(term or "") in normal_title:
        score += 0.4
    if query_words <= title_words:
        score += 0.2

    return min(score, 1.0)


def rank(term: str, hits: list[Hit], limit: int) -> list[Hit]:
    """
    یافته‌ها را بر پایهٔ همانندی می‌چیند و نامربوط‌ها را دور می‌ریزد.

    یافتهٔ بی‌نام هم دور ریخته می‌شود. پیش‌تر نگه داشته می‌شد — به
    این گمان که نامش را بعداً می‌گیریم — ولی همان‌ها هر سه جا را
    پر می‌کردند و یافتهٔ راستین اصلاً جا نداشت. اکنون نام‌گیری
    **پیش از** این تابع انجام می‌شود (نگاه کنید به `_name_them`)،
    پس هر چه بی‌نام مانده، راستی نامی ندارد.
    """
    scored: list[tuple[float, int, Hit]] = []
    for index, hit in enumerate(hits):
        if not hit.title:
            continue
        if hit.via_person:
            # برگهٔ مداح، خودش گواهِ ربط است. سنجشِ واژگانی
            # اینجا تنها زیان دارد.
            scored.append((1.0, index, hit))
            continue
        score = relevance(term, hit.title)
        if score < MIN_RELEVANCE:
            continue
        scored.append((score, index, hit))

    # index در کلید هست تا مرتب‌سازی پایدار بماند و Hit — که
    # سنجش‌پذیر نیست — هرگز با Hit مقایسه نشود.
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [hit for _, _, hit in scored[:limit]]


async def _search_one(session, site: SiteSource, term: str, limit: int) -> list[Hit]:
    """جست‌وجوی زنده در یک تارنما."""
    if not site.search_url:
        return []
    html = await _get_text(session, site.search_url.format(q=quote(term)))
    if not html:
        return []

    hits: list[Hit] = []
    seen: set[str] = set()
    for match in _LINK.finditer(html):
        url = urljoin(site.home, match.group(1))
        if not site.is_track_page(url) or url in seen:
            continue
        seen.add(url)
        hits.append(Hit(site=site.name, title=_title_from_url(url), page_url=url))
        if len(hits) >= limit:
            break
    return hits


# ═════════════════════════════════════════════════════════════
#  دفترِ مداحان — گشتن با **نام مداح**، نه تنها نام نوا
# ═════════════════════════════════════════════════════════════
#
# ## چرا این لازم شد
#
# جست‌وجوی kashoob تنها **نام نوا** را می‌بیند. کاربر معمولاً نام
# **مداح** می‌دهد — و آنگاه تارنما هیچ نمی‌یابد و به جایش چرخ‌فلکِ
# صفحهٔ خانه را برمی‌گرداند. آن پیوندها به‌ظاهر یافته بودند، از
# سنجش همانندی رد می‌شدند، و کاربر می‌دید که «کاشوب اصلاً نگشت».
#
# سنجیده شد: «شور» و «محرم» یافتهٔ راستین می‌دهند، ولی «محمود
# کریمی» هیچ. حال آنکه همان تارنما برگه‌ای دارد — /person/karimi —
# با ۴۴ نوای همو.
#
# پس دفترِ مداحان یک بار خوانده و در حافظه نگه داشته می‌شود، و
# پرسشی که به نامِ مداحی بخورد، یک‌راست از برگهٔ خودش برداشت
# می‌شود.

_PERSON_PAGES = (
    "https://kashoob.com/persons/madah",
    "https://kashoob.com/persons/madah?p=2",
)

_PERSON_LINK = re.compile(
    r'<a\s+href="(https://kashoob\.com/person/[^"]+)"[^>]*title="([^"]*)"'
)
_TITLED_AUDIO = re.compile(
    r'<a\s+href="(https://kashoob\.com/audio/[^"]+)"\s+title="([^"]*)"'
)

# دفتر روزی یک بار تازه می‌شود. مداحان هر روز افزوده نمی‌شوند و
# دو رفت‌وآمد شبکه برای هر جست‌وجو، گزاف است.
_DIRECTORY_TTL = 24 * 3600.0
_directory: tuple[float, dict[str, str]] | None = None
_directory_lock = asyncio.Lock()


async def _person_directory(session) -> dict[str, str]:
    """نگاشتِ «نام پارسیِ مداح» به نشانیِ برگه‌اش. با کشِ روزانه."""
    global _directory

    now = time.monotonic()
    if _directory is not None and now - _directory[0] < _DIRECTORY_TTL:
        return _directory[1]

    async with _directory_lock:
        # شاید هنگام انتظار پشت قفل، دیگری پرش کرده باشد.
        if _directory is not None and time.monotonic() - _directory[0] < _DIRECTORY_TTL:
            return _directory[1]

        found: dict[str, str] = {}
        for page in _PERSON_PAGES:
            html = await _get_text(session, page)
            if not html:
                continue
            for url, name in _PERSON_LINK.findall(html):
                clean = " ".join(name.split())
                if clean:
                    found.setdefault(clean, url)

        if not found:
            # دفترِ تهی کش نمی‌شود؛ وگرنه یک قطعیِ گذرا، یک روز
            # تمام این راه را می‌بست.
            logger.info("دفترِ مداحانِ کاشوب خوانده نشد.")
            return {}

        _directory = (time.monotonic(), found)
        logger.info("دفترِ مداحانِ کاشوب خوانده شد: %s نام.", len(found))
        return found


def _match_person(term: str, directory: dict[str, str]) -> str | None:
    """
    نشانیِ برگهٔ مداحی که نامش به پرسش می‌خورد — یا None.

    نامِ دفتر معمولاً لقب دارد («حاج محمود کریمی») و پرسشِ کاربر
    ندارد. پس واژه‌های معنادار سنجیده می‌شوند، نه رشتهٔ خام: اگر
    همهٔ واژه‌های پرسش در نام باشند، همان است.
    """
    query = _words(term)
    if not query:
        return None

    best: tuple[int, str] | None = None
    for name, url in directory.items():
        name_words = _words(name)
        if not name_words or not query <= name_words:
            continue
        # نامِ کوتاه‌تر، دقیق‌تر است: پرسشِ «کریمی» نباید به
        # «محمود کریمی زاده» برود اگر «کریمی» خودش هست.
        extra = len(name_words - query)
        if best is None or extra < best[0]:
            best = (extra, url)
    return best[1] if best else None


async def _person_tracks(session, term: str, limit: int) -> list[Hit]:
    """نواهای برگهٔ مداحی که نامش به پرسش می‌خورد."""
    try:
        directory = await _person_directory(session)
    except Exception:  # noqa: BLE001
        logger.debug("خواندن دفترِ مداحان لغزید.", exc_info=True)
        return []
    if not directory:
        return []

    url = _match_person(term, directory)
    if url is None:
        return []

    html = await _get_text(session, url)
    if not html:
        return []

    hits: list[Hit] = []
    seen: set[str] = set()
    for page_url, title in _TITLED_AUDIO.findall(html):
        if page_url in seen:
            continue
        seen.add(page_url)
        clean = " ".join(title.split())
        if not clean:
            continue
        hits.append(
            Hit(site="kashoob", title=clean, page_url=page_url, via_person=True)
        )
        if len(hits) >= limit:
            break

    logger.info("برگهٔ مداحِ «%s»: %s نوا.", term, len(hits))
    return hits


async def live_search(term: str, limit: int = 6) -> list[Hit]:
    """
    جست‌وجوی هم‌زمان در تارنماهایی که جست‌وجو دارند.

    مهلت کلی دارد: کاربر چشم‌به‌راه است و تارنمایی که پاسخ نمی‌دهد
    نباید بقیه را هم گروگان بگیرد.
    """
    sites = [s for s in SITES if s.enabled and s.search_url]
    if not sites:
        return []

    try:
        session = _session()
    except ImportError:
        logger.warning("aiohttp نصب نیست؛ جست‌وجوی تارنماها انجام نشد.")
        return []

    # مهلت روی **هر تارنما** جداگانه، نه روی همه با هم.
    #
    # پیش‌تر یک wait_for گردِ کل gather بود و سر آمدنش یعنی دور
    # ریختنِ هرچه رسیده بود — یک تارنمای کند، یافته‌های سه تای
    # دیگر را هم با خود می‌برد.
    async def _one(site: SiteSource) -> list[Hit]:
        try:
            return await asyncio.wait_for(
                _search_one(session, site, term, limit), timeout=LIVE_BUDGET
            )
        except asyncio.TimeoutError:
            logger.info("مهلت %s سر آمد («%s»).", site.name, term)
            return []

    async def _person() -> list[Hit]:
        # برگهٔ خودِ مداح — راهی که جست‌وجوی واژگانیِ تارنما ندارد.
        try:
            return await asyncio.wait_for(
                _person_tracks(session, term, limit), timeout=LIVE_BUDGET
            )
        except asyncio.TimeoutError:
            logger.info("مهلت دفترِ مداحان سر آمد («%s»).", term)
            return []

    async with session:
        done = await asyncio.gather(
            *(_one(site) for site in sites), _person(), return_exceptions=True
        )

    hits: list[Hit] = []
    for result in done:
        if isinstance(result, list):
            hits.extend(result)
        elif isinstance(result, BaseException):
            logger.debug("جست‌وجوی زنده لغزید: %s", result)
    return hits


def indexed_search(term: str, limit: int = 6) -> list[Hit]:
    """جست‌وجو در نمایهٔ محلی — بی هیچ رفت‌وآمد شبکه‌ای."""
    from core.db import site_index

    return [
        Hit(
            site=row["site"],
            title=row["title"],
            page_url=row["page_url"],
            file_url=row["file_url"],
        )
        for row in site_index.search(term, limit)
    ]


async def search(term: str, limit: int = 3) -> list[Hit]:
    """
    نخست نمایهٔ محلی، سپس جست‌وجوی زنده — و در پایان، رتبه‌بندی.

    نمایه بی‌درنگ است و اگر پاسخ داشت، کاربر را معطلِ شبکه
    نمی‌کنیم. جست‌وجوی زنده تنها برای چیزی است که نمایه نمی‌داند.

    هر دو سرچشمه بیش از `limit` می‌آورند و سپس `rank` می‌چیندشان.
    این عمدی است: اگر همان آغاز به `limit` ببُریم، چیدنِ پس از آن
    تنها همان چند تای نخست را جابه‌جا می‌کند و بهترین یافته که
    ششم بوده، هرگز دیده نمی‌شود.
    """
    from core.db import site_index

    site_index.ensure_table()

    pool = max(limit * 4, 12)
    found = indexed_search(term, pool)
    seen = {hit.page_url for hit in found}

    for hit in await live_search(term, pool):
        if hit.page_url in seen:
            continue
        seen.add(hit.page_url)
        found.append(hit)
        # هرچه زنده یافتیم، به نمایه هم می‌سپاریم؛ دفعهٔ بعد
        # بی‌درنگ خواهد بود.
        site_index.remember(hit.site, hit.page_url, hit.title)

    # نام‌ها پیش از رتبه‌بندی گرفته می‌شوند، وگرنه سنجش روی دادهٔ
    # نیم‌بند انجام می‌گیرد و زباله جای یافتهٔ راستین را می‌گیرد.
    found = await _name_them(found)
    return rank(term, found, limit)


async def _name_them(hits: list[Hit], cap: int = 8) -> list[Hit]:
    """
    نامِ یافته‌های بی‌نام را از خودِ برگه می‌گیرد.

    نامی که از نشانی درمی‌آید برای kashoob بس است (نشانی‌اش پارسیِ
    درصدنویسی‌شده است) ولی برای musicdel که نشانی‌اش عدد است هیچ
    نمی‌دهد. بی این گام، آن تارنما هرگز دیده نمی‌شد.

    سقف دارد و مهلت: هر نام یک رفت‌وآمد شبکه است و کاربر
    چشم‌به‌راه است.
    """
    missing = [hit for hit in hits if not hit.title][:cap]
    if not missing:
        return hits
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *(resolve(hit) for hit in missing), return_exceptions=True
            ),
            timeout=LIVE_BUDGET,
        )
    except asyncio.TimeoutError:
        logger.info("مهلت نام‌گیریِ یافته‌ها سر آمد.")
    except Exception:  # noqa: BLE001
        logger.debug("نام‌گیریِ یافته‌ها لغزید.")
    return hits


# ═════════════════════════════════════════════════════════════
#  رسیدن به خودِ فایل
# ═════════════════════════════════════════════════════════════

async def resolve(hit: Hit) -> Hit:
    """
    از صفحهٔ نوا به نشانی فایل و نام درست می‌رسد.

    نتیجه در نمایه می‌نشیند تا این رفت‌وآمد دوباره لازم نشود.
    """
    from core.db import site_index

    if hit.file_url:
        return hit

    try:
        session = _session()
    except ImportError:
        return hit

    async with session:
        html = await _get_text(session, hit.page_url)

    if not html:
        return hit

    title = _title_of(html) or hit.title
    media = _media_in(html, hit.page_url)
    hit.title = title or hit.title
    hit.file_url = media
    if media:
        site_index.set_media(hit.page_url, media, title or None, site=hit.site)
    elif title:
        site_index.remember(hit.site, hit.page_url, title)
    return hit


# سرِ چند ثانیه‌ای یک ام‌پی‌تری چند بایت است.
#
# ام‌پی‌تری جریانی است: سرِ فایل، سرِ صداست. پس برای ساختن یک
# پیش‌نمایش سی‌ثانیه‌ای نیازی به فرو گرفتنِ کلِ فایلِ چندمگابایتی
# نیست — همان سرش بس است. با ۳۲۰ کیلوبیت بر ثانیه (بالاترین نرخِ
# رایج) سی ثانیه حدود ۱٫۲ مگابایت می‌شود؛ سقف را همان می‌گذاریم
# تا هر نرخی پوشش داده شود و باز هم یک‌سی‌اُمِ فایل کامل باشد.
PREVIEW_BYTES = 1_200_000


async def download(
    url: str, destination: Path, max_bytes: int | None = None
) -> Path | None:
    """
    فایل را فرو می‌گیرد؛ None اگر نشد یا از سقف بزرگ‌تر بود.

    با `max_bytes` تنها همان اندازه از سرِ فایل گرفته می‌شود — با
    هدر Range اگر میزبان بپذیرد، وگرنه با بریدنِ جریان. نتیجه
    ام‌پی‌تریِ ناقصی است که ffmpeg می‌تواند بخواند و پیش‌نمایش از
    آن بسازد.
    """
    try:
        session = _session()
    except ImportError:
        return None

    cap = max_bytes or MAX_FILE_BYTES
    headers = {"Range": f"bytes=0-{max_bytes - 1}"} if max_bytes else None

    async with session:
        if not await _allowed(session, url):
            logger.info("robots.txt فرو گرفتن %s را ناروا دانست.", url)
            return None
        try:
            await _pace(urlparse(url).netloc)
            async with session.get(
                url, timeout=REQUEST_TIMEOUT * 3, headers=headers
            ) as response:
                # ۲۰۶ یعنی میزبان Range را پذیرفت؛ ۲۰۰ یعنی همه را
                # می‌فرستد و خودمان باید ببریم.
                if response.status not in (200, 206):
                    return None

                # سنجشِ سقفِ کلی تنها وقتی معنا دارد که کلِ فایل را
                # می‌خواهیم؛ برای پیش‌نمایش، بزرگیِ فایل بی‌اهمیت
                # است چون تنها سرش را می‌گیریم.
                if max_bytes is None:
                    length = response.headers.get("Content-Length")
                    if length and int(length) > MAX_FILE_BYTES:
                        logger.info("%s از سقف بزرگ‌تر است.", url)
                        return None

                destination.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with destination.open("wb") as handle:
                    async for chunk in response.content.iter_chunked(65536):
                        handle.write(chunk)
                        written += len(chunk)
                        if written >= cap:
                            break

                if max_bytes is None and written > MAX_FILE_BYTES:
                    destination.unlink(missing_ok=True)
                    return None
                if not written:
                    destination.unlink(missing_ok=True)
                    return None
                return destination
        except Exception as exc:  # noqa: BLE001
            logger.warning("فرو گرفتن %s شکست خورد: %s", url, exc)
            destination.unlink(missing_ok=True)
            return None


# ═════════════════════════════════════════════════════════════
#  ساختن نمایه از سیت‌مپ
# ═════════════════════════════════════════════════════════════

async def _walk_sitemap(session, url: str, depth: int = 0) -> list[str]:
    """
    نشانی‌های یک سیت‌مپ را می‌دهد؛ اگر خودش فهرستِ سیت‌مپ‌ها باشد،
    یک لایه پایین‌تر هم می‌رود.
    """
    if depth > 2:
        return []
    text = await _get_text(session, url)
    if not text:
        return []

    locs = [_TAGS.sub("", loc).strip() for loc in _LOC.findall(text)]
    if "<sitemapindex" in text[:2000].lower():
        out: list[str] = []
        for child in locs[:20]:
            out.extend(await _walk_sitemap(session, child, depth + 1))
            if len(out) >= MAX_URLS_PER_RUN:
                break
        return out
    return locs


async def refresh_index(site_name: str | None = None) -> dict[str, int]:
    """
    سیت‌مپ‌ها را می‌خواند و نشانی صفحه‌های نوا را در نمایه می‌نشاند.

    نام هنوز به دست نمی‌آید — سیت‌مپ تنها نشانی می‌دهد. آنچه از
    خودِ نشانی خوانده شود (مانند kashoob که نشانی‌اش پارسی است)
    همان‌جا می‌نشیند؛ بقیه در کارِ پرکردنِ نام، برگه‌به‌برگه به دست
    می‌آیند.
    """
    from core.db import site_index

    site_index.ensure_table()
    result: dict[str, int] = {}

    try:
        session = _session()
    except ImportError:
        logger.warning("aiohttp نصب نیست؛ نمایهٔ تارنماها ساخته نشد.")
        return result

    async with session:
        for site in SITES:
            if not site.enabled or (site_name and site.name != site_name):
                continue
            added = 0
            for sitemap in site.sitemaps:
                for url in await _walk_sitemap(session, sitemap):
                    if not site.is_track_page(url):
                        continue
                    site_index.remember(site.name, url, _title_from_url(url))
                    added += 1
                    if added >= MAX_URLS_PER_RUN:
                        break
                if added >= MAX_URLS_PER_RUN:
                    break
            result[site.name] = added
            logger.info("نمایهٔ %s: %s نشانی.", site.label, added)

    return result


async def top_up_titles(limit: int = 20) -> int:
    """
    نامِ صفحه‌هایی که هنوز بی‌نام‌اند را از خودِ برگه می‌گیرد.

    برگه‌به‌برگه و با درنگ. این کارِ شبانه است، نه کارِ لحظه‌ای:
    نمایه با گذشت شب‌ها پر می‌شود و جست‌وجوی کاربر روزبه‌روز
    بی‌نیازتر از رفتن به تارنما.
    """
    from core.db import site_index

    site_index.ensure_table()
    rows = site_index.untitled(limit)
    if not rows:
        return 0

    try:
        session = _session()
    except ImportError:
        return 0

    filled = 0
    async with session:
        for row in rows:
            html = await _get_text(session, row["page_url"])
            if not html:
                continue
            title = _title_of(html)
            media = _media_in(html, row["page_url"])
            if media:
                site_index.set_media(
                    row["page_url"], media, title or None, site=row["site"]
                )
                filled += 1
            elif title:
                site_index.remember(row["site"], row["page_url"], title)
                filled += 1
    return filled


async def nightly(context) -> None:
    """کار شبانه: تازه کردن نمایه و پر کردن نام‌ها."""
    try:
        await refresh_index()
        filled = await top_up_titles(limit=120)
        logger.info("نمایهٔ تارنماها تازه شد؛ %s نام به دست آمد.", filled)
    except Exception:  # noqa: BLE001
        logger.exception("تازه کردن نمایهٔ تارنماها شکست خورد.")


def stats() -> dict[str, tuple[int, int]]:
    from core.db import site_index

    site_index.ensure_table()
    return site_index.counts()


# ═════════════════════════════════════════════════════════════
#  پر کردنِ نمایه در راه‌اندازی
# ═════════════════════════════════════════════════════════════

# زیر این شمار نشانی، نمایه نحیف است و جست‌وجو در آن بی‌معنا.
#
# ## چرا این بایسته شد
#
# `nightly` روزانه ساعت ۴:۳۰ می‌رفت — و ربات هرگز آن ساعت روشن
# نبود. نتیجه در گنجینهٔ راستین: **۹۴ نشانی** در کل، و برای دو
# تارنما (رادیو نینوا و موزیک‌دل) **هیچ**. کاربر می‌پرسید و ربات
# می‌گفت «در تارنماها هم نیافتم» — نه چون نبود، بلکه چون جایی
# برای گشتن نداشت.
#
# سیصد، مرزِ میانِ «تهی» و «چیزی برای گشتن هست» است: هر تارنمای
# فعال دست‌کم چند ده نشانی می‌دهد و پنج تارنما زیر سیصد یعنی
# دست‌کم یکی‌شان یکسره خالی مانده.
THIN_INDEX = 300


def diagnose() -> list[dict]:
    """
    وضعیتِ هر تارنما، برای `/sites`.

    ## چرا لازم شد

    گزارشِ پیشین تنها می‌شمرد. ولی شمارِ ردیف گمراه‌کننده است:
    تارنمایی با ۴۰۰ ردیفِ **همه بی‌نام** و بی جست‌وجوی زنده،
    برای کاربر یکسره وجود ندارد — و در گزارش «۴۰۰ صفحه» دیده
    می‌شد. اکنون همان‌جا گفته می‌شود.
    """
    from core.db import site_index

    site_index.ensure_table()
    counts = site_index.counts()

    out: list[dict] = []
    for site in SITES:
        total, named = counts.get(site.name, (0, 0))
        host = urlparse(site.home).netloc

        troubles: list[str] = []
        if not site.enabled:
            troubles.append("خاموش")
        if site.page_pattern is None:
            troubles.append("الگوی صفحه ندارد — نمایه نمی‌شود")
        if total and not named:
            troubles.append("همهٔ صفحه‌ها بی‌نام‌اند — در جست‌وجو دیده نمی‌شوند")
        if not site.search_url and not named:
            troubles.append("نه جست‌وجوی زنده دارد نه صفحهٔ نام‌دار — سهمش صفر است")

        # وضعیتِ robots تنها وقتی معنا دارد که پرسیده شده باشد.
        if host in _robots:
            robots = "بسته" if _robots[host] is None else "باز"
        else:
            robots = "هنوز پرسیده نشده"

        out.append({
            "name": site.name,
            "label": site.label,
            "live": bool(site.search_url),
            "total": total,
            "named": named,
            "robots": robots,
            "troubles": troubles,
        })
    return out


async def bootstrap(context=None) -> int:
    """
    اگر نمایه نحیف است، همان‌جا پرش می‌کند.

    یک بار در راه‌اندازی می‌رود، نه دوره‌ای: کارِ شبانه از این پس
    نگهش می‌دارد. اگر نمایه از پیش پر باشد، بی‌درنگ بازمی‌گردد و
    چیزی به تارنماها بار نمی‌کند.

    بازگشتی: شمار نشانیِ افزوده — و صفر، پاسخِ درست و رایج است.

    ناکامی‌اش ربات را نمی‌شکند: نبودِ نمایه یعنی جست‌وجوی تارنما
    ضعیف می‌ماند، و آن از بالا نیامدنِ ربات بهتر است.
    """
    from core.db import site_index

    site_index.ensure_table()
    # شمارِ **نام‌دار**، نه شمارِ ردیف.
    #
    # ردیفِ بی‌نام برای کاربر وجود ندارد: `site_index.search` کنارش
    # می‌گذارد. پس نمایه‌ای با ۱۶۸۳ ردیف که ۱۱۳۶ تایش بی‌نام است،
    # با سنجهٔ کهنه «سیر» به نظر می‌رسید و هرگز تعمیر نمی‌شد.
    have = site_index.titled()
    if have >= THIN_INDEX:
        logger.debug("نمایهٔ تارنماها %s صفحهٔ نام‌دار دارد؛ بس است.", have)
        return 0

    logger.info(
        "نمایهٔ تارنماها تنها %s صفحهٔ نام‌دار دارد (از %s ردیف)؛ پر کردنش آغاز شد.",
        have, site_index.total(),
    )
    try:
        result = await refresh_index()
        added = sum(result.values())
        filled = await top_up_titles(limit=60)
        logger.info(
            "نمایهٔ تارنماها پر شد: %s نشانی افزوده، %s نام به دست آمد (اکنون %s).",
            added, filled, site_index.total(),
        )
        return added
    except Exception:  # noqa: BLE001
        logger.exception("پر کردنِ نمایهٔ تارنماها شکست خورد.")
        return 0
