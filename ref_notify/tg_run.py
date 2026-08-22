# -*- coding: utf-8 -*-
"""폰에서 온 말을 **주문으로 알아듣는** 층.

여태 봇은 `VERBS` 에 적힌 낱말 6개만 명령으로 보고 나머지는 전부 창고에 넣었다.
그래서 사장님이 "이걸 일본뇌전구로 만들어줘" 라고 하셔도 메모 한 줄로 쌓이고
아무 일도 일어나지 않았다 (2026-08-21~22 에 주문 6건이 그렇게 묻혔다).

여기서 두 가지를 가른다 — **인식**과 **실행**이다.

  ① 인식 — 주문처럼 생긴 말은 메모가 아니라 `orders.json` 에 주문으로 적고
     폰에 바로 "접수" 라고 답한다. 이건 늘 돈다. 위험이 없다.
  ② 실행 — 헤드리스 `claude -p` 를 띄워 실제로 만들게 한다.
     `run_config.json` 의 `enabled` 로 끌 수 있다 (기본 켜짐).

★권한은 넓게 열지 않는다 — 목록이 곧 울타리다
  파이프라인은 거의 전부 Bash(python·ffmpeg·curl)라 권한이 필요하다. 그런데
  헤드리스에는 물어볼 사람이 없어 **허용목록에 없는 것은 그대로 거부**된다.
  그 성질을 울타리로 쓴다 — `run_settings.json` 에 파이프라인이 쓰는 명령만 적고
  `--settings` 로 그 세션에만 얹는다. 사장님이 터미널에서 쓰시는 세션은 안 건드린다.
  런이 중간에 서면 `runs/run_*.log` 에 무엇이 거부됐는지 남으니 그 줄만 더한다.

★이 파일은 예외를 밖으로 던지지 않는다. `tg.py` 와 같은 규칙이다 —
  주문 인식이 죽어도 봇은 살아서 창고 노릇은 해야 한다.
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
import tg  # noqa: E402

ORDERS = os.path.join(HERE, "orders.json")
RUNCFG = os.path.join(HERE, "run_config.json")
RUNDIR = os.path.join(HERE, "runs")
RUNSTATE = os.path.join(HERE, "run_state.json")
WORKER = os.path.join(HERE, "tg_worker.py")

PYW = r"C:\Users\kjg34\AppData\Local\Programs\Python\Python312\pythonw.exe"

# ───────────────────────── 주문인지 가리는 자 ─────────────────────────
# ★두 조건을 **모두** 만족해야 주문이다 — 만들라는 말 + 무엇을 만들지.
#   한쪽만으로 걸면 "왜 시작안해?" · "한국커뮤형 언제나와" 같은 재촉이 주문으로 둔갑한다
#   (실제로 창고에 그런 말이 4건 있었다).

MAKE = ("만들어", "만들자", "만드러", "만들어라", "제작", "뽑아",
        "구워", "굽자", "작업해", "진행해", "시작해")

FORMAT = ("뇌전구", "인물형", "축구", "잭제이", "짹짹", "골프", "짧뷰",
          "칩칩", "랑카", "ランカー", "매일일보", "커뮤형", "커뮤", "경제형",
          "경제", "일본판", "영어학습", "숏단지", "숏피드", "방탐", "소재", "시트")


def has_link(t):
    return "http://" in t or "https://" in t


def looks_like_order(text):
    """주문처럼 보이면 True. 애매하면 False 로 둔다 — 잘못 시작하는 쪽이 더 나쁘다."""
    try:
        t = (text or "").strip()
        if len(t) < 4:
            return False
        if not any(w in t for w in MAKE):
            return False
        return has_link(t) or any(w in t for w in FORMAT)
    except Exception:
        return False


# ───────────────────────────── 설정·상태 ─────────────────────────────

DEFAULT_CFG = {
    "enabled": True,           # 폰에서 온 주문을 실제로 굽는다
    "perm": "scoped",          # "scoped"(run_settings.json 목록만) | "bypass"(쓰지 마라)
    "max_min": 180,            # 한 건이 이보다 오래 끌면 끊는다
}


def cfg():
    c = dict(DEFAULT_CFG)
    try:
        with io.open(RUNCFG, encoding="utf-8") as f:
            c.update(json.load(f))
    except Exception:
        pass
    return c


def _load(path, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid)],
                             capture_output=True, text=True, timeout=15)
        return str(pid) in (out.stdout or "")
    except Exception:
        return False


def running():
    """지금 도는 주문이 있으면 그 기록을, 없으면 None. 죽은 기록은 스스로 지운다."""
    st = _load(RUNSTATE, None)
    if not isinstance(st, dict) or not st.get("pid"):
        return None
    if not _alive(st["pid"]):
        _save(RUNSTATE, {})
        return None
    return st


# ────────────────────────────── 접수·실행 ──────────────────────────────

def record(text):
    """주문을 장부에 적는다. 실행을 못 해도 이건 남아야 자리에 앉아 꺼낼 수 있다."""
    rows = _load(ORDERS, [])
    if not isinstance(rows, list):
        rows = []
    rows.append({"t": time.strftime("%Y-%m-%d %H:%M"), "text": text,
                 "state": "대기", "run": None})
    _save(ORDERS, rows)
    return len(rows)


def pending():
    rows = _load(ORDERS, [])
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("state") == "대기"]


def _mark(idx, **kw):
    rows = _load(ORDERS, [])
    if isinstance(rows, list) and idx and 1 <= idx <= len(rows):
        rows[idx - 1].update(kw)
        _save(ORDERS, rows)


PROMPT = """[폰에서 온 지시 — 사장님]
{text}

위 지시대로 볼케이노 작업을 끝까지 진행해라.

- `CLAUDE.md` 규약을 그대로 따른다.
- **되묻지 마라.** 폰에서 온 것이라 답을 받을 수 없다. 판단이 필요하면
  가장 가까운 쪽을 골라 진행하고, 무엇을 골랐는지 마지막에 밝힌다.
- 소재를 고르라는 뜻이면 헌터 시트(`ref_*/out/_최신시트.md`)를 먼저 열어 본다.
- 다 만들었으면 반드시 `python deliver.py <workdir> "<제목> (카테고리)"` 로 납품한다.
- 이 지시 범위 밖의 일은 하지 않는다.
"""


def start(text, idx=None):
    """헤드리스 claude 를 떼어 내 띄운다. (성공?, 까닭) 을 돌려준다."""
    c = cfg()
    if not c.get("enabled"):
        return False, "off"
    if running():
        return False, "busy"
    try:
        os.makedirs(RUNDIR, exist_ok=True)
        stamp = time.strftime("%m%d_%H%M%S")
        job = os.path.join(RUNDIR, "job_%s.json" % stamp)
        _save(job, {"text": text, "prompt": PROMPT.format(text=text),
                    "log": os.path.join(RUNDIR, "run_%s.log" % stamp),
                    "perm": c.get("perm"), "max_min": c.get("max_min"),
                    "order": idx})
        p = subprocess.Popen(
            [PYW, WORKER, job], cwd=ROOT, close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x00000008 | 0x00000200)   # DETACHED | NEW_GROUP
        _save(RUNSTATE, {"pid": p.pid, "started": time.time(),
                         "text": text[:200], "job": job})
        _mark(idx, state="진행", run=job)
        return True, "started"
    except Exception as e:
        return False, "실패: %s" % e


def stop():
    st = running()
    if not st:
        return "지금 도는 게 없습니다."
    try:
        subprocess.run(["taskkill", "/PID", str(st["pid"]), "/T", "/F"],
                       capture_output=True, timeout=20)
        _save(RUNSTATE, {})
        return "⛔ 중단했습니다 — <i>%s</i>" % tg.esc(st.get("text", "")[:60])
    except Exception as e:
        return "중단하지 못했습니다: %s" % tg.esc(str(e)[:80])


def handle(text):
    """주문으로 알아들은 말을 처리하고 폰에 보낼 답을 돌려준다."""
    idx = record(text)
    ok, why = start(text, idx)
    if ok:
        return ("🎬 <b>접수 — 지금 시작합니다</b>\n<i>%s</i>\n\n"
                "다 되면 완성본이 이리로 옵니다. 그만두시려면 <b>중단</b>."
                % tg.esc(text[:160]))
    if why == "busy":
        st = running() or {}
        return ("⏳ <b>주문 %d번으로 받아 뒀습니다</b>\n지금 다른 걸 만들고 있습니다 — "
                "<i>%s</i>\n\n끝나면 이어서 합니다."
                % (idx, tg.esc(st.get("text", "")[:60])))
    if why == "off":
        return ("📋 <b>주문 %d번으로 받았습니다</b>\n<i>%s</i>\n\n"
                "다만 <b>폰에서 바로 만드는 스위치가 꺼져 있습니다.</b>\n"
                "자리에 앉으시면 '주문' 으로 꺼내 바로 만듭니다."
                % (idx, tg.esc(text[:160])))
    return "📋 주문으로 받았습니다만 시작하지 못했습니다 — %s" % tg.esc(str(why)[:100])


def cmd_orders(arg="", st=None):
    rows = _load(ORDERS, [])
    if not isinstance(rows, list) or not rows:
        return "받아 둔 주문이 없습니다."
    live = [(i, r) for i, r in enumerate(rows, 1)
            if isinstance(r, dict) and r.get("state") in ("대기", "진행")]
    if not live:
        return "대기 중인 주문이 없습니다. <i>(지난 주문 %d건)</i>" % len(rows)
    out = ["📋 <b>주문 %d건</b>" % len(live)]
    for i, r in live:
        out.append("<b>%d.</b> %s\n     <i>%s · %s</i>"
                   % (i, tg.esc(r.get("text", "")[:90]), r.get("t", ""), r.get("state")))
    cur = running()
    if cur:
        out.append("\n🎬 지금 도는 것 — <i>%s</i>" % tg.esc(cur.get("text", "")[:60]))
    return "\n".join(out)


def cmd_stop(arg="", st=None):
    return stop()


# ─────────────────────────── 자가검사 ───────────────────────────
# `python tg_run.py` 로 판정을 눈으로 본다. ★재촉하는 말이 주문으로 새면 안 된다 —
# 창고에 실제로 쌓여 있던 말들을 그대로 표본으로 박아 두었다.

SAMPLE = [
    # (주문이어야 하나?, 말)
    (True,  "이걸 소재로 일본뇌전구 형식으로 만들어줘 만들기시작하면 알려줘 "
            "https://news.yahoo.co.jp/articles/50c6"),
    (True,  "5시에 업로드할 한국 일본 커뮤형 경제형 현시점 댓글조회1등들로 제작해줘"),
    (True,  "https://youtu.be/abc123 골프로 만들어줘"),
    (True,  "경제 소재 뽑아 줘"),
    (True,  "칩칩으로 만들어줘"),
    (False, "진행시작햇으면알려줘"),
    (False, "한국커뮤형언제나와"),
    (False, "이거 되는거여?"),
    (False, "왜 시작안해?"),
    (False, "나오고있어?"),
    (False, "칩칩"),
    (False, "시트 커뮤"),
    (False, "3번"),
    (False, "밥 먹었어?"),
]


def selftest():
    bad = 0
    print("%-8s %-8s %s" % ("기대", "판정", "말"))
    print("-" * 74)
    for want, t in SAMPLE:
        got = looks_like_order(t)
        ok = (got == want)
        bad += 0 if ok else 1
        print("%-8s %-8s %s%s" % ("주문" if want else "창고",
                                  "주문" if got else "창고", t[:52],
                                  "" if ok else "   ← 틀림"))
    print("-" * 74)
    print("어긋남 %d건" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(selftest())
