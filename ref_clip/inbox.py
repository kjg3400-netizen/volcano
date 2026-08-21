# -*- coding: utf-8 -*-
"""소재 창고(`queue.json`) 를 **보는** 도구.

  python ref_clip/inbox.py --list     # 창고 보기

★★수거 기능은 은퇴했다 (2026-08-21). 이제 `ref_notify/tg_bot.py` 가 유일한 수거자다.

  왜 — 텔레그램 `offset` 은 봇마다 하나뿐이라 우편함을 비우는 쪽이 둘이면 메시지가
  둘로 갈린다. 게다가 여기 있던 수거기는 **링크 없는 메시지를 버리면서 offset 만
  올렸다**. 사장님이 "5시에 업로드할 … 제작해줘" 라고 보내신 지시가 그렇게 사라질
  뻔했다(실기로 잡았다). 지금은 tg_bot 이 링크는 이 `queue.json` 에 그대로 넣고,
  링크 없는 글·사진은 `ref_notify/inbox/inbox.json` 에 따로 담는다.

  예약 `볼케이노 소재창고 매시간` 은 껐다. 되살리지 마라.

★창고는 텔레그램이 아니라 이 PC 의 `queue.json` 이다 — 텔레그램은 받은 메시지를
  약 24시간만 갖고 있다.

★채널 배정은 링크만으로는 못 한다(인스타 릴스는 열어 봐야 안다).
  앞에 한 글자를 붙여 보내면 그대로 쓰고(`축`·`골`·`춤`), 없으면 `미정`으로 둔다.
  ※그 표(PREFIX·HOST)의 진짜 출처는 이제 `ref_notify/tg_bot.py` 다.
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(HERE, "queue.json")
sys.path.insert(0, os.path.join(ROOT, "ref_notify"))
import tg  # noqa: E402

# 앞머리 한 글자 → 채널
PREFIX = {"축": "짹짹", "축구": "짹짹", "골": "짧뷰", "골프": "짧뷰",
          "춤": "칩칩", "댄스": "칩칩"}
HOST = [("instagram.com", "인스타"), ("tiktok.com", "틱톡"),
        ("youtube.com", "유튜브"), ("youtu.be", "유튜브"),
        ("x.com", "X"), ("twitter.com", "X")]


def load():
    try:
        return json.load(io.open(QUEUE, encoding="utf-8"))
    except Exception:
        return {"items": [], "offset": 0}


def save(q):
    os.makedirs(HERE, exist_ok=True)
    json.dump(q, io.open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def platform_of(url):
    for h, name in HOST:
        if h in url:
            return name
    return "기타"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry", action="store_true", help="우편함을 비우지 않는다")
    a = ap.parse_args()

    q = load()

    if a.list:
        items = q["items"]
        done = [x for x in items if x.get("status") == "만듦"]
        todo = [x for x in items if x.get("status") != "만듦"]
        print(f"창고 {len(items)}건 — 남은 것 {len(todo)} · 만든 것 {len(done)}\n")
        for i, x in enumerate(todo, 1):
            print(f"{i:>3}. [{x['채널']}] {x['플랫폼']}  {x['받은때'][:16]}")
            print(f"     {x['링크'][:96]}")
            if x.get("메모"):
                print(f"     메모: {x['메모'][:60]}")
        return

    # ★★여기서 멈춘다. 우편함을 비우는 것은 ref_notify/tg_bot.py 하나뿐이다.
    #   수거자가 둘이면 메시지가 둘로 갈리고, 아래 코드는 링크 없는 글을 버린다.
    #   아래는 무엇을 하던 코드였는지 남겨 둔 것이고 다시 켜면 안 된다.
    sys.exit(
        "수거는 은퇴했다 — ref_notify/tg_bot.py 가 우편함을 비운다.\n"
        "  창고 보기 : python ref_clip/inbox.py --list\n"
        "  폰에서 보기: 봇에게 '창고'")

    tok = tg._token_from_keyfile()
    if not tok:
        sys.exit("토큰이 없다.")
    url = ("https://api.telegram.org/bot%s/getUpdates?limit=100&offset=%d"
           % (tok, q.get("offset", 0)))
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %d — 우편함을 못 읽었다" % e.code)

    ups = d.get("result", [])
    have = {x["링크"] for x in q["items"]}
    added, last = 0, q.get("offset", 0)

    for u in ups:
        last = max(last, u.get("update_id", 0) + 1)
        m = u.get("message") or u.get("channel_post") or {}
        txt = (m.get("text") or m.get("caption") or "").strip()
        if not txt:
            continue
        links = re.findall(r"https?://\S+", txt)
        if not links:
            continue
        head = txt.split()[0]
        ch = PREFIX.get(head, "미정")
        memo = re.sub(r"https?://\S+", "", txt).strip()
        if ch != "미정":
            memo = memo[len(head):].strip()
        for ln in links:
            ln = ln.rstrip(").,]")
            if ln in have:
                continue
            have.add(ln)
            q["items"].append({
                "링크": ln, "플랫폼": platform_of(ln), "채널": ch,
                "메모": memo, "상태": "대기", "status": "대기",
                "받은때": datetime.now().isoformat(timespec="seconds"),
            })
            added += 1

    # ★저장을 먼저 하고 그다음에 우편함을 비운다 (offset 을 올리면 텔레그램에선 사라진다)
    if not a.dry:
        q["offset"] = last
    save(q)
    print(f"새로 담은 것 {added}건 · 창고 총 {len(q['items'])}건")
    if a.dry:
        print("(--dry 라 우편함은 그대로 뒀다)")
    for x in q["items"][-added:] if added else []:
        print(f"  [{x['채널']}] {x['플랫폼']}  {x['링크'][:88]}")


if __name__ == "__main__":
    main()
