# -*- coding: utf-8 -*-
"""깃허브 토큰을 창에 붙여넣으면 저장하고 바로 올린다.

  python ref_backup/gh_paste.py

★토큰을 화면·대화기록에 찍지 않는다. 길이만 확인한다.
★remote URL 에 토큰을 박지 않는다 — .git/config 는 평문이라 나중에 새기 쉽다.
  대신 자격증명 저장소(git credential store)에 넣어 URL 은 깨끗하게 둔다.
"""
import io
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GIT = r"C:\Program Files\Git\cmd\git.exe"
USER = "kjg3400-netizen"
CRED = os.path.expanduser("~/.git-credentials")


def save_and_push():
    tok = "".join(box.get("1.0", "end").split())
    if not tok:
        messagebox.showwarning("비었음", "토큰을 붙여넣어 주세요.")
        return
    if not re.match(r"^gh[pousr]_[A-Za-z0-9]{20,}$", tok):
        if not messagebox.askyesno(
                "모양이 다릅니다",
                "깃허브 토큰은 보통 ghp_ 로 시작하는 40자쯤 되는 글자입니다.\n"
                f"지금 넣으신 건 {len(tok)}자입니다.\n\n그래도 진행할까요?"):
            return

    # 자격증명 저장소에 넣는다 (remote URL 은 그대로 둔다)
    line = f"https://{USER}:{tok}@github.com\n"
    old = ""
    if os.path.exists(CRED):
        old = "".join(l for l in io.open(CRED, encoding="utf-8")
                      if "github.com" not in l)
    io.open(CRED, "w", encoding="utf-8").write(old + line)
    subprocess.run([GIT, "config", "--global", "credential.helper", "store"],
                   cwd=ROOT)

    p = subprocess.run([GIT, "push", "-u", "origin", "main"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    # 혹시라도 토큰이 메시지에 섞여 나오면 가린다
    out = out.replace(tok, "***")
    if p.returncode == 0:
        messagebox.showinfo("올라갔습니다",
                            f"토큰 {len(tok)}자 저장 · 업로드 성공\n\n{out[-400:]}")
        root.destroy()
    else:
        messagebox.showerror("실패", out[-700:] or "알 수 없는 오류")


root = tk.Tk()
root.title("깃허브 토큰 넣기")
root.geometry("640x250")
root.attributes("-topmost", True)

tk.Label(root, text="복사하신 깃허브 토큰을 여기에 붙여넣으세요  (Ctrl+V)",
         font=("맑은 고딕", 11)).pack(pady=(14, 4))
tk.Label(root, text="저장 누르면 바로 업로드까지 합니다",
         font=("맑은 고딕", 9), fg="#666").pack()

box = tk.Text(root, height=3, font=("Consolas", 11), wrap="char")
box.pack(fill="x", padx=16, pady=10)
box.focus_set()

tk.Button(root, text="저장하고 올리기", font=("맑은 고딕", 11), width=18,
          command=save_and_push).pack(pady=(0, 6))
tk.Button(root, text="그만두기", font=("맑은 고딕", 9),
          command=root.destroy).pack()

root.mainloop()
