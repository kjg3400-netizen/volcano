# -*- coding: utf-8 -*-
"""일본어 제목을 한국어로 옮긴다 — 텔레그램 알림에 곁들일 뜻풀이용.

키가 필요 없는 공개 엔드포인트를 쓴다. 정식 번역 품질은 아니고
**폰에서 훑을 때 무슨 얘긴지 알아보는 정도**가 목적이다.

★한 번에 긴 문장을 보내면 조용히 잘린다 (2026-08-21 실측:
  `実は多い…《現金払い》にこだわる人たち　SNS「正直イラっとする」…` 를 통째로 보내면
  `실은 많다…《현금 지불》을 고집하는 사람들` 에서 끊기고 뒤가 통째로 사라진다.
  부호를 바꿔도 같다). 그래서 **끊어서 보내고 이어 붙인다.**

★번역이 실패해도 절대 예외를 던지지 않는다 — 알림이 그것 때문에 죽으면 안 된다.
"""
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_tr_cache.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
API = ("https://translate.googleapis.com/translate_a/single"
       "?client=gtx&sl=ja&tl=ko&dt=t&q=")
CHUNK = 28          # 이보다 길면 잘려서 온다
TIMEOUT = 6

_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.load(io.open(CACHE, encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _save():
    try:
        # 무한정 불어나지 않게 최근 것만 남긴다
        c = _load()
        if len(c) > 800:
            c = dict(list(c.items())[-500:])
            globals()["_cache"] = c
        json.dump(c, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def _call(t):
    req = urllib.request.Request(API + urllib.parse.quote(t, safe=""),
                                 headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
    return " ".join(x[0].strip() for x in d[0] if x and x[0])


def _split(t):
    """부호에서 먼저 끊고, 그래도 길면 글자수로 끊는다."""
    parts, buf = [], ""
    for piece in re.split(r"([　。！？…]+)", t):
        if not piece:
            continue
        if len(buf) + len(piece) <= CHUNK:
            buf += piece
        else:
            if buf:
                parts.append(buf)
            while len(piece) > CHUNK:
                parts.append(piece[:CHUNK])
                piece = piece[CHUNK:]
            buf = piece
    if buf:
        parts.append(buf)
    return [p for p in (x.strip() for x in parts) if p]


def ja2ko(text):
    """일본어 → 한국어. 실패하면 빈 문자열. 절대 예외를 던지지 않는다."""
    t = (text or "").strip()
    if not t:
        return ""
    c = _load()
    if t in c:
        return c[t]
    try:
        out = " ".join(x for x in (_call(p) for p in _split(t)) if x)
        out = re.sub(r"\s{2,}", " ", out).strip()
    except Exception:
        return ""
    if out and out != t:
        c[t] = out
        _save()
    return out


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for s in (sys.argv[1:] or [
            "「丸亀製麺」最高益から一転減益…「はなまるうどん」と明暗が分かれたワケ。猛追する「資さんうどん」",
            "実は多い…《現金払い》にこだわる人たち　SNS「正直イラっとする」「後ろの列のこと考えて」厳しい声も",
            "霞が関、国産AIシステム始動　「源内」国会答弁の作成支援も"]):
        print("JA", s)
        print("KO", ja2ko(s))
        print()
