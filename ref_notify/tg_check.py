# -*- coding: utf-8 -*-
"""키 파일의 토큰이 지금 쓸 수 있는 것인지 본다.

★텔레그램 토큰은 `봇번호:비밀문자열` 꼴이고 **봇번호는 절대 안 바뀐다.**
  revoke 해도 앞자리가 같으므로 앞 몇 글자로 새것/옛것을 가릴 수 없다
  (2026-08-21 에 이걸로 헛돌았다). 굳이 비교할 필요도 없다 —
  **revoke 하면 옛 토큰은 그 순간 죽으므로, 살아 있으면 그게 새 토큰이다.**
★값은 어떤 경우에도 찍지 않는다.
"""
import io, json, os, sys, urllib.error, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tg  # noqa: E402

tok = tg._token_from_keyfile()
if not tok:
    sys.exit("키 파일에 토큰이 없다: " + os.path.expanduser("~/.volcano/keys/telegram"))

bot_id, _, secret = tok.partition(":")
print("봇번호 %s (revoke 해도 안 바뀌는 부분) · 비밀부 %d자" % (bot_id, len(secret)))

try:
    with urllib.request.urlopen(
            "https://api.telegram.org/bot%s/getMe" % tok, timeout=15) as r:
        u = json.loads(r.read()).get("result", {})
    print("→ 정상 @%s (%s)" % (u.get("username"), u.get("first_name")))
    print("   이 토큰으로 알림이 나간다. revoke 를 하셨다면 이건 **새 토큰**이다.")
except urllib.error.HTTPError as e:
    if e.code == 401:
        print("→ 401 이 토큰은 죽었다.")
        print("   BotFather 가 준 새 토큰을 넣어라:")
        print("   python ref_notify/tg_paste.py")
    else:
        print("→ HTTP %d" % e.code)
except Exception as e:
    print("확인 실패:", e)
