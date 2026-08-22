# -*- coding: utf-8 -*-
"""영어학습형 화면 실측 — 프레임을 뽑아 밴드·제목·자막·팝업 좌표를 잰다.

`ref_maeil/work_ch_maeil/measure.py` 와 같은 자리의 도구다. 규격이 의심되면
새 표본을 여기에 통과시켜 `engl_spec.md` 의 표와 대조한다.

쓰는 법:
    python ref_engl/measure.py sample/ref_bobbylee_406x720.mp4
    python ref_engl/measure.py <mp4> --sheet          # 컨택트 시트도 만든다

★소스가 1080×1920 이 아니어도 된다. 모든 값을 1080p 로 환산해 찍는다
  (카카오톡으로 받은 406×720 압축본으로 재도 ±3px 안에 든다).

★검정띠를 프레임 하나로 재지 마라 — 띠 아래가 어두우면 부풀어 잡힌다.
  여러 프레임의 **최솟값**을 취한다 (매일일보형에서 밟은 함정과 같다).
"""
import argparse
import io
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

if getattr(sys.stdout, "encoding", "").lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

TIMES = [0.5, 3, 8, 14, 20, 26, 32, 38, 44, 50, 53]

white  = lambda r: (r[:, 0] > 170) & (r[:, 1] > 170) & (r[:, 2] > 170)
yellow = lambda r: (r[:, 0] > 170) & (r[:, 1] > 130) & (r[:, 2] < 115)


def grab(mp4, outdir, times):
    got = []
    for t in times:
        p = os.path.join(outdir, f"f_{t}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", mp4,
                        "-frames:v", "1", p, "-y"], check=False)
        if os.path.exists(p):
            got.append((t, p))
    return got


def arr(p):
    return np.asarray(Image.open(p).convert("RGB")).astype(int)


def ink(sub, fn, off=0):
    """색 조건에 맞는 잉크의 무게중심·범위. \an5 는 글자상자 기준이라
    실제로 눈에 보이는 중심은 이 값이다 ([[ass-an5-centers-glyph-box-not-ink]])."""
    ys, ws, xs = [], [], []
    for y in range(sub.shape[0]):
        m = fn(sub[y])
        if m.sum():
            ys.append(y); ws.append(m.sum()); xs.append(np.where(m)[0])
    if not ys:
        return None
    ys, ws = np.array(ys), np.array(ws)
    allx = np.concatenate(xs)
    return dict(cy=(ys * ws).sum() / ws.sum() + off, y0=ys.min() + off, y1=ys.max() + off,
                x0=int(allx.min()), x1=int(allx.max()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mp4")
    ap.add_argument("--sheet", action="store_true", help="컨택트 시트도 만든다")
    a = ap.parse_args()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration", "-of", "default=nw=1"],
        capture_output=True, text=True).stdout
    tmp = tempfile.mkdtemp(prefix="englmeas_")
    frames = grab(a.mp4, tmp, TIMES)
    if not frames:
        print("프레임을 못 뽑았다"); return

    H, W = arr(frames[0][1]).shape[:2]
    S = 1920.0 / H          # 1080p 환산비
    print(f"소스 {W}×{H}  → 1080p 환산비 {S:.3f}")
    print()

    # ── 영상 밴드: 행별 '비검정 비율' 이 높은 연속 구간 ────────────────
    print("=== 영상 밴드 ===")
    runs_all = []
    for t, p in frames:
        im = arr(p)
        prof = (im.max(axis=2) > 32).mean(axis=1)
        hi = prof > 0.55
        s, runs = None, []
        for y, v in enumerate(hi):
            if v and s is None:
                s = y
            if not v and s is not None:
                if y - s > 20:
                    runs.append((s, y))
                s = None
        if s is not None and len(hi) - s > 20:
            runs.append((s, len(hi)))
        if len(runs) == 1:
            runs_all.append(runs[0])
    if runs_all:
        y0 = int(np.median([r[0] for r in runs_all]))
        y1 = int(np.median([r[1] for r in runs_all]))
        print(f"  y {y0}~{y1}  → 1080p {y0*S:.0f}~{y1*S:.0f}  (높이 {(y1-y0)*S:.0f})")
        print(f"  ※표본 {len(runs_all)}프레임 중앙값. 표가 뜨는 끝 컷은 자동 제외된다")
    else:
        y0, y1 = int(H * 0.27), int(H * 0.73)
        print("  ★밴드를 못 잡았다 — 소재가 밝거나 어두우면 이렇게 된다")

    # ── 제목 (상단 검정띠 안) ─────────────────────────────────────────
    print()
    print("=== 제목 (상단 검정띠) ===")
    im = arr(frames[2][1])
    top = im[:y0]
    for nm, fn in (("1줄", white), ("2줄", yellow)):
        c = ink(top, fn)
        if c:
            print(f"  {nm}: 잉크중심 {c['cy']:6.1f} (y {c['y0']}~{c['y1']}) "
                  f"x {c['x0']}~{c['x1']}  → 1080p 중심 {c['cy']*S:.0f} "
                  f"잉크높이 {(c['y1']-c['y0'])*S:.0f}")
    px = top.reshape(-1, 3)
    if yellow(px).any():
        print(f"  노랑 {np.median(px[yellow(px)], axis=0).astype(int)}"
              f"  흰색 {np.median(px[white(px)], axis=0).astype(int)}")

    # ── 밴드 아래: 출처 줄 · 팝업 카드 ────────────────────────────────
    print()
    print("=== 밴드 아래 (출처 줄 · 팝업 카드) ===")
    for t, p in frames:
        im = arr(p)
        bot = im[y1:]
        nb = (bot.max(axis=2) > 32).mean(axis=1)
        ys = np.where(nb > 0.005)[0]
        if not len(ys):
            continue
        groups, s, prev = [], ys[0], ys[0]
        for y in ys[1:]:
            if y - prev > 3:
                groups.append((s + y1, prev + y1)); s = y
            prev = y
        groups.append((s + y1, prev + y1))
        desc = "  ".join(f"{g[0]}~{g[1]}(1080p {int(g[0]*S)}~{int(g[1]*S)})" for g in groups)
        print(f"  t={t:>4}s  {desc}")

    if a.sheet:
        ims = [Image.open(p) for _, p in frames]
        w, h = ims[0].size
        cols = 4
        rows = (len(ims) + cols - 1) // cols
        sheet = Image.new("RGB", (w * cols, h * rows), "white")
        for i, im2 in enumerate(ims):
            sheet.paste(im2, ((i % cols) * w, (i // cols) * h))
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sheet.png")
        sheet.save(out)
        print(f"\n시트 → {out}")


if __name__ == "__main__":
    main()
