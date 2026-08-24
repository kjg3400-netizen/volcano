# -*- coding: utf-8 -*-
"""
이미 만든 회차를 seen.json 에 모은다. hunt.py 가 이걸 보고 중복 후보를 뺀다.

  python ref_econ/seed_seen.py                       # 납품 폴더 + workdir 훑기
  python ref_econ/seed_seen.py --add "제목" ...       # 손으로 더 넣기
  python ref_econ/seed_seen.py --id 015_0005322924   # 기사 id 로 막기
  python ref_econ/seed_seen.py --list

납품 파일명은 `YYYYMMDD_<유튜브 제목>.mp4` 라 제목이 그대로 들어 있다.
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEEN = os.path.join(HERE, "seen.json")
DELIVER = os.path.expanduser(r"~\Desktop\볼케이노 완성본")


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
    """완성본 폴더의 mp4 파일명에서 제목을 뽑는다."""
    out = []
    if not os.path.isdir(DELIVER):
        print(f"! 납품 폴더 없음: {DELIVER}")
        return out
    for f in os.listdir(DELIVER):
        if not f.lower().endswith(".mp4"):
            continue
        t = os.path.splitext(f)[0]
        t = re.sub(r"^\d{8}_", "", t)          # 날짜 접두 제거
        # ★`(경제)` 는 채널 구분 꼬리표라 내용이 아니다. 떼고 비교해야
        #   경제 회차끼리 이 낱말 하나로 서로 닮아 보이는 일이 없다.
        t = re.sub(r"\((?:경제|정치|일본|커뮤)\)", "", t)
        t = re.sub(r"\(안씀\)|\[테스트\d*\]|_v\d+|_\d$", "", t).strip()
        if len(t) >= 6 and not re.fullmatch(r"v\d+", t):
            out.append(t)
    return out


def scan_workdirs():
    """workdir 의 delivered.json 에 적힌 제목·기사 id 를 줍는다."""
    titles, ids = [], []
    def _wds():
        for d in sorted(os.listdir(ROOT)):
            p = os.path.join(ROOT, d)
            if not os.path.isdir(p) or d.startswith((".", "_", "ref_")):
                continue
            if d.startswith("work_"):
                yield d, p
                continue
            # 채널 폴더(뇌전구_한국 …) 한 단계 아래의 workdir 도 본다 (2026-08-24 개편)
            for s in sorted(os.listdir(p)):
                q = os.path.join(p, s)
                if s.startswith("work_") and os.path.isdir(q):
                    yield s, q

    for d, p in _wds():
        m = re.match(r"work_(?:np_)?(\d{3})_?(\d{10})$", d) or re.match(r"work_(\d{10})$", d)
        if m and len(m.groups()) == 2:
            ids.append(f"{m.group(1)}_{m.group(2)}")
        j = os.path.join(p, "delivered.json")
        if os.path.exists(j):
            try:
                dd = json.load(open(j, encoding="utf-8"))
                for k in ("title", "youtube_title", "name"):
                    if isinstance(dd, dict) and dd.get(k):
                        titles.append(str(dd[k]))
                        break
            except Exception:
                pass
    return titles, ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", nargs="*", default=[], help="제목을 직접 추가")
    ap.add_argument("--id", nargs="*", default=[], help="기사 id(OID_AID) 를 직접 추가")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()

    d = {"ids": [], "titles": []} if a.clear else load()

    if a.list:
        print(f"막힌 기사 id {len(d['ids'])}개")
        for x in d["ids"]:
            print("  ", x)
        print(f"\n막힌 제목 {len(d['titles'])}개")
        for x in d["titles"]:
            print("  ", x)
        return

    before = (len(d["ids"]), len(d["titles"]))
    wt, wi = scan_workdirs()
    for t in scan_delivered() + wt + list(a.add):
        if t and t not in d["titles"]:
            d["titles"].append(t)
    for i in wi + list(a.id):
        if i and i not in d["ids"]:
            d["ids"].append(i)

    json.dump(d, open(SEEN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"기사 id  {before[0]} → {len(d['ids'])}")
    print(f"제목     {before[1]} → {len(d['titles'])}")
    print(f"\n{SEEN}")


if __name__ == "__main__":
    main()
