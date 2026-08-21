# -*- coding: utf-8 -*-
"""도구와 규칙만 OneDrive 로 복사한다. 날짜별로 남겨 되돌릴 수 있게 한다.

  python ref_backup/backup.py
  python ref_backup/backup.py --list     # 지금까지 뜬 백업 보기

★작업 폴더(work_*)는 **일부러 뺀다.** 15 GB 대부분이 캐시·mp4·wav 라 다시 만들면 되고,
  거기엔 `find_token.py`·`keys.py` 같은 것도 섞여 있다.
★`ig_cookies.txt` 는 절대 넣지 않는다 — 인스타 로그인 세션이라 비밀번호와 같다.
★열쇠(~/.volcano/keys)는 넣는다. 잃으면 서비스마다 재발급해야 하고,
  OneDrive 는 사장님 개인 저장소라 공개 저장소와는 다르다.
  ★단, **깃허브에는 절대 올리지 마라.**
"""
import argparse
import io
import os
import shutil
import sys
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEST_ROOT = os.path.join(os.environ.get("OneDrive", ""), "볼케이노_백업")
KEYS = os.path.expanduser("~/.volcano/keys")

# 복사할 것 — 도구와 규칙만
TARGETS = ["CLAUDE.md", "ref_econ", "ref_jpecon", "ref_comm", "ref_jpcomm",
           "ref_notify", "ref_clip", "ref_backup"]
# 폴더 안에서도 뺄 것 (결과물·캐시)
SKIP_DIRS = {"out", "__pycache__", "cache"}
# 이름이 이러면 절대 복사하지 않는다
NEVER = ["ig_cookies", "cookie"]

KEEP_DAYS = 30          # 이보다 오래된 백업은 지운다


def want(path, name):
    if any(w in name.lower() for w in NEVER):
        return False
    return True


def copy_tree(src, dst):
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not want(root, f):
                print("    건너뜀(민감):", f)
                continue
            s = os.path.join(root, f)
            rel = os.path.relpath(s, src)
            d = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if not DEST_ROOT or not os.environ.get("OneDrive"):
        sys.exit("OneDrive 를 못 찾았다.")

    if a.list:
        if not os.path.isdir(DEST_ROOT):
            print("아직 백업이 없다.")
            return
        for d in sorted(os.listdir(DEST_ROOT)):
            p = os.path.join(DEST_ROOT, d)
            if os.path.isdir(p):
                n = sum(len(f) for _, _, f in os.walk(p))
                sz = sum(os.path.getsize(os.path.join(r, f))
                         for r, _, fs in os.walk(p) for f in fs)
                print(f"  {d}  {n:>4}개 · {sz/1024:>7,.0f} KB")
        return

    stamp = datetime.now().strftime("%Y-%m-%d")
    dest = os.path.join(DEST_ROOT, stamp)
    total = 0
    print(f"→ {dest}")
    for t in TARGETS:
        src = os.path.join(ROOT, t)
        if not os.path.exists(src):
            continue
        if os.path.isfile(src):
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(src, os.path.join(dest, t))
            total += 1
        else:
            total += copy_tree(src, os.path.join(dest, t))
    # 열쇠 — 깃허브엔 안 올리지만 OneDrive 엔 넣는다
    if os.path.isdir(KEYS):
        total += copy_tree(KEYS, os.path.join(dest, "_keys"))

    print(f"복사 {total}개")

    # 오래된 백업 정리
    cut = datetime.now().timestamp() - KEEP_DAYS * 86400
    for d in sorted(os.listdir(DEST_ROOT)):
        p = os.path.join(DEST_ROOT, d)
        if os.path.isdir(p) and os.path.getmtime(p) < cut:
            shutil.rmtree(p, ignore_errors=True)
            print("  옛 백업 지움:", d)


if __name__ == "__main__":
    main()
