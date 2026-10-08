"""
آزمون سرتاسری با فایل‌های راستین.

گنجینه از فایل‌های mp3 راستین پر می‌شود، سپس تکه‌هایی با ffmpeg
بریده و به mp3/mp4 دوباره فشرده می‌شوند — درست همان‌گونه که کاربر
می‌فرستد. این تنها آزمونی است که زنجیرهٔ کامل (ffmpeg → رمزگشایی →
اثر انگشت → SQLite → تطبیق) را می‌پیماید.
"""
import sys, subprocess, tempfile, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.console import enable_utf8_console; enable_utf8_console()
import numpy as np

from core.audio.decode import decode, extract_audio
from core.audio.fingerprint import (
    FAN_OUT_INDEX,
    FAN_OUT_QUERY,
    fingerprint,
    fingerprint_query,
)
from core.audio import matcher
from core.db import database as db, fingerprints as fp_store

SRC = "pipelinetest"
N = 12
SECONDS = 90


def synth(seconds, seed):
    r = np.random.default_rng(seed)
    t = np.linspace(0, seconds, int(seconds * 44100), endpoint=False)
    x = np.zeros_like(t)
    base = r.uniform(95, 250)
    for k in range(1, 9):
        f = base * k
        if f > 20000: break
        env = 0.5 + 0.5*np.sin(2*np.pi*r.uniform(0.15,0.9)*t + r.uniform(0,6))
        vib = 1 + 0.015*np.sin(2*np.pi*r.uniform(3,7)*t)
        x += (r.uniform(0.4,1.0)/k)*env*np.sin(2*np.pi*f*vib*t)
    for _ in range(6):
        f = r.uniform(600, 6000)
        env = np.maximum(0, np.sin(2*np.pi*r.uniform(0.5,2.5)*t))**4
        x += r.uniform(0.15,0.5)*env*np.sin(2*np.pi*f*t)
    x += 0.015*r.standard_normal(t.size)
    return (x/np.max(np.abs(x))*0.9*32767).astype(np.int16)


def to_mp3(pcm, path, bitrate="128k"):
    raw = path.with_suffix(".raw"); raw.write_bytes(pcm.tobytes())
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-f","s16le","-ar","44100",
                    "-ac","1","-i",str(raw),"-b:a",bitrate,"-y",str(path)], check=True)
    raw.unlink()
    return path


def cut(src, dst, start, dur, bitrate="64k"):
    """تکه را می‌برد و دوباره فشرده می‌کند — مثل کاری که کاربر می‌کند."""
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-ss",str(start),
                    "-i",str(src),"-t",str(dur),"-b:a",bitrate,"-y",str(dst)], check=True)
    return dst


def cut_video(src, dst, start, dur):
    """تکه را به نماهنگ درمی‌آورد — مثل کلیپ اینستاگرام."""
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error",
                    "-f","lavfi","-i",f"testsrc=size=480x480:rate=25:duration={dur}",
                    "-ss",str(start),"-i",str(src),"-t",str(dur),
                    "-c:v","libx264","-preset","ultrafast","-c:a","aac","-b:a","96k",
                    "-shortest","-y",str(dst)], check=True)
    return dst


def cleanup():
    for row in db.query_all("SELECT id FROM tracks WHERE source=?", (SRC,)):
        fp_store.delete_for_track(int(row["id"]))
    db.execute("DELETE FROM tracks WHERE source=?", (SRC,))


def main():
    db.init_db(); cleanup()
    work = Path(tempfile.mkdtemp())
    print("═"*62); print("  آزمون سرتاسری با فایل راستین"); print("═"*62)

    print(f"\n▸ ساخت و نمایه‌سازی {N} نوای mp3 راستین")
    files, ids = [], []
    for i in range(N):
        p = to_mp3(synth(SECONDS, 7000+i), work/f"track_{i}.mp3")
        files.append(p)
        tid = db.add_track(file_id=f"PT_{i}", file_unique_id=f"ptuq_{i}", source=SRC,
                           title=f"نوا {i}", madah="مداح", duration=SECONDS)
        ids.append(tid)
        fpr = fingerprint(decode(p), fan_out=FAN_OUT_INDEX)
        fp_store.store(tid, fpr.hashes, fpr.offsets)
    print(f"  ✓ {N} نوا نمایه شد")

    rng = np.random.default_rng(31337)
    problems = []

    scenarios = [
        ("mp3 ۱۰ ثانیه، ۶۴k", lambda s,d,i: cut(files[i], d/"q.mp3", s, 10, "64k")),
        ("mp3 ۱۰ ثانیه، ۳۲k", lambda s,d,i: cut(files[i], d/"q.mp3", s, 10, "32k")),
        ("mp3 ۵ ثانیه، ۶۴k",  lambda s,d,i: cut(files[i], d/"q.mp3", s, 5,  "64k")),
        ("mp4 ۱۵ ثانیه",      lambda s,d,i: cut_video(files[i], d/"q.mp4", s, 15)),
    ]

    print("\n▸ بازجویی با فایل‌های بریده و دوباره‌فشرده")
    for label, maker in scenarios:
        hits = wrong = missed = 0
        for i in range(N):
            start = float(rng.integers(5, SECONDS-25))
            qdir = work/f"q{i}"; qdir.mkdir(exist_ok=True)
            try:
                qf = maker(start, qdir, i)
                fpr = fingerprint_query(decode(qf))
                m = matcher.match(fpr)
            except Exception as e:
                missed += 1; continue
            finally:
                shutil.rmtree(qdir, ignore_errors=True)
            if m is None: missed += 1
            elif m.track_id == ids[i]: hits += 1
            else: wrong += 1
        flag = "✓" if wrong == 0 and hits >= N*0.8 else "✗"
        print(f"  {flag} {label:22s} یافت {hits:>2}/{N}   نیافت {missed}   غلط {wrong}")
        if wrong: problems.append(f"{label}: {wrong} غلط")
        if hits < N*0.75: problems.append(f"{label}: تنها {hits}/{N}")

    print("\n▸ استخراج آوا از نماهنگ و بازجویی با همان")
    hits = 0
    for i in range(min(6, N)):
        start = float(rng.integers(5, SECONDS-25))
        qdir = work/f"v{i}"; qdir.mkdir(exist_ok=True)
        try:
            vid = cut_video(files[i], qdir/"v.mp4", start, 15)
            aud = extract_audio(vid, qdir/"a.mp3")
            m = matcher.match(fingerprint_query(decode(aud)))
            if m and m.track_id == ids[i]: hits += 1
        finally:
            shutil.rmtree(qdir, ignore_errors=True)
    print(f"  {'✓' if hits>=5 else '✗'} آوای استخراج‌شده: یافت {hits}/6")
    if hits < 5: problems.append(f"استخراج آوا: تنها {hits}/6")

    print("\n▸ نوایی که در گنجینه نیست")
    fp_count = 0
    for i in range(8):
        qdir = work/f"n{i}"; qdir.mkdir(exist_ok=True)
        p = to_mp3(synth(30, 88000+i), qdir/"n.mp3")
        q = cut(p, qdir/"nq.mp3", 5, 10, "64k")
        if matcher.match(fingerprint_query(decode(q))) is not None:
            fp_count += 1
        shutil.rmtree(qdir, ignore_errors=True)
    print(f"  {'✓' if fp_count==0 else '✗'} مثبت کاذب: {fp_count}/8")
    if fp_count: problems.append(f"{fp_count} مثبت کاذب")

    cleanup(); shutil.rmtree(work, ignore_errors=True)
    print("\n" + "═"*62)
    if problems:
        print("  ✗ ایرادها:")
        for p in problems: print(f"     • {p}")
        print("═"*62); return 1
    print("  ✓ زنجیرهٔ کامل با فایل راستین گذشت")
    print("═"*62); return 0


sys.exit(main())
