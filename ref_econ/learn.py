# -*- coding: utf-8 -*-
"""
채널 실적 학습기 — 올린 편들이 실제로 어떻게 나왔는지 재서 `channel_fit.json` 을 만든다.
`hunt.py` 가 이걸 읽어 후보 점수에 곱한다.

  python ref_econ/learn.py                    # 채널 받아서 다시 계산
  python ref_econ/learn.py --show             # 지금 쓰이는 가중치만 보기
  python ref_econ/learn.py --channel "@핸들"

★표본이 적을 때 비율을 그대로 쓰면 과적합이다. 15편 시점에 '한국vs해외'는
  1편(16,354회)뿐인데 그 배수 3.97 을 그대로 곱하면 그 유형만 상위를 독식한다.
  그래서 **표본 수에 따라 1.0 쪽으로 당기는 축소(shrinkage)** 를 건다 —
  편이 쌓이면 축소가 저절로 풀려 진짜 배수에 가까워진다.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FIT = os.path.join(HERE, "channel_fit.json")
CACHE = os.path.join(HERE, "out", "channel_raw.json")
DEFAULT_CH = "https://www.youtube.com/@%EC%88%8F%EB%8B%A8%EC%A7%801"

MATURE_H = 48        # 이보다 어린 편은 조회가 덜 붙어 비교가 안 된다
SHRINK_K = 3.0       # 클수록 1.0 쪽으로 세게 당긴다
CLAMP = (0.70, 1.60)

# 꼴 분류는 hunt.py 와 공용이다. 사전이 두 곳으로 갈라지면 학습한 가중치와
# 후보에 매기는 꼴이 어긋나 조용히 틀린다.
sys.path.insert(0, HERE)
from shapes import SHAPES, FALLBACK, shape_of      # noqa: E402


def fetch(channel):
    PY = sys.executable
    print("채널 카탈로그 받는 중...")
    p = subprocess.run([PY, "-m", "yt_dlp", "--no-update", "--flat-playlist", "-J",
                        channel.rstrip("/") + "/shorts"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        sys.exit("카탈로그 실패:\n" + (p.stderr or "")[-600:])
    cat = json.loads(p.stdout)
    ents = cat.get("entries") or []
    print(f"  {cat.get('channel')} · 구독 {cat.get('channel_follower_count') or 0:,} "
          f"· 쇼츠 {len(ents)}편")

    out = []
    for i, e in enumerate(ents):
        q = subprocess.run([PY, "-m", "yt_dlp", "--no-update", "--skip-download", "-J",
                            f"https://www.youtube.com/shorts/{e['id']}"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if q.returncode != 0:
            continue
        d = json.loads(q.stdout)
        out.append({k: d.get(k) for k in
                    ("id", "title", "timestamp", "view_count", "like_count",
                     "comment_count")})
        print(f"  {i+1}/{len(ents)} {d.get('view_count') or 0:>7,}  "
              f"{(d.get('title') or '')[:44]}")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump({"channel": cat.get("channel"),
               "subs": cat.get("channel_follower_count"),
               "videos": out}, open(CACHE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return out


def median(xs):
    s = sorted(xs)
    if not s:
        return 0
    n = len(s)
    # 짝수면 가운데 둘의 평균. 위쪽 값을 그냥 쓰면 2편짜리 묶음이 실제보다 좋아 보인다.
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=DEFAULT_CH)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--cached", action="store_true", help="다시 안 받고 캐시로 계산")
    a = ap.parse_args()

    if a.show:
        if not os.path.exists(FIT):
            sys.exit("아직 없다. python ref_econ/learn.py 를 먼저 돌려라.")
        f = json.load(open(FIT, encoding="utf-8"))
        print(f"기준 {f['stamp']} · 편수 {f['n_total']} · 성숙 {f['n_mature']} "
              f"· 채널 중앙 {f['median']:,}회\n")
        for s, w in sorted(f["weights"].items(), key=lambda x: -x[1]["mult"]):
            print(f"  {s:<10} {w['n']:>2}편  중앙 {w['median']:>7,}  "
                  f"원배수 {w['raw']:>4.2f} → 적용 {w['mult']:>4.2f}")
        return

    if a.cached and os.path.exists(CACHE):
        vids = json.load(open(CACHE, encoding="utf-8"))["videos"]
        print(f"캐시에서 {len(vids)}편")
    else:
        vids = fetch(a.channel)

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    mature = []
    for v in vids:
        ts = v.get("timestamp")
        if not ts:
            continue
        age = (now - datetime.fromtimestamp(ts, KST)).total_seconds() / 3600
        if age >= MATURE_H:
            mature.append({**v, "age_h": age, "v": v.get("view_count") or 0,
                           "shape": shape_of(v.get("title"))})

    if len(mature) < 5:
        sys.exit(f"성숙한 편이 {len(mature)}개뿐이라 아직 학습할 게 없다.")

    med = median([m["v"] for m in mature])
    groups = {}
    for m in mature:
        groups.setdefault(m["shape"], []).append(m)

    weights = {}
    print(f"\n채널 중앙 {med:,}회 · 성숙 {len(mature)}편 (업로드 {MATURE_H}시간 경과)")
    print("-" * 72)
    for s, g in groups.items():
        gm = median([x["v"] for x in g])
        raw = gm / med if med else 1.0
        n = len(g)
        mult = 1 + (raw - 1) * (n / (n + SHRINK_K))     # 표본이 적으면 1.0 쪽으로
        mult = max(CLAMP[0], min(CLAMP[1], mult))
        weights[s] = {"n": n, "median": gm, "raw": round(raw, 2),
                      "mult": round(mult, 3)}
        print(f"  {s:<10} {n:>2}편  중앙 {gm:>7,}  원배수 {raw:>4.2f} → 적용 {mult:>4.2f}")

    for s, _ in SHAPES:
        weights.setdefault(s, {"n": 0, "median": med, "raw": 1.0, "mult": 1.0})
    weights.setdefault(FALLBACK, {"n": 0, "median": med, "raw": 1.0, "mult": 1.0})

    json.dump({"stamp": now.strftime("%Y-%m-%d %H:%M"),
               "n_total": len(vids), "n_mature": len(mature),
               "median": med, "shrink_k": SHRINK_K, "clamp": list(CLAMP),
               "weights": weights},
              open(FIT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-" * 72)
    print(f"저장: {FIT}")
    print("편이 쌓인 뒤 다시 돌리면 축소가 풀려 배수가 날카로워진다.")


if __name__ == "__main__":
    main()
