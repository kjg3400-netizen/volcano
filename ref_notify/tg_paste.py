# -*- coding: utf-8 -*-
"""새 텔레그램 토큰을 작은 창에 쳐 넣으면 키 파일에 저장한다.

  python ref_notify/tg_paste.py

파일을 직접 열어 고치는 게 번거로워서 만들었다 — 창 하나만 뜨고 끝난다.
★다른 열쇠(evolink·typecast·speechmatics)는 건드리지 않는다. telegram 파일만 쓴다.
"""
import io, os, re, sys
import tkinter as tk
from tkinter import messagebox

KEY = os.path.expanduser("~/.volcano/keys/telegram")
PAT = re.compile(r"^\d{6,12}:[A-Za-z0-9_\-]{30,}$")


def save():
    t = box.get("1.0", "end").strip()
    if not t:
        messagebox.showwarning("비었음", "토큰을 넣어 주세요.")
        return
    t = "".join(t.split())                      # 줄바꿈·공백 제거
    if not PAT.match(t):
        if not messagebox.askyesno(
                "모양이 다릅니다",
                "텔레그램 토큰은 보통\n\n  숫자 : 영문숫자35자\n\n꼴입니다.\n"
                f"지금 넣으신 건 {len(t)}자이고 그 꼴이 아닙니다.\n\n그래도 저장할까요?"):
            return
    os.makedirs(os.path.dirname(KEY), exist_ok=True)
    io.open(KEY, "w", encoding="utf-8").write(t + "\n")
    messagebox.showinfo(
        "저장했습니다",
        f"{len(t)}자를 저장했습니다.\n\n{KEY}\n\n"
        "이제 클로드한테 '알림 확인해줘' 라고 하시면 됩니다.")
    root.destroy()


root = tk.Tk()
root.title("텔레그램 토큰 넣기")
root.geometry("620x230")
root.attributes("-topmost", True)

tk.Label(root, text="BotFather 가 준 새 토큰을 여기에 치거나 붙여넣으세요",
         font=("맑은 고딕", 11)).pack(pady=(14, 4))
tk.Label(root, text="다른 열쇠(evolink·typecast)는 건드리지 않습니다",
         font=("맑은 고딕", 9), fg="#666").pack()

box = tk.Text(root, height=3, font=("Consolas", 12), wrap="char")
box.pack(fill="x", padx=16, pady=10)
box.focus_set()

tk.Button(root, text="저장", font=("맑은 고딕", 11), width=14,
          command=save).pack(pady=(0, 6))
tk.Button(root, text="그만두기", font=("맑은 고딕", 9),
          command=root.destroy).pack()

root.mainloop()
