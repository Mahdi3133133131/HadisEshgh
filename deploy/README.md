# استقرار روی سرور

راهنمای بردنِ حدیث عشق روی یک سرور لینوکسی (اوبونتو ۲۲٫۰۴ به بالا).

---

## ۰) پیش از هر چیز — توکن

🔴 **توکن کنونی را از @BotFather باطل کنید و توکن تازه بگیرید.**

توکن مدت‌ها در دو پروندهٔ متنی به شکل ساده بود. اکنون از آن‌ها
برداشته شده، ولی هر که در این مدت آن‌ها را دیده باشد توکن را
دارد — و با توکن می‌شود کل ربات را در دست گرفت. پاک کردن از
پرونده، توکن را امن نمی‌کند؛ **تنها باطل کردن**.

در @BotFather: `/mybots` → ربات → `API Token` → `Revoke current token`

توکن تازه فقط در `.env` روی سرور بنشیند. `.env` در `.gitignore`
هست و هرگز نباید جایی منتشر شود.

---

## ۱) آماده‌سازی سرور

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg git
```

`ffmpeg` بایسته است — با pip نصب نمی‌شود و بی آن هیچ صوتی
رمزگشایی نمی‌شود. آزمودنش:

```bash
ffmpeg -version
```

---

## ۲) کاربر و جای برنامه

```bash
sudo useradd --system --home /opt/hadis --shell /usr/sbin/nologin hadis
sudo mkdir -p /opt/hadis
sudo chown hadis:hadis /opt/hadis
```

پرونده‌ها را در `/opt/hadis` بگذارید (با rsync، scp یا git).
**`.env` و پوشهٔ `data/` را از روی دستگاه خودتان نبرید** مگر
اینکه بخواهید گنجینهٔ کنونی هم برود.

---

## ۳) محیط مجازی و بسته‌ها

```bash
cd /opt/hadis
sudo -u hadis python3 -m venv .venv
sudo -u hadis .venv/bin/pip install --upgrade pip
sudo -u hadis .venv/bin/pip install -r requirements.txt
```

---

## ۴) پیکربندی

```bash
sudo -u hadis cp .env.example .env
sudo -u hadis nano .env
sudo chmod 600 /opt/hadis/.env
```

`chmod 600` یعنی تنها خودِ کاربر hadis بتواند بخواندش.

آنچه باید پر شود: `BOT_TOKEN` (توکنِ **تازه**)، `ADMIN_IDS`،
`CHANNEL_ID` و `CHANNEL_URL`، و شناسهٔ گروه‌ها.

---

## ۵) نخستین اجرا — دستی، نه با systemd

پیش از سپردن به systemd، یک بار دستی اجرا کنید تا اگر ایرادی
هست همان‌جا دیده شود:

```bash
sudo -u hadis /opt/hadis/.venv/bin/python /opt/hadis/main.py
```

باید پیام راه‌اندازی بدهد و بایستد. با Ctrl+C ببندید.

اگر خطای «ffmpeg در PATH یافت نشد» گرفتید، بند ۱ را دوباره
ببینید.

---

## ۶) سپردن به systemd

```bash
sudo cp /opt/hadis/deploy/hadis.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hadis
sudo systemctl status hadis
```

گزارش زنده:

```bash
journalctl -u hadis -f
```

واحد طوری تنظیم شده که از هر افتادنی برخیزد، ولی اگر در پنج
دقیقه پنج بار بیفتد بایستد — چون آنگاه ایراد پایدار است و
بازخیزی درمانش نمی‌کند. پس از رفعش:

```bash
sudo systemctl reset-failed hadis
sudo systemctl start hadis
```

---

## ۷) پس از نخستین راه‌اندازی

- **نمایه‌سازی دوباره** خودکار در پس‌زمینه آغاز می‌شود اگر نسخهٔ
  الگوریتم عوض شده باشد. تا پایانش جست‌وجو ناقص است. پیشرفتش در
  گزارش دیده می‌شود.
- `/addsource` برای کانال‌های مداحی — فهرست هنوز تهی است.
- ربات باید در هر کانالی که به فهرست‌ها می‌افزایید **مدیر** باشد.
- ربات‌های تلگرام **تاریخچهٔ کانال را نمی‌خوانند**؛ تنها پستِ تازه
  دیده می‌شود. پست‌های پیشین باید بازفرستاده شوند.

---

## ۸) پشتیبان

پشتیبان شبانه ساعت ۳ خودکار گرفته می‌شود و در `backups/`
می‌نشیند. ولی پشتیبانی که روی همان دستگاه بماند، پشتیبان نیست —
اگر دیسک برود، هر دو می‌روند. دست‌کم هفته‌ای یک بار بیرون ببریدش:

```bash
rsync -avz /opt/hadis/backups/ user@elsewhere:/backup/hadis/
```

**گنجینهٔ اثر انگشت باارزش‌ترین چیز این پروژه است و بازسازی‌اش
ناشدنی** — فایل‌ها را می‌شود دوباره گرفت، ولی ماه‌ها یادگیریِ
تصحیح‌های کاربران را نه.

---

## ۹) به‌روزرسانی

```bash
cd /opt/hadis
sudo systemctl stop hadis
# پرونده‌های تازه را بگذارید
sudo -u hadis .venv/bin/pip install -r requirements.txt
sudo systemctl start hadis
```

`data/` و `.env` دست نخورند.

---

## نکته‌ای دربارهٔ پیام‌های از دست رفته

`drop_pending_updates=True` در `main.py` هست: پیام‌هایی که هنگام
خاموشی ربات آمده‌اند، پس از راه‌اندازی **نادیده** گرفته می‌شوند.

این خواسته است نه ایراد — وگرنه پس از هر بازخیزی سیلی از
بازجویی‌های کهنه یکجا اجرا می‌شد. ولی بدانید که هست: اگر ربات
نیم‌ساعت پایین باشد، درخواست‌های آن نیم‌ساعت از دست می‌روند.
