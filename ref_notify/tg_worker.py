# -*- coding: utf-8 -*-
"""주문 하나를 실제로 굽는 일꾼. `tg_run.start()` 가 **떼어 내서** 띄운다.

봇은 예약이 1분마다 부르고 45초만 사는 몸이라, 30분씩 걸리는 제작을 봇 안에서
돌리면 그 사이 폰 메시지를 아무도 안 받는다. 그래서 일꾼을 따로 떼어 낸다.

하는 일은 셋뿐이다.
  ① 헤드리스 `claude -p` 에 지시문을 **stdin 으로** 흘려 넣는다
     (인자로 주면 따옴표·줄바꿈이 cmd 에서 깨진다)
  ② 오간 말을 `runs/run_*.log` 에 남긴다 — pythonw 라 화면이 없다
  ③ 끝나면 폰에 결과 한 줄

★완성된 mp4 는 여기서 안 보낸다. 프로젝트 `Stop` 훅의 `deliver_sweep.py` 가
  이미 납품과 동시에 폰으로 보낸다 — 두 번 보내지 마라.

★예외를 밖으로 던지지 않는다. 일꾼이 죽어도 조용히 죽고, 상태 파일은 비워 둔다.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tg        # noqa: E402
import tg_run    # noqa: E402

CLAUDE = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
SETTINGS = os.path.join(HERE, "run_settings.json")


# ★폰 알림 스위치 (사장님 지시 2026-08-28 「결과 나오면 텔레그램으로 보내던거 다 중지」)
#   주문이 끝났을 때 폰으로 가던 결과 한 줄(완료/시간초과/실패)을 껼다.
#   소재 알림(`notify_hunt.PUSH`) · 완성본 알림(`deliver_sweep.PUSH`) 과 같은 방식이다 —
#   되켜때는 이 한 줄만 `True` 로. 호출처(세 군데)는 손대지 않았다.
#   ★런 자체는 그대로 돌고 결과도 그대로 남는다 — 오간 말은 `runs/run_*.log` 에,
#     상태는 `orders.json` 에 찍힌다. 폰에서 `주문` · `상태` 로 그대로 꺼내진다.
PUSH = False


def note(msg):
    if not PUSH:
        return
    try:
        tg.send_text(msg)
    except Exception:
        pass


def perm_args(perm):
    """권한 울타리.

    ★기본은 `scoped` — `run_settings.json` 의 allow 목록만 돌게 한다.
      헤드리스에는 물어볼 사람이 없어 **목록에 없는 것은 그대로 거부**된다.
      그래서 그 목록이 곧 울타리이고, 권한을 통째로 여는 길로 갈 이유가 없다.
      런이 중간에 서면 `runs/run_*.log` 에 무엇이 거부됐는지 남으니 그 줄만 더한다.

    `bypass` 는 남겨 두었지만 쓰지 마라 — 목록을 넓히는 쪽이 언제나 낫다.
    """
    if perm == "bypass":
        return ["--dangerously-skip-permissions"]
    return ["--permission-mode", "acceptEdits", "--settings", SETTINGS]


def main():
    if len(sys.argv) < 2:
        return 2
    try:
        with io.open(sys.argv[1], encoding="utf-8") as f:
            job = json.load(f)
    except Exception:
        return 2

    logp = job.get("log") or os.path.join(tg_run.RUNDIR, "run.log")
    promptp = logp + ".prompt.txt"
    t0 = time.time()
    rc = -1
    try:
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        with io.open(promptp, "w", encoding="utf-8") as f:
            f.write(job.get("prompt", ""))

        cmd = ([os.environ.get("COMSPEC", "cmd.exe"), "/c", CLAUDE, "-p"]
               + perm_args(job.get("perm")))
        with io.open(promptp, "r", encoding="utf-8") as fin, \
                io.open(logp, "w", encoding="utf-8", errors="replace") as fout:
            fout.write("$ %s\n\n" % " ".join(cmd[3:]))
            fout.flush()
            rc = subprocess.call(cmd, cwd=ROOT, stdin=fin, stdout=fout,
                                 stderr=subprocess.STDOUT,
                                 timeout=int(job.get("max_min", 180)) * 60)
    except subprocess.TimeoutExpired:
        rc = -9
    except Exception as e:
        try:
            with io.open(logp, "a", encoding="utf-8", errors="replace") as fout:
                fout.write("\n[일꾼 실패] %s\n" % e)
        except Exception:
            pass

    mins = (time.time() - t0) / 60
    tail = ""
    try:
        with io.open(logp, encoding="utf-8", errors="replace") as f:
            tail = f.read()[-600:]
    except Exception:
        pass

    if rc == 0:
        note("✅ <b>주문 완료</b> <i>(%.0f분)</i>\n%s\n\n%s"
             % (mins, tg.esc(job.get("text", "")[:120]), tg.esc(tail[-400:])))
        state = "완료"
    elif rc == -9:
        note("⏱ <b>시간 초과로 끊었습니다</b> <i>(%.0f분)</i>\n%s"
             % (mins, tg.esc(job.get("text", "")[:120])))
        state = "시간초과"
    else:
        note("⚠️ <b>주문을 끝내지 못했습니다</b> <i>(%.0f분 · 코드 %s)</i>\n%s\n\n%s"
             % (mins, rc, tg.esc(job.get("text", "")[:120]), tg.esc(tail[-400:])))
        state = "실패"

    tg_run._mark(job.get("order"), state=state)
    tg_run._save(tg_run.RUNSTATE, {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
