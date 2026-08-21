# -*- coding: utf-8 -*-
"""축구·골프 소재 발굴 — 소스 채널 풀에서 낚는다.

  1단 발굴  python ref_sport/hunt.py --topic 축구 --scout   유튜브 검색으로 풀을 넓힌다 (가끔·3분)
  2단 사냥  python ref_sport/hunt.py --topic 축구           풀을 재서 오늘의 후보 (매일·3분)
  검증본    python ref_sport/hunt.py --topic 축구 --best    이미 크게 터진 클립 중에서
  시트      python ref_sport/hunt.py --topic 축구 --sheet   후보 썸네일 → out/<주제>/_후보시트.jpg
  기록      python ref_sport/hunt.py --topic 축구 --took <videoId> ...

★엔진은 `ref_chipchip/hunt.py` (다른 세션, 2026-08-21) 를 그대로 본떴다.
  거기 주석에 적힌 함정들이 전부 실기로 얻은 것이라 손대지 않고 옮겼다 —
  md5 캐시키 · norm_ws · 0건일 때 질의 넓히기 · 중앙값 바닥 2000 · 배수 상한 25 등.
★주제(질의·갈래·차단)는 `topics.py` 에 있다. 이 파일은 엔진이다.
"""
import argparse
import hashlib
import io
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import topics as T                                        # noqa: E402

CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NS = {"a": "http://www.w3.org/2005/Atom",
      "yt": "http://www.youtube.com/xml/schemas/2015",
      "m": "http://search.yahoo.com/mrss/"}

HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
KANA = re.compile(r"[぀-ヿ]")

TOPIC = None            # 주제 이름 (예: '축구')
CFG = None              # topics.TOPICS[TOPIC]
POOL = SEEN = CLIPS = OUT = None


def setup(name):
    """주제를 고르고 그 주제 전용 파일 경로를 연다.

    ★파일을 주제마다 가른다. 하나로 합치면 축구 풀에 골프 채널이 섞여
      다음 실행부터 조용히 엉킨다 (회차마다 전용 workdir 를 파는 것과 같은 이유)."""
    global TOPIC, CFG, POOL, SEEN, CLIPS, OUT
    TOPIC, CFG = T.get(name)
    k = CFG["key"]
    POOL = os.path.join(HERE, f"pool_{k}.json")
    SEEN = os.path.join(HERE, f"seen_{k}.json")
    CLIPS = os.path.join(HERE, f"clips_{k}.json")
    OUT = os.path.join(HERE, "out", k)
    os.makedirs(OUT, exist_ok=True)


# ── 거르개 ──────────────────────────────────────────────────────────────
def shape_of(title):
    t = title.lower()
    for name, mult, kws in CFG["shapes"]:
        for k in kws:
            if k.lower() in t:
                return name, mult
    return "기타", 1.00


def in_topic(title):
    """주제 맥락이 있나 — 풀이 주제에서 새는 것을 막는 자리다.

    ★칩칩이 여기서 데였다. 질의를 넓히면 회수는 늘지만 엉뚱한 채널이 상위를 먹는다.
      축구는 특히 위험하다 — `fan invades pitch` 를 넓히면 야구·럭비가 딸려 온다."""
    t = title.lower()
    return any(k in t for k in CFG["context"])


def dropped(*texts):
    """무조건 뺄 것. 축구는 FIFA(대회·게임), 둘 다 게임 화면."""
    for t in texts:
        if not t:
            continue
        low = t.lower()
        for k in CFG["drop"]:
            if k in low:
                return True
    return False


def is_domestic(*texts):
    """이미 본 나라 원본인가.

    축구는 짹짹(한국)·神ショーツ(일본) 양쪽에 나가므로 한글·가나 둘 다 뺀다.
    골프는 짧뷰(한국) 하나뿐이라 **일본 것은 막지 않는다** — 한글만 본다.
    ★한자만 있는 것은 중국·대만일 수 있어 안 뺀다 (칩칩과 같은 판단)."""
    for t in texts:
        if not t:
            continue
        if HANGUL.search(t):
            return True
        if CFG["skip_kana"] and KANA.search(t):
            return True
    return False


BLOCK_FILE = None
_BLOCK = None


def blocked(handle, name=""):
    """눈으로 보고 모은 차단목록. ★파일이 있어도 SEED 와 **합친다** —
    파일이 생긴 뒤 새 차단이 조용히 무시되는 게 칩칩이 겪은 함정이다."""
    global _BLOCK, BLOCK_FILE
    if _BLOCK is None:
        BLOCK_FILE = os.path.join(HERE, f"block_{CFG['key']}.json")
        b = load(BLOCK_FILE, {}) or {}
        save(BLOCK_FILE, b)
        _BLOCK = {k.strip().lower() for k in b}
    return ((name or "").strip().lower() in _BLOCK
            or (handle or "").strip().lower().lstrip("@") in _BLOCK)


def permit_mark(name, handle):
    """소스로 쓸 수 있나 · 허락이 날 만한가.

    ◎ 구단·브랜드 = 영상이 홍보 수단이라 승낙이 잘 난다
    ○ 개인 크리에이터 = 본인 수익이 사업이라 승낙이 어렵다
    ⚑ 재포장 = 소스가 아니라 레이더. 여기 걸린 것은 원본을 따로 찾아라
    ✖ 미디어·중계 = 손대지 마라
    ※표시는 참고용이다. 설명을 덧붙이지 않는다 (사장님이 알아서 하신다)."""
    t = (name + " " + handle).lower()
    for kind, mark, kws in CFG["kinds"]:
        for k in kws:
            if k in t:
                return mark
    return "○"


# ── 내려받기 ────────────────────────────────────────────────────────────
def fetch(url, key, ttl_hours=6.0, sleep=1.2, lang="en-US,en;q=0.9"):
    """캐시가 살아 있으면 그걸 쓴다. 재실행이 공짜여야 파서를 마음껏 고친다."""
    dst = os.path.join(CACHE, key)
    if os.path.exists(dst) and os.path.getsize(dst) > 800:
        age = (time.time() - os.path.getmtime(dst)) / 3600
        if age < ttl_hours:
            return open(dst, encoding="utf-8", errors="ignore").read()
    time.sleep(sleep)                  # ★속도 제한 — 하루에 두 사이트를 잃은 적이 있다
    # ★PowerShell 의 `curl` 은 Invoke-WebRequest 별칭이라 -sSL 에서 죽는다. curl.exe 로 부른다
    subprocess.run(["curl.exe", "-sSL", "-A", UA,
                    "-H", f"Accept-Language: {lang}", "-o", dst, url],
                   capture_output=True)
    if os.path.exists(dst) and os.path.getsize(dst) > 800:
        return open(dst, encoding="utf-8", errors="ignore").read()
    return ""


def norm_ws(t):
    """★태그 속성 사이 줄바꿈 때문에 패턴이 조용히 0건이 된다. 먼저 뭉갠다."""
    return re.sub(r"\s+", " ", t)


def initdata(html):
    t = norm_ws(html)
    for pat in (r"var ytInitialData = (\{.*?\});</script>",
                r'ytInitialData"\]\s*=\s*(\{.*?\});</script>'):
        m = re.search(pat, t)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return None


def walk(node, key, out):
    if isinstance(node, dict):
        if key in node:
            out.append(node[key])
        for v in node.values():
            walk(v, key, out)
    elif isinstance(node, list):
        for v in node:
            walk(v, key, out)
    return out


def txt(n):
    if isinstance(n, str):
        return n
    if isinstance(n, dict):
        if "simpleText" in n:  return n["simpleText"]
        if "content" in n:     return n["content"]
        if "runs" in n:        return "".join(r.get("text", "") for r in n["runs"])
    return ""


def views_of(s):
    """★단위 글자를 대소문자 둘 다 받는다.

    영국 로케일(gl=GB)은 `114k views` 처럼 **소문자 k** 로 쓴다. 미국은 `114K` 다.
    대문자만 보던 원본을 그대로 옮겼더니 114,000 이 **114** 로 읽혀 조회수 문턱
    30만을 아무것도 못 넘었다 — 오류는 안 나고 '후보 0건'으로만 나온다
    (실기 2026-08-21, 축구 첫 발굴이 통째로 빈손이었다)."""
    if not s:
        return 0
    s = s.replace(",", "")
    m = re.search(r"([\d.]+)\s*(만|억|천|[KkMmBb])?", s)
    if not m:
        return 0
    u = m.group(2) or ""
    if u.isascii():
        u = u.upper()
    return int(float(m.group(1)) *
               {"천": 1e3, "만": 1e4, "억": 1e8, "K": 1e3, "M": 1e6, "B": 1e9}
               .get(u, 1))


def shorts_cards(html):
    """쇼츠 카드 → (videoId, 조회수, 제목). 검색 페이지·채널 /shorts 둘 다 같은 꼴이다."""
    data = initdata(html)
    if not data:
        return []
    rows, seen = [], set()
    for vm in walk(data, "shortsLockupViewModel", []):
        vid = (vm.get("onTap", {}).get("innertubeCommand", {})
                 .get("reelWatchEndpoint", {}).get("videoId", "")) or \
              vm.get("entityId", "").replace("shorts-shelf-item-", "")
        if not re.fullmatch(r"[\w-]{11}", vid or "") or vid in seen:
            continue
        seen.add(vid)
        ov = vm.get("overlayMetadata", {})
        rows.append((vid, views_of(txt(ov.get("secondaryText", ""))),
                     txt(ov.get("primaryText", ""))))
    return rows


def oembed(vid):
    """videoId → (채널명, 핸들). 쇼츠 카드엔 채널이 안 붙어 있어 이걸로 캔다."""
    raw = fetch(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch"
                f"?v={vid}&format=json", f"oe_{vid}.json", ttl_hours=24 * 30, sleep=0.5)
    try:
        d = json.loads(raw)
    except Exception:
        return "", ""
    return d.get("author_name", ""), d.get("author_url", "").rsplit("/", 1)[-1]


def load(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return default


def save(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def cap_per_channel(rows, cap):
    """★한 채널이 시트를 도배하지 못하게 막는다.

    축구 첫 사냥에서 `4erasyl4` 가 12칸 중 7칸을 먹었다 (실기 2026-08-21).
    같은 채널의 비슷한 편이 줄줄이 오르면 **고를 게 없는 시트**가 된다.
    점수 순서는 유지한 채 넘치는 것만 뒤로 뺀다."""
    if cap <= 0:
        return rows
    keep, spill, n = [], [], {}
    for r in rows:
        h = r.get("handle", "")
        if n.get(h, 0) < cap:
            n[h] = n.get(h, 0) + 1
            keep.append(r)
        else:
            spill.append(r)
    return keep + spill          # 버리진 않는다 — 뒤로 밀 뿐이다


def save_sheet(rows, extra=None):
    """★`{meta, items}` 꼴로 낸다 — 알림기(`ref_notify/notify_hunt.py`)가 그 꼴만 읽는다.
    칩칩 헌터는 맨 목록으로 내는데, 그러면 알림기가 `sheet.get` 에서 그대로 죽는다."""
    meta = {"stamp": time.strftime("%m/%d %H:%M"), "topic": TOPIC,
            "label": CFG["label"], "n_raw": len(rows)}
    meta.update(extra or {})
    save(os.path.join(OUT, "_최신시트.json"), {"meta": meta, "items": rows})


# ── 1단 발굴 ────────────────────────────────────────────────────────────
def scout(args):
    pool = load(POOL, {})
    found = {}
    qs = CFG["queries_ko"] if args.ko else CFG["queries"]
    gl, hl = CFG["gl"], CFG["hl"]
    print(f"[{TOPIC}] {CFG['label']}")
    print(f"질의 {len(qs)}개 · {'국내' if args.ko else f'해외(로케일 {hl}-{gl})'}"
          f" · 캐시 {args.ttl}시간")
    if not args.ko and TOPIC == "축구":
        print("※로케일이 GB 다 — US 로 두면 `football` 이 미식축구로 나온다\n")
    else:
        print()

    def ask(q):
        html = fetch(f"https://www.youtube.com/results?search_query={quote(q)}"
                     f"&sp=EgIYAQ%253D%253D&hl={hl}&gl={gl}",
                     # ★파이썬 str 해시는 실행마다 바뀐다 — 캐시 키로 쓰면 매번 새로 받는다
                     f"q{CFG['key'][0]}_" +
                     hashlib.md5((q + gl).encode()).hexdigest()[:10] + ".html",
                     ttl_hours=args.ttl, sleep=args.sleep,
                     lang=f"{hl}-{gl},{hl};q=0.9")
        return shorts_cards(html)

    tot = {"drop": 0, "kj": 0, "off": 0}
    for q in qs:
        cards = ask(q)
        note = ""
        # ★좁은 검색어는 오류 없이 0건이 된다. 낱말을 덜어내며 넓힌다.
        #  ★★넓히다 **주제 낱말을 잃으면** 딴 종목을 물어 온다 —
        #    `bizarre moment football match` 가 `bizarre` 까지 깎여 자동차·크리켓
        #    채널을 풀에 넣었다 (실기 2026-08-21). 앵커를 도로 붙여 막는다
        anchor = CFG.get("anchor", "")
        wide = q
        while not cards and len(wide.split()) > 1:
            wide = " ".join(wide.split()[:-1])
            aq = wide if (not anchor or anchor in wide.lower()) else f"{wide} {anchor}"
            cards = ask(aq)
            note = f"  ← '{aq}' 로 넓힘"
        big = [c for c in cards if c[1] >= args.min_views]
        # ★넓힌 질의가 물어온 딴 주제를 여기서 끊는다
        hot = [c for c in big if in_topic(c[2])] if args.strict else big
        off = len(big) - len(hot)
        dr = [c for c in hot if dropped(c[2])]
        hot = [c for c in hot if not dropped(c[2])]
        kj = [c for c in hot if is_domestic(c[2])]
        hot = [c for c in hot if not is_domestic(c[2])]
        tot["drop"] += len(dr); tot["kj"] += len(kj); tot["off"] += off
        print(f"  {q[:33]:<35} 쇼츠 {len(cards):>3} · {args.min_views//1000}k↑ {len(big):>3}"
              f" · 남음 {len(hot):>3}  ({CFG['drop_why']} {len(dr)} 한일 {len(kj)}"
              f" 딴주제 {off}){note}")
        for vid, v, t in hot:
            if vid not in found or found[vid][0] < v:
                found[vid] = (v, t, q)

    print(f"\n걸러낸 것 — {CFG['drop_why']} {tot['drop']} · 한일 {tot['kj']} · 딴주제 {tot['off']}")
    print(f"조회수 {args.min_views:,} 넘는 쇼츠 {len(found)}건. 채널을 캔다…")
    tally, clips = {}, []
    for i, (vid, (v, t, q)) in enumerate(sorted(found.items(), key=lambda kv: -kv[1][0])):
        if i >= args.resolve:
            break
        name, handle = oembed(vid)
        if not handle:
            continue
        # 채널명으로 한 번 더 — 제목은 영어여도 채널이 한·일인 경우가 있다
        if is_domestic(name) or dropped(name, handle):
            continue
        d = tally.setdefault(handle, {"name": name, "hits": 0, "best": 0, "q": set()})
        d["hits"] += 1
        d["best"] = max(d["best"], v)
        d["q"].add(q)
        # ★긁은 클립을 버리지 마라 — 이미 터진 클립 자체가 제일 좋은 후보다 (--best)
        clips.append({"vid": vid, "views": v, "title": t, "q": q,
                      "ch": name, "handle": handle})
    # ★덮어쓰지 말고 쌓는다. 매번 갈아치우면 지난 발굴분이 통째로 날아간다
    merged = {c["vid"]: c for c in load(CLIPS, [])}
    for c in clips:
        merged[c["vid"]] = c
    save(CLIPS, list(merged.values()))
    print(f"\n클립 누적 {len(merged)}건 (이번에 {len(clips)}건)")

    print(f"\n{'채널':<30}{'걸린 편':>7}{'최고 조회':>12}  허락  질의")
    print("─" * 96)
    for h, d in sorted(tally.items(), key=lambda kv: -kv[1]["best"]):
        perm = permit_mark(d["name"], h)
        old = pool.get(h, {})
        pool[h] = {"name": d["name"],
                   "hits": old.get("hits", 0) + d["hits"],
                   "best": max(old.get("best", 0), d["best"]),
                   "perm": perm}
        print(f"{d['name'][:29]:<30}{d['hits']:>7}{d['best']:>12,}  {perm:<5} "
              f"{', '.join(sorted(d['q']))[:34]}")
    save(POOL, pool)
    print(f"\n풀 {len(pool)}곳 → {POOL}")
    print(f"다음: python ref_sport/hunt.py --topic {TOPIC}   (풀을 재서 오늘의 후보)")


# ── 2단 사냥 ────────────────────────────────────────────────────────────
def rss(cid_or_handle):
    """RSS 는 게시일·좋아요를 준다. 쇼츠/롱폼 구분은 안 되니 /shorts 와 교차한다."""
    h = cid_or_handle
    if not h.startswith("UC"):
        html = fetch(f"https://www.youtube.com/@{h.lstrip('@')}",
                     f"ch_{h.lstrip('@')}.html", ttl_hours=24 * 7)
        m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', norm_ws(html))
        if not m:
            return None, {}
        h = m.group(1)
    raw = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={h}",
                f"rss_{h}.xml", ttl_hours=3.0)
    out = {}
    try:
        root = ET.fromstring(raw)
    except Exception:
        return h, out
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", "", NS)
        g = e.find("m:group", NS)
        d = {"pub": e.findtext("a:published", "", NS)[:10], "views": 0, "likes": 0,
             "title": e.findtext("a:title", "", NS)}
        if g is not None:
            st = g.find("m:community/m:statistics", NS)
            sr = g.find("m:community/m:starRating", NS)
            if st is not None: d["views"] = int(st.get("views", 0))
            if sr is not None: d["likes"] = int(sr.get("count", 0))
        out[vid] = d
    return h, out


def days_since(iso):
    try:
        import datetime as dt
        return (dt.date.today() - dt.date(*map(int, iso.split("-")))).days
    except Exception:
        return 999


def hunt(args):
    pool = load(POOL, {})
    if not pool:
        print(f"풀이 비어 있다. 먼저:  python ref_sport/hunt.py --topic {TOPIC} --scout")
        return
    seen = set(load(SEEN, []))
    rows, radar = [], []
    print(f"[{TOPIC}] 풀 {len(pool)}곳을 잰다…\n")
    # ★레이더로만 돌릴 갈래는 **주제마다 다르다.** 춤은 재포장을 빼는 게 맞지만
    #   축구는 원본이 중계권자 것이라 '허락받을 원본 채널' 이 없다 — 재포장도 후보다
    radar_marks = CFG.get("radar_marks", ["⚑", "✖"])
    for handle, meta in pool.items():
        perm = meta.get("perm", "○")
        if perm in radar_marks and not args.with_repack:
            radar.append((handle, meta))
            continue
        if blocked(handle, meta.get("name", "")):
            continue
        cid, feed = rss(handle)
        if not cid:
            print(f"  !! @{handle} 못 읽음"); continue
        html = fetch(f"https://www.youtube.com/channel/{cid}/shorts",
                     f"sh_{cid}.html", ttl_hours=3.0)
        cards = shorts_cards(html)
        if not cards:
            # ★0건은 두 가지다. 대응이 정반대라 반드시 갈라 본다
            why = "차단·동의창" if (len(html) < 200000 or "consent" in html[:4000]) \
                  else "구조 변경이거나 쇼츠가 없다"
            print(f"  ⚠ {meta['name'][:20]:<22} 쇼츠 0건 — {why}")
            continue
        # ★★채널 **자체가** 주제인지 본다. 클립 한 편이 주제에 걸려 풀에 들어온 뒤
        #   그 뒤로 딴 것만 올리는 채널이 있다 — 골프 풀에 동물 채널(`ZooVibe`)이
        #   들어와 배수 8.2x 로 1·2위를 먹었다 (실기 2026-08-21).
        #   클립 한 편씩 재는 `topic` 배수(×0.30)로는 못 막는다. 배수가 그걸 눌러 버린다
        on = sum(1 for c in cards if in_topic(c[2]))
        if cards and on / len(cards) < args.ch_topic:
            print(f"  ✂ {meta['name'][:20]:<22} 주제 밖 채널 — "
                  f"최근 {len(cards)}편 중 {on}편만 {TOPIC}")
            continue
        # ★작은 채널이 배수로 상위를 독식하지 않게 바닥을 깐다
        base = max(statistics.median([c[1] for c in cards if c[1]] or [1]), 2000)
        cmap = {c[0]: c for c in cards}
        fresh = 0
        for vid, d in feed.items():
            if vid not in cmap or vid in seen:
                continue
            v = max(d["views"], cmap[vid][1])
            age = days_since(d["pub"])
            if age > args.days:
                continue
            # ★바닥을 깐다. 배수만 보면 조회 4천짜리가 시트에 올라온다 —
            #   재포장 채널이 쓸 소재는 **이미 사람이 본 것**이라야 한다 (실기 2026-08-21)
            if v < args.floor:
                continue
            title = d["title"] or cmap[vid][2]
            if dropped(title):          # ★FIFA·게임은 여기서도 끊는다
                continue
            fresh += 1
            shape, smult = shape_of(title)
            burst = min(v / base, 25.0)          # 배수 상한 — 작은 채널 독식 방지
            recency = 1.0 + 0.5 * max(0.0, 1 - age / max(args.days, 1))
            lr = d["likes"] / v * 100 if v else 0
            # 주제 맥락이 없으면 크게 깎는다. 버리진 않는다 — 눈으로 볼 기회는 남긴다
            topic = 1.0 if in_topic(title) else 0.30
            score = math.log10(max(v, 100)) * burst * smult * recency * topic
            rows.append({"vid": vid, "views": v, "burst": burst, "shape": shape,
                         "score": score, "age": age, "lr": lr, "perm": perm,
                         "ch": meta["name"], "handle": handle,
                         "ontopic": in_topic(title),
                         "title": title, "base": int(base)})
        print(f"  {meta['name'][:22]:<24} 쇼츠 {len(cards):>3} · 중앙 {int(base):>9,} · "
              f"최근 {args.days}일 {fresh}건")

    if radar:
        print(f"\n[레이더 {len(radar)}곳 — 소스로 쓰지 않는다. 여기 터진 클립은 원본을 찾아 가라]")
        print("  " + " · ".join(m["name"][:14] for _, m in radar))
        print("  전부 보려면 --with-repack")

    rows.sort(key=lambda r: -r["score"])
    rows = cap_per_channel(rows, args.per_ch)[:args.top]
    write_sheet(rows, args)
    save_sheet(rows, {"pool": len(pool), "radar": len(radar), "days": args.days})


def write_sheet(rows, args):
    mult = " · ".join(f"{n} ×{m:.2f}" for n, m, _ in CFG["shapes"])
    md = [f"# {TOPIC} 소재 후보 ({CFG['label']}) — 최근 {args.days}일", "",
          "점수 = log10(조회) × 그 채널 중앙 대비 배수 × 갈래 배수 × 신선도", "",
          "- **배수**가 크면 그 채널 기준으로 터진 것이다. 절대 조회수보다 이쪽을 믿어라",
          f"- 갈래 배수 — {mult}",
          "- ★배수는 아직 실측이 아니다. 채널 성격에 맞춘 값이라 회차가 쌓이면 다시 잰다", "",
          "| # | 조회 | 배수 | 갈래 | 허락 | 채널 | 제목 | 링크 |",
          "|--:|--:|--:|---|:-:|---|---|---|"]
    for i, r in enumerate(rows, 1):
        md.append(f"| {i} | {r['views']:,} | ×{r['burst']:.1f} | {r['shape']} | "
                  f"{r['perm']} | {r['ch'][:16]} | {r['title'][:44]} | "
                  f"https://youtube.com/shorts/{r['vid']} |")
    md += ["", "## 고르고 나서", "",
           "```", f"python ref_sport/hunt.py --topic {TOPIC} --took <videoId> [<videoId> ...]",
           "```", "쓴 것은 중복목록에 들어가 다음 실행부터 빠진다."]
    p = os.path.join(OUT, "_최신시트.md")
    open(p, "w", encoding="utf-8").write("\n".join(md))
    print(f"\n{'#':>3}{'조회':>11}{'배수':>7}  {'갈래':<12}{'허락':<4}{'채널':<18}제목")
    print("─" * 104)
    for i, r in enumerate(rows[:args.show], 1):
        print(f"{i:>3}{r['views']:>11,}{r['burst']:>6.1f}x  {r['shape']:<12}"
              f"{r['perm']:<4}{r['ch'][:16]:<18}{r['title'][:40]}")
    print(f"\n시트 → {p}")


def best(args):
    """이미 크게 터진 클립 중에서 고른다 — 신선도 말고 '검증된 것' 축이다."""
    clips = load(CLIPS, [])
    if not clips:
        print(f"발굴한 클립이 없다. 먼저:  python ref_sport/hunt.py --topic {TOPIC} --scout")
        return
    seen = set(load(SEEN, []))
    rows = []
    for c in clips:
        if c["vid"] in seen or is_domestic(c["title"], c["ch"]):
            continue
        if dropped(c["title"], c["ch"], c["handle"]):
            continue
        if blocked(c["handle"], c["ch"]):
            continue
        perm = permit_mark(c["ch"], c["handle"])
        if perm in CFG.get("radar_marks", ["⚑", "✖"]) and not args.with_repack:
            continue
        shape, smult = shape_of(c["title"])
        # ★log10 을 쓰면 안 된다. 9,900만과 100만이 8.0 대 6.0 이라 갈래 배수가
        #   조회수를 눌러 버린다 (칩칩 실기 2026-08-21). 여긴 조회수가 주(主)여야 한다
        rows.append({**c, "shape": shape, "perm": perm, "burst": 0.0, "base": 0,
                     "score": c["views"] * smult
                              * (1.0 if in_topic(c["title"]) else 0.45)})
    rows.sort(key=lambda r: -r["score"])
    rows = cap_per_channel(rows, args.per_ch)[:args.top]
    save_sheet(rows, {"mode": "검증본(이미 터진 것)", "pool": len(clips)})

    print(f"\n{'#':>3}{'조회':>12}  {'갈래':<12}{'채널':<20}제목")
    print("─" * 104)
    for i, r in enumerate(rows[:args.show], 1):
        print(f"{i:>3}{r['views']:>12,}  {r['shape']:<12}{r['ch'][:18]:<20}{r['title'][:44]}")
    md = [f"# {TOPIC} ({CFG['label']}) — 이미 터진 클립 중에서", "",
          "| # | 조회 | 갈래 | 채널 | 제목 | 링크 |", "|--:|--:|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        md.append(f"| {i} | {r['views']:,} | {r['shape']} | {r['ch'][:16]} | "
                  f"{r['title'][:44]} | https://youtube.com/shorts/{r['vid']} |")
    p = os.path.join(OUT, "_최신시트.md")
    open(p, "w", encoding="utf-8").write("\n".join(md))
    print(f"\n시트 → {p}")


def took(vids):
    seen = set(load(SEEN, []))
    seen |= set(vids)
    save(SEEN, sorted(seen))
    print(f"{len(vids)}건 기록. 중복목록 {len(seen)}건 → {SEEN}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="축구", help="축구 · 골프")
    ap.add_argument("--scout", action="store_true", help="검색으로 소스 채널 풀을 넓힌다")
    ap.add_argument("--best", action="store_true", help="이미 크게 터진 클립 중에서 고른다")
    ap.add_argument("--daily", action="store_true",
                    help="예약용 — 주제가 정한 방식(topics.py 의 daily_mode)으로 하루치를 돈다. "
                         "축구는 발굴+검증본, 골프는 신작 사냥이다")
    ap.add_argument("--sheet", action="store_true", help="후보 썸네일 시트를 만든다")
    ap.add_argument("--took", nargs="+", default=[], help="쓴 영상을 중복목록에 넣는다")
    ap.add_argument("--min-views", dest="min_views", type=int, default=300000,
                    help="발굴 때 이 조회수 아래는 채널 후보로 안 본다")
    ap.add_argument("--resolve", type=int, default=80, help="채널을 캘 영상 수 상한")
    ap.add_argument("--days", type=int, default=21, help="이보다 오래된 쇼츠는 버린다")
    ap.add_argument("--floor", type=int, default=20000,
                    help="사냥 때 이 조회수 아래는 후보로 안 본다 "
                         "(배수만 보면 조회 4천짜리가 시트에 올라온다)")
    ap.add_argument("--ch-topic", dest="ch_topic", type=float, default=0.25,
                    help="최근 쇼츠 중 이 비율만큼도 주제가 아니면 채널을 통째로 뺀다. "
                         "★골프 풀에 동물 채널이 들어와 1·2위를 먹은 적이 있다")
    ap.add_argument("--per-ch", dest="per_ch", type=int, default=3,
                    help="한 채널에서 이 편수까지만 위로 올린다 (0 이면 제한 없음). "
                         "★한 채널이 12칸 중 7칸을 먹은 적이 있다")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--show", type=int, default=25)
    ap.add_argument("--with-repack", dest="with_repack", action="store_true",
                    help="재포장·미디어 채널도 후보에 넣는다 (기본은 레이더로만 쓴다)")
    ap.add_argument("--loose", dest="strict", action="store_false", default=True,
                    help="발굴 때 주제 맥락 검사를 끈다 (풀이 주제에서 샌다)")
    ap.add_argument("--ko", action="store_true", help="국내 질의로 발굴한다")
    ap.add_argument("--ttl", type=float, default=12.0, help="검색 캐시 유효시간")
    ap.add_argument("--sleep", type=float, default=2.5, help="요청 간 쉬는 시간(초)")
    args = ap.parse_args()

    setup(args.topic)
    if args.took:
        took(args.took)
    elif args.daily:
        # 주제가 정한 방식으로 하루치를 돈다 (topics.py 의 daily_mode)
        if CFG.get("daily_mode") == "best":
            scout(args)     # 오늘 검색으로 새 클립을 풀에 넣고
            best(args)      # 이미 터진 것 중에서 고른다
        else:
            hunt(args)
    elif args.scout:
        scout(args)
    elif args.best:
        best(args)
    elif args.sheet:
        import sheet
        s = load(os.path.join(OUT, "_최신시트.json"), [])
        sheet.build(s.get("items", []) if isinstance(s, dict) else s, OUT, TOPIC)
    else:
        hunt(args)


main()
