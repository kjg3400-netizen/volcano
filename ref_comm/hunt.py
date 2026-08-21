# -*- coding: utf-8 -*-
"""커뮤형 뇌전구 — 소재 발굴

국내 커뮤니티 10곳의 실시간 인기글을 긁어 '진짜 이슈몰이 될 것'만 세운다.

경제 헌터(ref_econ/hunt.py)와 뼈대는 같지만 세 가지가 다르다.

  ① 반응 실측이 공짜다.
     네이버는 댓글수가 JS 로 채워져 기사마다 API 를 따로 불러 75초가 들었다.
     커뮤니티는 추천·댓글·조회가 **목록 HTML 에 이미 다 들어 있다**. 한 번만 긁으면 된다.

  ② 대신 사이트마다 눈금이 딴판이다.
     디시 추천 890 · 클리앙 추천 1 · 더쿠 댓글 651 — 절대값을 섞어 세우면
     디시 글만 상위를 도배한다. **사이트 안에서 중앙값 대비 몇 배인가**로 환산한다.

  ③ 최고의 신호는 '교차 커뮤 확산'이다.
     경제의 '몇 개 매체가 받아썼나'에 대응하는데 훨씬 세다.
     더쿠·펨코·디시에 동시에 떠 있으면 그건 진짜 터진 사건이다.

★그리고 커뮤니티 글은 검증된 보도가 아니다.
  네이버 기사는 매체가 책임을 지지만 커뮤 글은 개인 주장이다. 그대로 만들면
  오보가 되고 채널이 다친다. 그래서 상위 후보는 **네이버 뉴스에 같은 사건 기사가
  있는지 교차확인**해서 시트의 `기사` 열에 찍는다. 기사가 없는 소재는 만들지 마라.

조사·실측 2026-08-20.
"""
import argparse
import concurrent.futures as cf
import glob
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from math import log10
from statistics import median

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
# 중복목록은 경제 헌터와 같은 것을 쓴다 — 같은 채널의 납품 이력이라 나눌 이유가 없다
SEEN_PATH = os.path.join(HERE, "..", "ref_econ", "seen.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


# ── 유틸 ──────────────────────────────────────────────────────────────
def sess():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


class Blocked(Exception):
    """차단당했다. 구조 변경과 구별해야 한다."""


# 차단 페이지는 200 으로 오기도 한다 (내용으로 봐야 한다)
BLOCK_SIGNS = ["에펨코리아 보안 시스템", "Just a moment", "challenge-platform",
               "Enable JavaScript and cookies", "비정상적인 접근",
               "Access Denied", "abuse detected"]


def get_text(s, url, timeout=20):
    """★인코딩은 사이트마다 다르다 (웃대는 EUC-KR). utf-8 로 못박으면
    오류 없이 제목만 깨진다."""
    r = s.get(url, timeout=timeout)
    b = r.content
    if r.status_code in (403, 429, 430) or (
            len(b) < 20000 and any(x.encode() in b or x in b.decode("utf-8", "ignore")
                                   for x in BLOCK_SIGNS)):
        raise Blocked(f"HTTP {r.status_code}")
    enc = None
    m = re.search(r"charset=([\w\-]+)", r.headers.get("Content-Type", ""), re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb"charset=[\"']?([\w\-]+)", b[:3000], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    for cand in [enc, "utf-8", "cp949"]:
        if not cand:
            continue
        try:
            return b.decode(cand)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode("utf-8", "replace")


def strip_tags(t):
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def num(t):
    """'16,526' '조회 826' '[7]' '(37)' → int. 못 읽으면 0."""
    if t is None:
        return 0
    m = re.search(r"[\d,]+", str(t))
    if not m:
        return 0
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return 0


def age_from(txt):
    """커뮤 목록의 시간 표기는 대개 'HH:MM'(오늘) 아니면 'YYYY-MM-DD'다."""
    if not txt:
        return None
    txt = txt.strip()
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", txt)
    if m and not re.search(r"\d{4}", txt):
        now = datetime.now()
        h = now.replace(hour=int(m.group(1)) % 24, minute=int(m.group(2)),
                        second=0, microsecond=0)
        d = (now - h).total_seconds() / 3600.0
        return d if d >= 0 else d + 24.0
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", txt)
    if m:
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return max((datetime.now() - d).total_seconds() / 3600.0, 0.0)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})\s*$", txt)
    if m:
        try:
            now = datetime.now()
            d = datetime(now.year, int(m.group(1)), int(m.group(2)))
            return max((now - d).total_seconds() / 3600.0, 0.0)
        except ValueError:
            return None
    m = re.search(r"(\d+)\s*분\s*전", txt)
    if m:
        return int(m.group(1)) / 60.0
    m = re.search(r"(\d+)\s*시간\s*전", txt)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*일\s*전", txt)
    if m:
        return int(m.group(1)) * 24.0
    return None


def norm_ws(h):
    """★파싱 전에 반드시 부른다.

    커뮤 HTML 은 **태그 안에도 줄바꿈이 섞여 있다**.
        <li class="li
             li_best2_pop0 ...">
        <tr class="ub-content
             us-post thum" ...>
    그래서 `<li class="li li_best2` 같은 패턴이 **오류 없이 그냥 안 잡힌다**.
    실측 2026-08-20: 펨코·아카라이브가 0건, 디시가 49건 중 2건만 나왔다.
    사이트가 죽은 줄 알기 쉬운데 아니다 — 공백만 뭉개면 다 잡힌다.

    ※ 이 함정은 눈으로도 잘 안 보인다. HTML 을 덤프해 보는 스크립트가 대개
      보기 좋으라고 `\\s+ → ' '` 를 먼저 하기 때문이다(내가 그렇게 속았다).
    """
    return re.sub(r"\s+", " ", h)


# 글을 가리키는 파라미터만 남긴다. 나머지(정렬·탭·페이지)는 부를 때마다 달라져
# 같은 글이 매번 새 글로 보인다 — 누적 중복제거가 통째로 망가진다.
# ★실측 2026-08-21: 루리웹 `?m=humor_only&t=now`, 개드립 때문에
#   '53분 만에 100% 갈렸다'는 엉뚱한 값이 나왔다(실제로는 거의 그대로였다).
ID_PARAMS = {"no", "No", "id", "code", "document_srl", "num", "number",
             "bo_table", "wr_id", "articleId"}


def canon_link(u):
    if not u:
        return u
    base, _, qs = u.partition("?")
    if not qs:
        return base
    keep = [kv for kv in qs.split("&")
            if kv.split("=")[0] in ID_PARAMS and kv.split("=", 1)[-1]]
    return base + ("?" + "&".join(keep) if keep else "")


def blocks(h, start_pat):
    """start_pat 이 나오는 지점마다 다음 지점 직전까지를 한 행으로 자른다.
    중첩 태그가 많은 요즘 마크업(아카라이브)은 정규식으로 </a> 를 못 닫는다."""
    idx = [m.start() for m in re.finditer(start_pat, h)]
    return [h[a:b] for a, b in zip(idx, idx[1:] + [len(h)])]


# ── 사이트별 파서 ─────────────────────────────────────────────────────
# 각 파서는 [{title, link, vote, comment, view, age, cate}] 를 돌려준다.
# 없는 지표는 None 으로 둔다 (0 과 구별해야 정규화가 안 망가진다).

def p_theqoo(h):
    out = []
    for r in blocks(h, r"<tr[^>]*> <td[^>]*class=\"no\""):
        # 공지·이벤트 행은 <tr class="notice ..."> 이고 번호 자리에 글자가 들어간다
        if re.match(r'<tr[^>]*class="[^"]*notice', r):
            continue
        if not re.match(r'<tr[^>]*> <td class="no"> \d', r):
            continue
        m = re.search(r'<td class="title">(.*?)</td>', r, re.S)
        if not m:
            continue
        cell = m.group(1)
        a = re.search(r'<a href="(/hot/\d+)"[^>]*>(.*?)</a>', cell, re.S)
        if not a:
            continue
        cm = re.search(r'class="replyNum"[^>]*>([\d,]+)', cell)
        cate = re.search(r'<td class="cate">\s*<span>(.*?)</span>', r, re.S)
        tm = re.search(r'<td class="time">(.*?)</td>', r, re.S)
        vw = re.search(r'<td class="m_no">([\d,]+)</td>', r)
        out.append(dict(title=strip_tags(a.group(2)),
                        link="https://theqoo.net" + a.group(1),
                        vote=None, comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(strip_tags(tm.group(1)) if tm else ""),
                        cate=strip_tags(cate.group(1)) if cate else ""))
    return out


def p_fmkorea(h):
    out = []
    for r in blocks(h, r'<li class="li li_best2'):
        t = re.search(r'<h3 class="title"[^>]*> <a href="(/best/\d+)"[^>]*>(.*?)</a>',
                      r, re.S)
        if not t:
            continue
        cell = t.group(2)
        el = re.search(r'<span class="ellipsis-target">(.*?)</span>', cell, re.S)
        # 댓글수 span 을 먼저 떼야 제목에 '[270]' 이 딸려 들어가지 않는다
        title = strip_tags(el.group(1) if el else
                           re.sub(r'<span class="comment_count">.*', "", cell, flags=re.S))
        cm = re.search(r'<span class="comment_count">\s*\[?([\d,]+)', r)
        vt = re.search(r'class="pc_voted_count[^"]*"[^>]*>.*?<span class="count">([\d,]+)',
                       r, re.S)
        rg = re.search(r'<span class="regdate">(.*?)</span>', r, re.S)
        ct = re.search(r'<span class="category">(.*?)</span>', r, re.S)
        # ★펨코는 행 클래스에 정치 여부를 직접 박아 준다 (li_best2_politics0/1).
        #   제목으로 알아맞히는 것보다 정확하다.
        pol = bool(re.match(r'<li class="[^"]*li_best2_politics1', r))
        out.append(dict(title=title, link="https://www.fmkorea.com" + t.group(1),
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=None,
                        age=age_from(strip_tags(rg.group(1)) if rg else ""),
                        cate=strip_tags(ct.group(1)) if ct else "",
                        topic_hint="정치" if pol else ""))
    return out


def p_dcinside(h):
    out = []
    # us-post 만 실제 글이다 (icon_notice·설문 행이 섞여 있다)
    for r in blocks(h, r'<tr class="ub-content us-post'):
        a = re.search(r'<td class="gall_tit[^"]*"> <a href="([^"]+)"[^>]*>(.*?)</a>',
                      r, re.S)
        if not a:
            continue
        cell = a.group(2)
        # <strong>[싱갤]</strong> 은 출처 갤러리다 — 제목에서 떼어 cate 로 옮긴다
        gal = re.search(r'<strong>\[(.*?)\]</strong>', cell)
        title = strip_tags(re.sub(r'<strong>\[.*?\]</strong>', "", cell, flags=re.S))
        if not title or title in ("설문", "공지"):
            continue
        cm = re.search(r'<a href="[^"]*"[^>]*>\s*<em class="icon_reply"></em>\s*\[?([\d,]+)', r)
        if not cm:
            cm = re.search(r'class="reply_num"[^>]*>\s*\[?([\d,]+)', r)
        vw = re.search(r'<td class="gall_count">([\d,\-]+)</td>', r)
        vt = re.search(r'<td class="gall_recommend">([\d,\-]+)</td>', r)
        dt = re.search(r'<td class="gall_date"[^>]*title="([^"]+)"', r)
        link = a.group(1)
        if link.startswith("/"):
            link = "https://gall.dcinside.com" + link
        out.append(dict(title=title, link=link,
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(dt.group(1)) if dt else None,
                        cate=gal.group(1) if gal else ""))
    return out


def p_pann(h):
    out = []
    for r in blocks(h, r'<dl>\s*<dt>'):
        a = re.search(r'<dt>.*?<a href="(/talk/\d+)"[^>]*>(.*?)</a>', r, re.S)
        if not a:
            continue
        # dt 는 짧은 머리말, dd.txt 가 실제 본문 한 줄이라 이쪽이 제목으로 낫다
        body = re.search(r'<dd class="txt">\s*<a[^>]*>(.*?)</a>', r, re.S)
        head = strip_tags(a.group(2))
        title = strip_tags(body.group(1)) if body else head
        cm = re.search(r'class="reple-num">\s*\(([\d,]+)\)', r)
        vw = re.search(r'class="count">\s*조회\s*([\d,]+)', r)
        vt = re.search(r'class="rcm">\s*추천\s*([\d,]+)', r)
        out.append(dict(title=title, link="https://pann.nate.com" + a.group(1),
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=None, cate=head if head != title else ""))
    return out


def p_ruliweb(h):
    out = []
    for r in blocks(h, r'<tr class="table_body'):
        a = re.search(r'<a class="subject_link[^"]*" href="([^"]+)"[^>]*>(.*?)</a>',
                      r, re.S)
        if not a:
            continue
        cell = a.group(2)
        cm = re.search(r'class="num_reply[^"]*">\s*\(?([\d,]+)\)?', cell)
        title = strip_tags(re.sub(r'<span class="num_reply.*', "", cell, flags=re.S))
        # ★베스트 목록은 제목 앞에 순위 숫자를 붙인다 ('3 새덕후) …').
        #   그대로 두면 검색어와 겹침 계산이 오염된다.
        title = re.sub(r"^\d{1,2}\s+(?=.{6,})", "", title)
        vt = re.search(r'<td class="recomd[^"]*">\s*([\d,]+)', r)
        vw = re.search(r'<td class="hit[^"]*">\s*([\d,]+)', r)
        tm = re.search(r'<td class="time[^"]*">(.*?)</td>', r, re.S)
        link = a.group(1)
        if link.startswith("/"):
            link = "https://bbs.ruliweb.com" + link
        out.append(dict(title=title, link=link,
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(strip_tags(tm.group(1)) if tm else ""), cate=""))
    return out


def p_clien(h):
    out = []
    for r in blocks(h, r'<div class="list_item symph_row'):
        a = re.search(r'<a class="list_subject" href="([^"?]+)', r)
        t = re.search(r'data-role="list-title-text" title="([^"]*)"', r)
        if not a or not t:
            continue
        vt = re.search(r'data-role="list-like-count"><span>([\d,]+)</span>', r)
        cm = re.search(r'data-comment-count=([\d]+)', r)
        vw = re.search(r'class="list_hit"[^>]*>\s*<span[^>]*>([\d,\.kK]+)', r)
        tm = re.search(r'class="timestamp"[^>]*>(.*?)</span>', r, re.S)
        out.append(dict(title=html.unescape(t.group(1)).strip(),
                        link="https://www.clien.net" + a.group(1),
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(strip_tags(tm.group(1)) if tm else ""), cate=""))
    return out


def p_bobae(h):
    out = []
    for r in blocks(h, r'<tr itemscope'):
        a = re.search(r'<a class="bsubject"[^>]*href="([^"]+)"[^>]*title="([^"]*)"', r)
        if not a:
            continue
        cm = re.search(r'<strong class="totreply">([\d,]+)</strong>', r)
        cate = re.search(r'<td class="category"[^>]*title="([^"]*)"', r)
        tds = re.findall(r'<td class="date"[^>]*>(.*?)</td>', r, re.S)
        vw = re.search(r'<td class="count"[^>]*>\s*([\d,]+)', r)
        vt = re.search(r'<td class="recomm"[^>]*>\s*([\d,]+)', r)
        link = a.group(1)
        if link.startswith("/"):
            link = "https://www.bobaedream.co.kr" + link
        out.append(dict(title=html.unescape(a.group(2)).strip(), link=link,
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(strip_tags(tds[0]) if tds else ""),
                        cate=cate.group(1) if cate else ""))
    return out


def p_arca(h):
    """★일반 행은 <div class="vrow ...">, 공지만 <a class="vrow ... notice"> 다.
    <a> 를 행으로 잡으면 공지 3건만 나온다(실측)."""
    out = []
    for r in blocks(h, r'<div class="vrow '):
        if "notice" in r[:60]:
            continue
        a = re.search(r'<a class="title[^"]*" href="([^"]+)">(.*?)</a>', r, re.S)
        if not a:
            continue
        cell = a.group(2)
        cm = re.search(r'class="comment-count"[^>]*>\s*\[?([\d,]+)', cell)
        # 제목 앞 아이콘 span 과 뒤 info span 을 떼고 남는 게 제목이다
        title = strip_tags(re.sub(r'<span class="info".*', "", cell, flags=re.S))
        if not title:
            continue
        badge = re.search(r'<a class="badge" href="/b/[^"]*"[^>]*>(.*?)</a>', r, re.S)
        vw = re.search(r'<span class="vcol col-view"[^>]*>\s*([\d,]+)', r)
        vt = re.search(r'<span class="vcol col-rate"[^>]*>\s*([\d,\-]+)', r)
        tm = re.search(r'<time[^>]*>(.*?)</time>', r, re.S)
        u = a.group(1)
        if u.startswith("/"):
            u = "https://arca.live" + u
        out.append(dict(title=title, link=u.split("?")[0],
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(strip_tags(tm.group(1)) if tm else ""),
                        cate=strip_tags(badge.group(1)) if badge else ""))
    return out


def p_inven(h):
    out = []
    for r in blocks(h, r'<td class="thumb"'):
        a = re.search(r'<a class="subject-link" href="([^"]+)"[^>]*>(.*?)</a>', r, re.S)
        if not a:
            continue
        cell = a.group(2)
        cate = re.search(r'<span class="category">\[?(.*?)\]?</span>', cell, re.S)
        title = strip_tags(re.sub(r'<span class="category">.*?</span>', "", cell, flags=re.S))
        cm = re.search(r'class="con-comment"[^>]*>\s*\[?([\d,]+)', r)
        vw = re.search(r'<td class="view[^"]*">\s*([\d,]+)', r)
        vt = re.search(r'<td class="reco[^"]*">\s*([\d,]+)', r)
        tm = re.search(r'<td class="date[^"]*">(.*?)</td>', r, re.S)
        out.append(dict(title=title, link=a.group(1),
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(strip_tags(tm.group(1)) if tm else ""),
                        cate=strip_tags(cate.group(1)) if cate else ""))
    return out


def p_dogdrip(h):
    out = []
    for r in blocks(h, r'<li class="ed flex flex-left'):
        a = re.search(r'<a href="([^"]+)" class="ed title-link"[^>]*>(.*?)</a>', r, re.S)
        if not a:
            continue
        cm = re.search(r'class="ed text-primary text-xxsmall">\s*([\d,]+)', r)
        vt = re.search(r'class="[^"]*vote[^"]*"[^>]*>\s*([\d,]+)', r)
        vw = re.search(r'title="조회 수"[^>]*>\s*([\d,]+)', r)
        if not vw:
            vw = re.search(r'fa-eye[^>]*></i>\s*([\d,]+)', r)
        tm = re.search(r'<time[^>]*>(.*?)</time>', r, re.S)
        out.append(dict(title=strip_tags(a.group(2)), link=a.group(1),
                        vote=num(vt.group(1)) if vt else None,
                        comment=num(cm.group(1)) if cm else 0,
                        view=num(vw.group(1)) if vw else None,
                        age=age_from(strip_tags(tm.group(1)) if tm else ""), cate=""))
    return out


SITES = [
    # key,     이름,       색,  URL,                                            파서
    ("theqoo",  "더쿠",     "여", "https://theqoo.net/hot", p_theqoo),
    ("fmkorea", "펨코",     "남", "https://www.fmkorea.com/best", p_fmkorea),
    ("dcinside", "디시실베", "남", "https://gall.dcinside.com/board/lists/?id=dcbest", p_dcinside),
    # 힛갤은 실베와 달리 걸러진 유머·이슈다 — 경제·정치를 뺀 회차에서 값이 크다
    ("dchit", "디시힛갤", "유", "https://gall.dcinside.com/board/lists/?id=hit", p_dcinside),
    ("pann",    "네이트판", "여", "https://pann.nate.com/talk/ranking", p_pann),
    ("ruliweb", "루리웹",   "남", "https://bbs.ruliweb.com/best", p_ruliweb),
    ("clien",   "클리앙",   "시", "https://www.clien.net/service/board/park", p_clien),
    ("bobae",   "보배드림", "시", "https://www.bobaedream.co.kr/list?code=best", p_bobae),
    ("arca",    "아카라이브", "남", "https://arca.live/b/live", p_arca),
    ("inven",   "인벤",     "남", "https://www.inven.co.kr/board/webzine/2097", p_inven),
    ("dogdrip", "개드립",   "유", "https://www.dogdrip.net/dogdrip", p_dogdrip),
    # ── 종목 전용 갤러리 (2026-08-21 추가) ────────────────────────────
    # 짹짹(축구)·짧뷰(골프)는 **영상 클립**이 소재라 종합 게시판만으로는 안 잡힌다.
    # ★반드시 `exception_mode=recommend`(개념글)로만 긁는다 —
    #   원본 갤을 통째로 긁으면 음모론·짤만 쏟아진다([[dcinside-best-is-already-the-filter]]).
    # ★디시는 축구갤을 주기적으로 갈아치운다. 제목에 `202211~202404` 처럼 **기간이 박혀
    #   있으면 보관된 옛 갤**이라 새 글이 안 올라온다. 안 잡히면 여기 id 부터 의심해라
    #   (2026-08-21 실측: football·football_new6·football_new8 은 전부 보관본, new9 가 현재).
    ("dcfoot", "디시축구", "남",
     "https://gall.dcinside.com/board/lists/?id=football_new9&exception_mode=recommend",
     p_dcinside),
    # ★골프갤(id=golf)은 **죽었다** — 개념글 상위가 전부 `갤 이전 안내`·`대피소 안내`고
    #   본문 목록도 비어 있다(2026-08-21 실측). 미니갤로 옮겨 갔는데 그 id 를 못 찾았다.
    #   붙여 봐야 공지만 올라오므로 뺐다. 짧뷰(골프) 소재는 국내 커뮤가 약하다 —
    #   유튜브 계정 추적 쪽이 맞다.
]


# ── 뇌전구 적합도 ─────────────────────────────────────────────────────
# 커뮤 인기글의 대부분은 뇌전구로 못 만든다. 짤·잡담·팬질·성인물이 태반이라
# 반응 점수만으로 세우면 상위 20개가 죄다 못 쓸 것으로 찬다.
GOOD = [
    # 반전·역설 — 뇌전구의 뼈대다
    "알고보니", "알고 보니", "사실은", "반전", "불구", "오히려", "정작", "근데",
    "이유", "때문", "숨은", "몰랐", "비밀", "진실", "실체", "속사정",
    # 최초·최다·기록
    "최초", "최다", "최대", "최연소", "최고령", "처음", "유일", "1위", "돌파",
    "역대", "세계", "국내", "앞질", "제쳤", "기록",
    # 사건성
    "적발", "밝혀", "드러", "폭로", "확인", "판결", "무죄", "유죄", "구속",
    "고발", "송치", "공개", "해명", "발칵", "논란", "충격",
    # 정보·연구
    "연구", "조사", "통계", "분석", "실험", "발견", "차이", "비교", "결과",
]
# 뇌전구로 못 만드는 것 — 감점
BAD = [
    # 짤·움짤
    ".gif", ".jpg", ".png", ".mp4", "움짤", "짤방", "짤.", "고화질",
    # 잡담·질문·투표
    "추천 좀", "추천좀", "질문", "어떰", "어떻게 생각", "골라줘", "골라주",
    "뭐가 나음", "vs ", " vs", "고민", "삽니다", "팝니다", "후기 좀",
    # 팬질·연예 잡담
    "직캠", "무대", "컴백", "앨범", "티저", "뮤비", "셀카", "비주얼", "포토",
    "예능", "출연", "인스타", "스토리", "브이앱", "위버스", "굿즈", "콘서트",
    # 성인·후방
    "후방", "약후", "노출", "몸매", "다리", "섹시", "글래머", "비키니",
    # 스포츠 실황
    "선발", "라인업", "하이라이트", "결승골", "승리", "패배", "경기 결과",
    # 커뮤 내부
    "공지", "이벤트", "출석", "등업", "가입인사", "필독", "정모",
]
NUM_UNIT = re.compile(r"\d+\s*(?:%|％|배|억|조|만|천|위|명|건|년|개국|일|시간|퍼센트)")
# 커뮤는 제목 끝에 확장자를 붙여 '짤'임을 알린다 (.jpg .gif .avi .txt .eu ...).
# 낱말 목록으로는 못 잡는다 — 아무 글자나 붙이기 때문이다(.euk .mp4a .ㅇㅇ).
EXT = re.compile(r"\.[A-Za-z가-힣]{1,8}\s*$")
# 창작물(만화·그림·제작기)은 반응이 크게 붙지만 뇌전구로는 못 만든다.
# ★확장자 놀이를 '...manhwa' 처럼 길게 붙이면 EXT 만으로는 못 잡는다.
MADE = ["manhwa", "manga", "웹툰", "만화", "제작 과정", "제작과정", "그려봤",
        "그림", "창작", "습작", "낙서", "커미션", "도색", "자작"]
# 정치 인물·정당은 이슈몰이는 되지만 채널 톤과 위험도 때문에 눌러 둔다
POLI = ["이재명", "윤석열", "국민의힘", "민주당", "조국", "한동훈", "文", "尹",
        "좌파", "우파", "빨갱이", "친일", "토착왜구"]


def title_fit(t):
    """−1 ~ +1. 점수를 ±40% 만 흔드는 보조다."""
    s, hit = 0.0, []
    low = t.lower()
    for w in GOOD:
        if w in low:
            s += 0.30
            hit.append(w)
            if s >= 0.9:
                break
    if NUM_UNIT.search(t):
        s += 0.25
        hit.append("숫자")
    if EXT.search(t):
        s -= 0.55
        hit.append("−짤")
    for w in MADE:
        if w in low:
            s -= 0.60
            hit.append("−창작")
            break
    for w in BAD:
        if w in low:
            s -= 0.55
            hit.append("−" + w.strip())
            break
    for w in POLI:
        if w in t:
            s -= 0.35
            hit.append("−정치")
            break
    # 제목이 너무 짧으면 사건이 아니라 잡담일 확률이 높다
    if len(t) < 10:
        s -= 0.25
        hit.append("−짧음")
    return max(-1.0, min(1.0, s)), hit


# ── 갈래 나누기 ───────────────────────────────────────────────────────
# 경제·정치는 다른 채널에서 다루므로 커뮤형에서는 뺀다(사장님 지시 2026-08-20).
# ★순서가 중요하다. 잡학을 먼저 본다 —
#   'F1에서 상식적인 것들이 규정으로 금지되는 이유' 는 스포츠 낱말이 들어 있지만
#   실제로는 잡학이고, 뇌전구에 가장 잘 맞는 갈래다.
TOPIC_WORDS = [
    ("잡학", ["싱글벙글", "와들와들", "미스터리", "역사", "유래", "어원", "원리",
              "하는 이유", "인 이유", "된 이유", "안 되는 이유", "실제로", "알고보니",
              "알고 보니", "과학", "연구", "실험", "우주", "심리", "동물", "생물",
              "질병", "의학", "발견", "정체", "비밀", "차이", "왜 ", "정작"]),
    ("정치", ["대통령", "국회", "여당", "야당", "민주당", "국민의힘", "장관", "검찰",
              "법무부", "대법관", "청와대", "용산", "의원", "개헌", "특검", "탄핵",
              "계엄", "이재명", "윤석열", "한동훈", "조국", "與", "野", "靑",
              "공수처", "총리", "내란", "지지율", "정부", "당대표"]),
    ("경제", ["파산", "적자", "흑자", "매출", "주가", "코스피", "코스닥", "금리",
              "환율", "시총", "상폐", "나스닥", "분양", "집값", "부동산", "전세",
              "대출", "세수", "기본소득", "실업급여", "연봉", "물가", "인플레",
              "투자", "펀드", "코인", "비트코인", "일감", "공시", "임금", "폐업",
              "창업", "자영업", "경기침체", "반도체", "수출", "관세", "억원", "조원"]),
    # ★FIFA 는 축구보다 **먼저** 본다. 사장님 지시 2026-08-21 — 짹짹(축구)에서
    #   FIFA 것은 무조건 뺀다. 갈래로 따로 세워 두면 기본 --drop 에서 빠지면서도
    #   `--only FIFA` 로 무엇이 걸렸는지 눈으로 볼 수 있다(조용히 버리지 않는다).
    ("FIFA", ["FIFA", "피파", "월드컵", "W컵", "클럽월드컵", "컨페더레이션스",
              "FC온라인", "피파온라인", "EA FC", "국제축구연맹"]),
    # ★흔한 낱말을 넣으면 안 된다. 첫 판에 `그린`(그리다) 때문에 '여태 그린 낙서들'이,
    #   `이글` 때문에 엉뚱한 글이 골프로 잡혔다. `보기`·`슈팅`·`드리블`·`퇴장`·`댄스`·
    #   `챌린지` 도 같은 이유로 뺐다 — 다른 종목·문맥에서 너무 많이 쓰인다.
    #   **그 종목에서만 쓰는 말**만 남긴다.
    ("축구", ["축구", "손흥민", "골키퍼", "오프사이드", "프리킥", "코너킥",
              "페널티킥", "해트트릭", "EPL", "프리미어리그", "라리가", "분데스리가",
              "챔피언스리그", "K리그", "레드카드", "자책골", "선제골", "역전골",
              "골 세리머니", "월클", "축구선수"]),
    ("골프", ["골프", "스윙", "퍼팅", "홀인원", "티샷", "어프로치", "벙커샷",
              "캐디", "PGA", "LPGA", "골프채", "라운딩", "구력", "아이언샷",
              "드라이버샷", "버디 퍼트", "그린 위", "18홀"]),
    ("춤", ["안무", "커버댄스", "칼군무", "군무", "댄서", "춤선", "비보이",
            "발레", "댄스챌린지", "댄스 챌린지", "브레이킹", "왁킹", "힙합댄스"]),
    ("연예", ["아이돌", "걸그룹", "보이그룹", "배우", "가수", "예능", "드라마",
              "컴백", "앨범", "직캠", "무대", "열애", "결별", "소속사", "데뷔",
              "캐스팅", "출연료", "시청률", "논란 해명"]),
    ("스포츠", ["KBO", "프로야구", "리그", "이적", "감독", "선발투수",
                "타점", "홈런", "승부", "우승", "구단", "국가대표"]),
    ("유머", ["유머", "움짤", "개그", "짤방", "웃긴", "드립", "밈 ", "레전드"]),
]
# 유머 성향이 짙은 판 — 다른 신호가 없으면 유머로 본다
FUN_SITES = {"dchit", "dogdrip"}

# ── 클립 표시 ─────────────────────────────────────────────────────────
# 짹짹(축구)·짧뷰(골프)·칩칩(춤)은 **영상 클립**을 재창작하는 채널이라
# 글(잡담·여론)이 아니라 영상이 붙은 글이 필요하다.
# 디시 축구갤 개념글은 상위가 죄다 여론 글이었다(2026-08-21) —
# `이강인은 환상임` 같은 것. 그래서 영상 표시를 따로 본다.
CLIP_WORDS = ["gif", "GIF", "움짤", "짤", "영상", "동영상", "클립", "매치",
              "하이라이트", "골장면", "장면", "리플레이", "mp4", "유튜브",
              "쇼츠", "직캠", "풀영상", "다시보기"]


def has_clip(title, cate=""):
    t = (title or "") + " " + (cate or "")
    return any(w in t for w in CLIP_WORDS)


def topic_of(title, cate="", hint="", site=""):
    """★순서가 결과를 바꾼다. 잡학을 맨 먼저 본다 —
    '싱글벙글 F1에서 상식적인 게 금지된 이유' 는 유머 게시판 글이지만
    알맹이는 잡학이고, 뇌전구에 제일 잘 맞는 갈래다.

    ※갈래는 어디까지나 거친 자다. **'유머라서 못 쓴다'가 아니라
      '알맹이가 없어서 못 쓴다'** 가 맞다 — 갈래로 통째로 자르지 말고
      `fit`(알맹이 점수)과 같이 봐라.
    """
    if hint:
        return hint
    t = title + " " + (cate or "")
    for name, ws in TOPIC_WORDS:
        for w in ws:
            if w in t:
                return name
    if EXT.search(title) or re.search(r"[ㅋㅎ]{2,}", title):
        return "유머"
    if site in FUN_SITES:
        return "유머"
    return "이슈"


# ── 사건 묶기 (커뮤 경계를 넘어) ──────────────────────────────────────
TITLE_STRIP = re.compile(r"[\[\]\(\)\"'“”‘’…·,.\-—~!?%\s]+")


def bigrams(t):
    t = TITLE_STRIP.sub("", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def title_sim(a, b):
    if not a or not b:
        return 0.0
    ov = len(a & b)
    if ov < 4:
        return 0.0
    return ov / min(len(a), len(b))


def group_events(items, th=0.30):
    """같은 사건을 하나로 묶는다. ★커뮤 경계를 넘어 묶는 게 핵심이다 —
    몇 개 커뮤에 동시에 떴는지가 이 헌터에서 가장 센 신호다.

    커뮤는 서로 퍼나르면서 제목을 조금씩 바꾸므로 경제(0.32)보다 살짝 눅인다.
    ★대표하고만 비교하는 그리디다 (전체쌍 union-find 는 A-B-C 로 이어져 뭉갠다).
    """
    order = sorted(items, key=lambda x: -x.get("_hot", 0))
    groups = []
    for it in order:
        bg = bigrams(it["title"])
        placed = False
        for g in groups:
            if title_sim(bg, g["bg"]) >= th:
                g["mem"].append(it)
                placed = True
                break
        if not placed:
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
        rep["n_posts"] = len(g)
        rep["hot"] = sum(x["_hot"] for x in g)
        rep["comment"] = sum(x.get("comment") or 0 for x in g)
        rep["vote"] = sum(x.get("vote") or 0 for x in g)
        rep["view"] = sum(x.get("view") or 0 for x in g)
        ages = [x["age"] for x in g if x.get("age") is not None]
        rep["age"] = min(ages) if ages else None
        # 같은 사건이 커뮤마다 다르게 읽힐 수 있다 — 가장 많이 나온 갈래로 정한다
        tc = {}
        for x in g:
            tc[x.get("topic", "이슈")] = tc.get(x.get("topic", "이슈"), 0) + 1
        rep["topic"] = max(tc.items(), key=lambda kv: (kv[1], kv[0] != "이슈"))[0]
        rep["members"] = [{"site": x["site"], "site_name": x["site_name"],
                           "title": x["title"], "link": x["link"]} for x in g[:8]]
        out.append(rep)
    return out


# ── 점수 ──────────────────────────────────────────────────────────────
def normalize(rows):
    """★사이트별로 눈금을 맞춘다.
    디시 추천 890 과 클리앙 추천 1 을 그대로 더하면 디시가 목록을 독식한다.
    그 사이트 이번 수집분의 **중앙값 대비 몇 배**로 환산한다."""
    by = {}
    for r in rows:
        by.setdefault(r["site"], []).append(r)
    for site, rs in by.items():
        med = {}
        for k in ("vote", "comment", "view"):
            vals = [r[k] for r in rs if r.get(k)]
            med[k] = median(vals) if vals else 0
        for r in rs:
            # 댓글이 이슈몰이의 핵심 지표다. 조회는 낚시성 제목에도 붙고,
            # 추천은 커뮤 성향을 더 타서 보조로만 쓴다.
            parts, w = 0.0, 0.0
            for k, wt in (("comment", 1.0), ("vote", 0.7), ("view", 0.45)):
                if r.get(k) is not None and med[k]:
                    parts += wt * (r[k] / med[k])
                    w += wt
            r["_hot"] = parts / w if w else 0.0
            r["_med"] = med
    return rows


def score_item(it):
    hot = it.get("hot", 0.0)
    hrs = it.get("age")
    hrs_eff = max(hrs if hrs is not None else 5.0, 0.6)

    heat = 46 * log10(1 + hot)
    # ★교차 커뮤 확산 — 이 헌터에서 가장 센 신호다.
    #   더쿠·펨코·디시에 동시에 떠 있으면 그건 진짜 터진 사건이다.
    spread = 55 * log10(it.get("n_sites", 1)) + 12 * log10(it.get("n_posts", 1))
    # 갓 올라왔는데 벌써 뜨거운가
    vel = 22 * log10(1 + hot / hrs_eff)
    # 남초·여초·시사에 걸쳐 떴으면 전 국민 이슈다
    kinds = {SITE_KIND.get(s, "") for s in it.get("sites", [])}
    cross = 14 * max(len(kinds) - 1, 0)

    fit, hitw = title_fit(it["title"])
    tb, tw = trend_bonus(it["title"])
    it["score"] = round((heat + spread + vel + cross + tb) * (1 + 0.40 * fit), 1)
    it["fit"] = round(fit, 2)
    it["fit_hit"] = hitw
    it["trend"] = tw
    it["parts"] = {"heat": round(heat, 1), "spread": round(spread, 1),
                   "vel": round(vel, 1), "cross": round(cross, 1), "trend": tb}
    return it


SITE_KIND = {k: kind for k, _n, kind, _u, _p in SITES}
SITE_NAME = {k: n for k, n, _kd, _u, _p in SITES}


# ── 수집 ──────────────────────────────────────────────────────────────
# 커뮤 공지·이벤트·운영글은 반응이 크게 붙어 그냥 두면 상위를 독식한다
# (실측: 더쿠 이용규칙·비밀번호 공지가 1·2·3위였다)
NOTICE = ["공지", "이용 규칙", "이용규칙", "운영진", "패치노트", "점검 안내",
          "체험단", "이벤트", "당첨자", "모집", "필독", "안내드립니다",
          "비밀번호", "서버 이전", "업데이트 안내"]


def is_notice(t):
    return any(w in t for w in NOTICE)


def collect(site, s):
    key, name, kind, url, parser = site
    t0 = time.time()
    try:
        # ★norm_ws 를 빼면 파서가 오류 없이 0건을 돌려준다. norm_ws 주석을 봐라.
        h = norm_ws(get_text(s, url))
        rows = parser(h) or []
    except Blocked as e:
        # ★구조 변경과 반드시 구별해서 알린다. 대응이 정반대다 —
        #   구조가 바뀐 거면 파서를 고쳐야 하고, 차단이면 손대지 말고 쉬어야 한다.
        return key, [], f"⛔ 차단 ({e}) — 파서 건드리지 말고 쉬었다 다시"
    except Exception as e:                                  # noqa: BLE001
        return key, [], f"실패: {type(e).__name__} {e}"
    for r in rows:
        r["site"] = key
        r["site_name"] = name
        r["kind"] = kind
        r["link"] = canon_link(r.get("link", ""))
        r["topic"] = topic_of(r["title"], r.get("cate", ""),
                              r.get("topic_hint", ""), key)
    ok = [r for r in rows
          if r.get("title") and len(r["title"]) >= 2 and not is_notice(r["title"])]
    note = f"{len(ok)}건 / {time.time() - t0:.1f}초"
    if not ok:
        note = "⚠ 0건 — 페이지 구조가 바뀌었을 수 있다"
    return key, ok, note


def gather():
    s = sess()
    res, notes = [], {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(collect, site, s): site[0] for site in SITES}
        for f in cf.as_completed(futs):
            key, rows, note = f.result()
            notes[key] = note
            res.extend(rows)
    return res, notes


# ── 누적 ──────────────────────────────────────────────────────────────
# ★실시간 베스트는 몇 시간이면 완전히 갈린다. 한 번 돌리면 그 순간 걸린 것만
#   보게 되는데, 잡학처럼 드문 갈래는 그래서 하루 30여 건밖에 안 잡힌다.
#
#   소스를 늘려서 풀려고 했다가 실패했다(2026-08-21). 잡학은 별도 판에 사는 게
#   아니라 여러 판에서 가끔 나오는 걸 **베스트가 걸러 올려주는** 구조다 —
#   원본 갤러리(싱갤·미스터리갤·역사갤)를 직접 긁으면 음모론·창작·짤만 쏟아진다.
#   ★디시 실베·힛갤이 이미 필터 노릇을 하고 있다. 그 앞단을 긁지 마라.
#
#   그래서 답은 **여러 번 돌려 쌓는 것**이다. 하루 3~4회면 풀이 서너 배가 된다.
def save_raw(rows, stamp):
    keep = ["site", "site_name", "kind", "title", "link", "vote", "comment",
            "view", "age", "cate", "topic"]
    json.dump([{k: r.get(k) for k in keep} for r in rows],
              open(os.path.join(OUT, f"raw_{stamp}.json"), "w", encoding="utf-8"),
              ensure_ascii=False)


def load_accum(rows, hours):
    """지난 실행 결과를 합친다. 같은 글은 링크로 묶고 **반응이 큰 쪽**을 남긴다
    (시간이 지나면 댓글·조회가 늘어나므로 나중 관측이 대개 크다)."""
    if hours <= 0:
        return rows, 0
    cut = time.time() - hours * 3600
    by = {}
    for r in rows:
        by[r["link"]] = r
    added = 0
    for p in sorted(glob.glob(os.path.join(OUT, "raw_*.json"))):
        try:
            if os.path.getmtime(p) < cut:
                continue
            old = json.load(open(p, encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            continue
        for r in old:
            if not r.get("link") or not r.get("title"):
                continue
            cur = by.get(r["link"])
            if cur is None:
                by[r["link"]] = r
                added += 1
            elif (r.get("comment") or 0) > (cur.get("comment") or 0):
                # 옛 관측이 더 크면 그쪽을 남긴다 (베스트에서 내려간 뒤 반응이 준 경우)
                by[r["link"]] = r
    return list(by.values()), added


# ── 구글 트렌드 (가산점 전용) ─────────────────────────────────────────
# ★소재원이 아니다. 낱말만 오므로 그것만으론 대본을 못 쓴다.
#   쓰임은 하나 — **커뮤 안에서만 도는 글인가, 전국이 검색 중인가**를 가른다.
#   경제 헌터의 '전 섹션 랭킹 진입' 가산점과 같은 자리다.
#   공식 RSS 라 막힐 일이 없다(커뮤·네이버와 달리).
TRENDS = {}


def fetch_trends(s):
    try:
        h = get_text(s, "https://trends.google.co.kr/trending/rss?geo=KR", timeout=15)
    except Exception:                                       # noqa: BLE001
        return {}
    out = {}
    for m in re.finditer(r"<item>(.*?)</item>", h, re.S):
        blk = m.group(1)
        t = re.search(r"<title>(.*?)</title>", blk, re.S)
        tr = re.search(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", blk, re.S)
        if not t:
            continue
        w = strip_tags(t.group(1))
        if len(w) >= 2:
            out[w] = num(tr.group(1)) if tr else 0
    return out


def trend_bonus(title):
    """★두 글자짜리 일반 낱말(`배우`·`욕조`·`이륙`)이 아무 제목에나 걸린다.
    그래서 상한을 낮게 잡아 **순위를 뒤집지는 못하게** 둔다. 밀어주는 정도다."""
    best, word = 0, ""
    for w, v in TRENDS.items():
        if w in title and v > best:
            best, word = v, w
    if not best:
        return 0.0, ""
    return round(min(9 * log10(1 + best / 100.0), 14.0), 1), word


# ── 뉴스 교차확인 ─────────────────────────────────────────────────────
STOP = {"근황", "레전드", "오늘", "요즘", "진짜", "실화", "이거", "그냥",
        "너무", "이번", "정도", "사람", "이런", "저런", "우리"}
# 커뮤 말머리·은어 — 검색어에 그냥 넣으면 기사를 못 찾는다.
# 실측: '[좆됨] 법인 파산…' 이 '좆됨 법인 파산 반년' 으로 나가 0건이었고,
#       말머리만 떼니 같은 사건 기사 10건이 바로 잡혔다.
JUNK = {"싱글벙글", "우울증", "흠좀무", "소름", "충격", "실화", "근황", "레전드",
        "만화", "유머", "정보", "질문", "오늘자", "스압", "혐주의", "펌",
        "movie", "jpg", "gif", "png", "mp4", "webp", "좆됨", "ㅇㅎ"}


def news_words(title):
    t = re.sub(r"[\[\(【][^\]\)】]{0,12}[\]\)】]", " ", title)   # 말머리 [좆됨] (2)
    t = re.sub(r"\.(jpg|gif|png|mp4|webp)\b", " ", t, flags=re.I)
    t = re.sub(r"[ㄱ-ㅎㅏ-ㅣ]+", " ", t)                        # ㅋㅋ ㄷㄷ ㅠㅠ
    t = re.sub(r"[‘’“”'\"…·♥★▶◆~!?]+", " ", t)
    return [w for w in re.findall(r"[가-힣A-Za-z0-9]+", t)
            if len(w) >= 2 and w not in STOP and w.lower() not in JUNK]


# ★글자 **뒤**에 숫자가 붙으면 고유명사다 (기안84·GS25·아이폰17).
#   숫자가 앞이면 수치일 뿐이다 (100m·3위까지·1년치) — 넣으면 안 된다.
# 꼬리 조사까지 받아 준다 — `기안84가` 를 그대로 두면 기사의 `기안84` 와 안 맞는다.
MIXED = re.compile(r"^([가-힣]+\d+|[A-Za-z]+\d+)[가-힣]{0,2}$")
# 짧고 흔해서 사건을 못 가리는 낱말
GENERIC = {"사람", "여자", "남자", "친구", "회사", "학교", "얘기", "생각", "상황",
           "영상", "사진", "댓글", "반응", "근황", "레전드", "이유", "정도"}
# 활용형·조사 꼬리 — 고유명사가 아니다 (`위반으로` 가 `새덕후` 를 제치면 안 된다)
TAIL = ("으로", "에서", "까지", "부터", "라고", "하고", "하자", "했다", "한다",
        "이다", "지만", "는데", "니까", "면서", "려고", "도록", "처럼")
# ★길이로 고유명사를 가리려 하지 마라 — 한국어는 활용형이 길어진다.
#   `생기자마자`(5자)가 `기안84` 를 제치고 엉뚱한 기사를 물어 왔다(실측).
#   용언·조사로 끝나는 낱말은 이름이 아니다.
VERB_END = set("다고서며자나니지게면야라죠요이가은는을를의에도만")


def keywords(title):
    """사건을 가려내는 '특징 낱말'. 흔한 낱말은 빼고 드문 것만 남긴다.

    ★두 글자는 넣지 않는다 — `AI`·`TV`·`한화` 같은 게 아무 기사에나 걸린다.
      다만 숫자가 섞인 것(`기안84`)은 짧아도 고유명사라 예외로 둔다.
    """
    out, mixed = [], set()
    for w in news_words(title):
        m = MIXED.match(w)
        if m:
            core = m.group(1)          # `기안84가` → `기안84`
            out.append(core)
            mixed.add(core)
        elif w[0].isdigit():
            continue                   # 수치다 (100m·1년치) — 사건을 못 가린다
        elif (len(w) >= 3 and w not in GENERIC
              and not w.endswith(TAIL) and w[-1] not in VERB_END):
            out.append(w)
    # 드문 것부터 — 글자+숫자(고유명사) 먼저, 그다음 긴 것
    out.sort(key=lambda w: (0 if w in mixed else 1, -len(w)))
    return out[:4]


def news_queries(title):
    """넓은 것 → 좁은 것 순으로 검색어 후보를 만든다.

    ★4낱말로 좁히면 오히려 못 찾는다. 실측 2026-08-21:
        '새덕후 경찰이 동물 보호법'  → 0건
        '새덕후'                    → 10건, 전부 그 사건 기사
      커뮤 제목에는 기사에 안 쓰이는 말(말투·반응·인용)이 섞여 있어서
      낱말을 더할수록 교집합이 사라진다. **고유명사 하나가 제일 세다.**

    막 짧게만 물으면 엉뚱한 기사가 오지만, 그건 `겹침`이 걸러 준다.
    """
    ws = news_words(title)
    if not ws:
        return []
    # ★특징 낱말(고유명사)을 **맨 먼저** 묻는다.
    #   낱말을 늘어놓은 검색어를 먼저 물면 그게 아무 기사나 8건 채워 버려서
    #   정작 `기안84` 를 물어볼 차례가 오지 않는다(실측 2026-08-21).
    out = list(keywords(title)[:2])
    out.append(" ".join(ws[:4]))
    if len(ws) > 2:
        out.append(" ".join(ws[:2]))
    # 특징 낱말을 어떻게 고르는지는 keywords() 를 봐라 —
    #   맨 앞 낱말도, 가장 긴 낱말도 답이 아니다. 둘 다 실측으로 틀렸다.
    seen, uniq = set(), []
    for q in out:
        if len(q) >= 2 and q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def title_overlap(comm_title, news_title):
    """커뮤 제목과 기사 제목이 같은 사건을 가리키나. 0~1.

    ★낱말 교집합으로만 재면 안 된다. 한국어는 조사·어미가 붙어
      `동물` ≠ `동물권`, `경찰이` ≠ `경찰` 이 되고, 커뮤 제목의 말투
      (`하자고`·`했다네`)가 분모만 키운다.
      실측 2026-08-21: 새덕후 기사 10건이 전부 겹침 0.12 로 나와
      문턱 0.20 에 걸려 통째로 버려질 뻔했다.

    셋 중 가장 큰 값을 쓴다 —
      ① 낱말 교집합  ② 글자쌍 포함도  ③ **고유명사 적중**(제일 세다)
    """
    a = toks(comm_title)
    tok = len(a & toks(news_title)) / max(len(a), 1)
    bg = title_sim(bigrams(comm_title), bigrams(news_title))
    # 특징 낱말이 기사 제목에 그대로 있으면 같은 사건일 가능성이 높다.
    # ★두 글자짜리를 여기 넣으면 안 된다. `AI 여친…기안84` 의 첫 낱말이 `AI` 라
    #   AI 기사마다 0.55 가 붙어 **엉뚱한 기사 10건이 전부 만점**이 됐다
    #   (실측 2026-08-21). 짧은 낱말은 사건을 못 가린다.
    # 긴 낱말일수록 드물다 — 길이로 확신도를 매긴다.
    key = 0.0
    for w in keywords(comm_title):
        if w in news_title:
            key = max(key, min(0.35 + 0.08 * (len(w) - 3), 0.65))
    return round(max(tok, bg, key), 2)


def news_check(s, title):
    """★커뮤 글은 검증된 보도가 아니다. 같은 사건 기사가 실제로 있는지 본다.
    기사가 없으면 그 소재로 뇌전구를 만들면 안 된다 — 오보가 된다.

    돌려주는 것은 (건수, 가장 가까운 기사 제목, 겹침). ★건수만 보면 안 된다 —
    '절이나 교회를 다니지 마십시오' 가 무관한 북카페 기사 7건을 물어 온다.
    겹침(커뮤 제목 낱말 중 기사 제목에도 있는 비율)이 실제 관련도다.
    """
    hits = []
    for q in news_queries(title):
        url = ("https://search.naver.com/search.naver?where=news&query="
               + requests.utils.quote(q))
        try:
            h = get_text(s, url, timeout=15)
        except Blocked:
            # ★네이버도 몰아치면 403 으로 막는다. 더 두드리지 말고 물러난다.
            return -1, "", 0.0
        except Exception:                                   # noqa: BLE001
            time.sleep(1.0)
            continue
        hits = re.findall(
            r'class="sds-comps-text[^"]*headline1[^"]*"[^>]*>(.*?)</span>', h, re.S)
        if not hits:
            hits = re.findall(r'class="news_tit"[^>]*title="([^"]*)"', h)
        if hits:
            break
        # ★결과 없는 JS 껍데기(30KB 남짓)는 진짜 0건과 구별이 안 된다.
        time.sleep(1.0 if len(h) < 80000 else 0.5)
    hits = [x for x in (strip_tags(y) for y in hits) if x]
    if not hits:
        return 0, "", 0.0
    best, bt = 0.0, hits[0]
    for x in hits[:10]:
        ov = title_overlap(title, x)
        if ov > best:
            best, bt = ov, x
    return len(hits), bt[:52], round(best, 2)


# ── 중복 제거 ─────────────────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            return json.load(open(SEEN_PATH, encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            pass
    return {"ids": [], "titles": []}


def toks(t):
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]+", t) if len(w) >= 2}


def is_seen(it, seen):
    a = toks(it["title"])
    if not a:
        return False
    for old in seen.get("titles", []):
        b = toks(old)
        if b and len(a & b) / max(len(a | b), 1) >= 0.45:
            return True
    return False


# ── 출력 ──────────────────────────────────────────────────────────────
def write_sheet(rows, path, meta):
    L = [f"# 커뮤형 뇌전구 소재 후보 — {meta['stamp']}", ""]
    L.append(f"수집 {meta['n_raw']}건 → 사건 {meta['n_ev']}묶음 → 상위 {len(rows)}")
    L.append("")
    L.append("## 커뮤별 수집")
    L.append("")
    L.append("| 커뮤 | 결과 |")
    L.append("|---|---|")
    for k, n, _kd, _u, _p in SITES:
        L.append(f"| {n} | {meta['notes'].get(k, '-')} |")
    L.append("")
    if meta.get("news_on"):
        L.append("`기사` 열 — 네이버 뉴스 검색 건수와 **제목 겹침**이다. "
                 "겹침이 실제 관련도다(건수만 보면 무관한 기사에 속는다).")
        L.append("")
        L.append("- `❌0` — 기사가 없다. **커뮤 안에서만 도는 미검증 글이니 그대로 만들지 마라.**")
        L.append("- 겹침 `0.4` 이상이면 같은 사건일 가능성이 높다. 그래도 기사를 열어 확인한다.")
    else:
        L.append("※ 뉴스 교차확인을 끄고 돌렸다. `--news` 로 켠다.")
    L.append("")
    L.append("| # | 점수 | 갈래 | 커뮤 | 제목 | 댓글 | 추천 | 조회 | 경과 | 적합 | 기사 |")
    L.append("|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|")
    for i, r in enumerate(rows, 1):
        sn = "·".join(SITE_NAME.get(x, x) for x in r["sites"][:4])
        if r["n_sites"] > 4:
            sn += f"+{r['n_sites'] - 4}"
        age = f"{r['age']:.1f}h" if r.get("age") is not None else "-"
        t = r["title"].replace("|", "/")[:46]
        nc = r.get("news_n")
        if nc is None:
            news = "-"
        elif nc < 0:
            news = "확인불가"
        elif nc == 0:
            news = "❌0"
        else:
            news = f"{nc} / {r.get('news_ov', 0):.2f}"
        L.append(f"| {i} | {r['score']} | {r.get('topic', '-')} | {sn} | "
                 f"[{t}]({r['link']}) | "
                 f"{r['comment']} | {r['vote']} | {r['view']} | {age} | "
                 f"{r['fit']} | {news} |")
    L.append("")
    L.append("## 상세")
    L.append("")
    for i, r in enumerate(rows, 1):
        L.append(f"### {i}. {r['title']}")
        L.append("")
        L.append(f"- 점수 {r['score']}  {r['parts']}")
        L.append(f"- 적합 {r['fit']} {r['fit_hit']}")
        if r.get("trend"):
            L.append(f"- 🔥 구글 트렌드 `{r['trend']}` — 전국이 검색 중이다")
        if r.get("news_first"):
            L.append(f"- 기사 {r['news_n']}건 (겹침 {r.get('news_ov', 0)}) — {r['news_first']}")
        elif r.get("news_n") == 0:
            L.append("- ❌ 관련 기사를 못 찾았다 — 미검증 커뮤 글이다")
        for m in r["members"]:
            L.append(f"- [{m['site_name']}] [{m['title'][:52]}]({m['link']})")
        L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--group-th", type=float, default=0.30)
    ap.add_argument("--min-fit", type=float, default=-0.60,
                    help="이 밑으로는 버린다 (짤·팬질·성인물 걸러내기)")
    ap.add_argument("--drop", default="정치,경제,FIFA",
                    help="뺄 갈래. 경제·정치는 다른 채널에서 다룬다. "
                         "FIFA 는 짹짹(축구)에서 무조건 뺀다(사장님 지시 2026-08-21). "
                         "`--only FIFA` 로 뭐가 걸렸는지 볼 수 있다. "
                         "'' 로 주면 아무것도 안 뺀다")
    ap.add_argument("--only", default="",
                    help="이 갈래만 본다 (예: 잡학,이슈)")
    ap.add_argument("--sport", action="store_true",
                    help="짹짹·짧뷰·칩칩용 묶음 스위치 — `--only 축구,골프,춤 --tag sport` 와 같다. "
                         "★예약 .cmd 가 한글 인자를 넘기지 않아도 되게 하려고 둔 것이다 "
                         "(cmd 파일에 한글이 들어가면 콘솔 코드페이지에 따라 깨진다)")
    ap.add_argument("--tag", default="",
                    help="결과 파일 앞머리를 바꾼다 (예: sport). 갈래 걸러 돌릴 때 쓴다 — "
                         "안 주면 정규 커뮤 시트를 덮어쓴다")
    ap.add_argument("--clip", action="store_true",
                    help="영상·gif 가 붙은 글만 본다. 짹짹·짧뷰·칩칩처럼 "
                         "**영상을 재창작**하는 채널용이다 (갤 개념글은 여론 글이 태반이라 "
                         "이걸 안 켜면 잡담만 올라온다)")
    ap.add_argument("--trends", action="store_true", default=True,
                    help="구글 트렌드 가산점 (기본 켜짐). 소재원이 아니라 가산점이다")
    ap.add_argument("--no-trends", dest="trends", action="store_false")
    ap.add_argument("--accum-hours", type=float, default=24.0,
                    help="지난 실행 결과를 몇 시간치까지 합칠까. "
                         "실시간 베스트는 몇 시간이면 갈리므로 여러 번 돌려 쌓는다. "
                         "0 이면 이번 것만")
    ap.add_argument("--news", action="store_true", default=True,
                    help="네이버 뉴스 교차확인 (기본 켜짐)")
    ap.add_argument("--no-news", dest="news", action="store_false")
    ap.add_argument("--news-n", type=int, default=60,
                    help="뉴스 교차확인할 상위 후보 수 (결과가 점수에 반영된다)")
    ap.add_argument("--no-seen", action="store_true", help="중복 제거 끄기")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    t0 = time.time()
    raw, notes = gather()
    print(f"수집 {len(raw)}건 / {time.time() - t0:.1f}초")
    for k, _n, _kd, _u, _p in SITES:
        print(f"  {SITE_NAME[k]:<10} {notes.get(k, '-')}")
    if not raw:
        print("아무것도 못 긁었다. 네트워크나 차단을 확인하라.")
        return 1

    save_raw(raw, stamp)
    raw, added = load_accum(raw, a.accum_hours)
    if added:
        print(f"지난 {a.accum_hours:.0f}시간치 누적 → {len(raw)}건 (+{added})")

    global TRENDS
    TRENDS = fetch_trends(sess()) if a.trends else {}
    if TRENDS:
        print("구글 트렌드 — " + ", ".join(
            f"{k}({v})" for k, v in sorted(TRENDS.items(), key=lambda kv: -kv[1])[:8]))

    normalize(raw)
    events = group_events(raw, th=a.group_th)
    for e in events:
        score_item(e)

    tally = {}
    for e in events:
        tally[e["topic"]] = tally.get(e["topic"], 0) + 1
    print("갈래 — " + "  ".join(f"{k} {v}" for k, v in
                                sorted(tally.items(), key=lambda kv: -kv[1])))

    if a.sport:                       # 한글 인자를 .cmd 밖으로 빼기 위한 묶음
        if not a.only:
            # ★춤은 뺐다 (2026-08-21) — 칩칩 전용 헌터(`ref_chipchip/hunt.py`)가
            #   소스 채널 풀로 훨씬 잘 잡는다. 같은 일을 두 군데서 하면 헷갈리기만 한다.
            #   축구·골프도 클립 본진은 `ref_sport/hunt.py` 다 — 이쪽은 **커뮤 글**로
            #   '무슨 일이 있었나'를 알려주는 레이더 몫만 한다
            a.only = "축구,골프"
        if not a.tag:
            a.tag = "sport"
    drop = {x.strip() for x in a.drop.split(",") if x.strip()}
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    seen = load_seen() if not a.no_seen else {"ids": [], "titles": []}
    events = [e for e in events
              if e["fit"] >= a.min_fit
              and e["topic"] not in drop
              and (not only or e["topic"] in only)
              and (not a.clip or has_clip(e.get("title"), e.get("cate")))
              and not is_seen(e, seen)]
    if drop:
        print(f"  → {'·'.join(sorted(drop))} 빼고 {len(events)}묶음")
    if a.clip:
        print(f"  → 영상 붙은 것만 {len(events)}묶음")
    events.sort(key=lambda x: -x["score"])

    if a.news and events:
        s = sess()
        cand = events[:a.news_n]
        print(f"뉴스 교차확인 {len(cand)}건 …")
        # ★몰아치면 네이버가 빈 껍데기를 주다가 끝내 403 으로 막는다
        #   (2026-08-21 실기 — 하루 종일 막혔다). 동시 2 로 눌러 둔다.
        with cf.ThreadPoolExecutor(max_workers=2) as ex:
            futs = {ex.submit(news_check, s, r["title"]): r for r in cand}
            for f in cf.as_completed(futs):
                r = futs[f]
                try:
                    r["news_n"], r["news_first"], r["news_ov"] = f.result()
                except Exception:                           # noqa: BLE001
                    r["news_n"], r["news_first"], r["news_ov"] = -1, "", 0.0
        # 기사로 뒷받침되는 이슈를 올리고, 커뮤 안에서만 도는 잡담을 내린다.
        # ★버리지는 않는다 — 언론이 아직 안 받은 특종일 수도 있어 사람이 본다.
        for r in events:
            ov = r.get("news_ov", 0.0)
            n = r.get("news_n")
            if n is None:
                continue
            # ★건수가 아니라 겹침으로 판정한다. 겹침 0.2 미만은 '검색은 됐지만
            #   딴 사건'이다 — 실측: '절이나 교회를 다니지 마십시오' 가 무관한
            #   북카페 기사 7건을 물어 와 3위까지 올라왔다.
            if n <= 0 or ov < 0.20:
                r["score"] = round(r["score"] * 0.55, 1)
                r["news_weak"] = True
            else:
                r["score"] = round(r["score"] * (1 + 0.55 * min(ov * 1.6, 1.0)), 1)
        events.sort(key=lambda x: -x["score"])

    rows = events[:a.top]

    meta = {"stamp": stamp, "n_raw": len(raw), "n_ev": len(events),
            "notes": notes, "news_on": a.news}
    # ★꼬리표를 주면 **파일 이름 앞머리가 바뀐다**(`hunt_` 가 아니라 `sport_`).
    #   알림기가 `hunt_*.json` 중 최신을 집어 가므로, 같은 이름으로 쓰면
    #   갈래 걸러 돌린 결과가 정규 커뮤 알림을 덮어쓴다. 그래서 앞머리를 가른다.
    #   누적 원자료(raw_*.json)는 같은 폴더를 그대로 쓴다 — 물량이 얇아 공유가 이득이다.
    pre = a.tag if a.tag else "hunt"
    md = os.path.join(OUT, f"{pre}_{stamp}.md")
    write_sheet(rows, md, meta)
    json.dump({"meta": meta, "rows": rows},
              open(os.path.join(OUT, f"{pre}_{stamp}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if a.tag:                      # 고정 경로본 — 알림기가 이걸 본다
        write_sheet(rows, os.path.join(OUT, f"_최신시트_{a.tag}.md"), meta)
        json.dump({"meta": meta, "rows": rows},
                  open(os.path.join(OUT, f"_최신시트_{a.tag}.json"), "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n시트 → {md}")
    for i, r in enumerate(rows[:14], 1):
        sn = "·".join(SITE_NAME.get(x, x) for x in r["sites"][:3])
        nc = r.get("news_n")
        if nc is None:
            tag = ""
        elif nc <= 0:
            tag = "  [기사없음]"
        else:
            tag = f"  [기사{nc}·겹침{r.get('news_ov', 0):.2f}]"
        tr = f" 🔥{r['trend']}" if r.get("trend") else ""
        print(f"{i:>2}. {r['score']:>6}  {r.get('topic', '-'):<4} {sn:<14} "
              f"{r['title'][:38]}{tr}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
