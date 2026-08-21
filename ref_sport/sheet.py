# -*- coding: utf-8 -*-
"""후보 썸네일 시트 — 눈으로 고르기 위한 판.

`hunt.py --sheet` 가 부른다. 목록만 보면 제목이 낚시라 실제 화면을 못 읽는다.
★번호를 크게 박는다 — 사장님이 `<번호>번으로 가` 라고 부르실 수 있어야 한다.
"""
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
COLS, TW, TH, PAD, BAR = 5, 300, 400, 10, 54     # 쇼츠라 세로 썸네일이다


def _font(sz):
    for p in (r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def build(rows, out_dir, topic, limit=25):
    rows = rows[:limit]
    if not rows:
        print("후보가 없다. 먼저 사냥부터 돌려라.")
        return
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
    os.makedirs(cache, exist_ok=True)

    cells = []
    for i, r in enumerate(rows, 1):
        dst = os.path.join(cache, f"th_{r['vid']}.jpg")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 2000):
            # ★쇼츠는 oardefault 가 세로 원본이다. 없으면 hqdefault 로 떨어진다
            for u in (f"https://i.ytimg.com/vi/{r['vid']}/oardefault.jpg",
                      f"https://i.ytimg.com/vi/{r['vid']}/hqdefault.jpg"):
                subprocess.run(["curl.exe", "-sSL", "-A", UA, "-o", dst, u],
                               capture_output=True)
                if os.path.exists(dst) and os.path.getsize(dst) > 2000:
                    break
        try:
            im = Image.open(dst).convert("RGB")
        except Exception:
            im = Image.new("RGB", (TW, TH), (40, 40, 40))
        # 비율 유지해 채우고 가운데를 남긴다
        s = max(TW / im.width, TH / im.height)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
        l, t = (im.width - TW) // 2, (im.height - TH) // 2
        cells.append((i, r, im.crop((l, t, l + TW, t + TH))))

    rowsn = (len(cells) + COLS - 1) // COLS
    W = COLS * TW + (COLS + 1) * PAD
    H = rowsn * (TH + BAR) + (rowsn + 1) * PAD + 46
    sheet = Image.new("RGB", (W, H), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 12), f"{topic} 소재 후보 {len(cells)}건 — 번호로 고르세요",
           font=_font(24), fill=(255, 255, 255))

    for n, (i, r, im) in enumerate(cells):
        cx = PAD + (n % COLS) * (TW + PAD)
        cy = 46 + PAD + (n // COLS) * (TH + BAR + PAD)
        sheet.paste(im, (cx, cy))
        # 번호 — 왼쪽 위에 크게
        d.rectangle([cx, cy, cx + 62, cy + 46], fill=(0, 0, 0))
        d.text((cx + 10, cy + 4), f"{i}", font=_font(32), fill=(255, 220, 60))
        # 아래 띠 — 조회·배수·갈래·채널
        d.rectangle([cx, cy + TH, cx + TW, cy + TH + BAR], fill=(32, 32, 32))
        v = r["views"]
        vs = f"{v/10000:.0f}만" if v >= 10000 else f"{v:,}"
        b = f"  ×{r['burst']:.1f}" if r.get("burst") else ""
        d.text((cx + 6, cy + TH + 3), f"{vs}{b}  {r.get('shape','')}",
               font=_font(17), fill=(120, 230, 255))
        d.text((cx + 6, cy + TH + 27), r.get("ch", "")[:20],
               font=_font(15), fill=(180, 180, 180))

    p = os.path.join(out_dir, "_후보시트.jpg")
    sheet.save(p, quality=88)
    print(f"시트 → {p}   ({len(cells)}건)")
