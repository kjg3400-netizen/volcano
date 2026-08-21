# -*- coding: utf-8 -*-
"""봇에 온 메시지에서 chat_id 를 찾아 tg_config.json 에 박는다.

사장님이 봇한테 아무 말이나 한 번 보내신 뒤 이걸 돌리면 된다.
봇을 새로 만들거나 대화창을 지웠을 때도 다시 돌리면 된다.
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "tg_config.json")


def main():
    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    token = cfg.get("token")
    if not token:
        print("tg_config.json 의 token 이 비었다"); return 1

    url = "https://api.telegram.org/bot%s/getUpdates" % token
    with urllib.request.urlopen(url, timeout=30) as r:
        res = json.loads(r.read().decode("utf-8"))
    if not res.get("ok"):
        print("봇이 응답을 거부했다: %s" % res.get("description")); return 1

    # 개인 대화(private)만 고른다 — 그룹에 초대된 경우까지 잡으면 엉뚱한 데로 간다
    found = {}
    for u in res["result"]:
        m = u.get("message") or u.get("edited_message") or {}
        ch = m.get("chat") or {}
        if ch.get("type") == "private" and ch.get("id"):
            found[ch["id"]] = (ch.get("first_name") or "") + (ch.get("username") and
                              " (@%s)" % ch["username"] or "")

    if not found:
        print("아직 봇에 온 메시지가 없다.")
        print("폰에서 @%s 를 찾아 [시작] 을 누르고 아무 말이나 보낸 뒤 다시 돌려라."
              % (cfg.get("bot_username") or "봇"))
        return 1

    if len(found) > 1:
        print("대화창이 여럿이다 — 첫 번째를 쓴다: %s" % list(found.items()))
    chat_id, who = list(found.items())[0]

    cfg["chat_id"] = chat_id
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    print("chat_id = %s  (%s)  → tg_config.json 에 저장했다" % (chat_id, who.strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
