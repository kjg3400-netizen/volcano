# -*- coding: utf-8 -*-
"""헌터가 뽑은 최신 시트를 폰으로 요약해 보낸다.

    python ref_notify/notify_hunt.py --src econ     # 경제 (네이버)
    python ref_notify/notify_hunt.py --src comm     # 커뮤 11곳
    python ref_notify/notify_hunt.py --src jp       # 일본 경제 (야후)
    python ref_notify/notify_hunt.py --src comm --dry --top 5

각 daily.cmd 끝에 매달아 두면 헌터가 돈 직후 폰으로 날아온다.
★알림이 실패해도 종료코드는 0 이다 — 헌터의 성패와 알림의 성패는 별개다.

★세 헌터는 시트 모양이 제각각이다. 하나로 뭉뚱그리지 말고 소스별로 찍는다.

  | | 경제 | 커뮤 | 일본 |
  |---|---|---|---|
  | 최상위 키 | items | **rows** | items |
  | 최신 시트 | _최신시트.json | **없다 (hunt_*.json 중 최신)** | _최신시트.json |
  | 주소 | oid+aid 로 조립 | link | aid 로 조립 |
  | 경과 | age_text | age (시간, 실수) | age_hours |
  | 눈여겨볼 것 | 채널배수 | **기사 유무·교차 커뮤** | **대전제 안전도** |
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg  # noqa: E402

try:
    import translate  # noqa: E402  일본어 제목 뜻풀이 (없어도 알림은 나간다)
except Exception:
    translate = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ★★폰 알림은 꺼 두었다 (사장님 지시 2026-08-25 「소재 창고 이제 보내지마」).
#   헌터는 그대로 돈다 — 시트는 여전히 `ref_*/out/` 에 쌓이고, 폰으로 **밀어 주기만**
#   멈춘 것이다. 자리에 앉으시면 봇의 `시트`·`시트 커뮤` 로 그대로 꺼내진다.
#   ※완성본 알림(`deliver_sweep.py`)도 2026-08-28 에 껐다 — 스위치는 그 파일의 PUSH 다.
#   되켤 때는 이 한 줄만 True 로. 호출처(daily.cmd 6개·7군데)는 손대지 않았다.
PUSH = False


# 채널 실적이 좋은 꼴은 별을 붙인다 (CLAUDE.md 배수표: 한국vs해외 1.60 · 인물거액 1.48)
GOOD_MULT = 1.35
# 교차 커뮤가 이만큼이면 크게 터진 것이다 (CLAUDE.md: 가장 센 신호는 교차 확산)
GOOD_CROSS = 3
# 기사 겹침이 이 밑이면 딴 사건이다 — 만들지 마라
MIN_OVERLAP = 0.20


def newest(dirname, fname=None):
    """_최신시트.json 이 있으면 그것, 없으면 hunt_*.json 중 가장 최근 것.

    커뮤 헌터는 _최신시트.json 을 안 만든다 — 그래서 폴백이 필요하다.
    fname 을 주면 그 파일만 본다 — 갈래 걸러 돌린 결과(`_최신시트_sport.json`)처럼
    같은 폴더에 있지만 정규 시트와 섞이면 안 되는 것에 쓴다."""
    out = os.path.join(ROOT, dirname, "out")
    if fname:
        p = os.path.join(out, fname)
        return p if os.path.isfile(p) else None
    latest = os.path.join(out, "_최신시트.json")
    if os.path.isfile(latest):
        return latest
    cand = sorted(glob.glob(os.path.join(out, "hunt_*.json")))
    return cand[-1] if cand else None


def age_str(it):
    if it.get("age_text"):
        return str(it["age_text"])
    h = it.get("age_hours", it.get("age"))
    if h is None:
        return ""
    h = float(h)
    return "%d분전" % round(h * 60) if h < 1 else "%.0f시간전" % h


def head(i, title, url, mark=""):
    t = tg.esc(str(title).strip())
    if url:
        return "<b>%d.</b> %s<a href=\"%s\">%s</a>" % (i, mark, tg.esc(url), t)
    return "<b>%d.</b> %s%s" % (i, mark, t)


def ko_line(title):
    """일본어 제목 밑에 붙일 한국어 뜻풀이 줄. 실패하면 빈 문자열."""
    if not translate or not title:
        return ""
    try:
        ko = translate.ja2ko(title)
    except Exception:
        return ""
    return ("\n     <i>%s</i>" % tg.esc(ko)) if ko else ""


def china_block(sheet, top=5):
    """★중국 칸 — 실적으로 확인된 이 채널 최고 꼴이라 알림 맨 위에 따로 둔다.

    hunt.py 가 `china` 키에 따로 실어 준다. 점수 상위 N 밖에 있어도 여기엔
    뜬다 — items 만 읽으면 정작 제일 좋은 소재가 조용히 빠진다.
    """
    cc = [x for x in (sheet.get("china") or []) if x.get("title")]
    if not cc:
        return ""
    out = []
    for x in cc[:top]:
        mark = "○" if x.get("china") in ("관련",) else "◎"
        url = ""
        if x.get("oid") and x.get("aid"):
            url = "https://n.news.naver.com/article/%s/%s" % (x["oid"], x["aid"])
        elif x.get("aid"):
            # 야후(일본판)는 oid 가 없고 aid 하나로 주소가 선다
            url = "https://news.yahoo.co.jp/articles/%s" % x["aid"]
        t = tg.esc(str(x["title"]).strip())
        if url:
            line = '%s <a href="%s">%s</a>' % (mark, tg.esc(url), t)
        else:
            line = "%s %s" % (mark, t)
        bits = []
        if x.get("cluster_comments"):
            bits.append("💬%s" % x["cluster_comments"])
        bits.append(age_str(x))
        out.append(line + "\n     " + " · ".join(b for b in bits if b))
    nd = sum(1 for x in cc if x.get("china") not in ("관련",))
    cap = "🇨🇳 <b>중국 소재</b> — 이 채널 최고 꼴" + (" (◎ %d건)" % nd if nd else "")
    return cap + "\n" + "\n".join(out) + "\n\n➖➖➖➖➖\n"


def fmt_econ(i, it):
    url = ""
    if it.get("oid") and it.get("aid"):
        url = "https://n.news.naver.com/article/%s/%s" % (it["oid"], it["aid"])
    mult = it.get("ch_mult")
    mark = "⭐ " if mult and float(mult) >= GOOD_MULT else ""
    bits = ["<b>%.0f</b>점" % float(it.get("score") or 0)]
    if it.get("shape"):
        bits.append(tg.esc(it["shape"]) + (" ×%s" % mult if mult else ""))
    if it.get("cluster_comments"):
        bits.append("💬%s" % it["cluster_comments"])
    if it.get("cluster_n"):
        bits.append("%s매체" % it["cluster_n"])
    bits.append(age_str(it))
    return head(i, it.get("title"), url, mark) + "\n     " + " · ".join(b for b in bits if b)


def fmt_comm(i, it):
    """커뮤는 점수보다 ①기사가 있나 ②몇 곳에 동시에 떴나 가 먼저다."""
    n_sites = it.get("n_sites") or len(it.get("sites") or [])
    mark = "⭐ " if n_sites >= GOOD_CROSS else ""

    names, seen = [], set()
    for m in it.get("members") or []:
        nm = m.get("site_name")
        if nm and nm not in seen:
            seen.add(nm)
            names.append(nm)
    if not names and it.get("site_name"):
        names = [it["site_name"]]

    bits = ["<b>%.0f</b>점" % float(it.get("score") or 0)]
    if it.get("topic") or it.get("cate"):
        bits.append(tg.esc(it.get("topic") or it.get("cate")))
    if names:
        bits.append("🔗%d곳(%s)" % (n_sites or len(names), tg.esc("·".join(names[:3]))))
    if it.get("comment"):
        bits.append("💬%s" % it["comment"])
    bits.append(age_str(it))

    # ★기사 교차확인 — 이게 커뮤에서 제일 중요한 칸이다
    n, ov = it.get("news_n"), float(it.get("news_ov") or 0)
    warn = ""
    if n is None:
        warn = "\n     <i>기사 확인 안 함</i>"
    elif n < 0:
        warn = "\n     <i>기사 확인 실패</i>"
    elif n == 0:
        warn = "\n     ⛔ <b>관련 기사 없음 — 만들지 마라</b>"
    elif ov < MIN_OVERLAP:
        warn = "\n     ⛔ <b>겹침 %.2f — 딴 사건이다</b>" % ov
    else:
        bits.append("📰%d건(겹침%.2f)" % (n, ov))
    if it.get("trend"):
        bits.append("🔥%s" % tg.esc(it["trend"]))

    return (head(i, it.get("title"), it.get("link"), mark)
            + "\n     " + " · ".join(b for b in bits if b) + warn)


def fmt_jp(i, it):
    url = "https://news.yahoo.co.jp/articles/%s" % it["aid"] if it.get("aid") else ""
    mult = it.get("ch_mult")
    mark = "⭐ " if mult and float(mult) >= GOOD_MULT else ""
    bits = ["<b>%.0f</b>점" % float(it.get("score") or 0)]
    if it.get("shape"):
        bits.append(tg.esc(it["shape"]))
    if it.get("cluster_comments"):
        bits.append("💬%s" % it["cluster_comments"])
    if it.get("cluster_n") and int(it["cluster_n"]) > 1:
        bits.append("%s매체" % it["cluster_n"])
    bits.append(age_str(it))

    # ★대전제 안전도 — 음수면 일본을 나무라는 꼴이 될 위험이 있다
    safe = it.get("safety")
    warn = ""
    if safe is not None and float(safe) <= -0.30:
        why = tg.esc(" · ".join(it.get("safety_why") or [])[:60])
        warn = "\n     ⚠️ <b>안전도 %.2f</b>%s" % (float(safe), (" — " + why) if why else "")
    return (head(i, it.get("title"), url, mark) + ko_line(it.get("title"))
            + "\n     " + " · ".join(b for b in bits if b) + warn)


def fmt_jpcomm(i, it):
    """일본 커뮤 — 시트 모양이 커뮤와 **같다**(rows·link·age·교차확산·기사확인).
    다른 건 일본판 대전제 안전도가 하나 더 붙는다는 것뿐이라 그것만 얹는다."""
    s = fmt_comm(i, it)
    # 제목 줄 바로 밑에 한국어 뜻풀이를 끼운다 (커뮤 포맷은 첫 줄이 제목이다)
    ko = ko_line(it.get("title"))
    if ko:
        first, nl, rest = s.partition("\n")
        s = first + ko + nl + rest
    safe = it.get("safety")
    if safe is not None and float(safe) <= -0.30:
        why = tg.esc(" · ".join(it.get("safety_why") or [])[:60])
        s += "\n     ⚠️ <b>안전도 %.2f</b>%s" % (float(safe), (" — " + why) if why else "")
    return s


def fmt_sport(i, it):
    """축구·골프 클립 후보. 절대 조회수보다 **그 채널 중앙 대비 배수**가 먼저다 —
    큰 채널의 평범한 편보다 작은 채널에서 터진 편이 재포장 가치가 높다."""
    burst = float(it.get("burst") or 0)
    mark = "⭐ " if burst >= 3.0 else ""
    v = int(it.get("views") or 0)
    bits = ["%.0f만" % (v / 10000) if v >= 10000 else "%s" % format(v, ",")]
    if burst:
        bits.append("×%.1f" % burst)
    if it.get("shape"):
        bits.append(tg.esc(it["shape"]))
    if it.get("ch"):
        bits.append(tg.esc(str(it["ch"])[:18]))
    if it.get("age") is not None:
        bits.append("%d일전" % int(it["age"]))
    if not it.get("ontopic", True):
        bits.append("⚠️주제밖")
    url = "https://youtube.com/shorts/%s" % it.get("vid", "")
    return head(i, it.get("title"), url, mark) + "\n     " + " · ".join(bits)


SRC = {
    "econ": {"label": "📈 경제 소재", "dir": "ref_econ", "fmt": fmt_econ},
    "comm": {"label": "💬 커뮤 소재", "dir": "ref_comm", "fmt": fmt_comm},
    "jp":   {"label": "🇯🇵 일본 경제", "dir": "ref_jpecon", "fmt": fmt_jp},
    "jpcomm": {"label": "🇯🇵 일본 커뮤", "dir": "ref_jpcomm", "fmt": fmt_jpcomm},
    # 짹짹(축구)·짧뷰(골프) 용 **커뮤 글** 갈래. 같은 ref_comm 폴더를 쓰지만 파일을
    # 갈라 정규 커뮤 알림과 섞이지 않게 한다 (hunt.py --tag sport 가 만든다).
    # ※춤은 뺐다 — 칩칩 전용 헌터(`ref_chipchip/hunt.py`)가 더 잘 잡는다
    "sport": {"label": "⚽ 축구·골프 (커뮤 글)", "dir": "ref_comm",
              "file": "_최신시트_sport.json", "fmt": fmt_comm},
    # ★이쪽이 본진이다 — 소스 채널 풀에서 낚은 **클립** 후보 (ref_sport/hunt.py).
    #   위 커뮤 갈래는 '무슨 일이 있었나' 를 알려주는 레이더고, 여기가 실제 소재다
    "soccer": {"label": "⚽ 축구 클립 (짹짹·神ショーツ)", "dir": "ref_sport",
               "file": os.path.join("soccer", "_최신시트.json"), "fmt": fmt_sport},
    "golf":   {"label": "⛳ 골프 클립 (짧뷰)", "dir": "ref_sport",
               "file": os.path.join("golf", "_최신시트.json"), "fmt": fmt_sport},
}


def stats(meta):
    s = []
    if meta.get("pool") or meta.get("n_raw"):
        s.append("%s건 수집" % (meta.get("pool") or meta.get("n_raw")))
    if meta.get("events") or meta.get("n_ev"):
        s.append("%s사건" % (meta.get("events") or meta.get("n_ev")))
    if meta.get("dropped_seen"):
        s.append("기존 %s개 제외" % meta["dropped_seen"])
    if meta.get("blocked"):
        s.append("대전제 위반 %s개 제외" % meta["blocked"])
    return " · ".join(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="econ", choices=sorted(SRC))
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--dry", action="store_true", help="보내지 말고 화면에만 찍는다")
    a = ap.parse_args()

    # 시트를 읽기도 전에 나간다 — 꺼져 있는데 「건진 게 없다」가 날아가면 안 된다.
    if not (PUSH or a.dry):
        sys.stdout.reconfigure(errors="replace")
        print("폰 알림 꺼짐 (notify_hunt.PUSH=False) - 시트는 %s/out/ 에 그대로 있다"
              % SRC[a.src]["dir"])
        return 0

    spec = SRC[a.src]
    path = newest(spec["dir"], spec.get("file"))
    if not path:
        tg._log("시트가 없다: %s/out/" % spec["dir"])
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            sheet = json.load(f)
    except Exception as e:
        tg._log("시트를 못 읽었다 (%s): %s" % (path, e))
        return 0

    meta = sheet.get("meta") or {}
    items = [it for it in (sheet.get("items") or sheet.get("rows") or [])
             if not it.get("blocked")]

    if not items:
        tg.send_text("%s — 건진 게 없다 (%s)"
                     % (spec["label"], tg.esc(meta.get("stamp", ""))), silent=True)
        return 0

    body = [spec["fmt"](i, it) for i, it in enumerate(items[:a.top], 1)]
    cn = china_block(sheet) if a.src in ("econ", "jp") else ""
    msg = "%s <b>%s</b>\n<i>%s</i>\n\n%s%s" % (
        spec["label"], tg.esc(meta.get("stamp", "")), tg.esc(stats(meta)),
        cn, "\n\n".join(body))

    if a.dry:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(msg)
        print("\n--- %d자 (상한 %d) · %s" % (len(msg), tg.TEXT_LIMIT, path))
        return 0

    print("알림 보냄" if tg.send_text(msg) else "알림 실패 (헌터 결과는 멀쩡하다)")
    return 0  # 알림 실패로 예약작업을 빨갛게 만들지 않는다


if __name__ == "__main__":
    sys.exit(main())
