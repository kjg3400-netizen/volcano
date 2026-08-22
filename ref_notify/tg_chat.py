# -*- coding: utf-8 -*-
"""폰에서 온 말에 **바로 답하는** 층.

봇은 여태 `VERBS` 낱말 6개만 알아듣고 나머지는 전부 창고에 넣고 끝냈다.
그래서 사장님이 「이제 여기서보내도 클로드코드랑 대화도가능하나?」 라고 물으셔도
돌아오는 답이 "📥 창고에 넣었습니다" 였다 (2026-08-22 17:34).

여기서 그 갈래를 연다 — 메뉴에도 없고 주문도 아닌 말은 **질문으로 보고 답한다.**

  · 헤드리스 `claude -p` 에 그대로 묻고 답을 폰으로 돌려준다
  · `--session-id` 로 대화가 **이어진다** — "그거 말고 다른 거" 가 통한다
  · 권한은 `tg_worker` 와 같은 울타리(`run_settings.json`)를 쓴다

★긴 제작은 여기서 하지 않는다. 그건 `tg_run` 이 일꾼을 떼어 내 굽는다 —
  여기서 굽으면 답이 올 때까지 봇이 다른 메시지를 못 받는다.

★예외를 밖으로 던지지 않는다. 답하기가 죽어도 봇은 살아서 창고 노릇은 해야 한다.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tg  # noqa: E402

CHATSTATE = os.path.join(HERE, "chat_state.json")
SETTINGS = os.path.join(HERE, "run_settings.json")
CLAUDE = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")

TIMEOUT = 150          # 이보다 오래 걸리면 끊는다 (봇을 붙잡고 있는 시간이다)
IDLE_NEW = 6 * 3600    # 이만큼 조용했으면 새 대화로 친다

PROMPT = """[폰에서 온 말 — 사장님]
{text}

텔레그램으로 답한다. 아래를 지켜라.

- **짧게.** 폰 화면이다. 길어야 6~8줄, 표·코드블록은 쓰지 마라.
- 마크다운을 쓰지 마라. 굵게는 <b>…</b> 만 쓴다 (텔레그램 HTML 이다).
- 모르면 모른다고 한다. 지어내지 마라.
- **오래 걸리는 제작·렌더는 시작하지 마라.** 만들라는 뜻으로 읽히면
  "주문으로 넣을까요?" 하고 되물어라 — 굽는 것은 따로 도는 일꾼 몫이다.
- 파일을 읽어 확인해야 답할 수 있으면 읽어라. `CLAUDE.md` 규약을 따른다.
"""


def _load():
    try:
        with io.open(CHATSTATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    try:
        with io.open(CHATSTATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def typing():
    """답이 오기까지 몇십 초 걸린다 — 폰에 '입력 중' 을 띄워 둔다."""
    try:
        tg.call("sendChatAction", {"action": "typing"})
    except Exception:
        pass


def _sid():
    """이어 갈 대화 id. 오래 조용했으면 새로 판다 — 옛 맥락이 답을 흐린다."""
    st = _load()
    if st.get("sid") and (time.time() - st.get("t", 0)) < IDLE_NEW:
        return st["sid"], True
    return str(uuid.uuid4()), False


def ask(text):
    """묻고 답을 돌려준다. 못 하면 None — 부른 쪽이 창고로 되돌린다."""
    sid, resume = _sid()
    try:
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", CLAUDE, "-p",
               "--output-format", "json",
               "--permission-mode", "acceptEdits",
               "--settings", SETTINGS]
        cmd += (["--resume", sid] if resume else ["--session-id", sid])

        out = subprocess.run(cmd, cwd=ROOT, input=PROMPT.format(text=text),
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=TIMEOUT)
        ans = _answer(out.stdout)
        if not ans and resume:                 # 옛 대화가 사라졌을 수 있다 — 한 번만 새로
            sid = str(uuid.uuid4())
            out = subprocess.run(cmd[:-2] + ["--session-id", sid], cwd=ROOT,
                                 input=PROMPT.format(text=text),
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace",
                                 timeout=TIMEOUT)
            ans = _answer(out.stdout)
        if not ans:
            return None
        _save({"sid": sid, "t": time.time()})
        return ans
    except subprocess.TimeoutExpired:
        return ("⏱ 생각이 길어져 끊었습니다 (%d초). "
                "짧게 다시 물어봐 주세요." % TIMEOUT)
    except Exception:
        return None


def _answer(stdout):
    """`--output-format json` 응답에서 답만 꺼낸다. 모양이 바뀌어도 안 죽는다."""
    try:
        d = json.loads((stdout or "").strip())
    except Exception:
        return None
    if isinstance(d, list):                    # 혹시 배열로 오면 마지막 것
        d = d[-1] if d else {}
    if not isinstance(d, dict):
        return None
    if d.get("is_error"):
        return None
    r = d.get("result") or d.get("text") or ""
    r = str(r).strip()
    return r or None


def reply_to(text):
    """봇이 부르는 자리. 답 문자열(HTML)을 돌려준다. 실패하면 None."""
    typing()
    ans = ask(text)
    if not ans:
        return None
    return _htmlize(ans)


def _htmlize(s):
    """모델이 <b> 를 쓰기로 했지만 안 지킬 수도 있다 —
    태그를 <b><i><code> 만 남기고 나머지는 글자로 만든다. 안 그러면 텔레그램이 반려한다."""
    keep = {"<b>", "</b>", "<i>", "</i>", "<code>", "</code>"}
    out, i = [], 0
    while i < len(s):
        if s[i] == "<":
            j = s.find(">", i)
            tag = s[i:j + 1].lower() if j != -1 else ""
            if tag in keep:
                out.append(s[i:j + 1])
                i = j + 1
                continue
            out.append("&lt;")
        elif s[i] == "&":
            out.append("&amp;")
        else:
            out.append(s[i])
        i += 1
    return "".join(out)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    q = " ".join(sys.argv[1:]) or "지금 볼케이노 폴더에 헌터가 몇 개 있나?"
    print("물음:", q)
    t0 = time.time()
    a = reply_to(q)
    print("답(%.0f초):" % (time.time() - t0))
    print(a or "(못 받았다)")
