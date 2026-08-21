# -*- coding: utf-8 -*-
"""
일본 회차 중복목록 갱신 — 납품 폴더에서 **일본어 제목만** 골라 seen.json 에 넣는다.

  python ref_jpecon/seed_seen.py
  python ref_jpecon/seed_seen.py --add "제목" --id <40hex>
  python ref_jpecon/seed_seen.py --list

★한국·일본 완성본이 한 폴더에 섞여 있다. **가나(ひらがな·カタカナ)가 있으면 일본어**로
  가른다 — 한자만 보면 한국어 제목의 한자와 구별이 안 된다.
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "seen.json")
DELIVER = os.path.expanduser(r"~\Desktop\볼케이노 완성본")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")     # 히라가나·가타카나


def load():
    if os.path.exists(SEEN):
        try:
            d = json.load(open(SEEN, encoding="utf-8"))
            d.setdefault("ids", [])
            d.setdefault("titles", [])
            return d
        except Exception:
            pass
    return {"ids": [], "titles": []}


def scan_delivered():
    out = []
    if not os.path.isdir(DELIVER):
        print(f"! 납품 폴더 없음: {DELIVER}")
        return out
    for f in os.listdir(DELIVER):
        if not f.lower().endswith(".mp4"):
            continue
        t = os.path.splitext(f)[0]
        t = re.sub(r"^\d{8}_", "", t)                       # 날짜 접두
        t = re.sub(r"\((?:경제|정치|사회|국제|축구|골프|인물|칩칩)\)", "", t)
        t = re.sub(r"\(안씀\)|\[테스트\d*\]|_v\d+|_\d$", "", t).strip()
        if len(t) >= 6 and KANA.search(t):                  # ★가나가 있어야 일본어
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", nargs="*", default=[])
    ap.add_argument("--id", nargs="*", default=[])
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    d = load()
    if a.list:
        print(f"막힌 기사 id {len(d['ids'])}개")
        for x in d["ids"]:
            print("  ", x)
        print(f"\n막힌 제목 {len(d['titles'])}개")
        for x in d["titles"]:
            print("  ", x)
        return

    before = (len(d["ids"]), len(d["titles"]))
    for t in scan_delivered() + list(a.add):
        if t and t not in d["titles"]:
            d["titles"].append(t)
    for i in list(a.id):
        if i and i not in d["ids"]:
            d["ids"].append(i)

    json.dump(d, open(SEEN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"기사 id  {before[0]} → {len(d['ids'])}")
    print(f"제목     {before[1]} → {len(d['titles'])}")
    print(f"\n{SEEN}")


if __name__ == "__main__":
    main()
