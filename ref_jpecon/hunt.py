# -*- coding: utf-8 -*-
"""
일본 경제 뇌전구 소재 발굴기

Yahoo!ニュース 経済에서 후보를 긁고, 기사마다 코멘트 수와 하테나 북마크를 재서
점수순으로 세운다. ★한국판과 가장 다른 점은 **대전제 안전 판정**이다 —
일본을 나무라는 쪽으로 흐를 소재는 반응이 좋아도 깎는다.

  python ref_jpecon/hunt.py
  python ref_jpecon/hunt.py --top 25
  python ref_jpecon/hunt.py --show-unsafe    # 걸러진 것도 같이 본다
  python ref_jpecon/hunt.py --from-raw ref_jpecon/out/raw_*.json

야후는 네이버와 달리 **랭킹이 카테고리별로 제대로 갈린다**(실측 2026-08-21).
`/ranking/comment/business` 와 `/ranking/access/news/business` 가 경제만 준다.
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
from shapes_jp import shape_of, safety            # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

SOURCES = [
    ("コメント多い", "https://news.yahoo.co.jp/ranking/comment/business"),
    ("よく読まれた", "https://news.yahoo.co.jp/ranking/access/news/business"),
    ("経済トップ", "https://news.yahoo.co.jp/categories/business"),
]

FIT_W = {}


def sess():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def strip_tags(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


TIME_RE = re.compile(r"(\d{1,2})/(\d{1,2})\([月火水木金土日]\)\s*(\d{1,2}):(\d{2})")


def parse_jst(txt, now):
    """'8/20(木) 17:00' → datetime. 연말연시 넘김을 감안해 미래면 작년으로 본다."""
    m = TIME_RE.search(txt or "")
    if not m:
        return None
    mo, d, h, mi = (int(x) for x in m.groups())
    try:
        t = datetime(now.year, mo, d, h, mi)
    except ValueError:
        return None
    if t > now + timedelta(hours=6):
        t = t.replace(year=now.year - 1)
    return t


# ── 수집 ──────────────────────────────────────────────────────────────
def collect(s, tag, url, now):
    """랭킹·카테고리 페이지에서 기사 id·제목·매체·시각을 뽑는다.

    ★항목 안 텍스트 조각의 **순서가 일정하지 않다**(매체가 먼저 오기도 한다).
      위치로 집지 말고 모양으로 가른다 — 시각은 `8/20(木) 17:00` 꼴,
      제목은 남은 것 중 가장 긴 것."""
    try:
        h = s.get(url, timeout=20).text
    except Exception as e:
        print(f"  ! {tag} 실패: {e}")
        return {}

    body = h.split('class="newsFeed_list"')
    body = body[1] if len(body) > 1 else h
    out = {}
    for chunk in body.split("<li ")[1:]:
        chunk = chunk[:3000]
        m = re.search(r"/articles/([0-9a-f]{40})", chunk)
        if not m:
            continue
        aid = m.group(1)
        if aid in out:
            continue
        texts = [strip_tags(x) for x in re.findall(r">([^<>]{2,90})</", chunk)]
        texts = [t for t in texts if t]
        tm, press, cands = None, "", []
        for t in texts:
            if TIME_RE.search(t):
                tm = t
            elif t.isdigit():          # 순위 숫자
                continue
            else:
                cands.append(t)
        if cands:
            cands.sort(key=len, reverse=True)
            title = cands[0]
            press = cands[1] if len(cands) > 1 and len(cands[1]) <= 30 else ""
        else:
            continue
        pub = parse_jst(tm, now)
        out[aid] = {"aid": aid, "title": title, "press": press,
                    "pub": pub.isoformat() if pub else None,
                    "age_hours": (now - pub).total_seconds() / 3600 if pub else None,
                    "src": {tag: len(out) + 1}}
    print(f"  {tag:<10} {len(out):>3}건")
    return out


def gather(now):
    s = sess()
    print("[Yahoo!ニュース 経済] 목록 수집")
    pool = {}
    for tag, url in SOURCES:
        got = collect(s, tag, url, now)
        for k, v in got.items():
            if k in pool:
                pool[k]["src"].update(v["src"])
                if pool[k].get("age_hours") is None:
                    pool[k]["age_hours"] = v.get("age_hours")
                    pool[k]["pub"] = v.get("pub")
            else:
                pool[k] = v
    return pool


# ── 실측 ──────────────────────────────────────────────────────────────
def fetch_metrics(item):
    """코멘트 수는 기사 페이지 JSON 의 totalCount 에 있다.
    하테나 북마크는 0건이면 **빈 응답**이 오므로 그대로 파싱하면 죽는다."""
    s = sess()
    aid = item["aid"]
    url = f"https://news.yahoo.co.jp/articles/{aid}"

    item["comments"] = 0
    try:
        t = s.get(url, timeout=20).text
        m = re.search(r'"totalCount"\s*:\s*(\d+)', t)
        if m:
            item["comments"] = int(m.group(1))
    except Exception:
        pass

    item["hatena"] = 0
    try:
        r = s.get("https://b.hatena.ne.jp/entry/jsonlite/",
                  params={"url": url}, timeout=15)
        body = (r.text or "").strip()
        if body:
            item["hatena"] = int(json.loads(body).get("count") or 0)
    except Exception:
        pass
    return item


# ── 점수 ──────────────────────────────────────────────────────────────
def rank_bonus(src):
    b = 0.0
    if "コメント多い" in src:
        b += max(0.0, 32 - src["コメント多い"] * 0.55)
    if "よく読まれた" in src:
        b += max(0.0, 20 - src["よく読まれた"] * 0.35)
    if "経済トップ" in src:
        b += 8.0
    return b


def score_item(it):
    com = it.get("cluster_comments", it.get("comments", 0))
    hb = it.get("cluster_hatena", it.get("hatena", 0))
    hrs = max(it.get("age_hours") or 8.0, 0.7)

    heat = 55 * log10(1 + com) + 26 * log10(1 + hb)   # 하테나는 적게 붙어 가중을 크게
    vel = 34 * log10(1 + com / hrs)
    spread = 18 * log10(it.get("cluster_n", 1))
    rb = rank_bonus(it.get("src", {}))

    saf, why = safety(it["title"])
    sh = shape_of(it["title"])
    w = (FIT_W.get(sh) or {}).get("mult", 1.0)

    base = heat + vel + spread + rb
    # ★대전제는 ±40% 가 아니라 **당락**에 가깝게 건다. 반응이 아무리 좋아도
    #   일본을 나무라야 하는 소재면 만들 수 없다 — 순위 아래로 확실히 내린다.
    it["safety"] = round(saf, 2)
    it["safety_why"] = why
    it["blocked"] = saf <= -0.5
    it["shape"] = sh
    it["ch_mult"] = round(w, 2)
    it["base_score"] = round(base, 1)
    it["score"] = round(base * (1 + 0.55 * saf) * w, 1)
    it["parts"] = {"heat": round(heat, 1), "vel": round(vel, 1),
                   "spread": round(spread, 1), "rank": round(rb, 1)}
    return it


# ── 사건 묶기 (한국판과 같은 방식) ────────────────────────────────────
STRIP = re.compile(r"[\[\]（）()「」『』\"'…、。・,.\-—~!?%\s]+")


def bigrams(t):
    t = STRIP.sub("", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def sim(a, b):
    if not a or not b:
        return 0.0
    ov = len(a & b)
    return 0.0 if ov < 5 else ov / min(len(a), len(b))


def group_events(items, th=0.32):
    order = sorted(items, key=lambda x: -x.get("comments", 0))
    groups = []
    for it in order:
        bg = bigrams(it["title"])
        for g in groups:
            if sim(bg, g["bg"]) >= th:
                g["mem"].append(it)
                break
        else:
            groups.append({"bg": bg, "mem": [it]})
    out = []
    for g in groups:
        mem = g["mem"]
        rep = dict(mem[0])
        rep["cluster_n"] = len(mem)
        rep["cluster_comments"] = sum(x.get("comments", 0) for x in mem)
        rep["cluster_hatena"] = sum(x.get("hatena", 0) for x in mem)
        ages = [x["age_hours"] for x in mem if x.get("age_hours") is not None]
        if ages:
            rep["age_hours"] = max(ages)
        src = {}
        for x in mem:
            for k, v in x.get("src", {}).items():
                if k not in src or v < src[k]:
                    src[k] = v
        rep["src"] = src
        rep["also"] = [x.get("press", "") for x in mem[1:6] if x.get("press")]
        out.append(rep)
    return out


# ── 중복 ──────────────────────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            return json.load(open(SEEN_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"ids": [], "titles": []}


def is_seen(it, seen):
    if it["aid"] in seen.get("ids", []):
        return True
    a = bigrams(it["title"])
    for old in seen.get("titles", []):
        if sim(a, bigrams(old)) >= 0.45:
            return True
    return False


# ── 출력 ──────────────────────────────────────────────────────────────
def write_sheet(rows, blocked, path, meta):
    L = [f"# 일본 경제 뇌전구 소재 후보 — {meta['stamp']}", "",
         f"기사 {meta['pool']}건 → {meta['measured']}건 실측 → {meta['events']}개 사건 "
         f"→ 대전제 위험 {meta['blocked']}건 제외 → 상위 {len(rows)}개", ""]
    L.append("| # | 꼴 | 안전 | 배수 | 최종 | コメント | はてブ | 매체 | 경과 | 제목 |")
    L.append("|--:|:--|--:|--:|--:|--:|--:|--:|--:|---|")
    for i, r in enumerate(rows, 1):
        age = f"{r['age_hours']:.0f}h" if r.get("age_hours") is not None else "?"
        L.append(f"| {i} | {r['shape']} | {r['safety']:+.2f} | ×{r['ch_mult']} "
                 f"| **{r['score']}** | {r['cluster_comments']} | {r['cluster_hatena']} "
                 f"| {r['cluster_n']} | {age} | {r['title']} |")
    L += ["", "---", ""]
    for i, r in enumerate(rows, 1):
        age = f"{r['age_hours']:.0f}시간 전" if r.get("age_hours") is not None else "시각미상"
        src = " · ".join(f"{k} {v}위" for k, v in r.get("src", {}).items())
        L.append(f"### {i}. {r['title']}")
        L.append(f"- 최종 **{r['score']}** = 기본 {r['base_score']} × 안전 {r['safety']:+.2f}"
                 f" × 채널 {r['shape']} ×{r['ch_mult']}")
        L.append(f"- 안전 판정: {', '.join(r['safety_why']) or '중립'}")
        L.append(f"- コメント **{r['cluster_comments']}** · はてブ {r['cluster_hatena']} · {age}"
                 + (f" · {r['cluster_n']}개 매체" if r["cluster_n"] > 1 else
                    (f" · {r.get('press','')}" if r.get("press") else "")))
        if src:
            L.append(f"- 랭킹: {src}")
        L.append(f"- https://news.yahoo.co.jp/articles/{r['aid']}")
        L.append("")
    if blocked:
        L += ["---", "", "## 대전제로 걸러낸 것 — 만들지 마라", "",
              "반응은 좋지만 **일본을 나무라는 쪽으로 흐를 수밖에 없는** 소재다.", ""]
        for r in blocked[:12]:
            L.append(f"- `{r['safety']:+.2f}` ({', '.join(r['safety_why'])}) "
                     f"コメント {r['cluster_comments']} — {r['title']}")
    open(path, "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--group-th", dest="group_th", type=float, default=0.32)
    ap.add_argument("--from-raw", dest="from_raw", default="")
    ap.add_argument("--show-unsafe", action="store_true")
    ap.add_argument("--no-seen", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M")

    global FIT_W
    try:
        f = json.load(open(FIT_PATH, encoding="utf-8"))
        FIT_W = f.get("weights", {})
        print(f"채널 실적 가중치 ({f.get('stamp')} 기준 {f.get('n_mature')}편)")
    except Exception:
        print("채널 실적 가중치 없음 — 편이 5개 넘으면 learn.py 로 만든다 (지금은 전부 ×1.0)")

    if a.from_raw:
        items = json.load(open(a.from_raw, encoding="utf-8"))["items"]
        pool = {x["aid"]: x for x in items}
        print(f"캐시에서 {len(items)}건")
    else:
        pool = gather(now)
        print(f"\n후보 {len(pool)}건")
        ages = [v["age_hours"] for v in pool.values() if v.get("age_hours") is not None]
        if ages:
            print(f"긁힌 범위 {now - timedelta(hours=max(ages)):%m-%d %H:%M} ~ "
                  f"{now - timedelta(hours=min(ages)):%m-%d %H:%M} = {max(ages):.1f}시간치")
        items = [v for v in pool.values()
                 if v.get("age_hours") is None or v["age_hours"] <= a.hours]
        print(f"최근 {a.hours:.0f}시간 필터 → {len(items)}건")
        print(f"실측 중... (코멘트 + はてブ, {a.workers} 병렬)")
        t1 = time.time()
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            items = list(ex.map(fetch_metrics, items))
        print(f"실측 완료 ({time.time()-t1:.1f}s)")
        json.dump({"stamp": stamp, "items": items},
                  open(os.path.join(OUT, f"raw_{stamp}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)

    measured = len(items)
    items = group_events(items, a.group_th)
    print(f"사건 묶음 → {len(items)}개")

    seen = {"ids": [], "titles": []} if a.no_seen else load_seen()
    items = [x for x in items if not is_seen(x, seen)]
    items = [score_item(x) for x in items]

    blocked = sorted([x for x in items if x["blocked"]], key=lambda x: -x["base_score"])
    safe = sorted([x for x in items if not x["blocked"]], key=lambda x: -x["score"])
    rows = safe[: a.top]
    print(f"대전제 위험으로 뺀 것 {len(blocked)}건")

    meta = {"stamp": now.strftime("%Y-%m-%d %H:%M"), "pool": len(pool),
            "measured": measured, "events": len(items) + len(blocked),
            "blocked": len(blocked)}
    mp = os.path.join(OUT, f"hunt_{stamp}.md")
    write_sheet(rows, blocked, mp, meta)
    write_sheet(rows, blocked, os.path.join(OUT, "_최신시트.md"), meta)
    # ★시각 박힌 json 도 남긴다 — brief.py 가 이걸 읽고, 지난 시트로 되돌아갈 때도 쓴다
    for p in (os.path.join(OUT, f"hunt_{stamp}.json"),
              os.path.join(OUT, "_최신시트.json")):
        json.dump({"meta": meta, "items": rows}, open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    print("\n" + "=" * 92)
    for i, r in enumerate(rows, 1):
        age = f"{r['age_hours']:.0f}h" if r.get("age_hours") is not None else " ?"
        print(f"{i:>2}. [{r['score']:>6.1f}] {r['shape']:<12} 안전{r['safety']:>+5.2f} "
              f"コメ{r['cluster_comments']:>5} {age:>4}  {r['title'][:40]}")
    if a.show_unsafe and blocked:
        print("\n--- 대전제로 걸러낸 것 ---")
        for r in blocked[:8]:
            print(f"    [{r['safety']:>+5.2f}] {','.join(r['safety_why']):<16} "
                  f"コメ{r['cluster_comments']:>5}  {r['title'][:40]}")
    print("=" * 92)
    print(f"\n시트: {mp}")


if __name__ == "__main__":
    main()
