# -*- coding: utf-8 -*-
"""봇에게 온 메시지를 본다 (getUpdates). 토큰은 절대 찍지 않는다.

  python ref_notify/tg_inbox.py

★텔레그램은 받은 메시지를 **약 24시간**만 갖고 있다. 그 안에 가져가지 않으면
  사라진다 — 소재 창고를 만들면 이걸 주기적으로 비워 와야 한다.
"""
import io, json, os, sys, urllib.error, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tg  # noqa: E402

tok = tg._token_from_keyfile()
if not tok:
    sys.exit("토큰이 없다.")

try:
    with urllib.request.urlopen(
            "https://api.telegram.org/bot%s/getUpdates?limit=50" % tok, timeout=20) as r:
        d = json.loads(r.read())
except urllib.error.HTTPError as e:
    sys.exit("HTTP %d" % e.code)

ups = d.get("result", [])
print("받은 것 %d건\n" % len(ups))
for u in ups:
    m = u.get("message") or u.get("channel_post") or {}
    if not m:
        continue
    frm = (m.get("from") or {}).get("first_name", "?")
    txt = m.get("text") or m.get("caption") or ""
    kinds = [k for k in ("photo", "video", "document", "animation", "voice")
             if m.get(k)]
    print("  #%s  %s  %s" % (u.get("update_id"), frm,
                             ("[" + ",".join(kinds) + "]") if kinds else ""))
    if txt:
        print("     %s" % txt[:160])
    # 링크만 따로
    for w in txt.split():
        if w.startswith("http"):
            print("     → 링크 %s" % w[:110])
    print()
