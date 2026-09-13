# -*- coding: utf-8 -*-
"""회차 하나가 납품될 때까지 기다렸다가 폰으로 한 줄 보낸다.
★사장님이 「끝나면 알려줘」 하신 그 한 건에만 쓴다 — 밀어 주기 스위치(PUSH=False)와 무관한
일회성 대답이다. 헌터·훅·일꾼에서 부르지 마라.

  python ref_notify/tg_wait_done.py <workdir> --label "용혜인 편" --detach

- 끝난 신호: <workdir>/delivered.json 이 생기면 제목·파일·검사 결과를 보내고 끝난다
- 보조 신호: --outdir(완성본 폴더) 맨 위에 새 mp4 가 오면 delivered.json 을 몇 분 더
  기다렸다가 그래도 없으면 파일명만 보내고 끝난다
- 멈춤: 폴더 안 파일이 --stall 분 동안 하나도 안 바뀌면 「멈춘 것 같다」를 한 번만 보내고
  계속 기다린다 (드라이브는 모델 차례마다 죽었다 살아나므로 프로세스 유무로는 못 잰다)
- 상한: --hours 지나면 「아직 안 끝났다」 한 줄 남기고 끝난다
- 기록: ref_notify/runs/wait_done_<workdir 이름>.log
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tg  # noqa: E402

PY = sys.executable
POLL = 30          # 초
GRACE_POLLS = 6    # 새 mp4 만 보이고 delivered.json 이 없을 때 더 기다리는 횟수 (3분)


def say(s):
    print(time.strftime("%H:%M:%S"), s, flush=True)


def latest_mtime(wd):
    latest = 0.0
    for root, _dirs, files in os.walk(wd):
        for fn in files:
            try:
                m = os.stat(os.path.join(root, fn)).st_mtime
            except OSError:
                continue
            if m > latest:
                latest = m
    return latest


def top_mp4s(outdir, since):
    if not outdir or not os.path.isdir(outdir):
        return set()
    got = set()
    for fn in os.listdir(outdir):
        p = os.path.join(outdir, fn)
        if fn.lower().endswith(".mp4") and os.path.isfile(p):
            try:
                if os.stat(p).st_mtime > since:
                    got.add(fn)
            except OSError:
                pass
    return got


def send(msg):
    ok = tg.send_text(msg)
    say(("보냄: " if ok else "★발송 실패: ") + msg.replace("\n", " / "))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--label", default="회차")
    ap.add_argument("--outdir", default="D:/제작공장/03_볼케이노 완성본/정치")
    ap.add_argument("--stall", type=int, default=90, help="이 분 동안 변화가 없으면 한 번 알린다")
    ap.add_argument("--hours", type=float, default=12.0, help="이 시간이 지나면 포기하고 끝난다")
    ap.add_argument("--detach", action="store_true")
    a = ap.parse_args()

    wd = os.path.abspath(a.workdir)
    if not os.path.isdir(wd):
        sys.exit("작업 폴더가 없다: " + wd)

    if a.detach:
        runs = os.path.join(HERE, "runs")
        os.makedirs(runs, exist_ok=True)
        logp = os.path.join(runs, "wait_done_%s.log" % os.path.basename(wd))
        cmd = [PY, os.path.abspath(__file__), wd, "--label", a.label, "--outdir", a.outdir,
               "--stall", str(a.stall), "--hours", str(a.hours)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        with open(logp, "w", encoding="utf-8") as f:
            p = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=f, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, creationflags=0x00000008 | 0x00000200)
        print("떼어 냈다 pid=%d · 기록 %s" % (p.pid, logp))
        return

    label = tg.esc(a.label)
    started = time.time()
    deadline = started + a.hours * 3600
    delivered = os.path.join(wd, "delivered.json")
    seen_mp4 = top_mp4s(a.outdir, 0)          # 지금 있는 것은 빼고 센다
    stall_told = False
    grace_left = None
    say("기다린다: %s (label=%s, stall=%d분, 상한 %.1f시간)" % (wd, a.label, a.stall, a.hours))

    while True:
        if os.path.exists(delivered):
            try:
                with open(delivered, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception as e:  # 쓰는 도중일 수 있다 — 한 번 더 돈다
                say("delivered.json 읽기 실패, 다시: %s" % e)
                time.sleep(5)
                continue
            lines = ["🟢 <b>%s 끝났습니다</b>" % label]
            if d.get("title"):
                lines.append(tg.esc(d["title"]))
            if d.get("file"):
                lines.append("파일: " + tg.esc(d["file"]))
            if d.get("check"):
                lines.append("검사: " + tg.esc(d["check"]))
            copies = d.get("copies") or []
            if copies:
                lines.append("완성본: " + tg.esc(copies[-1]))
            send("\n".join(lines))
            return

        new_mp4 = top_mp4s(a.outdir, started) - seen_mp4
        if new_mp4:
            if grace_left is None:
                grace_left = GRACE_POLLS
                say("새 mp4 보임, delivered.json 을 조금 더 기다린다: %s" % sorted(new_mp4))
            elif grace_left <= 0:
                send("🟢 <b>%s 완성본이 나왔습니다</b>\n%s\n(delivered.json 은 아직 없음)"
                     % (label, tg.esc("\n".join(sorted(new_mp4)))))
                return
            grace_left -= 1

        idle_min = (time.time() - latest_mtime(wd)) / 60
        if idle_min >= a.stall and not stall_told:
            stall_told = True
            send("🟠 <b>%s 가 %d분째 멈춰 있습니다</b>\n폴더에 새 파일이 없음. 계속 지켜봅니다"
                 % (label, int(idle_min)))
        elif idle_min < a.stall / 2:
            stall_told = False       # 다시 움직이면 다음 멈춤도 알린다

        if time.time() > deadline:
            send("🟠 <b>%s — %.0f시간이 지나도 안 끝났습니다</b>\n지켜보기를 그만둡니다"
                 % (label, a.hours))
            return
        time.sleep(POLL)


if __name__ == "__main__":
    main()
