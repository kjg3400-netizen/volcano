# -*- coding: utf-8 -*-
"""
일본 채널(ショーフィ) 실적 학습기 → `channel_fit.json`.
`hunt.py` 가 이걸 읽어 후보 점수에 곱한다.

  python ref_jpecon/learn.py            # 채널 받아서 다시 계산
  python ref_jpecon/learn.py --show
  python ref_jpecon/learn.py --cached

★성숙한 편(48시간 지난 것)이 5개 미만이면 **아무것도 하지 않고 조용히 끝난다.**
  2026-08-21 기준 3개라 아직 못 돈다 — 예약 실행이 매일 부르므로 편이 쌓이면
  저절로 켜진다. 그때까지 hunt 의 배수는 전부 ×1.0 이고 안전 판정만 작동한다.

★한국판 배수를 가져다 쓰지 마라. 숏단지 최고 꼴은 `한국이 중국에 밀린` 이야기인데
  일본판에서 `日本が負けた` 를 하면 대전제 위반이다. 정반대다.
"""
import argparse
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FIT = os.path.join(HERE, "channel_fit.json")
CACHE = os.path.join(HERE, "out", "channel_raw.json")
DEFAULT_CH = "https://www.youtube.com/@%E3%82%B7%E3%83%A7%E3%83%BC%E3%83%95%E3%82%A31"

MATURE_H = 48
SHRINK_K = 3.0
CLAMP = (0.70, 1.60)
MIN_MATURE = 5

sys.path.insert(0, HERE)
from shapes_jp import SHAPES, FALLBACK, shape_of      # noqa: E402  (hunt.py 와 공용)

JST = timezone(timedelta(hours=9))


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
              f"{(d.get('title') or '')[:40]}")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump({"channel": cat.get("channel"),
               "subs": cat.get("channel_follower_count"), "videos": out},
              open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def median(xs):
    s = sorted(xs)
    if not s:
        return 0
    n = len(s)
    # 짝수면 가운데 둘의 평균. 위쪽 값을 쓰면 2편짜리 묶음이 실제보다 좋아 보인다.
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=DEFAULT_CH)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--cached", action="store_true")
    a = ap.parse_args()

    if a.show:
        if not os.path.exists(FIT):
            sys.exit("아직 없다. python ref_jpecon/learn.py 를 먼저 돌려라.")
        f = json.load(open(FIT, encoding="utf-8"))
        print(f"기준 {f['stamp']} · 편수 {f['n_total']} · 성숙 {f['n_mature']} "
              f"· 채널 중앙 {f['median']:,}회\n")
        for s, w in sorted(f["weights"].items(), key=lambda x: -x[1]["mult"]):
            print(f"  {s:<12} {w['n']:>2}편  중앙 {w['median']:>7,}  "
                  f"원배수 {w['raw']:>4.2f} → 적용 {w['mult']:>4.2f}")
        return

    if a.cached and os.path.exists(CACHE):
        vids = json.load(open(CACHE, encoding="utf-8"))["videos"]
        print(f"캐시에서 {len(vids)}편")
    else:
        vids = fetch(a.channel)

    now = datetime.now(JST)
    mature = []
    for v in vids:
        ts = v.get("timestamp")
        if not ts:
            continue
        age = (now - datetime.fromtimestamp(ts, JST)).total_seconds() / 3600
        if age >= MATURE_H:
            mature.append({**v, "v": v.get("view_count") or 0,
                           "shape": shape_of(v.get("title"))})

    if len(mature) < MIN_MATURE:
        # ★오류가 아니다. 예약 실행이 매일 부르므로 조용히 끝내고 다음 날을 기다린다.
        print(f"성숙한 편이 {len(mature)}개뿐이다 (필요 {MIN_MATURE}) — 아직 학습하지 않는다.")
        print("hunt 는 배수 ×1.0 으로 돌고 대전제 안전 판정만 작동한다.")
        return

    med = median([m["v"] for m in mature])
    groups = {}
    for m in mature:
        groups.setdefault(m["shape"], []).append(m)

    weights = {}
    print(f"\n채널 중앙 {med:,}회 · 성숙 {len(mature)}편")
    print("-" * 72)
    for s, g in groups.items():
        gm = median([x["v"] for x in g])
        raw = gm / med if med else 1.0
        n = len(g)
        mult = 1 + (raw - 1) * (n / (n + SHRINK_K))
        mult = max(CLAMP[0], min(CLAMP[1], mult))
        weights[s] = {"n": n, "median": gm, "raw": round(raw, 2), "mult": round(mult, 3)}
        print(f"  {s:<12} {n:>2}편  중앙 {gm:>7,}  원배수 {raw:>4.2f} → 적용 {mult:>4.2f}")

    for s, _ in SHAPES:
        weights.setdefault(s, {"n": 0, "median": med, "raw": 1.0, "mult": 1.0})
    weights.setdefault(FALLBACK, {"n": 0, "median": med, "raw": 1.0, "mult": 1.0})

    json.dump({"stamp": now.strftime("%Y-%m-%d %H:%M"), "n_total": len(vids),
               "n_mature": len(mature), "median": med, "shrink_k": SHRINK_K,
               "clamp": list(CLAMP), "weights": weights},
              open(FIT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-" * 72)
    print(f"저장: {FIT}")


if __name__ == "__main__":
    main()
