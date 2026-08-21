# -*- coding: utf-8 -*-
"""텔레그램으로 알림을 보내는 얇은 모듈.

외부 패키지를 쓰지 않는다 — 표준 라이브러리만으로 글·사진·영상·파일을 보낸다.
토큰은 코드에 박지 않고 옆의 tg_config.json 에서 읽는다.

★이 모듈은 절대 예외를 밖으로 던지지 않는다.
  알림이 실패했다고 헌터나 렌더가 같이 죽으면 안 된다 — 실패는 False 로만 알린다.
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "tg_config.json")
# ★토큰은 레포 밖 키 파일에서 먼저 읽는다 — EvoLink·Typecast 와 같은 자리다.
#   tg_config.json 은 작업 폴더 안이라 폴더를 훑거나 파일을 찍어 보다가
#   토큰이 화면·대화기록에 그대로 새기 쉽다(2026-08-21 실제로 그랬다).
#   chat_id 는 비밀이 아니라 tg_config.json 에 그대로 둔다.
KEY_PATH = os.path.expanduser("~/.volcano/keys/telegram")
API = "https://api.telegram.org/bot{token}/{method}"


def _token_from_keyfile():
    """환경변수 → 키 파일 순으로 찾는다. 없으면 None.
    ★값은 어떤 경로로도 로그에 찍지 않는다."""
    env = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if len(env) >= 20:
        return env
    try:
        t = open(KEY_PATH, encoding="utf-8").read().strip()
        return t if len(t) >= 20 else None
    except Exception:
        return None

# 텔레그램 봇 API 상한 (초과하면 서버가 반려하므로 미리 거른다)
LIMIT = {"sendPhoto": 10 * 1024 * 1024, "sendVideo": 50 * 1024 * 1024,
         "sendDocument": 50 * 1024 * 1024}
TEXT_LIMIT = 4096


def _log(msg):
    sys.stderr.write("[tg] %s\n" % msg)


def cfg():
    """설정을 읽는다. 없거나 덜 채워졌으면 None."""
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            c = json.load(f)
    except Exception as e:
        _log("설정을 못 읽었다 (%s): %s" % (CFG_PATH, e))
        return None
    # 키 파일이 있으면 그쪽이 이긴다. tg_config.json 의 token 은 옛 방식이다.
    kf = _token_from_keyfile()
    if kf:
        c["token"] = kf
    if not c.get("token"):
        _log("token 이 비었다 — %s 에 넣어라" % KEY_PATH)
        return None
    if not c.get("chat_id"):
        _log("chat_id 가 비었다 — python ref_notify/tg_setup.py 를 먼저 돌려라")
        return None
    return c


def _multipart(fields, files):
    """multipart/form-data 본문을 손으로 짠다 (외부 패키지를 안 쓰려고)."""
    boundary = "----volcano%d" % int(time.time() * 1000)
    out = bytearray()
    for k, v in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n"
                % (boundary, k)).encode("utf-8")
        out += str(v).encode("utf-8") + b"\r\n"
    for k, path in files.items():
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            blob = f.read()
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                "Content-Type: %s\r\n\r\n" % (boundary, k, name, ctype)).encode("utf-8")
        out += blob + b"\r\n"
    out += ("--%s--\r\n" % boundary).encode("utf-8")
    return bytes(out), "multipart/form-data; boundary=%s" % boundary


def call(method, fields, files=None, tries=3):
    """봇 API 를 한 번 부른다. 성공하면 result, 실패하면 None."""
    c = cfg()
    if not c:
        return None
    fields = dict(fields)
    fields.setdefault("chat_id", c["chat_id"])
    url = API.format(token=c["token"], method=method)

    if files:
        body, ctype = _multipart(fields, files)
    else:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        ctype = "application/x-www-form-urlencoded"

    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": ctype})
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.loads(r.read().decode("utf-8"))
            if res.get("ok"):
                return res["result"]
            _log("%s 반려: %s" % (method, res.get("description")))
            return None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            _log("%s HTTP %s: %s" % (method, e.code, detail))
            if e.code == 429 and i < tries - 1:
                time.sleep(5 * (i + 1))
                continue
            return None
        except Exception as e:
            _log("%s 실패(%d/%d): %s" % (method, i + 1, tries, e))
            if i < tries - 1:
                time.sleep(3 * (i + 1))
    return None


def esc(s):
    """HTML 모드에서 제목에 <, >, & 가 들어가도 안 깨지게."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def send_text(text, silent=False, preview=False):
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT - 20] + "\n…(줄임)"
    ok = call("sendMessage", {
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false" if preview else "true",
        "disable_notification": "true" if silent else "false",
    })
    return ok is not None


def _send_file(method, field, path, caption="", extra=None):
    if not os.path.isfile(path):
        _log("파일이 없다: %s" % path)
        return False
    size = os.path.getsize(path)
    cap = LIMIT.get(method)
    if cap and size > cap:
        _log("%s 상한 초과 (%.1fMB > %dMB) — 건너뛴다: %s"
             % (method, size / 1048576, cap // 1048576, os.path.basename(path)))
        return False
    fields = {"caption": caption[:1024], "parse_mode": "HTML"}
    if extra:
        fields.update(extra)
    return call(method, fields, files={field: path}) is not None


def send_photo(path, caption=""):
    return _send_file("sendPhoto", "photo", path, caption)


def send_video(path, caption=""):
    """쇼츠는 세로라 supports_streaming 을 켜 두면 폰에서 바로 재생된다."""
    return _send_file("sendVideo", "video", path, caption,
                      {"supports_streaming": "true"})


def send_doc(path, caption=""):
    """사진을 원본 화질 그대로 보낼 때 (sendPhoto 는 압축한다)."""
    return _send_file("sendDocument", "document", path, caption)


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "볼케이노 알림 시험 ✅"
    print("보냄" if send_text(esc(msg)) else "실패")
