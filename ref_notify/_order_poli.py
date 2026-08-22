# -*- coding: utf-8 -*-
"""폰에서 받은 정치형 이어굽기 주문 한 건을 접수한다. (일회용)"""
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tg_run

TEXT = (
    "정치채널 첫 영상을 이어서 제작해줘. work_poli_0822_taegyu 에 job.json 이 이미 있다"
    "(2026-08-22 법사위 김태규 호칭 충돌). 거기서 이어간다 — "
    "① 소재 영상 https://www.youtube.com/watch?v=4vZhUOLaZbA (연합뉴스TV 2:09) 을 "
    "yt-dlp 로 그 폴더 src.mp4 로 받는다. 안 되면 _영상후보 둘째·셋째를 쓴다. "
    "② ref_maeil/asr_subs.py 로 전사해 subs 를 채운다. 커버리지를 재고 빠진 창은 잘라 재시도한다. "
    "③ brand 는 빈칸 그대로 둔다 — 사장님이 나중에 캡컷에서 채널명을 직접 넣으신다. 경고는 무시해도 된다. "
    "④ card.badge 는 '긴급뉴스' 를 베끼지 말고 문구를 새로 지어 넣는다. "
    "⑤ 길이는 캡하지 말고 소재가 끝나는 데서 끝낸다. 효과를 얹지 않는다. "
    "⑥ python ref_poli/poli_build.py work_poli_0822_taegyu/job.json --check 로 굽고 "
    "python deliver.py work_poli_0822_taegyu \"<제목> (정치)\" 로 납품한다."
)

print(tg_run.handle(TEXT))
