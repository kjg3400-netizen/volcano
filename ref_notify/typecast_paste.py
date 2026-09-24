# -*- coding: utf-8 -*-
"""새 Typecast API 키를 작은 창에 붙여넣으면 — 저장 **전에** 그 키로 계정 요금제를 확인하고 — 키 파일에 저장한다.

  python ref_notify/typecast_paste.py

tg_paste.py(텔레그램 토큰)와 같은 꼴. 2026-09-24 사용자 요청 「api키 새로 입력할수있게 열어줘 다른거 유료 플랜으로 넣을께」
(옛 키 계정이 무료로 바뀌며 복제 목소리가 사라짐 — 우격다짐·Astra 연예인 둘 다).
★옛 키는 지우지 않는다 — `typecast.bak_<시각>` 으로 옮겨 두고 새 키를 쓴다.
★키 값은 화면·기록 어디에도 찍지 않는다. 결과(요금제·복제 자리·크레딧)만 stdout 한 줄로 남긴다.
★다른 열쇠(evolink·telegram·speechmatics)는 건드리지 않는다. typecast 파일만 쓴다.
"""
import io, json, os, shutil, sys, time, urllib.error, urllib.request
import tkinter as tk
from tkinter import messagebox

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
KEY = os.path.expanduser("~/.volcano/keys/typecast")


def 요금제(key):
    req = urllib.request.Request("https://api.typecast.ai/v1/users/me/subscription",
                                 headers={"X-API-KEY": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode("utf-8", "replace")
    except Exception as e:                      # noqa: BLE001
        return None, repr(e)


def save():
    t = "".join(box.get("1.0", "end").split())   # 줄바꿈·공백 제거
    if not t:
        messagebox.showwarning("비었음", "Typecast API 키를 붙여넣어 주세요.")
        return
    try:
        old = io.open(KEY, encoding="utf-8").read().strip() if os.path.exists(KEY) else ""
    except OSError:
        old = ""
    if t == old:
        messagebox.showwarning("같은 키", "지금 저장된 키(무료 계정)와 같은 키입니다.\n유료 계정의 새 키를 넣어 주세요.")
        return
    st, d = 요금제(t)
    if st != 200 or not isinstance(d, dict):
        messagebox.showerror("확인 실패", f"이 키로 Typecast 계정을 못 읽었습니다 (응답 {st}).\n\n{str(d)[:200]}\n\n저장하지 않았습니다.")
        print(f"RESULT=fail status={st}", flush=True)
        return
    plan = d.get("plan"); lim = d.get("limits") or {}; cr = d.get("credits") or {}
    slot = lim.get("custom_voice_slot")
    msg = (f"요금제: {plan}\n복제 목소리 자리: {slot}개\n"
           f"크레딧: {cr.get('used_credits')} / {cr.get('plan_credits')} 사용")
    if not slot:
        if not messagebox.askyesno("복제 자리가 없습니다",
                                   msg + "\n\n이 계정은 복제 목소리 자리가 0개라 우팔롬아 목소리를 다시 만들 수 없습니다.\n그래도 저장할까요?"):
            print(f"RESULT=cancel plan={plan} slot={slot}", flush=True)
            return
    os.makedirs(os.path.dirname(KEY), exist_ok=True)
    bak = ""
    if os.path.exists(KEY):
        bak = KEY + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(KEY, bak)
    io.open(KEY, "w", encoding="utf-8").write(t + "\n")
    print(f"RESULT=saved plan={plan} slot={slot} credits={cr.get('used_credits')}/{cr.get('plan_credits')} "
          f"len={len(t)} backup={os.path.basename(bak) if bak else '-'}", flush=True)
    messagebox.showinfo("저장했습니다",
                        msg + f"\n\n새 키({len(t)}자)를 저장했습니다.\n옛 키는 {os.path.basename(bak) or '없음'} 으로 옮겨 두었습니다.\n\n"
                        "이제 클로드한테 '넣었어' 라고 하시면 됩니다.")
    root.destroy()


root = tk.Tk()
root.title("Typecast API 키 넣기")
root.geometry("660x250")
root.attributes("-topmost", True)

tk.Label(root, text="유료 플랜 계정의 Typecast API 키를 여기에 붙여넣으세요",
         font=("맑은 고딕", 11)).pack(pady=(14, 4))
tk.Label(root, text="저장 전에 그 키의 요금제·복제 목소리 자리를 확인합니다 · 옛 키는 백업으로 남깁니다",
         font=("맑은 고딕", 9), fg="#666").pack()

box = tk.Text(root, height=3, font=("Consolas", 12), wrap="char")
box.pack(fill="x", padx=16, pady=10)
box.focus_set()

tk.Button(root, text="확인하고 저장", font=("맑은 고딕", 11), width=16,
          command=save).pack(pady=(0, 6))
tk.Button(root, text="그만두기", font=("맑은 고딕", 9),
          command=lambda: (print("RESULT=closed", flush=True), root.destroy())).pack()

root.mainloop()
