# -*- coding: utf-8 -*-
"""tg_config.json 의 토큰을 레포 밖 키 파일로 옮기고 설정에서는 비운다.

  python ref_notify/tg_movekey.py

★토큰 값을 화면에 찍지 않는다. 길이와 앞 4글자만 보여 준다.
 왜 옮기나 — tg_config.json 은 작업 폴더 안이라, 폴더를 훑거나 파일을 찍어 보다가
 토큰이 화면·대화기록에 그대로 새기 쉽다(2026-08-21 실제로 그랬다).
 EvoLink·Typecast 처럼 `~/.volcano/keys/` 에 두면 그럴 일이 없다.
"""
import io, json, os, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "tg_config.json")
KEY = os.path.expanduser("~/.volcano/keys/telegram")


def mask(t):
    return "%s… (%d자)" % (t[:4], len(t)) if t else "(없음)"


cfg = json.load(io.open(CFG, encoding="utf-8"))
tok = (cfg.get("token") or "").strip()

if not tok:
    print("tg_config.json 에 토큰이 없다 — 이미 옮겼거나 아직 안 넣었다.")
    have = os.path.exists(KEY) and len(io.open(KEY, encoding="utf-8").read().strip()) >= 20
    print("키 파일:", KEY, "→", "있음" if have else "없음")
    sys.exit(0)

os.makedirs(os.path.dirname(KEY), exist_ok=True)
io.open(KEY, "w", encoding="utf-8").write(tok + "\n")
print("키 파일에 옮김:", KEY, mask(tok))

cfg["token"] = ""
cfg["_token"] = "★여기 넣지 마라. ~/.volcano/keys/telegram 에 넣는다 (레포 밖)."
json.dump(cfg, io.open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("tg_config.json 의 token 을 비웠다.")
print("\n남은 값(비밀 아님): bot", cfg.get("bot_username"), "· chat_id", cfg.get("chat_id"))
