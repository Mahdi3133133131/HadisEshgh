# ─────────────────────────────────────────────────────────────
#  حدیث عشق — ایمیج Railway
#
#  چرا Dockerfile و نه Nixpacks خودکار:
#  ۱) نسخهٔ پایتون را خودمان پین می‌کنیم (۳٫۱۳ — همان که
#     requirements.txt با آن سنجیده شده).
#  ۲) بستهٔ سیستمی ffmpeg و libsndfile1 را می‌آوریم؛ اولی با pip
#     نصب نمی‌شود و بی آن هیچ صوتی رمزگشایی نمی‌شود، دومی برای
#     soundfile (همراه librosa) لازم است.
# ─────────────────────────────────────────────────────────────
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg برای رمزگشایی صوت + libsndfile1 برای soundfile/librosa
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY bot/ bot/
COPY core/ core/
COPY services/ services/
COPY worker/ worker/
COPY texts/ texts/
COPY assets/ assets/
COPY config.py main.py setup_project.py ./

# پوشه‌های زمان اجرا (محتویاتشان روی Volume می‌نشیند، نه ایمیج)
RUN mkdir -p data logs tmp backups

CMD ["python", "main.py"]
