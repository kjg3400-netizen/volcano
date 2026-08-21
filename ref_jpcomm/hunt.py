# -*- coding: utf-8 -*-
"""일본 커뮤형 소재 발굴기 — 커뮤 9곳 + 마토메 2곳

한국판(`ref_comm/hunt.py`)과 뼈대는 같다. 다른 것은 세 가지다.

  ① **소스가 딴판이다.** 일본엔 펨코 같은 '전 게시판 베스트'가 없다.
     대신 판이 갈래별로 흩어져 있어 **여러 곳을 나란히 긁어야** 그림이 나온다.
     - 5ch `subject.txt` — 반응(レス数)이 원문 그대로 들어 있다. HTML 이 아니라 안 깨진다
     - ガールズちゃんねる — 여초 최대. 코멘트 수가 목록에 박혀 있다
     - 発言小町 — 요미우리가 굴리는 상담판. 논쟁이 제일 세게 붙는다
     - はてなブックマーク — 북마크 수. **이미 기사라서** 교차확인이 필요 없다
     - Togetter — X(트위터) 화제 묶음. pv 가 목록에 있다
     - まとめ(ハム速·痛いニュース) — 반응 수치는 없지만 **큐레이터가 고른 것**이라
       확산 신호로만 쓴다 (한국판 디시 힛갤 자리)

  ② **절대금지 층이 하나 더 있다** (`shapes_jpc.hard`).
     일본 커뮤 상위권은 국적·정치·연예인 두들기기가 태반이다. 반응만 보고 세우면
     상위 20개가 죄다 만들면 안 되는 것으로 찬다. 빼고, 왜 뺐는지 시트에 적는다.

  ③ 뉴스 교차확인이 **Yahoo!ニュース検索** 이고, 필요한 소스에만 건다.
     はてブ·ヤフコメ·5chニュース+ 는 애초에 기사가 원본이라 물어볼 이유가 없다.

  python ref_jpcomm/hunt.py
  python ref_jpcomm/hunt.py --top 30 --show-blocked
  python ref_jpcomm/hunt.py --no-news        # 빠르게 (교차확인 끄기)
  python ref_jpcomm/hunt.py --only 生活・マナー論争

조사·실측 2026-08-21.
"""
import argparse
import concurrent.futures as cf
import glob
import html
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from math import log10
from statistics import median

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SEEN_PATH = os.path.join(HERE, "seen.json")

sys.path.insert(0, HERE)
from shapes_jpc import hard, safety, shape_of, title_fit      # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


# ── 유틸 ──────────────────────────────────────────────────────────────
def sess():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


class Blocked(Exception):
    """차단당했다. 구조 변경(⚠ 0건)과 반드시 구별해서 봐라 — 대응이 정반대다."""


BLOCK_SIGNS = ["Just a moment", "challenge-platform", "Enable JavaScript and cookies",
               "Access Denied", "Attention Required", "アクセスが制限"]


def get_text(s, url, timeout=25):
    """★일본 사이트는 인코딩이 셋이다.
    5ch `subject.txt` 는 **cp932**(Shift-JIS), 痛いニュース는 **euc-jp**,
    나머지는 utf-8. utf-8 로 못박으면 오류 없이 제목만 깨진다."""
    r = s.get(url, timeout=timeout)
    b = r.content
    if r.status_code in (403, 429, 430) or (
            len(b) < 20000 and any(x in b.decode("utf-8", "ignore") for x in BLOCK_SIGNS)):
        raise Blocked(f"HTTP {r.status_code}")
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    enc = None
    m = re.search(r"charset=([\w\-]+)", r.headers.get("Content-Type", ""), re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb"charset=[\"']?([\w\-]+)", b[:3000], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    for cand in [enc, "utf-8", "cp932", "euc-jp"]:
        if not cand:
            continue
        try:
            return b.decode(cand)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode("utf-8", "replace")


def norm_ws(h):
    """★파싱 전에 반드시 부른다. 태그 안에도 줄바꿈이 섞여 있어
    클래스 패턴이 **오류 없이 그냥 안 잡힌다** (한국판에서 크게 물린 자리)."""
    return re.sub(r"\s+", " ", h)


def strip_tags(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def num(t):
    if t is None:
        return 0
    m = re.search(r"[\d,]+", str(t))
    if not m:
        return 0
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return 0


def blocks(h, start_pat):
    idx = [m.start() for m in re.finditer(start_pat, h)]
    return [h[a:b] for a, b in zip(idx, idx[1:] + [len(h)])]


def age_jp(txt):
    """일본 커뮤의 시간 표기 — `28分前` `3時間前` `2日前` ·
    ISO(`2026-08-20T13:49:40Z` / `+09:00`) · `2026年08月20日 22:49`."""
    if not txt:
        return None
    t = txt.strip()
    m = re.search(r"(\d+)\s*分前", t)
    if m:
        return int(m.group(1)) / 60.0
    m = re.search(r"(\d+)\s*時間前", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*日前", t)
    if m:
        return int(m.group(1)) * 24.0
    m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+\-]\d{2}:\d{2})", t)
    if m:
        try:
            d = datetime.fromisoformat(m.group(0).replace("Z", "+00:00"))
            return max((datetime.now(timezone.utc) - d).total_seconds() / 3600.0, 0.0)
        except ValueError:
            return None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", t)
    if m:
        try:
            y, mo, d, h, mi = (int(x) for x in m.groups())
            # 표기가 JST 다. 이 PC 도 JST 가 아니므로 UTC 로 맞춰 잰다.
            dt = datetime(y, mo, d, h, mi, tzinfo=timezone(_JST))
            return max((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 0.0)
        except ValueError:
            return None
    return None


from datetime import timedelta                                # noqa: E402
_JST = timedelta(hours=9)


def canon(u):
    return (u or "").split("?")[0].rstrip("/")


# ── 사이트별 파서 ─────────────────────────────────────────────────────
# 각 파서는 [{title, link, vote, comment, view, age, cate}] 를 돌려준다.
# 없는 지표는 None (0 과 구별해야 사이트별 정규화가 안 망가진다).

def p_garuchan(h):
    """ガールズちゃんねる. `/rank/`(인기) 와 `/new/`(신착) 이 같은 구조다."""
    out = []
    for r in blocks(h, r'<li class="flc">'):
        a = re.search(r'<a href="(/topics/\d+/)"', r)
        t = re.search(r'<p class="title">(.*?)</p>', r, re.S)
        if not a or not t:
            continue
        cm = re.search(r"<span>([\d,]+)コメント</span>", r)
        dt = re.search(r'<span class="datetime">(.*?)</span>', r, re.S)
        out.append(dict(title=strip_tags(t.group(1)),
                        link="https://girlschannel.net" + a.group(1),
                        vote=None, comment=num(cm.group(1)) if cm else 0,
                        view=None,
                        age=age_jp(strip_tags(dt.group(1)) if dt else ""),
                        cate=""))
    return out


def p_komachi(h):
    """発言小町. レス数가 `c-iconRes` 에, 갈래가 `GenreShortName` 에 있다."""
    out = []
    for r in blocks(h, r'<div class="p-topiList__item"'):
        a = re.search(r'<a href="(/topics/id/\d+/)"', r)
        t = re.search(r'itemContentTitle"[^>]*>(.*?)</div>', r, re.S)
        if not a or not t:
            continue
        res = re.search(r'c-iconRes"[^>]*>\s*([\d,]+)', r)
        tm = re.search(r'<time[^>]*datetime="([^"]+)"', r)
        g = re.search(r'GenreShortName"[^>]*>(.*?)</span>', r, re.S)
        out.append(dict(title=strip_tags(t.group(1)),
                        link="https://komachi.yomiuri.co.jp" + a.group(1),
                        vote=None, comment=num(res.group(1)) if res else 0,
                        view=None, age=age_jp(tm.group(1) if tm else ""),
                        cate=strip_tags(g.group(1)) if g else ""))
    return out


# ★5ch subject.txt 는 HTML 이 아니라 한 줄 한 스레다.
#     1787237849.dat<>【速報】…… ★2 [ぐれ★] (597)
#   `(597)` 가 レス数, 앞의 숫자가 스레 id 이면서 **작성 unix 시각**이다.
#   `★2` 는 続きスレ — 1편이 1000레스를 채워 넘어온 것이니 실제 반응은
#   `(seq-1)*1000 + レス数` 다. 이걸 안 세면 제일 터진 스레가 밀린다.
RE_5CH = re.compile(r"^(\d{9,11})\.dat<>(.*)\((\d{1,5})\)\s*$")
RE_SEQ = re.compile(r"★\s*(\d{1,3})\s*$")


def p_5ch(txt, url=""):
    """★링크를 만들어 줘야 한다. subject.txt 에는 dat 번호밖에 없어서
    그대로 두면 시트에서 눌러지지 않는다.
      https://asahi.5ch.net/newsplus/subject.txt
        → https://asahi.5ch.net/test/read.cgi/newsplus/<dat>/"""
    m = re.match(r"(https?://[^/]+)/([^/]+)/subject\.txt", url or "")
    base = f"{m.group(1)}/test/read.cgi/{m.group(2)}/" if m else ""
    out = []
    now = time.time()
    for line in txt.splitlines():
        m = RE_5CH.match(line.strip())
        if not m:
            continue
        tid, title, res = m.group(1), m.group(2).strip(), int(m.group(3))
        # 스레 세운 사람 이름표 `[ぐれ★]` 를 뗀다 (제목이 아니다)
        title = re.sub(r"\s*\[[^\]]{1,20}★?\]\s*$", "", title).strip()
        seq = RE_SEQ.search(title)
        n = int(seq.group(1)) if seq else 1
        if seq:
            title = title[:seq.start()].strip()
        cate = ""
        c = re.match(r"【([^】]{1,10})】", title)
        if c:
            cate = c.group(1)
        total = (min(n, 60) - 1) * 1000 + res
        age = max((now - int(tid)) / 3600.0, 0.0)
        out.append(dict(title=html.unescape(title),
                        link=(base + tid + "/") if base else f"5ch#{tid}",
                        vote=None, comment=total,
                        view=None, age=age, cate=cate, seq=n))
    return out


def p_hatena(h):
    """はてなブックマーク. link 가 **기사 URL 그대로**라 교차확인이 필요 없다."""
    out = []
    for r in blocks(h, r'<div class="entrylist-contents">'):
        a = re.search(r'entrylist-contents-title"> <a href="([^"]+)" title="([^"]*)"', r)
        if not a:
            continue
        us = re.search(r'entrylist-contents-users"> <a[^>]*><span>([\d,]+)</span>', r)
        ct = re.search(r'data-entry-category="([^"]*)"', r)
        dt = re.search(r'entrylist-contents-date"[^>]*>(.*?)</', r, re.S)
        out.append(dict(title=html.unescape(a.group(2)).strip(), link=a.group(1),
                        vote=num(us.group(1)) if us else 0,
                        comment=None, view=None,
                        age=age_jp(strip_tags(dt.group(1)) if dt else ""),
                        cate=ct.group(1) if ct else "", news_ok=True))
    return out


def p_togetter(h):
    # ★행 클래스가 두 가지다 — `<li class=" clearfix">` 와
    #   `<li class=" has_thumb clearfix">`. 앞의 것만 잡으면 **25건 중 10건**만 온다.
    out = []
    for r in blocks(h, r'<li class="[^"]*clearfix"'):
        a = re.search(r'<a href="(https://togetter\.com/li/\d+)" title="([^"]*)"', r)
        if not a:
            continue
        pv = re.search(r'view_str"><span>([\d,]+)</span>pv', r)
        fav = re.search(r'count_favorite">.*?</svg>([\d,]+)</span>', r, re.S)
        hb = re.search(r'http-bookmark">([\d,]+) users', r)
        tm = re.search(r'<time[^>]*datetime="([^"]+)"', r)
        out.append(dict(title=html.unescape(a.group(2)).strip(), link=a.group(1),
                        vote=(num(fav.group(1)) if fav else 0) + (num(hb.group(1)) if hb else 0),
                        comment=None,
                        view=num(pv.group(1)) if pv else None,
                        age=age_jp(tm.group(1) if tm else ""), cate=""))
    return out


def p_yahoo(h):
    """ヤフコメランキング. React SSR 이라 클래스가 해시라 못 믿는다 —
    ★위치로 집지 말고 **모양**으로 가른다 (경제 헌터와 같은 수법):
      제목은 텍스트 조각 중 가장 긴 것.

    ★행 경계로 `newsFeed_item` 을 쓰면 안 된다. 이 페이지에 있는 건
      `newsFeed_item_body` 뿐이고 그건 **기사 링크보다 뒤에** 온다 —
      0건이 나온다(실측). 목록은 `<ol class="newsFeed_list">` 안의
      `<li data-ual-view-type="list">` 다."""
    body = h.split('class="newsFeed_list"')
    h = body[1] if len(body) > 1 else h
    out = []
    for r in blocks(h, r'<li data-ual'):
        m = re.search(r"/articles/([0-9a-f]{40})", r)
        if not m:
            continue
        texts = [x for x in (strip_tags(y) for y in
                             re.findall(r">([^<>]{2,120})</", r[:4000])) if x]
        cands = [t for t in texts if not t.isdigit()
                 and not re.match(r"^\d{1,2}:\d{2}$", t)]
        if not cands:
            continue
        cands.sort(key=len, reverse=True)
        title = cands[0]
        tm = re.search(r"<time[^>]*>(.*?)</time>", r, re.S)
        out.append(dict(title=title,
                        link=f"https://news.yahoo.co.jp/articles/{m.group(1)}",
                        vote=None, comment=None, view=None,
                        age=_yahoo_age(strip_tags(tm.group(1)) if tm else ""),
                        cate="", aid=m.group(1), news_ok=True))
    return out


def _yahoo_age(t):
    m = re.search(r"(\d{1,2})/(\d{1,2})\([月火水木金土日]\)\s*(\d{1,2}):(\d{2})", t or "")
    if not m:
        return age_jp(t)
    mo, d, h, mi = (int(x) for x in m.groups())
    now = datetime.now(timezone(_JST))
    try:
        dt = datetime(now.year, mo, d, h, mi, tzinfo=timezone(_JST))
    except ValueError:
        return None
    if dt > now + timedelta(hours=6):
        dt = dt.replace(year=now.year - 1)
    return max((now - dt).total_seconds() / 3600.0, 0.0)


def p_livedoor(h):
    """まとめ (ハムスター速報·痛いニュース). ★반응 수치가 목록에 없다.
    그래서 이 둘은 **점수를 만들지 않고 확산 신호로만** 쓴다 (아래 MATOME_FLOOR).

    행 경계를 `dc:identifier=` 로 잡는다 — RDF 주석이 글마다 앞에 붙고
    거기에 URL·시각·갈래가 다 들어 있다."""
    out = []
    for r in blocks(h, r'dc:identifier="'):
        u = re.search(r'dc:identifier="([^"]+)"', r)
        t = re.search(r'class="[^"]*entry-title"><a href="[^"]*"[^>]*>(.*?)</a>', r, re.S)
        if not u or not t:
            continue
        d = re.search(r'dc:date="([^"]+)"', r)
        g = re.search(r'dc:subject="([^"]*)"', r)
        title = strip_tags(t.group(1))
        if not title:
            continue
        out.append(dict(title=title, link=u.group(1), vote=None, comment=None,
                        view=None, age=age_jp(d.group(1) if d else ""),
                        cate=g.group(1) if g else ""))
    return out


# ── 소스 ──────────────────────────────────────────────────────────────
# 결: 여 여초 · 남 남초 · 지 지식층 · 잡 잡다(X) · 뉴 뉴스반응 · 마 마토메
# news: 이 소스 글은 뉴스 교차확인이 필요한가 (はてブ·ヤフコメ는 원본이 기사다)
SITES = [
    ("garu_rank", "ガルちゃん人気", "여", "https://girlschannel.net/", p_garuchan, True),
    ("garu_new", "ガルちゃん新着", "여", "https://girlschannel.net/new/", p_garuchan, True),
    ("komachi", "発言小町 日", "여", "https://komachi.yomiuri.co.jp/ranking/", p_komachi, True),
    ("komachi_w", "発言小町 週", "여", "https://komachi.yomiuri.co.jp/topics/ranking/weekly/", p_komachi, True),
    ("newsplus", "5chニュー速+", "남", "https://asahi.5ch.net/newsplus/subject.txt", p_5ch, False),
    ("mnewsplus", "5ch芸スポ+", "남", "https://hayabusa9.5ch.net/mnewsplus/subject.txt", p_5ch, False),
    ("poverty", "5ch嫌儲", "남", "https://greta.5ch.net/poverty/subject.txt", p_5ch, True),
    ("hatena", "はてブ総合", "지", "https://b.hatena.ne.jp/hotentry", p_hatena, False),
    ("hatena_life", "はてブ暮らし", "지", "https://b.hatena.ne.jp/hotentry/life", p_hatena, False),
    ("hatena_know", "はてブ学び", "지", "https://b.hatena.ne.jp/hotentry/knowledge", p_hatena, False),
    ("togetter", "Togetter注目", "잡", "https://togetter.com/hot", p_togetter, True),
    ("togetter_t", "Togetterトップ", "잡", "https://togetter.com/", p_togetter, True),
    ("yahoo_com", "ヤフコメ総合", "뉴", "https://news.yahoo.co.jp/ranking/comment", p_yahoo, False),
    ("yahoo_dom", "ヤフコメ国内", "뉴", "https://news.yahoo.co.jp/ranking/comment/domestic", p_yahoo, False),
    ("yahoo_life", "ヤフコメ生活", "뉴", "https://news.yahoo.co.jp/ranking/comment/life", p_yahoo, False),
    ("hamusoku", "ハム速", "마", "https://hamusoku.com/", p_livedoor, True),
    ("itainews", "痛いニュース", "마", "https://itainews.com/", p_livedoor, True),
]
SITE_NAME = {k: n for k, n, _kd, _u, _p, _nw in SITES}
SITE_KIND = {k: kd for k, _n, kd, _u, _p, _nw in SITES}
SITE_NEWS = {k: nw for k, _n, _kd, _u, _p, nw in SITES}
MATOME = {"hamusoku", "itainews"}

# ★★확산을 '사이트 수'로 세면 안 된다 — 5ch 세 판과 마토메 두 곳은
#   **서로 다른 커뮤가 아니라 한 커뮤**다. 마토메는 5ch 를 베껴 오고,
#   ニュー速+·嫌儲·芸スポ+ 는 같은 사람들이 판만 옮겨 세운다.
#   그대로 세면 5ch 화제 하나가 '5개 커뮤 동시 확산'으로 둔갑해
#   小町·ガルちゃん 의 진짜 원본 논쟁을 전부 눌러 버린다(실측 2026-08-21).
#   그래서 확산은 **계열(family) 수**로 센다.
SITE_FAMILY = {
    "newsplus": "5ch", "mnewsplus": "5ch", "poverty": "5ch",
    "hamusoku": "5ch", "itainews": "5ch",
    "garu_rank": "garu", "garu_new": "garu",
    "komachi": "komachi", "komachi_w": "komachi",
    "hatena": "hatena", "hatena_life": "hatena", "hatena_know": "hatena",
    "togetter": "togetter", "togetter_t": "togetter",
    "yahoo_com": "yahoo", "yahoo_dom": "yahoo", "yahoo_life": "yahoo",
}
# ★마토메는 반응 수치가 없다. 0 을 주면 사라지고, 크게 주면 근거 없이 이긴다.
#   **혼자 뜨면 못 이기고, 다른 커뮤와 겹치면 확산으로 이기는** 값을 준다.
MATOME_FLOOR = 0.55

NOTICE = ["お知らせ", "運営", "メンテナンス", "利用規約", "アンケートにご協力",
          "プレゼント", "キャンペーン", "募集", "ガイドライン", "PR）"]


def is_notice(t):
    return any(w in t for w in NOTICE)


def collect(site, s):
    key, name, kind, url, parser, _nw = site
    t0 = time.time()
    try:
        raw = get_text(s, url)
        # ★5ch 는 HTML 이 아니라 한 줄 한 스레라 공백을 뭉개면 안 된다.
        rows = (p_5ch(raw, url) if parser is p_5ch else parser(norm_ws(raw))) or []
    except Blocked as e:
        return key, [], f"⛔ 차단 ({e}) — 파서 건드리지 말고 쉬었다 다시"
    except Exception as e:                                    # noqa: BLE001
        return key, [], f"실패: {type(e).__name__} {e}"
    for r in rows:
        r["site"] = key
        r["site_name"] = name
        r["kind"] = kind
        r["link"] = canon(r.get("link", ""))
    ok = [r for r in rows if r.get("title") and len(r["title"]) >= 4
          and not is_notice(r["title"])]
    note = f"{len(ok)}건 / {time.time() - t0:.1f}초"
    if not ok:
        note = "⚠ 0건 — 페이지 구조가 바뀌었을 수 있다 (차단과 구별해서 봐라)"
    return key, ok, note


def gather():
    s = sess()
    res, notes = [], {}
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(collect, site, s): site[0] for site in SITES}
        for f in cf.as_completed(futs):
            key, rows, note = f.result()
            notes[key] = note
            res.extend(rows)
    return res, notes


# ── 누적 ──────────────────────────────────────────────────────────────
def save_raw(rows, stamp):
    keep = ["site", "site_name", "kind", "title", "link", "vote", "comment",
            "view", "age", "cate"]
    json.dump([{k: r.get(k) for k in keep} for r in rows],
              open(os.path.join(OUT, f"raw_{stamp}.json"), "w", encoding="utf-8"),
              ensure_ascii=False)


def load_accum(rows, hours):
    if hours <= 0:
        return rows, 0
    cut = time.time() - hours * 3600
    by = {r["link"]: r for r in rows}
    added = 0
    for p in sorted(glob.glob(os.path.join(OUT, "raw_*.json"))):
        try:
            if os.path.getmtime(p) < cut:
                continue
            old = json.load(open(p, encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            continue
        for r in old:
            if not r.get("link") or not r.get("title"):
                continue
            cur = by.get(r["link"])
            if cur is None:
                by[r["link"]] = r
                added += 1
            elif (r.get("comment") or 0) > (cur.get("comment") or 0):
                by[r["link"]] = r
    return list(by.values()), added


# ── 사이트별 눈금 맞추기 ──────────────────────────────────────────────
def normalize(rows):
    """★5ch 레스 1002 · 小町 レス 252 · はてブ 456 · Togetter pv 24741 —
    절대값을 섞어 세우면 Togetter 가 목록을 독식한다.
    그 사이트 이번 수집분의 **중앙값 대비 몇 배**로 환산한다."""
    by = {}
    for r in rows:
        by.setdefault(r["site"], []).append(r)
    for site, rs in by.items():
        if site in MATOME:
            for r in rs:
                r["_hot"] = MATOME_FLOOR
            continue
        med = {}
        for k in ("vote", "comment", "view"):
            vals = [r[k] for r in rs if r.get(k)]
            med[k] = median(vals) if vals else 0
        for r in rs:
            parts, w = 0.0, 0.0
            for k, wt in (("comment", 1.0), ("vote", 0.7), ("view", 0.45)):
                if r.get(k) is not None and med[k]:
                    parts += wt * (r[k] / med[k])
                    w += wt
            r["_hot"] = parts / w if w else 0.0
    return rows


# ── 사건 묶기 ─────────────────────────────────────────────────────────
STRIP = re.compile(r"[\[\]（）()「」『』【】\"'…、。・,.\-—~!?%\s★☆→]+")


def bigrams(t):
    t = STRIP.sub("", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def title_sim(a, b):
    """★분모가 `min(len)` 이라 **짧은 제목이 긴 제목에 흡수된다.**
    실측 2026-08-21: 「こんなテレビ番組が見たい(要望)」가
    「こんなところになぜ食パン…投棄」에 붙었고(`こん·んな·な…`),
    「三山凌輝はなぜモテるのか？」가 「なぜSAPIX→…東大」에 붙었다.
    엉뚱한 글이 딸려 들어오면 확산 점수가 근거 없이 오른다.

    한국어보다 겹침 하한을 높게 잡는다 — 일본어는 조사·활용이 한 글자라
    글자쌍이 우연히 겹치기 쉽다."""
    if not a or not b:
        return 0.0
    ov = len(a & b)
    if ov < 7 or min(len(a), len(b)) < 8:
        return 0.0
    return ov / min(len(a), len(b))


def group_events(items, th=0.30):
    order = sorted(items, key=lambda x: -x.get("_hot", 0))
    groups = []
    for it in order:
        bg = bigrams(it["title"])
        for g in groups:
            if title_sim(bg, g["bg"]) >= th:
                g["mem"].append(it)
                break
        else:
            groups.append({"bg": bg, "mem": [it]})
    out = []
    for gg in groups:
        g = gg["mem"]
        rep = dict(g[0])
        sites = []
        for x in g:
            if x["site"] not in sites:
                sites.append(x["site"])
        rep["sites"] = sites
        rep["n_sites"] = len(sites)
        # ★확산은 계열 수로 센다 (SITE_FAMILY 주석을 봐라)
        fams = sorted({SITE_FAMILY.get(x, x) for x in sites})
        rep["fams"] = fams
        rep["n_fams"] = len(fams)
        rep["n_posts"] = len(g)
        rep["hot"] = sum(x.get("_hot", 0) for x in g)
        rep["comment"] = sum(x.get("comment") or 0 for x in g)
        rep["vote"] = sum(x.get("vote") or 0 for x in g)
        rep["view"] = sum(x.get("view") or 0 for x in g)
        ages = [x["age"] for x in g if x.get("age") is not None]
        rep["age"] = min(ages) if ages else None
        rep["news_ok"] = any(x.get("news_ok") for x in g)
        rep["members"] = [{"site_name": x["site_name"], "title": x["title"],
                           "link": x["link"]} for x in g[:8]]
        out.append(rep)
    return out


# ── 점수 ──────────────────────────────────────────────────────────────
def score_item(it):
    hot = it.get("hot", 0.0)
    hrs = max(it.get("age") if it.get("age") is not None else 6.0, 0.6)

    heat = 46 * log10(1 + hot)
    # 계열 수로 센다. 같은 계열 안에서 판만 갈아탄 것은 `n_posts` 로 조금만 준다.
    spread = 48 * log10(it.get("n_fams", 1)) + 10 * log10(it.get("n_posts", 1))
    vel = 22 * log10(1 + hot / hrs)
    kinds = {SITE_KIND.get(s, "") for s in it.get("sites", [])}
    cross = 14 * max(len(kinds) - 1, 0)

    fit, hitw = title_fit(it["title"])
    saf, why = safety(it["title"])
    hz, hw = hard(it["title"])

    base = heat + spread + vel + cross
    it["fit"] = round(fit, 2)
    it["fit_hit"] = hitw
    it["safety"] = round(saf, 2)
    it["safety_why"] = why
    it["hard"] = hz
    it["hard_word"] = hw
    it["shape"] = shape_of(it["title"])
    it["base_score"] = round(base, 1)
    # ★알맹이를 한국판(0.40)보다 세게 건다. 일본 커뮤 상위권은 사고·사건 스레가
    #   레스 수로 밀고 올라오는데, 반응만 크고 30초 안에 뒤집을 알맹이가 없다.
    # 대전제는 경제판과 같게 ±55%.
    it["score"] = round(base * (1 + 0.55 * fit) * (1 + 0.55 * saf), 1)
    it["parts"] = {"heat": round(heat, 1), "spread": round(spread, 1),
                   "vel": round(vel, 1), "cross": round(cross, 1)}
    return it


# ── 뉴스 교차확인 (Yahoo!ニュース検索) ────────────────────────────────
# ★일본어는 띄어쓰기가 없어 한국판의 낱말 자르기를 그대로 못 쓴다.
#   대신 **한자 덩어리 · 가타카나 덩어리 · 「」 인용** 을 고유명사로 본다.
KANJI = re.compile(r"[一-龥々]{2,6}")
KATA = re.compile(r"[ァ-ヴー]{3,8}")
ALNUM = re.compile(r"[A-Za-z][A-Za-z0-9]{2,9}")
QUOTED = re.compile(r"[「『【]([^」』】]{2,12})[」』】]")
# 아무 기사에나 걸려 사건을 못 가리는 한자말
GENERIC = {"日本", "女性", "男性", "会社", "仕事", "自分", "相手", "問題",
           "結果", "理由", "場合", "今回", "発表", "報道", "話題", "状況",
           "世界", "人生", "生活", "時間", "気持", "本当", "最近", "必要",
           "可能", "以上", "以下", "全国", "現在", "一部", "関係", "内容"}


def keywords(title):
    """사건을 가려내는 특징 낱말. 인용 → 긴 한자말 → 가타카나 → 영숫자 순."""
    t = title or ""
    out = []
    for m in QUOTED.findall(t):
        if len(m) >= 3:
            out.append(m)
    kj = [w for w in KANJI.findall(t) if w not in GENERIC and len(w) >= 3]
    kj.sort(key=len, reverse=True)
    out += kj
    out += [w for w in KATA.findall(t)]
    out += [w for w in ALNUM.findall(t)]
    if not out:
        out = [w for w in KANJI.findall(t) if w not in GENERIC]
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq[:4]


def news_queries(title):
    ks = keywords(title)
    if not ks:
        return []
    q = []
    if len(ks) >= 2:
        q.append(ks[0] + " " + ks[1])
    q.append(ks[0])
    return [x for x in q if len(x) >= 2]


def title_overlap(a, b):
    """같은 사건을 가리키나. 0~1. 글자쌍 포함도와 고유명사 적중 중 큰 쪽."""
    bg = title_sim(bigrams(a), bigrams(b))
    key = 0.0
    for w in keywords(a):
        if len(w) >= 3 and w in b:
            key = max(key, min(0.35 + 0.08 * (len(w) - 3), 0.65))
    return round(max(bg, key), 2)


def news_check(s, title):
    """★커뮤 글은 검증된 보도가 아니다. 같은 사건 기사가 실제로 있는지 본다.
    돌려주는 것은 (건수, 가장 가까운 기사 제목, 겹침).
    ★건수만 보면 속는다 — 겹침이 실제 관련도다."""
    for q in news_queries(title):
        url = "https://news.yahoo.co.jp/search?p=" + requests.utils.quote(q)
        try:
            h = norm_ws(get_text(s, url, timeout=20))
        except Blocked:
            return -1, "", 0.0
        except Exception:                                     # noqa: BLE001
            time.sleep(1.0)
            continue
        # ★검색결과 제목은 검색어가 <em> 로 쪼개져 있다.
        #   그대로 텍스트 조각을 뽑으면 `東武鉄道` `４人` `死亡事故` 로 흩어져
        #   **겹침이 전부 0.00 으로 나온다**(실측 2026-08-21). 먼저 <em> 을 지운다.
        h = re.sub(r"</?em[^>]*>", "", h)
        # ★한 기사에 앵커가 둘이다(썸네일 + 제목). `_cl_link:title` 로 행을 자르면
        #   썸네일 쪽 토막이 제목 없이 잡혀 건수만 두 배로 부푼다(39건·40건).
        #   기사 id 로 묶고 그 id 에서 나온 **가장 긴 텍스트**를 제목으로 본다.
        byid = {}
        for r in blocks(h, r"/articles/[0-9a-f]{40}"):
            m = re.match(r"/articles/([0-9a-f]{40})", r)
            if not m:
                continue
            texts = [strip_tags(x) for x in re.findall(r">([^<>]{8,140})</", r[:3500])]
            texts = [t for t in texts if t and not re.match(
                r"^\d{1,2}/\d{1,2}\([月火水木金土日]\)", t)]
            if not texts:
                continue
            best = max(texts, key=len)
            if len(best) > len(byid.get(m.group(1), "")):
                byid[m.group(1)] = best
        titles = [v for v in byid.values() if len(v) >= 8]
        if titles:
            best, bt = 0.0, titles[0]
            for x in titles[:20]:
                ov = title_overlap(title, x)
                if ov > best:
                    best, bt = ov, x
            return len(titles), bt[:60], round(best, 2)
        time.sleep(0.8)
    return 0, "", 0.0


# ── 중복 ──────────────────────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            return json.load(open(SEEN_PATH, encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            pass
    return {"titles": []}


def is_seen(it, seen):
    a = bigrams(it["title"])
    for old in seen.get("titles", []):
        if title_sim(a, bigrams(old)) >= 0.45:
            return True
    return False


# ── 출력 ──────────────────────────────────────────────────────────────
def write_sheet(rows, blocked, path, meta):
    L = [f"# 일본 커뮤형 소재 후보 — {meta['stamp']}", "",
         f"수집 {meta['n_raw']}건 → 사건 {meta['n_ev']}묶음 → "
         f"절대금지 {meta['n_hard']}건 제외 → 상위 {len(rows)}", "",
         "## 커뮤별 수집", "", "| 커뮤 | 결 | 결과 |", "|---|---|---|"]
    for k, n, kd, _u, _p, _nw in SITES:
        L.append(f"| {n} | {kd} | {meta['notes'].get(k, '-')} |")
    L += ["", "`⛔ 차단` 과 `⚠ 0건`(구조 변경)은 **대응이 정반대다** — "
          "차단이면 손대지 말고 쉬고, 0건이면 파서를 고친다.", ""]
    if meta.get("news_on"):
        L += ["`기사` 열 — Yahoo!ニュース検索 건수와 **제목 겹침**. "
              "겹침이 실제 관련도다.", "",
              "- `❌0` — 기사가 없다. 커뮤 안에서만 도는 미검증 글이니 그대로 만들지 마라",
              "- `원본기사` — はてブ·ヤフコメ·5chニュース+ 는 애초에 기사가 원본이라 안 물었다", ""]
    L += ["| # | 점수 | 꼴 | 커뮤 | 제목 | 반응 | 경과 | 알맹이 | 안전 | 기사 |",
          "|---:|---:|:--|:--|:--|---:|---:|---:|---:|:--|"]
    for i, r in enumerate(rows, 1):
        sn = "·".join(SITE_NAME.get(x, x) for x in r["sites"][:3])
        if r["n_sites"] > 3:
            sn += f"+{r['n_sites'] - 3}"
        sn += f" ({r.get('n_fams', 1)}계열)"
        age = f"{r['age']:.0f}h" if r.get("age") is not None else "-"
        t = r["title"].replace("|", "/")[:44]
        react = max(r.get("comment", 0), r.get("vote", 0), r.get("view", 0) // 20)
        if r.get("news_ok"):
            news = "원본기사"
        else:
            nc = r.get("news_n")
            news = ("-" if nc is None else "확인불가" if nc < 0 else
                    "❌0" if nc == 0 else f"{nc}/{r.get('news_ov', 0):.2f}")
        L.append(f"| {i} | **{r['score']}** | {r['shape']} | {sn} | "
                 f"[{t}]({r['link']}) | {react} | {age} | {r['fit']} | "
                 f"{r['safety']:+.2f} | {news} |")
    L += ["", "## 상세", ""]
    for i, r in enumerate(rows, 1):
        L.append(f"### {i}. {r['title']}")
        L.append("")
        L.append(f"- 점수 **{r['score']}** = 기본 {r['base_score']} × "
                 f"알맹이 {r['fit']:+.2f} × 안전 {r['safety']:+.2f}  {r['parts']}")
        L.append(f"- 꼴 `{r['shape']}` · 안전 사유: {', '.join(r['safety_why']) or '중립'}")
        L.append(f"- 알맹이 근거: {r['fit_hit']}")
        if r.get("news_first"):
            L.append(f"- 기사 {r['news_n']}건 (겹침 {r.get('news_ov', 0)}) — {r['news_first']}")
        elif r.get("news_ok"):
            L.append("- 원본이 기사다 (はてブ·ヤフコメ·5chニュース+)")
        elif r.get("news_n") == 0:
            L.append("- ❌ 관련 기사를 못 찾았다 — **미검증 커뮤 글이다**")
        for m in r["members"]:
            L.append(f"- [{m['site_name']}] [{m['title'][:56]}]({m['link']})")
        L.append("")
    if blocked:
        L += ["---", "", "## ★만들지 마라 — 절대금지로 뺀 것", "",
              "**반응은 여기가 제일 크다.** 그래서 반드시 읽어야 한다 — "
              "반응만 보고 고르면 이쪽으로 끌려간다.", "",
              "| 사유 | 걸린 낱말 | 반응 | 제목 |", "|:--|:--|---:|:--|"]
        for r in blocked[:20]:
            react = max(r.get("comment", 0), r.get("vote", 0), r.get("view", 0) // 20)
            L.append(f"| {r['hard']} | `{r['hard_word']}` | {react} | "
                     f"{r['title'].replace('|', '/')[:50]} |")
    open(path, "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--group-th", type=float, default=0.30)
    ap.add_argument("--min-fit", type=float, default=-0.20,
                    help="알맹이가 이 밑이면 버린다. 일본 커뮤 인기글의 태반이 "
                         "실황·잡담·짤이라 이걸 안 걸면 상위가 그걸로 찬다")
    ap.add_argument("--min-safety", type=float, default=-0.50)
    ap.add_argument("--only", default="", help="이 꼴만 본다")
    ap.add_argument("--accum-hours", type=float, default=24.0)
    ap.add_argument("--news", action="store_true", default=True)
    ap.add_argument("--no-news", dest="news", action="store_false")
    ap.add_argument("--news-n", type=int, default=45)
    ap.add_argument("--show-blocked", action="store_true")
    ap.add_argument("--no-seen", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    t0 = time.time()
    raw, notes = gather()
    print(f"수집 {len(raw)}건 / {time.time() - t0:.1f}초")
    for k, n, _kd, _u, _p, _nw in SITES:
        print(f"  {n:<16} {notes.get(k, '-')}")
    if not raw:
        print("아무것도 못 긁었다. 네트워크나 차단을 확인하라.")
        return 1

    save_raw(raw, stamp)
    raw, added = load_accum(raw, a.accum_hours)
    if added:
        print(f"지난 {a.accum_hours:.0f}시간치 누적 → {len(raw)}건 (+{added})")

    normalize(raw)
    events = group_events(raw, th=a.group_th)
    for e in events:
        score_item(e)

    hardlist = sorted([e for e in events if e["hard"]], key=lambda x: -x["base_score"])
    events = [e for e in events if not e["hard"]]
    print(f"절대금지로 뺀 것 {len(hardlist)}건 "
          f"({', '.join(sorted({x['hard'] for x in hardlist}))})")

    tally = {}
    for e in events:
        tally[e["shape"]] = tally.get(e["shape"], 0) + 1
    print("꼴 — " + "  ".join(f"{k} {v}" for k, v in
                              sorted(tally.items(), key=lambda kv: -kv[1])))

    only = {x.strip() for x in a.only.split(",") if x.strip()}
    seen = {"titles": []} if a.no_seen else load_seen()
    events = [e for e in events
              if e["fit"] >= a.min_fit and e["safety"] >= a.min_safety
              and (not only or e["shape"] in only)
              and not is_seen(e, seen)]
    events.sort(key=lambda x: -x["score"])
    print(f"알맹이·안전 문턱 통과 {len(events)}묶음")

    if a.news and events:
        s = sess()
        cand = [e for e in events[:a.news_n] if not e.get("news_ok")]
        print(f"뉴스 교차확인 {len(cand)}건 …")
        with cf.ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(news_check, s, r["title"]): r for r in cand}
            for f in cf.as_completed(futs):
                r = futs[f]
                try:
                    r["news_n"], r["news_first"], r["news_ov"] = f.result()
                except Exception:                             # noqa: BLE001
                    r["news_n"], r["news_first"], r["news_ov"] = -1, "", 0.0
        for r in events:
            if r.get("news_ok") or r.get("news_n") is None:
                continue
            # ★건수가 아니라 겹침으로 판정한다.
            if r["news_n"] <= 0 or r.get("news_ov", 0) < 0.20:
                r["score"] = round(r["score"] * 0.60, 1)
            else:
                r["score"] = round(r["score"] * (1 + 0.45 * min(r["news_ov"] * 1.6, 1.0)), 1)
        events.sort(key=lambda x: -x["score"])

    rows = events[:a.top]
    meta = {"stamp": datetime.now().strftime("%Y-%m-%d %H:%M"), "n_raw": len(raw),
            "n_ev": len(events) + len(hardlist), "n_hard": len(hardlist),
            "notes": notes, "news_on": a.news}
    md = os.path.join(OUT, f"hunt_{stamp}.md")
    write_sheet(rows, hardlist, md, meta)
    write_sheet(rows, hardlist, os.path.join(OUT, "_최신시트.md"), meta)
    json.dump({"meta": meta, "rows": rows},
              open(os.path.join(OUT, "_최신시트.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("\n" + "=" * 100)
    for i, r in enumerate(rows[:16], 1):
        sn = "·".join(SITE_NAME.get(x, x) for x in r["sites"][:2])
        nc = r.get("news_n")
        tag = ("[원본기사]" if r.get("news_ok") else "" if nc is None
               else "[기사없음]" if nc <= 0 else f"[기사{nc}·{r.get('news_ov', 0):.2f}]")
        print(f"{i:>2}. {r['score']:>6}  {r['shape']:<16} 안전{r['safety']:>+5.2f} "
              f"{sn:<22} {r['title'][:34]} {tag}")
    if a.show_blocked and hardlist:
        print("\n--- 절대금지로 뺀 것 (반응은 여기가 제일 크다) ---")
        for r in hardlist[:10]:
            print(f"    [{r['hard']:<12}] {r['title'][:44]}")
    print("=" * 100)
    print(f"\n시트 → {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
