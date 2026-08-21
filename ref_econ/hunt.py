# -*- coding: utf-8 -*-
"""
경제 뇌전구 소재 발굴기 (1단계 — 넓게 긁고 실측 반응으로 점수)

네이버 뉴스 경제(101) 에서 후보를 긁어와, 기사마다 실제 댓글수·감정반응을
API 로 재고 점수순으로 세운다. 사람은 시트를 보고 번호 하나만 고르면 된다.

  python ref_econ/hunt.py                    # 기본: 경제, 상위 25
  python ref_econ/hunt.py --top 40
  python ref_econ/hunt.py --hours 12         # 최근 12시간 기사만
  python ref_econ/hunt.py --sid 101,105      # 경제 + IT/과학
  python ref_econ/hunt.py --min-comments 50

결과: ref_econ/out/hunt_<날짜시각>.json  +  .md (사람이 보는 시트)
"""
import argparse
import concurrent.futures as cf
import html
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from math import log10

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SEEN_PATH = os.path.join(HERE, "seen.json")
FIT_PATH = os.path.join(HERE, "channel_fit.json")

sys.path.insert(0, HERE)
from shapes import shape_of                        # noqa: E402  (learn.py 와 공용)


FIT_W = {}          # 꼴 → {"mult": 배수}. main 에서 채운다


def load_fit():
    """채널 실적 가중치. `learn.py` 가 만든다. 없으면 전부 1.0 으로 돈다 —
    새 채널이나 다른 채널에 이 발굴기를 쓸 때 그냥 동작해야 한다."""
    try:
        f = json.load(open(FIT_PATH, encoding="utf-8"))
        return f.get("weights", {}), f.get("stamp", ""), f.get("n_mature", 0)
    except Exception:
        return {}, "", 0

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

SECTION_NAME = {"101": "경제", "105": "IT/과학", "100": "정치",
                "102": "사회", "103": "생활/문화", "104": "세계"}

# 네이버 반응 라벨 (reactionTextMap.ko 실측 2026-08-20)
# ★현재 노출되는 건 아래 5종뿐이다. 옛 좋아요/화나요/슬퍼요 세트는 없어졌으니
#   'angry 비율' 같은 걸로 논쟁도를 재려 하지 마라 — 항상 0 이 나온다.
REACT_KO = {"useful": "쏠쏠정보", "wow": "흥미진진", "touched": "공감백배",
            "analytical": "분석탁월", "recommend": "후속강추",
            "like": "좋아요", "warm": "훈훈해요", "sad": "슬퍼요",
            "angry": "화나요", "want": "후속요청"}
INFO_R = ("useful", "wow", "analytical")     # 정보·놀라움 — 뇌전구 결에 맞는다
FEEL_R = ("touched", "recommend", "warm")    # 공감·화제성

# ── 뇌전구 적합도 사전 ────────────────────────────────────────────────
# 납품 이력에서 뽑은 패턴: "A인데 B" 역설 + 구체적 숫자 + 순위/최초
PARADOX = ["는데", "은데", "불구", "오히려", "알고 보니", "알고보니", "사실은",
           "반전", "뒤집", "정작", "그런데", "하지만", "인데도", "줄 알았"]
SUPER = ["최다", "최대", "최초", "최고", "처음", "사상", "역대", "1위", "앞질",
         "제쳤", "제치", "추월", "돌파", "신기록", "유일", "세계 1", "굴욕"]
SHOCK = ["반토막", "급등", "급락", "폭락", "폭등", "무너", "터졌", "멈췄", "끊",
         "철수", "포기", "충격", "적자", "흑자", "구조조정", "감원", "손절",
         "빚", "파산", "회생", "역대급", "사라졌", "떠났"]
# 시세·공시·행사 같은 하루살이 기사 — 뇌전구로 뒤집을 알맹이가 없다
NOISE = ["[표]", "[특징주]", "[fn", "[마켓", "[시황", "[매매동향", "[공시",
         "[게시판", "[인사", "[부고", "[포토", "[영상", "[사진",
         "코스피", "코스닥", "환율", "개장", "마감", "시황", "증시",
         "인사", "부고", "동정", "분양", "채용", "오늘의", "주간전망",
         "장중", "상한가", "하한가", "블록딜", "유상증자", "조간", "브리핑"]
NUM_UNIT = re.compile(r"\d+\s*(?:%|％|배|억|조|만|천|위|명|건|년|개국|퍼센트)")

# ── 갈래 ──────────────────────────────────────────────────────────────
# 네이버는 전부 '경제' 한 덩어리로 준다. 증시 기사와 전세 제도 기사가
# 같은 칸에 섞여 있으면 고르기가 어려워 갈래를 따로 붙인다.
LANES = [
    ("부동산", ["전세", "월세", "임대", "집값", "아파트", "분양", "재건축", "재개발",
                "청약", "주담대", "매매가", "호가", "부동산", "공시가", "전셋값",
                "집주인", "세입자", "보증금", "다주택", "임대차"]),
    ("증시", ["코스피", "코스닥", "주가", "증시", "개미", "상장", "공모주", "배당",
              "자사주", "증권", "매수", "매도", "시총", "레버리지", "서학", "ETF",
              "주주환원", "지수", "종목", "하이닉스", "삼전", "목표주가", "시가총액",
              "IB", "물린", "급등", "폭등", "만원 간다"]),
    ("거시", ["환율", "금리", "물가", "수출", "무역", "한국은행", "한은", "GDP",
              "경상수지", "인플레", "기준금리", "가계부채", "재정", "국채", "달러"]),
    ("제도", ["정부", "법안", "개정", "지원금", "보험", "연금", "세금", "규제",
              "도입", "제도", "정책", "국회", "부처", "장관", "공공", "예산",
              "세제", "급여", "혜택", "신탁"]),
    ("기업", ["삼성", "SK", "현대", "LG", "실적", "영업이익", "공장", "인수",
              "합병", "파운드리", "반도체", "배터리", "조선", "항공", "노조",
              "성과급", "임금", "대표이사", "회장"]),
    ("생활", ["편의점", "마트", "외식", "배달", "프랜차이즈", "가격 인상", "물가상승",
              "치킨", "커피", "라면", "소비자", "택배", "여행", "항공권", "카페",
              "매장", "점포", "창업", "빽다방", "메뉴", "잔씩", "불티"]),
]


def lane_of(title):
    best, hi = "", 0
    for name, words in LANES:
        n = sum(1 for w in words if w in title)
        if n > hi:
            best, hi = name, n
    return best or "기타"


# ── 유틸 ──────────────────────────────────────────────────────────────
def sess():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def get_text(s, url, timeout=15):
    """★페이지마다 인코딩이 다르다. 랭킹(.naver)은 EUC-KR, 섹션은 UTF-8.
    utf-8 로 못박으면 한글이 통째로 깨지고 시간·제목 파싱이 조용히 망가진다."""
    r = s.get(url, timeout=timeout)
    b = r.content
    enc = None
    m = re.search(r"charset=([\w\-]+)", r.headers.get("Content-Type", ""), re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb"charset=[\"']?([\w\-]+)", b[:2048], re.I)
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
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


def parse_age_hours(txt):
    """'3시간전' '12분전' '2일전' → 시간(float). 못 읽으면 None."""
    if not txt:
        return None
    txt = txt.replace(" ", "")
    m = re.search(r"(\d+)분전", txt)
    if m:
        return int(m.group(1)) / 60.0
    m = re.search(r"(\d+)시간전", txt)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)일전", txt)
    if m:
        return int(m.group(1)) * 24.0
    m = re.search(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})", txt)
    if m:
        d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return max((datetime.now() - d).total_seconds() / 3600.0, 0.0)
    return None


# ── 수집 ──────────────────────────────────────────────────────────────
def collect_global_rank(s):
    """전체 랭킹 2종(많이 본 / 댓글 많은) → {기사키: {탭: 순위}}

    ★랭킹 페이지의 sectionId 파라미터는 **무시된다** (실측 2026-08-20:
      sectionId 를 101/100 으로 바꿔도, 아예 빼도 똑같은 375건이 온다).
      전 섹션 언론사별 랭킹이라 경제만 걸러내는 데는 못 쓴다.
      그래서 후보 풀로 쓰지 않고 '전 섹션 통틀어 랭킹에 들었다'는 가산점으로만 쓴다.
      SECTION_RANKING_NEWS?sid= 도 마찬가지로 sid 를 무시한다."""
    marks = {}
    for url, tag in [
        ("https://news.naver.com/main/ranking/popularDay.naver", "많이본"),
        ("https://news.naver.com/main/ranking/popularMemo.naver", "댓글많은"),
    ]:
        try:
            h = get_text(s, url)
        except Exception as e:
            print(f"  ! 랭킹({tag}) 실패: {e}")
            continue
        n = 0
        for m in re.finditer(
            r'<a href="[^"]*?/article/(\d{3})/(\d{10})[^"]*"\s+class="list_title[^"]*"', h
        ):
            key = f"{m.group(1)}_{m.group(2)}"
            n += 1
            marks.setdefault(key, {})
            marks[key].setdefault(tag, n)
        print(f"  전체랭킹 {tag:<6} {n:>3}건")
    return marks


def parse_items(h, sid, tag):
    """섹션 페이지·섹션목록 API 가 같은 sa_item 구조를 쓴다. 덩어리로 잘라 파싱."""
    out = {}
    for chunk in h.split('class="sa_item')[1:]:
        chunk = chunk[:4000]
        m = re.search(r'/article/(\d{3})/(\d{10})', chunk)
        if not m:
            continue
        oid, aid = m.group(1), m.group(2)
        key = f"{oid}_{aid}"
        if key in out:
            continue
        mt = re.search(r'class="sa_text_title[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
        title = strip_tags(mt.group(1)) if mt else ""
        if not title:
            continue
        # ★<div class="sa_text_datetime is_recent"><b>18분전</b></div> — span 이 아니라 div 다
        md = re.search(r'class="sa_text_datetime[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        tm = strip_tags(md.group(1)) if md else ""
        mp = re.search(r'class="sa_text_press[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        press = strip_tags(mp.group(1)) if mp else ""
        # ★네이버가 같은 사건을 묶어 두는 클러스터 id. 이게 있어야 한 사건이
        #   매체별로 3~4건씩 후보에 겹쳐 오르는 걸 막을 수 있다.
        mcl = re.search(r'href="/cluster/(c_\d+_\d+)/', chunk)
        out[key] = {"oid": oid, "aid": aid, "title": title,
                    "age_hours": parse_age_hours(tm), "age_text": tm,
                    "press": press, "sid": sid, "src": {tag: len(out) + 1},
                    "cluster": mcl.group(1) if mcl else ""}
    return out


def collect_section(s, sid, pages):
    """경제 섹션 기사 목록. ★이 경로만 sid 를 제대로 존중한다
    (실측: SECTION_ARTICLE_LIST sid=101 과 sid=100 은 겹치는 기사가 0건).

    섹션 페이지 1장 + SECTION_ARTICLE_LIST 페이지네이션.
    커서는 항목의 data-cursor(yyyymmddHHMMSS) 를 next= 로 넘긴다."""
    pool = {}
    try:
        h = get_text(s, f"https://news.naver.com/section/{sid}")
        pool.update(parse_items(h, sid, "섹션"))
    except Exception as e:
        print(f"  ! 섹션 페이지 실패: {e}")
        h = ""

    cur = ""
    mc = re.findall(r'data-cursor="(\d{14})"', h)
    if mc:
        cur = mc[-1]

    for pg in range(1, pages + 1):
        try:
            u = ("https://news.naver.com/section/template/SECTION_ARTICLE_LIST"
                 f"?sid={sid}&sid2=&cluid=&pageNo={pg}&date=&next={cur}&_=1")
            r = s.get(u, headers={"Referer": f"https://news.naver.com/section/{sid}"},
                      timeout=15)
            hh = r.json()["renderedComponent"].get("SECTION_ARTICLE_LIST") or ""
        except Exception as e:
            print(f"  ! 목록 p{pg} 실패: {e}")
            break
        if not hh:
            break
        got = parse_items(hh, sid, "섹션")
        new = {k: v for k, v in got.items() if k not in pool}
        pool.update(new)
        mc = re.findall(r'data-cursor="(\d{14})"', hh)
        if mc:
            cur = mc[-1]
        if not new:
            break
    return pool


def gather(sids, pages):
    s = sess()
    print("[전체 랭킹] 가산점용 수집")
    marks = collect_global_rank(s)

    pool = {}
    for sid in sids:
        got = collect_section(s, sid, pages)
        print(f"[{SECTION_NAME.get(sid, sid)}] 섹션 기사 {len(got)}건")
        for k, v in got.items():
            if k not in pool:
                pool[k] = v

    hit = 0
    for k, v in pool.items():
        if k in marks:
            v["src"].update(marks[k])
            hit += 1
    print(f"이 중 전체 랭킹에도 든 기사 {hit}건")
    return pool


# ── 실측: 댓글수 · 감정반응 ───────────────────────────────────────────
def fetch_metrics(item):
    oid, aid = item["oid"], item["aid"]
    s = sess()
    ref = f"https://n.news.naver.com/article/{oid}/{aid}"

    comments = 0
    try:
        u = ("https://apis.naver.com/commentBox/cbox/web_naver_list_jsonp.json"
             f"?ticket=news&templateId=default_economy&pool=cbox5&lang=ko&country=KR"
             f"&objectId=news{oid}%2C{aid}&pageSize=1&indexSize=1&page=1")
        t = s.get(u, headers={"Referer": ref}, timeout=12).text
        m = re.search(r'"count":\{[^}]*"total":(\d+)', t)
        if m:
            comments = int(m.group(1))
    except Exception:
        pass

    reactions, rmap = 0, {}
    try:
        u = ("https://news.like.naver.com/v1/search/contents"
             f"?suppress_response_codes=true&q=NEWS%5Bne_{oid}_{aid}%5D")
        d = s.get(u, headers={"Referer": "https://n.news.naver.com/"}, timeout=12).json()
        for x in d["contents"][0]["reactions"]:
            rmap[x["reactionType"]] = x["count"]
        reactions = sum(rmap.values())
    except Exception:
        pass

    item["comments"] = comments
    item["reactions"] = reactions
    item["react_map"] = rmap
    return item


# ── 점수 ──────────────────────────────────────────────────────────────
def title_fit(title):
    """뇌전구 적합도 -1.0 ~ +1.0. 역설·숫자·순위는 +, 시세·공시는 -."""
    t = title
    sc = 0.0
    hit = []
    if any(w in t for w in PARADOX):
        sc += 0.35; hit.append("역설")
    if any(w in t for w in SUPER):
        sc += 0.30; hit.append("최초/최다")
    if any(w in t for w in SHOCK):
        sc += 0.25; hit.append("급변")
    if NUM_UNIT.search(t):
        sc += 0.30; hit.append("숫자")
    n_noise = sum(1 for w in NOISE if w in t)
    if n_noise:
        sc -= 0.45 * min(n_noise, 2); hit.append(f"시세성-{n_noise}")
    if len(t) < 14:
        sc -= 0.15
    return max(-1.0, min(1.0, sc)), hit


def rank_bonus(src):
    """전 섹션 통틀어 랭킹에 든 경제 기사는 드물다 — 들었으면 그 자체가 신호."""
    b = 0.0
    if "댓글많은" in src:              # 실제로 사람이 말을 얹은 기사
        b += max(0.0, 30 - src["댓글많은"] * 0.06)
    if "많이본" in src:
        b += max(0.0, 20 - src["많이본"] * 0.04)
    return b


TITLE_STRIP = re.compile(r"[\[\]\(\)\"'“”‘’…·,.\-—~!?%\s]+")


def bigrams(t):
    t = TITLE_STRIP.sub("", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def title_sim(a, b):
    """포함도(짧은 쪽 기준). 같은 사건인데 매체마다 제목 길이가 달라서
    자카드는 너무 짜게 나온다.
    ★겹치는 글자쌍이 5개 미만이면 0 으로 본다 — 짧은 제목이 긴 제목 안에
      우연히 들어가 엉뚱하게 묶이는 걸 막는다."""
    if not a or not b:
        return 0.0
    ov = len(a & b)
    if ov < 5:
        return 0.0
    return ov / min(len(a), len(b))


def group_events(items, th=0.32):
    """같은 사건을 하나로 묶는다.

    한 사건을 매체 10곳이 쓰면 후보 목록이 그 사건 하나로 도배된다.
    두 신호를 같이 쓴다 —
      ① 네이버 클러스터 id: 정확하지만 목록에 붙는 건 일부뿐이다
         (실측 138건 중 10건). 붙은 것만 정답으로 쓴다.
      ② 제목 글자 bigram 포함도: 커버리지 100%. 클러스터가 놓친
         '전세 안심신탁' 7건 같은 걸 잡아낸다.

    ★대표와만 비교하는 그리디 방식이다. 전체쌍 union-find 로 하면
      A-B, B-C 가 이어져 상관없는 45건이 한 덩어리가 된다(실측).
    """
    order = sorted(items, key=lambda x: -x.get("comments", 0))
    groups = []          # [{"rep": item, "bg": set, "cluster": str, "mem": [...]}]
    for it in order:
        bgs = bigrams(it["title"])
        cid = it.get("cluster") or ""
        placed = False
        for g in groups:
            sm = title_sim(bgs, g["bg"])
            # 클러스터가 같으면 문턱을 절반으로 깎아 준다 — 면제가 아니다.
            # 면제로 두면 넓은 주제묶음 하나가 서로 상관없는 사건을 다 삼킨다.
            same_cluster = bool(cid) and cid == g["cluster"]
            if sm >= th or (same_cluster and sm >= th * 0.5):
                g["mem"].append(it)
                if not g["cluster"] and cid:
                    g["cluster"] = cid
                placed = True
                break
        if not placed:
            groups.append({"rep": it, "bg": bgs, "cluster": cid, "mem": [it]})

    out = []
    for gg in groups:
        g = gg["mem"]
        rep = dict(g[0])
        rep["cluster_n"] = len(g)
        rep["cluster_comments"] = sum(x.get("comments", 0) for x in g)
        rep["cluster_reactions"] = sum(x.get("reactions", 0) for x in g)
        rm = {}
        for x in g:
            for k2, v in x.get("react_map", {}).items():
                rm[k2] = rm.get(k2, 0) + v
        rep["react_map"] = rm
        rep["also"] = [x.get("press", "") for x in g[1:9] if x.get("press")]
        # 같은 사건 다른 매체 기사 — 사진 후보를 넓힐 때 쓴다.
        # 뇌전구는 컷마다 다른 그림이 필요해서 한 기사 사진만으론 대개 모자란다.
        rep["members"] = [{"oid": x["oid"], "aid": x["aid"],
                           "press": x.get("press", ""), "title": x["title"]}
                          for x in g[:10]]
        # 사건이 터진 지 얼마나 됐나 = 그 묶음에서 가장 오래된 기사
        ages = [x["age_hours"] for x in g if x.get("age_hours") is not None]
        if ages:
            rep["age_hours"] = max(ages)
        # 랭킹 진입은 묶음 안 어느 기사가 들었어도 인정한다
        src = {}
        for x in g:
            for k2, v in x.get("src", {}).items():
                if k2 not in src or v < src[k2]:
                    src[k2] = v
        rep["src"] = src
        out.append(rep)
    return out


def score_item(it):
    com = it.get("cluster_comments", it.get("comments", 0))
    rea = it.get("cluster_reactions", it.get("reactions", 0))
    hrs = it.get("age_hours")
    hrs_eff = max(hrs if hrs is not None else 6.0, 0.7)

    heat = 55 * log10(1 + com) + 20 * log10(1 + rea)
    vel = 38 * log10(1 + com / hrs_eff)          # 신선한데 벌써 뜨거운 사건
    spread = 20 * log10(it.get("cluster_n", 1))  # 여러 매체가 동시에 받아썼다
    rb = rank_bonus(it.get("src", {}))
    fit, hit = title_fit(it["title"])

    rm = it.get("react_map", {})
    tot = sum(rm.values()) or 1
    info = sum(rm.get(k, 0) for k in INFO_R) / tot
    feel = sum(rm.get(k, 0) for k in FEEL_R) / tot

    # 경제 뇌전구는 '몰랐던 사실'을 뒤집는 포맷이라
    # 쏠쏠정보·흥미진진·분석탁월 쪽으로 기운 기사가 결이 맞는다
    tone = 14 * info + 4 * feel

    base = (heat + vel + spread + rb + tone) * (1 + 0.40 * fit)

    # ★채널 실적 가중치 — 네이버에서 반응이 좋아도 이 채널에서 안 먹히는 꼴이 있다.
    #   실측(11편): 한국vs해외 16,354 · 인물거액 8,102 · 증시기업 4,024
    #              · 사연 2,658 · 제도거시 2,409 (채널 중앙 4,119)
    #   표본이 적어 learn.py 가 1.0 쪽으로 당겨 둔 배수를 쓴다.
    sh = shape_of(it["title"])
    w = (FIT_W.get(sh) or {}).get("mult", 1.0)
    it["shape"] = sh
    it["ch_mult"] = round(w, 2)
    it["naver_score"] = round(base, 1)
    it["score"] = round(base * w, 1)
    it["lane"] = lane_of(it["title"])
    it["fit"] = round(fit, 2)
    it["fit_hit"] = hit
    it["feel_pct"] = round(feel * 100)
    it["info_pct"] = round(info * 100)
    it["parts"] = {"heat": round(heat, 1), "vel": round(vel, 1),
                   "spread": round(spread, 1), "rank": round(rb, 1),
                   "tone": round(tone, 1)}
    return it


# ── 중복 제거 ─────────────────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            return json.load(open(SEEN_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"ids": [], "titles": []}


def toks(t):
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]+", t) if len(w) >= 2}


def is_seen(it, seen):
    if f"{it['oid']}_{it['aid']}" in seen.get("ids", []):
        return True
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
    L = []
    L.append(f"# 경제 뇌전구 소재 후보 — {meta['stamp']}")
    L.append("")
    L.append(f"기사 {meta['pool']}건 수집 → {meta['measured']}건 반응 실측 → "
             f"{meta['events']}개 사건으로 묶음 → 기존회차 {meta['dropped_seen']}개 제외 "
             f"→ 상위 {len(rows)}개")
    L.append("")
    L.append("| # | 꼴 | 채널배수 | 최종 | 네이버 | 댓글 | 반응 | 매체 | 경과 "
             "| 정보% | 갈래 | 제목 |")
    L.append("|--:|:--|--:|--:|--:|--:|--:|--:|--:|--:|:--|---|")
    for i, r in enumerate(rows, 1):
        age = f"{r['age_hours']:.0f}h" if r.get("age_hours") is not None else "?"
        L.append(f"| {i} | {r['shape']} | ×{r['ch_mult']} | **{r['score']}** "
                 f"| {r['naver_score']} | {r['cluster_comments']} "
                 f"| {r['cluster_reactions']} | {r['cluster_n']} | {age} "
                 f"| {r['info_pct']} | {r['lane']} | {r['title']} |")
    L.append("")
    L.append("---")
    L.append("")
    for i, r in enumerate(rows, 1):
        age = f"{r['age_hours']:.0f}시간 전" if r.get("age_hours") is not None else "시각미상"
        src = " · ".join(f"{k} {v}위" for k, v in r.get("src", {}).items())
        rm = r.get("react_map", {})
        top_r = sorted(rm.items(), key=lambda x: -x[1])[:3]
        rs = " · ".join(f"{REACT_KO.get(k, k)} {v}" for k, v in top_r) or "반응 없음"
        L.append(f"### {i}. {r['title']}")
        L.append(f"- 최종 **{r['score']}** = 네이버 {r['naver_score']} "
                 f"× 채널 {r['shape']} ×{r['ch_mult']}")
        L.append(f"- 네이버 내역 (열기 {r['parts']['heat']} / "
                 f"속도 {r['parts']['vel']} / 확산 {r['parts']['spread']} / "
                 f"랭킹 {r['parts']['rank']} / 결 {r['parts']['tone']}"
                 f" / 적합도 {r['fit']:+.2f} {','.join(r['fit_hit']) or '-'})")
        L.append(f"- 댓글 **{r['cluster_comments']}** · 반응 {r['cluster_reactions']} ({rs}) · {age}")
        if r["cluster_n"] > 1:
            also = ", ".join(r.get("also", [])[:6])
            L.append(f"- **{r['cluster_n']}개 매체가 보도** ({r.get('press','')} 외 {also})")
        elif r.get("press"):
            L.append(f"- {r['press']} 단독")
        if src:
            L.append(f"- 전체 랭킹: {src}")
        L.append(f"- https://n.news.naver.com/article/{r['oid']}/{r['aid']}")
        L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", default="101", help="섹션 id, 쉼표로 여러 개 (101 경제)")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--hours", type=float, default=36.0, help="이보다 오래된 기사는 버린다")
    ap.add_argument("--min-comments", type=int, default=0)
    # ★8장(=약 6~7시간치)이 기본이었는데, 하루 3번 돌리면 20~23시 기사가
    #   어느 실행에도 안 잡히는 구멍이 생겼다. 16장이면 10시간치라 이어진다.
    ap.add_argument("--pages", type=int, default=16, help="섹션 목록을 몇 장 넘길지 (1장 36건)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-seen", action="store_true", help="중복 제거를 끈다")
    ap.add_argument("--from-raw", dest="from_raw", default="",
                    help="out/raw_*.json 에서 다시 굴린다 (실측 생략)")
    ap.add_argument("--no-fit", dest="no_fit", action="store_true",
                    help="채널 실적 가중치를 끄고 네이버 반응만으로 세운다")
    ap.add_argument("--group-th", dest="group_th", type=float, default=0.32,
                    help="사건 묶는 제목 유사도 임계값 (낮출수록 많이 묶는다)")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    sids = [x.strip() for x in a.sid.split(",") if x.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    global FIT_W
    if not a.no_fit:
        FIT_W, fstamp, fn = load_fit()
        if FIT_W:
            ws = " · ".join(f"{k} ×{v['mult']}" for k, v in
                            sorted(FIT_W.items(), key=lambda x: -x[1]["mult"]))
            print(f"채널 실적 가중치 ({fstamp} 기준 {fn}편): {ws}")
        else:
            print("채널 실적 가중치 없음 — python ref_econ/learn.py 로 만들 수 있다")

    if a.from_raw:
        # 실측은 75초쯤 걸린다. 점수·묶음만 손볼 때는 캐시에서 다시 굴린다.
        raw = json.load(open(a.from_raw, encoding="utf-8"))
        items = raw["items"]
        pool = {f"{x['oid']}_{x['aid']}": x for x in items}
        print(f"캐시에서 {len(items)}건 불러옴: {a.from_raw}")
    else:
        t0 = time.time()
        pool = gather(sids, a.pages)
        print(f"\n후보 {len(pool)}건 수집 ({time.time()-t0:.1f}s)")

        # ★몇 시간치가 실제로 긁혔는지 반드시 찍는다.
        #   섹션 목록은 페이지 수만큼만 거슬러 올라가므로 --hours 를 아무리 키워도
        #   그보다 옛 기사는 애초에 없다. 이걸 안 보여 주면 '36시간 필터'라는
        #   말만 믿고 사실은 6시간치만 보고 있었다는 걸 아무도 모른다(실제로 그랬다).
        ages = [v["age_hours"] for v in pool.values() if v.get("age_hours") is not None]
        if ages:
            now_ = datetime.now()
            old = now_ - timedelta(hours=max(ages))
            new = now_ - timedelta(hours=min(ages))
            span = max(ages)
            print(f"긁힌 범위 {old:%m-%d %H:%M} ~ {new:%m-%d %H:%M} = {span:.1f}시간치")
            if span < 9:
                print(f"  ! {span:.1f}시간치뿐이다 — 하루 3번 돌리면 사이가 빈다. "
                      f"--pages 를 올려라 (지금 {a.pages}장)")

        items = list(pool.values())
        if a.hours:
            items = [x for x in items
                     if x.get("age_hours") is None or x["age_hours"] <= a.hours]
            print(f"최근 {a.hours:.0f}시간 필터 → {len(items)}건")

        print(f"반응 실측 중... (댓글 API + 감정 API, {a.workers} 병렬)")
        t1 = time.time()
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            items = list(ex.map(fetch_metrics, items))
        print(f"실측 완료 ({time.time()-t1:.1f}s)")
        rawp = os.path.join(OUT, f"raw_{stamp}.json")
        json.dump({"stamp": stamp, "sids": sids, "items": items},
                  open(rawp, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"실측 캐시: {rawp}")

    measured = len(items)
    items = group_events(items, a.group_th)
    multi = sum(1 for x in items if x["cluster_n"] > 1)
    print(f"같은 사건끼리 묶음 → {len(items)}개 사건 (2건 이상 묶인 사건 {multi}개)")

    if a.min_comments:
        items = [x for x in items if x["cluster_comments"] >= a.min_comments]

    seen = {"ids": [], "titles": []} if a.no_seen else load_seen()
    before = len(items)
    items = [x for x in items if not is_seen(x, seen)]
    dropped = before - len(items)
    if dropped:
        print(f"기존 회차와 겹치는 {dropped}건 제외")

    items = [score_item(x) for x in items]
    items.sort(key=lambda x: -x["score"])
    rows = items[: a.top]

    meta = {"stamp": datetime.now().strftime("%Y-%m-%d %H:%M"), "sids": sids,
            "pool": len(pool), "measured": measured, "events": len(items) + dropped,
            "dropped_seen": dropped}
    jp = os.path.join(OUT, f"hunt_{stamp}.json")
    mp = os.path.join(OUT, f"hunt_{stamp}.md")
    json.dump({"meta": meta, "items": rows}, open(jp, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    write_sheet(rows, mp, meta)
    # 예약 실행으로 돌 때 사장님이 바로 열 수 있게 고정 경로에도 쓴다.
    # (시각이 박힌 파일명은 폴더에서 찾아야 해서 불편하다)
    write_sheet(rows, os.path.join(OUT, "_최신시트.md"), meta)
    json.dump({"meta": meta, "items": rows},
              open(os.path.join(OUT, "_최신시트.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("\n" + "=" * 78)
    for i, r in enumerate(rows, 1):
        age = f"{r['age_hours']:.0f}h" if r.get("age_hours") is not None else " ?"
        print(f"{i:>2}. [{r['score']:>6.1f}] {r['shape']:<6}×{r['ch_mult']:<4} "
              f"댓{r['cluster_comments']:>5} 매체{r['cluster_n']:>3} {age:>4}  "
              f"{r['title'][:42]}")
    print("=" * 78)
    print(f"\n시트: {mp}\n원자료: {jp}")


if __name__ == "__main__":
    main()
