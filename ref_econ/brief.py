# -*- coding: utf-8 -*-
"""
소재 준비기 (2단계 — 고른 사건 하나를 제작 직전까지 차려 놓는다)

hunt.py 시트에서 번호를 고르면 전용 workdir 를 파고
  · 기사 본문 · 사진 후보 전부 · 눈으로 고를 썸네일 시트
까지 만들어 둔다. 뇌전구는 실사 사진이 기본이라 사진 확보가 절반이다.

  python ref_econ/brief.py --pick 3
  python ref_econ/brief.py --pick 3 --with-siblings   # 같은 사건 다른 매체 사진까지
  python ref_econ/brief.py --url https://n.news.naver.com/article/015/0005322924

자산 내려받기는 curl.exe 로 한다 (PowerShell 의 curl 은 Invoke-WebRequest 별칭이라
-sSL 에서 죽고, 네이버 이미지 CDN 은 파이썬 UA 를 가끔 막는다).
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

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")


def curl(url, dest, referer="https://n.news.naver.com/"):
    try:
        subprocess.run(["curl.exe", "-sSL", "-A", UA, "-e", referer,
                        "--max-time", "30", "-o", dest, url], check=True)
        return os.path.exists(dest) and os.path.getsize(dest) > 900
    except Exception:
        return False


def latest_hunt():
    f = sorted(glob.glob(os.path.join(OUT, "hunt_*.json")))
    if not f:
        sys.exit("hunt 결과가 없다. 먼저 python ref_econ/hunt.py 를 돌려라.")
    return f[-1]


def parse_article(h):
    """네이버 기사 페이지에서 제목·언론사·날짜·본문·사진을 뽑는다."""
    d = {}
    m = re.search(r'<h2[^>]*id="title_area"[^>]*>(.*?)</h2>', h, re.S)
    d["title"] = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    m = re.search(r'<meta property="og:title" content="([^"]*)"', h)
    if not d["title"] and m:
        d["title"] = html.unescape(m.group(1))

    m = re.search(r'<span class="media_end_head_top_logo_text[^"]*">(.*?)</span>', h, re.S)
    if m:
        d["press"] = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    else:
        m = re.search(r'<meta property="og:article:author" content="([^"|]*)', h)
        d["press"] = html.unescape(m.group(1)).strip() if m else ""

    m = re.search(r'data-date-time="([^"]*)"', h)
    d["date"] = m.group(1) if m else ""

    m = re.search(r'<article[^>]*id="dic_area"[^>]*>(.*?)</article>', h, re.S)
    body = m.group(1) if m else ""

    imgs = []
    for t in re.findall(r"<img[^>]+>", body):
        ms = re.search(r'data-src="([^"]+)"', t) or re.search(r'src="([^"]+)"', t)
        if not ms:
            continue
        u = html.unescape(ms.group(1))
        u = re.sub(r"\?type=.*$", "", u)          # 썸네일 파라미터 제거 → 원본
        ma = re.search(r'alt="([^"]*)"', t)
        imgs.append({"url": u, "alt": html.unescape(ma.group(1)) if ma else ""})
    m = re.search(r'<meta property="og:image" content="([^"]+)"', h)
    if m:
        u = re.sub(r"\?type=.*$", "", html.unescape(m.group(1)))
        if u not in [x["url"] for x in imgs]:
            imgs.insert(0, {"url": u, "alt": "og:image"})
    d["images"] = imgs

    d["captions"] = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r'<em class="img_desc">(.*?)</em>', body, re.S)]

    t = re.sub(r'<span class="end_photo_org">.*?</span>', "\n", body, flags=re.S)
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    d["body"] = re.sub(r"\n{3,}", "\n\n", t).strip()
    return d


def sheet(files, dest, cols=4, tw=430):
    from PIL import Image, ImageDraw
    thumbs = []
    for f in files:
        try:
            im = Image.open(f).convert("RGB")
        except Exception:
            continue
        h = max(1, int(im.height * tw / im.width))
        thumbs.append((os.path.basename(f), im.size, im.resize((tw, h), Image.LANCZOS)))
    if not thumbs:
        return None
    th = max(t.height for _, _, t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    sh = Image.new("RGB", (cols * tw, rows * (th + 30)), (18, 18, 18))
    d = ImageDraw.Draw(sh)
    for i, (name, size, t) in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * (th + 30)
        sh.paste(t, (x, y + 30))
        # 뇌전구 규격 1184x880 에 견줘 쓸 만한지 바로 보이게 원본 크기를 박는다
        d.text((x + 6, y + 8), f"{name}  {size[0]}x{size[1]}", fill=(255, 226, 110))
    sh.save(dest, quality=88)
    return dest, len(thumbs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", type=int, default=0, help="hunt 시트의 번호")
    ap.add_argument("--url", default="")
    ap.add_argument("--hunt", default="", help="특정 hunt_*.json 지정")
    ap.add_argument("--with-siblings", action="store_true",
                    help="같은 사건 다른 매체 기사 사진까지 후보로 긁는다")
    ap.add_argument("--dir", default="", help="workdir 이름 직접 지정")
    a = ap.parse_args()

    targets, ev = [], None
    if a.url:
        m = re.search(r"/article/(\d{3})/(\d{10})", a.url)
        if not m:
            sys.exit("네이버 기사 링크가 아니다.")
        targets = [(m.group(1), m.group(2))]
    else:
        if not a.pick:
            sys.exit("--pick N 또는 --url 이 필요하다.")
        hp = a.hunt or latest_hunt()
        data = json.load(open(hp, encoding="utf-8"))
        if not 1 <= a.pick <= len(data["items"]):
            sys.exit(f"1~{len(data['items'])} 사이로 골라라.")
        ev = data["items"][a.pick - 1]
        targets = [(ev["oid"], ev["aid"])]
        print(f"시트: {os.path.basename(hp)}  #{a.pick}")
        print(f"고른 사건: {ev['title']}")
        print(f"  댓글 {ev['cluster_comments']} · 반응 {ev['cluster_reactions']} "
              f"· {ev['cluster_n']}개 매체 · 점수 {ev['score']}")
        if a.with_siblings:
            for m in ev.get("members", [])[1:6]:
                if (m["oid"], m["aid"]) not in targets:
                    targets.append((m["oid"], m["aid"]))
            print(f"  같은 사건 기사 {len(targets)}건에서 사진을 모은다")

    oid, aid = targets[0]
    name = a.dir or f"work_econ_{datetime.now():%Y%m%d}_{oid}{aid[-6:]}"
    # 회차 workdir 는 채널 폴더 아래에 판다 (사장님 지시 2026-08-24)
    wd = os.path.join(ROOT, "뇌전구_한국", name)
    real = os.path.join(wd, "real")
    os.makedirs(real, exist_ok=True)
    print(f"\nworkdir: {wd}")

    arts = []
    for o, i in targets:
        hp = os.path.join(wd, f"article_{o}{i[-6:]}.html")
        if not curl(f"https://n.news.naver.com/article/{o}/{i}", hp):
            print(f"  ! 기사 받기 실패 {o}/{i}")
            continue
        d = parse_article(open(hp, encoding="utf-8", errors="ignore").read())
        d["oid"], d["aid"] = o, i
        arts.append(d)

    if not arts:
        sys.exit("기사를 하나도 못 받았다.")

    main_art = arts[0]
    print(f"\n제목 : {main_art['title']}")
    print(f"매체 : {main_art['press']}   작성: {main_art['date']}")
    print(f"본문 : {len(main_art['body'])}자")

    # 사진 후보 내려받기
    n = 0
    seen = set()
    for d in arts:
        for im in d["images"]:
            u = im["url"]
            if u in seen:
                continue
            seen.add(u)
            ext = ".jpg"
            me = re.search(r"\.(jpg|jpeg|png|gif)(?:$|\?)", u, re.I)
            if me:
                ext = "." + me.group(1).lower()
            dest = os.path.join(real, f"p{n:02d}{ext}")
            if curl(u, dest, referer=f"https://n.news.naver.com/article/{d['oid']}/{d['aid']}"):
                im["file"] = os.path.basename(dest)
                n += 1
    print(f"사진 : {n}장 내려받음 → real/")

    # 본문 저장
    with open(os.path.join(wd, "body.txt"), "w", encoding="utf-8") as f:
        for d in arts:
            f.write(f"### {d['press']} | {d['title']}\n{d['date']}\n")
            f.write(f"https://n.news.naver.com/article/{d['oid']}/{d['aid']}\n\n")
            f.write(d["body"] + "\n\n")
            if d["captions"]:
                f.write("[사진설명]\n" + "\n".join("- " + c for c in d["captions"]) + "\n\n")
            f.write("=" * 70 + "\n\n")

    meta = {"picked": ev, "articles": [{k: v for k, v in d.items() if k != "body"}
                                       for d in arts]}
    json.dump(meta, open(os.path.join(wd, "brief.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    files = sorted(glob.glob(os.path.join(real, "*")))
    if files:
        r = sheet(files, os.path.join(wd, "_sheet_real.jpg"))
        if r:
            print(f"시트 : {r[0]}  ({r[1]}장)")

    if main_art["captions"]:
        print("\n사진설명:")
        for c in main_art["captions"][:6]:
            print("  -", c[:70])

    print(f"\n다음: 시트를 눈으로 보고 쓸 사진을 고른 뒤 뇌전구 대본(240자 이내)을 쓴다.")
    print(f"본문 : {os.path.join(wd, 'body.txt')}")


if __name__ == "__main__":
    main()
