# -*- coding: utf-8 -*-
"""
سنجش یکپارچگی نوشتارها.

اجرا:  python tests/consistency.py

نوشتارهای ربات در YAML‌اند و کد با کلید صدایشان می‌زند. پس دو گونه
خرابی شدنی است که هیچ آزمون دیگری نمی‌گیردشان، چون تنها هنگام
فرستادن همان پیام رخ می‌دهند:

  • کلیدی که در کد هست و در YAML نیست  → KeyError در دست کاربر
  • جای‌گاهی که پیام می‌خواهد و کد نمی‌دهد → پیام اصلاً نمی‌رود

اینجا با تجزیهٔ نحوی (ast) سنجیده می‌شوند، نه با الگوی رشته‌ای؛
الگوی رشته‌ای بر فراخوان‌های چندسطری و پرانتزتودرتو می‌لغزد و
هشدارهای دروغین می‌دهد.

کلیدهایی که پویا صدا زده می‌شوند (مانند texts.msg(exc.message_key))
اینجا «بی‌کاربرد» گزارش می‌شوند؛ این هشدار است نه ایراد.
"""

import os
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.console import enable_utf8_console  # noqa: E402

enable_utf8_console()
import ast, pathlib, re, sys, yaml

msgs = yaml.safe_load(open("texts/messages.yaml", encoding="utf-8"))
btns = yaml.safe_load(open("texts/buttons.yaml", encoding="utf-8"))
stks = yaml.safe_load(open("texts/stickers.yaml", encoding="utf-8"))

# ── تنها کدِ خودِ پروژه ───────────────────────────────────────
#
# پیش‌تر تنها `__pycache__` کنار گذاشته می‌شد، و آن بس نبود: به‌محض
# آنکه محیط مجازی در ریشهٔ پروژه ساخته شود (`install.bat` همین را
# می‌کند)، این پیمایش هزاران پروندهٔ site-packages را هم برمی‌دارد.
# یکی از آن‌ها UTF-8 نیست و سنجه با UnicodeDecodeError می‌شکند —
# خطایی که هیچ ربطی به درستیِ نوشتارهای ربات ندارد.
SKIP_DIRS = {
    "__pycache__", ".venv", "venv", "env", "site-packages",
    ".git", "node_modules", "graphify-out", "backups", "tmp", "build", "dist",
}

files = [
    p for p in pathlib.Path(".").rglob("*.py")
    if not SKIP_DIRS.intersection(p.parts)
]
problems, used_msg, used_btn, used_stk = [], set(), set(), set()

def fname(node):
    f = node.func
    if isinstance(f, ast.Attribute):
        parts = []
        cur = f
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr); cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(f, ast.Name):
        return f.id
    return ""

for p in files:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = fname(node)
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        key = first.value
        if name.endswith("texts.msg") or name.endswith("messages.raw") or name == "msg":
            used_msg.add(key)
            if key not in msgs:
                problems.append(f"{p}:{node.lineno} پیام ناموجود «{key}»")
                continue
            if name.endswith("messages.raw"):
                continue
            needed = set(re.findall(r"\{([a-zA-Z_]\w*)\}", str(msgs[key])))
            given = {kw.arg for kw in node.keywords if kw.arg}
            if any(kw.arg is None for kw in node.keywords):
                continue  # **kwargs
            if needed - given:
                problems.append(f"{p}:{node.lineno} «{key}» جای‌گاه {sorted(needed-given)} می‌خواهد")
            if given - needed:
                problems.append(f"{p}:{node.lineno} «{key}» آرگومان زائد {sorted(given-needed)}")
        elif name.endswith("texts.btn") or name == "btn":
            used_btn.add(key)
            if key not in btns:
                problems.append(f"{p}:{node.lineno} دکمهٔ ناموجود «{key}»")
        elif name.endswith("_send_sticker") and len(node.args) >= 3:
            third = node.args[2]
            if isinstance(third, ast.Constant) and isinstance(third.value, str):
                used_stk.add(third.value)
                if third.value not in stks:
                    problems.append(f"{p}:{node.lineno} برچسب ناموجود «{third.value}»")
        if name.endswith("_send_sticker"):
            for kw in node.keywords:
                if kw.arg in ("key", "sticker_key") and isinstance(kw.value, ast.Constant):
                    used_stk.add(kw.value.value)
        for kw in node.keywords:
            if kw.arg == "sticker_key" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                used_stk.add(kw.value.value)
                if kw.value.value not in stks:
                    problems.append(f"{p}:{node.lineno} برچسب ناموجود «{kw.value.value}»")

orphan_msg = sorted(set(msgs) - used_msg)
orphan_btn = sorted(set(btns) - used_btn)
print(f"{len(files)} پرونده · {len(msgs)} پیام · {len(btns)} دکمه")
if orphan_msg:
    print(f"  پیام‌های بی‌کاربرد ({len(orphan_msg)}): {'، '.join(orphan_msg)}")
if orphan_btn:
    print(f"  دکمه‌های بی‌کاربرد ({len(orphan_btn)}): {'، '.join(orphan_btn)}")
if problems:
    print("\n✗ ایرادها:")
    for x in problems: print("  •", x)
    sys.exit(1)
print("✓ بی‌ایراد")
