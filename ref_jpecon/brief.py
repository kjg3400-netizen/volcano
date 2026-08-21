# -*- coding: utf-8 -*-
"""
일본 소재 준비기 — 고른 사건 하나를 제작 직전까지 차려 놓는다.

  python ref_jpecon/brief.py --pick 1
  python ref_jpecon/brief.py --url https://news.yahoo.co.jp/articles/<40hex>

2026-08-21 에 마루가메 회차를 손으로 만들며 부딪힌 것을 전부 넣었다 —
  · 본문은 <div class="article_body highLightSearchTarget"> 안이다
  · 기사 사진은 **newsatcl-pctr 호스트만** 이다. s.yimg.jp 는 야후 UI 아이콘이고,
    news-pctr 은 사이드바 추천기사 사진이라 섞이면 세븐일레븐·고교야구가 딸려 온다
  · ★사진 캡션의 **스톡 크레딧**을 반드시 본다. 야후 기사 대표사진이
    `stock.adobe.com` 인 경우가 흔한데, 그건 **매체가 라이선스한 것**이라
    우리가 쓸 수 없다. 뉴스 사진 인용과는 다른 문제다
"""
import argparse
import glob
import html
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

# 캡션에 이게 보이면 우리가 쓸 수 없는 사진이다
STOCK = ["stock.adobe.com", "shutterstock", "getty", "iStock", "PIXTA",
         "amanaimages", "写真AC", "Adobe Stock"]


def curl(url, dest, referer):
    try:
        subprocess.run(["curl.exe", "-sSL", "-A", UA, "-e", referer,
                        "--max-time", "30", "-o", dest, url], check=True)
        return os.path.exists(dest) and os.path.getsize(dest) > 4000
    except Exception:
        return False


def latest_hunt():
    f = sorted(glob.glob(os.path.join(OUT, "hunt_*.json")))
    if f:
        return f[-1]
    p = os.path.join(OUT, "_최신시트.json")     # 고정 경로본으로 물러선다
    if os.path.exists(p):
        return p
    sys.exit("hunt 결과가 없다. 먼저 python ref_jpecon/hunt.py 를 돌려라.")


def fetch_article(s, aid):
    """본문·사진·캡션. 야후는 본문이 여러 쪽으로 나뉜다(?page=2…)."""
    body, imgs, caps = [], [], []
    title = press = date = ""
    for pg in range(1, 8):
        u = f"https://news.yahoo.co.jp/articles/{aid}" + (f"?page={pg}" if pg > 1 else "")
        r = s.get(u, timeout=25)
        if r.status_code != 200:
            break
        h = r.text
        if pg == 1:
            m = re.search(r'<meta property="og:title" content="([^"]*)"', h)
            title = html.unescape(m.group(1)) if m else ""
            # og:title 은 `기사제목（매체） - Yahoo!ニュース` 꼴이다. 꼬리부터 떼고 매체를 뽑는다
            title = re.sub(r"\s*-\s*Yahoo!ニュース\s*$", "", title)
            m = re.search(r"（(.{2,20}?)）\s*$", title)
            if m:
                press = m.group(1)
                title = title[: m.start()].strip()
            m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', h)
            date = m.group(1) if m else ""
        i = h.find('class="article_body')
        if i < 0:
            break
        seg = h[i:i + 60000]
        txt = []
        for p in re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S):
            t = re.sub(r"<br\s*/?>", "\n", p)
            t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
            if len(t) > 12:
                txt.append(t)
        page = "\n".join(txt)
        if not page or (body and page[:50] in body[-1]):
            break
        body.append(page)
        # ★기사 사진만. news-pctr(사이드바 추천) 과 s.yimg(UI) 는 제외한다
        for im in re.findall(r"(https://newsatcl-pctr[^\"'?]+\.jpg)", h):
            if im not in imgs:
                imgs.append(im)
        for c in re.findall(r'<figcaption[^>]*>(.*?)</figcaption>', seg, re.S):
            c = html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            if c and c not in caps:
                caps.append(c)
        if f"page={pg+1}" not in h:
            break
    return {"title": title, "press": press, "date": date,
            "body": "\n\n".join(body), "images": imgs, "captions": caps}


def sheet(files, dest, cols=3, tw=470):
    from PIL import Image, ImageDraw
    th = []
    for f in files:
        try:
            im = Image.open(f).convert("RGB")
        except Exception:
            continue
        th.append((os.path.basename(f), im.size,
                   im.resize((tw, max(1, int(im.height * tw / im.width))), Image.LANCZOS)))
    if not th:
        return None
    TH = max(t.height for _, _, t in th)
    rows = (len(th) + cols - 1) // cols
    sh = Image.new("RGB", (cols * tw, rows * (TH + 30)), (18, 18, 18))
    d = ImageDraw.Draw(sh)
    for i, (name, size, t) in enumerate(th):
        x, y = (i % cols) * tw, (i // cols) * (TH + 30)
        sh.paste(t, (x, y + 30))
        # 뇌전구 규격 1184x880 에 견줘 쓸 만한지 바로 보이게
        d.text((x + 6, y + 8), f"{name}  {size[0]}x{size[1]}", fill=(255, 226, 110))
    sh.save(dest, quality=88)
    return dest, len(th)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", type=int, default=0)
    ap.add_argument("--url", default="")
    ap.add_argument("--hunt", default="")
    ap.add_argument("--dir", default="")
    a = ap.parse_args()

    ev = None
    if a.url:
        m = re.search(r"/articles/([0-9a-f]{40})", a.url)
        if not m:
            sys.exit("야후 기사 링크가 아니다.")
        aid = m.group(1)
    else:
        if not a.pick:
            sys.exit("--pick N 또는 --url 이 필요하다.")
        hp = a.hunt or latest_hunt()
        data = json.load(open(hp, encoding="utf-8"))
        if not 1 <= a.pick <= len(data["items"]):
            sys.exit(f"1~{len(data['items'])} 사이로 골라라.")
        ev = data["items"][a.pick - 1]
        aid = ev["aid"]
        print(f"시트: {os.path.basename(hp)}  #{a.pick}")
        print(f"고른 사건: {ev['title']}")
        print(f"  コメント {ev['cluster_comments']} · 안전 {ev['safety']:+.2f} "
              f"({', '.join(ev['safety_why']) or '중립'}) · 꼴 {ev['shape']}")
        if ev["safety"] < 0:
            print("  ! 안전도가 음수다 — 대전제에 걸리지 않게 화살표 방향을 확인해라")

    name = a.dir or f"work_jp_{datetime.now():%Y%m%d}_{aid[:8]}"
    wd = os.path.join(ROOT, name)
    os.makedirs(os.path.join(wd, "real"), exist_ok=True)
    print(f"\nworkdir: {wd}")

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    d = fetch_article(s, aid)
    if not d["body"]:
        sys.exit("본문을 못 읽었다 — 야후 구조가 바뀌었는지 확인해라")

    print(f"\n제목 : {d['title']}")
    print(f"매체 : {d['press']}   작성: {d['date']}")
    print(f"본문 : {len(d['body'])}자 · 사진후보 {len(d['images'])}")

    # ★스톡 크레딧 경고
    warn = [c for c in d["captions"] if any(k.lower() in c.lower() for k in STOCK)]
    if warn:
        print("\n! 스톡 사진 크레딧이 보인다 — 매체가 산 것이라 우리가 못 쓴다:")
        for c in warn:
            print("   ", c[:70])
        print("  그 장면은 생성으로 대체해라.")

    n = 0
    for im in d["images"][:10]:
        dest = os.path.join(wd, "real", f"p{n:02d}.jpg")
        if curl(im, dest, f"https://news.yahoo.co.jp/articles/{aid}"):
            n += 1
    print(f"사진 : {n}장 → real/")

    with open(os.path.join(wd, "body.txt"), "w", encoding="utf-8") as f:
        f.write(f"### {d['press']} | {d['title']}\n{d['date']}\n")
        f.write(f"https://news.yahoo.co.jp/articles/{aid}\n\n{d['body']}\n")
        if d["captions"]:
            f.write("\n[写真キャプション]\n" + "\n".join("- " + c for c in d["captions"]))
    json.dump({"picked": ev, "article": {k: v for k, v in d.items() if k != "body"}},
              open(os.path.join(wd, "brief.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    files = sorted(glob.glob(os.path.join(wd, "real", "*.jpg")))
    if files:
        r = sheet(files, os.path.join(wd, "_sheet_real.jpg"))
        if r:
            print(f"시트 : {r[0]}  ({r[1]}장) — ★눈으로 보고 쓸 것을 골라라")

    print(f"\n다음: 대전제(비난 금지)를 지켜 일본어 대본을 쓴다.")
    print(f"  188자 이내 · 컷 12~15 · 한 줄 전각 12자 이하 · です・ます 금지")
    print(f"본문 : {os.path.join(wd, 'body.txt')}")


if __name__ == "__main__":
    main()
