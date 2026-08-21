# -*- coding: utf-8 -*-
"""커뮤형 뇌전구 — 고른 사건을 소재로 준비한다

    python ref_comm/brief.py --pick 2
    python ref_comm/brief.py --pick 2 --with-siblings

★커뮤 글 본문을 긁어 오지 않는다. 일부러 그렇게 짰다.

  커뮤 글은 개인이 쓴 미검증 주장이고 저작물이다. 본문을 그대로 옮기면
  ① 오보를 그대로 만들 수 있고 ② 남의 글을 베끼는 게 된다.

  그래서 이 브리퍼는 **커뮤를 레이더로만 쓴다** —
  커뮤에서 터진 사건을 보도한 **네이버 기사**를 찾아 그것을 소재로 넘긴다.
  실제 자료 준비(본문·사진·시트)는 검증된 경제 브리퍼(ref_econ/brief.py)가 한다.

  커뮤 쪽에서 가져오는 건 '어디서 얼마나 터졌나' 하나뿐이고, 그건
  `comm_context.txt` 에 적어 둔다. 훅("커뮤니티가 뒤집힌 이유")에 쓰라고 남기는 것이다.
"""
import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import hunt                                                  # noqa: E402


def latest_hunt(path=""):
    if path:
        return path
    got = sorted(glob.glob(os.path.join(HERE, "out", "hunt_*.json")))
    if not got:
        print("hunt 결과가 없다. 먼저 `python ref_comm/hunt.py` 를 돌려라.")
        sys.exit(1)
    return got[-1]


# ── 언론사 직링크 경로 ────────────────────────────────────────────────
# ★연예·방송 기사는 네이버 뉴스에 안 실린다. 언론사 자체 페이지에만 있다.
#   실측 2026-08-21: `기안84 AI 여친` 은 기사가 10건씩 나오는데
#   **n.news 링크가 0개**였다. 네이버 경로만 보면 '기사 없음' 이 되고,
#   그러면 커뮤형에서 연예·방송 갈래가 통째로 막힌다.
SKIP_HOST = ("naver.com", "naver.net", "pstatic.net", "daum.net", "kakao.com",
             "google.", "youtube.com", "facebook.com", "twitter.com", "x.com",
             "instagram.com")


def _load_econ_brief():
    """ref_econ/brief.py 의 curl·sheet 를 그대로 쓴다.
    ★둘 다 파일 이름이 brief.py 라 sys.path 로 섞으면 나중 것이 이긴다."""
    import importlib.util
    p = os.path.join(ROOT, "ref_econ", "brief.py")
    spec = importlib.util.spec_from_file_location("econ_brief", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["econ_brief"] = m
    spec.loader.exec_module(m)
    return m


def press_links(h):
    """검색 결과에서 언론사 기사 링크를 긁는다."""
    out, seen = [], set()
    for u in re.findall(r'href="(https?://[^"]+)"', h):
        u = u.split("#")[0]
        host = u.split("/")[2].lower()
        if any(k in host for k in SKIP_HOST):
            continue
        path = "/" + "/".join(u.split("/")[3:])
        # 기사 주소는 대개 숫자 id 를 품는다. 목록·섹션 페이지를 걸러낸다.
        if not re.search(r"\d{5,}", path):
            continue
        key = host + re.sub(r"\d+", "#", path)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out[:12]


def press_meta(s, url):
    """언론사 기사에서 제목·본문·사진을 뽑는다 (매체 공통 규격만 쓴다)."""
    try:
        h = hunt.get_text(s, url, timeout=20)
    except Exception:                                        # noqa: BLE001
        return None
    def meta(prop):
        m = re.search(r'<meta[^>]+property="%s"[^>]+content="([^"]*)"' % prop, h)
        if not m:
            m = re.search(r'<meta[^>]+content="([^"]*)"[^>]+property="%s"' % prop, h)
        return hunt.strip_tags(m.group(1)) if m else ""

    title = meta("og:title")
    if not title:
        m = re.search(r"<title>([^<]{4,120})</title>", h)
        title = hunt.strip_tags(m.group(1)) if m else ""
    if not title:
        return None

    # 본문 — 매체마다 그릇이 달라 여러 후보를 뽑아 **가장 본문다운 것**을 고른다.
    # ★첫 번째로 걸리는 걸 쓰면 안 된다. 실측 2026-08-21: 뉴스1에서
    #   사이드바 '관련기사' 목록을 본문으로 집어 388자짜리 링크 뭉치를 냈다.
    #   글자 수만 보면 그럴듯해 **조용히 지나간다.**
    #   본문은 문장이 길고 링크가 드물다. 사이드바는 그 반대다.
    cands = []
    for pat in (r'<article[^>]*>(.*?)</article>',
                r'<div[^>]+itemprop="articleBody"[^>]*>(.*?)</div>\s*</div>',
                r'<div[^>]+id="[^"]*article[^"]*"[^>]*>(.*?)</div>\s*</div>',
                r'<div[^>]+class="[^"]*article[_-]?(?:body|content|txt|view)[^"]*"[^>]*>(.*?)</div>\s*</div>',
                r'<div[^>]+class="[^"]*(?:news|cont)[_-]?(?:body|content|view)[^"]*"[^>]*>(.*?)</div>\s*</div>'):
        for m in re.finditer(pat, h, re.S | re.I):
            cands.append(m.group(1))

    def score(blk):
        txt = html.unescape(re.sub(r"<[^>]+>", " ", blk))
        links = len(re.findall(r"<a\s", blk))
        # 마침표·따옴표가 있어야 문장이다. 링크 하나당 크게 깎는다.
        sent = len(re.findall(r"[.!?”\"]", txt))
        return len(txt.strip()) + 40 * sent - 220 * links

    body = max(cands, key=score) if cands else ""
    if score(body) < 300:
        body = ""
    imgs = []
    for t in re.findall(r"<img[^>]+>", body or h):
        ms = re.search(r'data-src="([^"]+)"', t) or re.search(r'src="([^"]+)"', t)
        if not ms:
            continue
        u = html.unescape(ms.group(1))
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http") or re.search(r"\.(gif|svg)(\?|$)", u, re.I):
            continue
        if u not in imgs:
            imgs.append(u)
    og = meta("og:image")
    if og and og not in imgs:
        imgs.insert(0, og)

    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    txt = re.sub(r"<br\s*/?>", "\n", txt)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", txt))
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    # ★범용 본문 추출은 매체마다 그릇이 달라 자주 빈손이다. 그때는
    #   어느 매체에나 있는 og:description 을 쓴다 — 짧지만 요지는 정확하다.
    #   빈 body.txt 를 내놓고 '자료가 있다' 고 하면 안 된다.
    if len(txt.strip()) < 120:
        desc = meta("og:description")
        if desc:
            txt = desc + "\n\n(※ 본문 추출 실패 — og:description 이다. " \
                         "기사 링크를 직접 열어 사실을 확인하라.)"
    return {"url": url, "title": title, "press": meta("og:site_name") or url.split("/")[2],
            "body": re.sub(r"\n{3,}", "\n\n", txt).strip(), "images": imgs[:14]}


def article_candidates(s, title):
    """네이버 뉴스 검색에서 n.news 기사 후보를 긁는다.

    ★넓은 검색어(고유명사 하나)가 좁은 것보다 잘 찾는다 — hunt.news_queries 주석 참고."""
    qs = hunt.news_queries(title)
    if not qs:
        return [], "", []
    seen, out, press = set(), [], []
    blocked = 0
    for qq in qs:
        try:
            h = hunt.get_text(
                s, "https://search.naver.com/search.naver?where=news&query="
                + requests.utils.quote(qq), timeout=20)
        except hunt.Blocked:
            # ★차단을 삼키고 '기사 없음' 이라고 하면 안 된다 — 오진이다.
            #   실측 2026-08-21: 네이버가 403 인 동안 '새덕후' 를 기사 0건으로
            #   보고했는데, 풀린 뒤 같은 검색어로 기사 10건이 그대로 나왔다.
            blocked += 1
            time.sleep(1.0)
            continue
        except Exception:                                    # noqa: BLE001
            time.sleep(1.0)
            continue
        for oid, aid in re.findall(
                r'https?://n\.news\.naver\.com/(?:mnews/)?article/(\d{3})/(\d{10})', h):
            if (oid, aid) not in seen:
                seen.add((oid, aid))
                out.append((oid, aid))
        for u in press_links(h):
            if u not in press:
                press.append(u)
        time.sleep(0.6)
    if not out and not press and blocked:
        return [], f"네이버 검색이 막혀 있다 ({blocked}회 시도 전부 차단)", []
    return out[:10], "", press[:12]


def article_title(s, oid, aid):
    try:
        h = hunt.get_text(s, f"https://n.news.naver.com/article/{oid}/{aid}", timeout=20)
    except Exception:                                        # noqa: BLE001
        return ""
    m = re.search(r'<meta property="og:title" content="([^"]*)"', h)
    return hunt.strip_tags(m.group(1)) if m else ""


def pick_article(s, ev):
    """후보 기사를 열어 제목이 가장 많이 겹치는 것을 고른다.
    ★검색 결과 카드에서 링크와 제목을 짝지으려 하지 마라 — 네이버가 카드를
      조각내 놔서 정규식으로 안 붙는다(실측). 기사를 여는 편이 확실하다."""
    cands, err, plinks = article_candidates(s, ev["title"])
    if err:
        print(f"   ⛔ {err}")
        return None, err, None
    best = None
    for oid, aid in cands:
        t = article_title(s, oid, aid)
        if not t:
            continue
        # ★낱말 교집합으로만 재지 마라 — hunt.title_overlap 주석 참고
        ov = hunt.title_overlap(ev["title"], t)
        print(f"   {ov:.2f}  [네이버] {t[:50]}")
        if best is None or ov > best[0]:
            best = (ov, oid, aid, t)
        time.sleep(0.4)

    # 네이버에 없으면 언론사 직링크를 본다 (연예·방송 기사가 여기 있다)
    bp = None
    if not best or best[0] < 0.20:
        for u in plinks:
            d = press_meta(s, u)
            if not d:
                continue
            ov = hunt.title_overlap(ev["title"], d["title"])
            print(f"   {ov:.2f}  [{d['press'][:10]}] {d['title'][:44]}")
            if bp is None or ov > bp[0]:
                bp = (ov, d)
            time.sleep(0.5)
    return best, "", bp


def build_press_workdir(ev, d):
    """언론사 기사로 작업 폴더를 만든다. 네이버 경로(ref_econ/brief.py)와 결과가 같게."""
    eb = _load_econ_brief()
    host = re.sub(r"[^a-z0-9]", "", d["url"].split("/")[2].lower())[:14]
    wd = os.path.join(ROOT, f"work_comm_{datetime.now():%m%d}_{host}")
    os.makedirs(os.path.join(wd, "real"), exist_ok=True)

    with open(os.path.join(wd, "body.txt"), "w", encoding="utf-8") as f:
        f.write(f"{d['title']}\n\n{d['press']}\n{d['url']}\n\n{d['body']}\n")

    got = []
    for i, u in enumerate(d["images"]):
        dest = os.path.join(wd, "real", f"r{i:02d}.jpg")
        if eb.curl(u, dest, referer=d["url"]):
            got.append(dest)
    made = eb.sheet(got, os.path.join(wd, "_sheet_real.jpg")) if got else None
    print(f"\n작업 폴더 → {wd}")
    print(f"  본문 {len(d['body'])}자 · 사진 {len(got)}장")
    if made:
        print(f"  시트 → {made[0]}  ★눈으로 봐라 (규격 1184x880 미달이 섞인다)")
    else:
        print("  ⚠ 쓸 만한 사진을 못 받았다 — 생성 이미지로 가야 한다")
    return wd


def write_context(wd, ev):
    L = [f"# 커뮤 반응 — {ev['title']}", ""]
    L.append(f"- 점수 {ev['score']}  /  커뮤 {ev['n_sites']}곳  글 {ev['n_posts']}개")
    L.append(f"- 댓글 {ev['comment']}  추천 {ev['vote']}  조회 {ev['view']}")
    if ev.get("age") is not None:
        L.append(f"- 가장 오래된 글 {ev['age']:.1f}시간 전")
    if ev.get("news_n"):
        L.append(f"- 기사 {ev['news_n']}건 (겹침 {ev.get('news_ov', 0)}) — {ev.get('news_first', '')}")
    L.append("")
    L.append("## 어디서 터졌나")
    L.append("")
    for m in ev.get("members", []):
        L.append(f"- [{m['site_name']}] {m['title'][:60]}")
        L.append(f"  {m['link']}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("★대본의 사실관계는 **기사(body.txt)** 에서 가져온다.")
    L.append("  이 파일은 훅에 쓸 '어디서 얼마나 터졌나' 용이다.")
    L.append("  커뮤 글 문장을 그대로 옮기지 마라 — 미검증이고 남의 저작물이다.")
    L.append("  캡쳐를 쓸 거면 닉네임·프로필 사진·커뮤 로고를 가린다.")
    open(os.path.join(wd, "comm_context.txt"), "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", type=int, required=True, help="hunt 시트의 번호")
    ap.add_argument("--hunt", default="", help="특정 hunt_*.json 지정")
    ap.add_argument("--with-siblings", action="store_true")
    ap.add_argument("--dry", action="store_true", help="기사만 찾고 멈춘다")
    a = ap.parse_args()

    hp = latest_hunt(a.hunt)
    data = json.load(open(hp, encoding="utf-8"))
    rows = data["rows"]
    if not 1 <= a.pick <= len(rows):
        print(f"1 ~ {len(rows)} 중에서 골라라. (시트: {hp})")
        return 1
    ev = rows[a.pick - 1]
    print(f"고른 사건: {ev['title']}")
    print(f"  커뮤 {ev['n_sites']}곳 · 댓글 {ev['comment']} · 점수 {ev['score']}")

    if ev.get("news_n") == 0:
        print("\n⚠ 이 사건은 관련 기사를 못 찾았다.")
        print("  커뮤 안에서만 도는 미검증 글이다. 그대로 만들면 오보가 된다.")
        print("  기사가 나올 때까지 기다리거나 다른 번호를 골라라.")
        return 2

    s = hunt.sess()
    print("\n기사 후보 —")
    best, err, bp = pick_article(s, ev)
    if err:
        print("\n⛔ 판단 불가 — 기사가 없는 게 아니라 검색이 막혔다.")
        print("  쉬었다 다시 돌려라. 이 상태로 '기사 없음' 이라 여기지 마라.")
        return 4

    # 네이버에 없고 언론사에만 있는 경우 (연예·방송 기사가 대개 그렇다)
    if (not best or best[0] < 0.20) and bp and bp[0] >= 0.20:
        d = bp[1]
        print(f"\n고른 기사 (겹침 {bp[0]:.2f}, 언론사 직링크): {d['title']}")
        print(f"  {d['url']}")
        if a.dry:
            return 0
        wd = build_press_workdir(ev, d)
        write_context(wd, ev)
        print(f"커뮤 반응 → {os.path.join(wd, 'comm_context.txt')}")
        return 0

    if not best or best[0] < 0.20:
        print("\n⚠ 네이버 뉴스에 실린 같은 사건 기사를 못 찾았다.")
        print("  (언론사 자체 페이지에만 있는 경우다. 링크를 직접 주면 된다:)")
        print("  python ref_econ/brief.py --url <네이버 기사 링크>")
        for m in ev.get("members", [])[:5]:
            print(f"   [{m['site_name']}] {m['link']}")
        return 3

    ov, oid, aid, title = best
    url = f"https://n.news.naver.com/article/{oid}/{aid}"
    print(f"\n고른 기사 (겹침 {ov:.2f}): {title}")
    print(f"  {url}")
    if a.dry:
        return 0

    cmd = [sys.executable, os.path.join(ROOT, "ref_econ", "brief.py"), "--url", url]
    if a.with_siblings:
        cmd.append("--with-siblings")
    print(f"\n→ {' '.join(cmd[1:])}")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        return r.returncode

    # 방금 만들어진 workdir 를 찾아 커뮤 반응을 적어 둔다
    wds = sorted(glob.glob(os.path.join(ROOT, f"work_econ_*{aid[-6:]}*")),
                 key=os.path.getmtime)
    if not wds:
        wds = sorted(glob.glob(os.path.join(ROOT, "work_econ_*")),
                     key=os.path.getmtime)
    if wds:
        write_context(wds[-1], ev)
        print(f"\n커뮤 반응 → {os.path.join(wds[-1], 'comm_context.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
