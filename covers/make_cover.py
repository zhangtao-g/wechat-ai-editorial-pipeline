#!/usr/bin/env python3
"""
make_cover.py — 用 A1「科技暗黑」模板生成公众号封面图（940x400 @2x，2.35:1）。

用法：
  python3 make_cover.py \
    --title '苹果把AI<br>塞进<em>客厅</em>' \
    --sub '299 美元的屏，苹果智能还是没来' \
    --kicker 'AI · 消费电子' \
    --author 'AGENT 实验室' \
    --accent '#00FF9D' \
    --out /path/to/cover.png

title 里可以用 <br> 换行、用 <em>…</em> 包住要强调的词（会染成 accent 色并发光）。
accent 常用：#00FF9D 荧光绿(默认) / #FB7185 警示红 / #60A5FA 科技蓝 / #FBBF24 琥珀。
标题两行、每行不超过 6 个汉字效果最好（缩略图里才看得清）。
"""
import argparse
import os
import subprocess
import sys
import tempfile

CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux/chrome"),
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]

TPL = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:940px;height:400px;overflow:hidden}}
body{{font-family:"Noto Sans CJK SC","WenQuanYi Zen Hei",sans-serif}}
.cover{{width:940px;height:400px;position:relative;overflow:hidden;background:#000;
 display:flex;align-items:center;padding:0 52px}}
.glow{{position:absolute;width:700px;height:700px;border-radius:50%;
 background:radial-gradient(circle,{accent}30 0%,{accent}00 65%);right:-200px;top:-180px}}
.glow2{{position:absolute;width:420px;height:420px;border-radius:50%;
 background:radial-gradient(circle,{accent}24 0%,{accent}00 70%);left:280px;bottom:-260px}}
.bar{{position:absolute;left:0;top:0;width:9px;height:400px;
 background:linear-gradient(180deg,{accent} 0%,#00704A 60%,#000 100%)}}
.content{{position:relative;z-index:3}}
.kicker{{font-size:14px;letter-spacing:.36em;color:{accent};margin-bottom:22px;font-weight:700;
 text-shadow:0 0 18px {accent}bf}}
h1{{font-size:{size}px;line-height:1.02;color:#fff;font-weight:700;letter-spacing:-.03em;
 text-shadow:0 0 42px rgba(255,255,255,.22)}}
h1 em{{font-style:normal;color:{accent};
 text-shadow:0 0 30px {accent}f2,0 0 70px {accent}8c}}
.sub{{margin-top:24px;font-size:19px;color:#9CA3AF;letter-spacing:.01em}}
.badge{{position:absolute;right:52px;bottom:36px;z-index:3;font-size:12px;
 color:#3F4A56;letter-spacing:.24em}}
</style></head><body><div class="cover">
<div class="glow"></div><div class="glow2"></div><div class="bar"></div>
<div class="content">
 <div class="kicker">{kicker}</div>
 <h1>{title}</h1>
 <div class="sub">{sub}</div>
</div>
<div class="badge">{author}</div>
</div></body></html>"""


def find_chrome():
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    hits = []
    base = os.path.expanduser("~/.cache/ms-playwright")
    for root, _dirs, files in os.walk(base):
        if "chrome" in files:
            hits.append(os.path.join(root, "chrome"))
    return hits[0] if hits else None


def auto_size(title: str) -> int:
    """标题越长，字号越小，保证放在 940x400 里。"""
    import re
    plain = re.sub(r"<[^>]+>", "", title)
    lines = [l for l in re.split(r"<br\s*/?>", title) if l.strip()]
    longest = max((len(re.sub(r"<[^>]+>", "", l)) for l in lines), default=len(plain))
    if longest <= 4:
        return 108
    if longest == 5:
        return 96
    if longest == 6:
        return 88
    if longest == 7:
        return 80
    return 70


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="主标题，支持 <br> 和 <em>")
    ap.add_argument("--sub", default="")
    ap.add_argument("--kicker", default="")
    ap.add_argument("--author", default="AGENT 实验室")
    ap.add_argument("--accent", default="#00FF9D")
    ap.add_argument("--size", type=int, default=0, help="字号，留空自动")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    chrome = find_chrome()
    if not chrome:
        print("ERROR: 找不到 chromium 可执行文件", file=sys.stderr)
        return 2

    size = a.size or auto_size(a.title)
    html = TPL.format(accent=a.accent, size=size, title=a.title,
                      sub=a.sub, kicker=a.kicker, author=a.author)

    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp_html = f.name

    cmd = [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
           "--force-device-scale-factor=2", "--window-size=940,400",
           "--screenshot=" + out, "file://" + tmp_html]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    os.unlink(tmp_html)

    if os.path.exists(out):
        from PIL import Image
        w, h = Image.open(out).size
        print("OK %s  %dx%d  %d KB  (字号 %d, 强调色 %s)" % (
            out, w, h, os.path.getsize(out) // 1024, size, a.accent))
        return 0
    print("FAILED\nstdout:%s\nstderr:%s" % (r.stdout[-500:], r.stderr[-800:]), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
