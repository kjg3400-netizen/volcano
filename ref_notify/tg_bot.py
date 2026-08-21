# -*- coding: utf-8 -*-
"""폰에서 보낸 것을 받아 **정해진 메뉴만** 답한다 (양방향 2단계).

    python ref_notify/tg_bot.py            # 한 번 길게 기다렸다 받는다 (예약 작업이 부른다)
    python ref_notify/tg_bot.py --once     # 기다리지 않고 쌓인 것만 즉시 처리
    python ref_notify/tg_bot.py --dry      # 답장을 보내지 말고 화면에만 찍는다
    python ref_notify/tg_bot.py --menu     # 메뉴만 확인

★★이것은 원격 셸이 아니다. 반드시 지킨다 (CLAUDE.md 2단계 조항).
  ① tg_config.json 의 chat_id **하나만** 받는다. 다른 사람이 봇을 찾아 말을 걸어도 무시한다
  ② 자유 명령을 받지 않는다. 아래 VERBS 에 적힌 낱말만 돌고, 셸·파일경로·코드를 받지 않는다
  ③ 메뉴에 없는 말은 명령이 아니라 **소재**로 본다 — 창고에 넣고 끝난다
  ④ 예외를 밖으로 던지지 않는다 (tg.py 와 같은 성질). 한 메시지가 죽어도 다음 것은 처리한다

★왜 상주 프로세스가 아닌가 — 예약 작업이 1분마다 부르고 한 번에 45초를 기다린다.
  체감은 상주와 같은데 재부팅에 살아남고, 죽어도 다음 분에 되살아난다.
  겹쳐 도는 것만 막으면 되므로 잠금 파일 하나를 쓴다.

★텔레그램은 받은 메시지를 **약 24시간**만 갖고 있다. PC 가 꺼져 있어도 그 안에 켜면
  쌓인 것이 한꺼번에 들어온다 — 그래서 우편함으로 쓸 수 있다.

★`offset` 을 밀면 그 메시지는 서버에서 사라진다. 그래서 이 봇이 도는 동안
  `tg_inbox.py` 로는 아무것도 안 보인다 — 받은 것은 `창고` 로 본다.

★★우편함을 비우는 것은 **이 파일 하나뿐이어야 한다.**
  텔레그램 offset 은 봇마다 하나뿐이라 수거자가 둘이면 메시지가 둘로 갈린다.
  `ref_clip/inbox.py` 가 매시간 같은 일을 하고 있었고(예약 `볼케이노 소재창고 매시간`),
  그쪽은 **링크 없는 메시지를 버리면서 offset 만 올렸다** — 사장님이 보내신 지시가
  그렇게 사라질 뻔했다(2026-08-21 실기). 그 예약은 껐고, 여기로 합쳤다.
  링크가 든 것은 그대로 `ref_clip/queue.json` 에 넣어 기존 창고를 살려 둔다.
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg            # noqa: E402
import notify_hunt   # noqa: E402  시트 읽기·소스별 서식을 그대로 쓴다

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(HERE, "bot_state.json")
LOCK = os.path.join(HERE, "bot.lock")
INBOX = os.path.join(HERE, "inbox")
INBOX_DB = os.path.join(INBOX, "inbox.json")
CLIP_QUEUE = os.path.join(ROOT, "ref_clip", "queue.json")   # 링크는 기존 클립 창고로
DEST = r"C:\Users\kjg34\Desktop\볼케이노 완성본"

POLL_SEC = 45          # 한 번 부를 때 기다리는 시간 (예약 간격 1분보다 짧게)
LOCK_STALE = 300       # 잠금이 이보다 오래되면 죽은 것으로 보고 뺏는다
MAX_FILE = 20 * 1024 * 1024   # 봇 API 가 받아올 수 있는 상한

# 시트 이름 → notify_hunt.SRC 키. 사장님이 부르시는 말을 전부 받는다.
SHEET_ALIAS = {
    "경제": "econ", "숏단지": "econ", "네이버": "econ",
    "커뮤": "comm", "커뮤니티": "comm",
    "일본": "jp", "일경": "jp", "쇼피드": "jp", "야후": "jp",
    "일커": "jpcomm", "일본커뮤": "jpcomm",
    "축구": "soccer", "짹짹": "soccer",
    "골프": "golf", "짧뷰": "golf",
    "스포츠": "sport",
}


LOGFILE = os.path.join(HERE, "bot_log.txt")
LOG_MAX = 1024 * 1024


def log(m):
    """★예약은 `pythonw` 로 돈다 — 창을 안 띄우는 대신 stdout·stderr 가 없다.
    그래서 화면이 아니라 파일에 남긴다. 로그가 죽어도 봇은 살아야 하므로 전부 감싼다."""
    line = "%s [bot] %s" % (time.strftime("%m-%d %H:%M:%S"), m)
    try:
        if sys.stderr is not None:
            sys.stderr.write(line + "\n")
    except Exception:
        pass
    try:
        if os.path.exists(LOGFILE) and os.path.getsize(LOGFILE) > LOG_MAX:
            os.remove(LOGFILE)          # 1분마다 도는 작업이라 그냥 두면 무한정 큰다
        with io.open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ────────────────────────────── 상태·잠금 ──────────────────────────────

def load(path, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    except Exception as e:
        log("저장 실패 %s: %s" % (path, e))


def take_lock():
    """겹쳐 돌면 같은 메시지를 두 번 답한다. 오래된 잠금은 뺏는다."""
    try:
        if os.path.exists(LOCK):
            age = time.time() - os.path.getmtime(LOCK)
            if age < LOCK_STALE:
                return False
            log("잠금이 %d초 묵었다 — 뺏는다" % age)
        io.open(LOCK, "w", encoding="utf-8").write(str(os.getpid()))
        return True
    except Exception as e:
        log("잠금 실패: %s" % e)
        return False


def drop_lock():
    try:
        os.remove(LOCK)
    except Exception:
        pass


# ────────────────────────────── 봇 API ──────────────────────────────
# tg.call() 은 chat_id 를 자동으로 끼워 넣는 '보내기' 전용이라 여기선 안 쓴다.

def api(method, params=None, timeout=30):
    c = tg.cfg()
    if not c:
        return None
    url = tg.API.format(token=c["token"], method=method)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("result") if d.get("ok") else None
    except urllib.error.HTTPError as e:
        log("%s HTTP %s" % (method, e.code))
    except Exception as e:
        log("%s 실패: %s" % (method, e))
    return None


def reply(text, dry=False):
    if dry:
        try:                                  # pythonw 로 돌면 stdout 이 없다
            sys.stdout.write(text + "\n" + "-" * 40 + "\n")
        except Exception:
            log(text)
        return True
    return tg.send_text(text)


# ──────────────────────── 창고 ① 링크 (ref_clip) ────────────────────────
# 링크가 든 것은 예전부터 쓰던 클립 창고에 그대로 넣는다 — `ref_clip/inbox.py --list`
# 와 그 아래 붙은 것들이 계속 살아 있어야 하므로 스키마를 손대지 않는다.

# ★이 두 표가 이제 진짜 출처다. 예전에는 ref_clip/inbox.py 에 있었지만 그쪽 수거는
#   은퇴시켰다(폴러가 둘이면 안 된다). 불러다 쓰지 않고 여기 둔 이유가 하나 더 있다 —
#   그 파일은 최상단에서 sys.stdout 을 다시 감싸는데, 실행해 불러오면 그 과정에서
#   스트림이 닫혀 이쪽 로그가 통째로 죽는다(2026-08-21 실기).
PREFIX = {"축": "짹짹", "축구": "짹짹", "골": "짧뷰", "골프": "짧뷰",
          "춤": "칩칩", "댄스": "칩칩"}
HOST = [("instagram.com", "인스타"), ("tiktok.com", "틱톡"),
        ("youtube.com", "유튜브"), ("youtu.be", "유튜브"),
        ("x.com", "X"), ("twitter.com", "X")]


def platform_of(url):
    for h, name in HOST:
        if h in url:
            return name
    return "기타"


def stash_links(text):
    """링크를 클립 창고에 담고 **(새로 담은 수, 들어 있던 링크 수)** 를 돌려준다.

    ★둘을 갈라서 돌려주는 이유 — '링크가 없다'와 '링크는 있는데 이미 담긴 것'은
      다르다. 하나로 뭉치면 같은 링크를 다시 보내셨을 때 메모 창고로 샌다."""
    links = re.findall(r"https?://\S+", text or "")
    if not links:
        return 0, 0
    q = load(CLIP_QUEUE, {"items": [], "offset": 0})
    have = {x.get("링크") for x in q.get("items", [])}

    head = text.split()[0]
    ch = PREFIX.get(head, "미정")
    memo = re.sub(r"https?://\S+", "", text).strip()
    if ch != "미정":
        memo = memo[len(head):].strip()

    added = 0
    for ln in links:
        ln = ln.rstrip(").,]")
        if ln in have:
            continue
        have.add(ln)
        q.setdefault("items", []).append({
            "링크": ln, "플랫폼": platform_of(ln), "채널": ch,
            "메모": memo, "상태": "대기", "status": "대기",
            "받은때": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        added += 1
    if added:
        save(CLIP_QUEUE, q)
    return added, len(links)


def clip_todo():
    q = load(CLIP_QUEUE, {})
    return [x for x in q.get("items", []) if x.get("status") != "만듦"]


# ──────────────────── 창고 ② 그 밖의 것 (글·사진·지시) ────────────────────
# ★링크 없는 메시지를 버리지 않는다 — ref_clip 이 그렇게 버려서 지시가 날아갔다.

def fetch_file(file_id, name_hint):
    """폰에서 던진 사진·영상·파일을 창고에 내려받는다. 실패해도 글은 남는다."""
    info = api("getFile", {"file_id": file_id})
    if not info or not info.get("file_path"):
        return None
    if int(info.get("file_size") or 0) > MAX_FILE:
        log("파일이 커서 안 받는다 (%.1fMB)" % (info["file_size"] / 1048576))
        return None
    c = tg.cfg()
    if not c:
        return None
    src = "https://api.telegram.org/file/bot%s/%s" % (c["token"], info["file_path"])
    ext = os.path.splitext(info["file_path"])[1] or ".bin"
    dst = os.path.join(INBOX, "files", "%s_%s%s"
                       % (time.strftime("%Y%m%d_%H%M%S"), name_hint, ext))
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with urllib.request.urlopen(src, timeout=120) as r, io.open(dst, "wb") as f:
            f.write(r.read())
        return dst
    except Exception as e:
        log("내려받기 실패: %s" % e)
        return None


def stash(msg, text):
    """메뉴에 없는 말은 소재로 본다 — 창고에 넣는다.

    링크는 클립 창고(ref_clip)로, 그 밖의 글·사진은 이쪽 창고로 갈라 넣는다.
    ★어느 쪽에도 안 맞는다고 버리지 않는다."""
    added, n_link = stash_links(text)

    kinds = [k for k in ("photo", "video", "document", "animation", "voice")
             if msg.get(k)]
    path = None
    if kinds:
        blob = msg[kinds[0]]
        if isinstance(blob, list):          # 사진은 해상도별 목록 — 제일 큰 것
            blob = blob[-1]
        path = fetch_file(blob.get("file_id"), kinds[0])

    db = load(INBOX_DB, [])
    if not n_link or kinds:                 # 링크가 든 글은 클립 창고에만 둔다
        db.append({"t": time.strftime("%Y-%m-%d %H:%M"), "text": text,
                   "kind": kinds[0] if kinds else "text",
                   "file": path, "used": False})
        save(INBOX_DB, db)

    if n_link and not added and not kinds:
        return ("🔗 <b>이미 창고에 있는 링크</b>입니다 — 그대로 뒀습니다.\n"
                "<i>클립 %d건 · 메모 %d건</i>"
                % (len(clip_todo()), len([x for x in db if not x.get("used")])))

    bits = []
    if added:
        bits.append("🔗 링크 %d건을 클립 창고에" % added)
    if path:
        bits.append("%s 받음" % kinds[0])
    left = len([x for x in db if not x.get("used")])
    head = "📥 창고에 넣었습니다" + (" (%s)" % " · ".join(bits) if bits else "")
    return ("%s\n<i>클립 %d건 · 메모 %d건 — 자리에 앉으면 '창고' 로 꺼냅니다.</i>"
            % (head, len(clip_todo()), left))


# ────────────────────────────── 메뉴 ──────────────────────────────

def cmd_menu(arg, st):
    return ("🌋 <b>볼케이노 봇</b>\n\n"
            "<b>시트</b> — 최신 소재 시트 (경제·커뮤·일본·일커·축구·골프)\n"
            "     예) <code>시트 커뮤</code>\n"
            "<b>3번</b> — 방금 본 시트에서 그 번호를 찜한다\n"
            "<b>찜</b> — 찜해 둔 목록\n"
            "<b>창고</b> — 폰에서 던져 둔 소재\n"
            "<b>상태</b> — 헌터가 언제 돌았나\n"
            "<b>납품</b> — 최근 완성본 (<code>납품 1</code> 이면 그 영상을 보낸다)\n\n"
            "<i>그 밖의 말·링크·사진은 전부 창고로 들어갑니다.</i>")


def cmd_sheet(arg, st):
    key = SHEET_ALIAS.get(arg.strip(), "econ" if not arg.strip() else None)
    if not key:
        return ("어느 시트인지 모르겠습니다 — %s 중에서 골라 주세요."
                % " · ".join(sorted(set(SHEET_ALIAS))))

    spec = notify_hunt.SRC[key]
    path = notify_hunt.newest(spec["dir"], spec.get("file"))
    if not path:
        return "%s — 아직 시트가 없습니다." % spec["label"]
    sheet = load(path, {})
    items = [it for it in (sheet.get("items") or sheet.get("rows") or [])
             if not it.get("blocked")]
    if not items:
        return "%s — 건진 게 없습니다." % spec["label"]

    top = items[:5]
    body = [spec["fmt"](i, it) for i, it in enumerate(top, 1)]
    meta = sheet.get("meta") or {}

    # 번호를 찜으로 받으려면 무엇이 몇 번이었는지 기억해야 한다
    st["last_sheet"] = {
        "src": key, "label": spec["label"], "stamp": meta.get("stamp", ""),
        "items": [{"title": it.get("title"), "link": it.get("link"),
                   "oid": it.get("oid"), "aid": it.get("aid"), "vid": it.get("vid")}
                  for it in top],
    }
    return ("%s <b>%s</b>\n\n%s\n\n<i>만들 것은 번호로 찜해 두세요 — 예) 3번</i>"
            % (spec["label"], tg.esc(meta.get("stamp", "")), "\n\n".join(body)))


def item_url(it):
    if it.get("link"):
        return it["link"]
    if it.get("oid") and it.get("aid"):
        return "https://n.news.naver.com/article/%s/%s" % (it["oid"], it["aid"])
    if it.get("aid"):
        return "https://news.yahoo.co.jp/articles/%s" % it["aid"]
    if it.get("vid"):
        return "https://youtube.com/shorts/%s" % it["vid"]
    return ""


def cmd_pick(arg, st):
    """번호를 찜한다. ★실행은 안 한다 — 자리에 앉아야 만든다. 정직하게 그렇게 답한다."""
    last = st.get("last_sheet")
    if not last:
        return "먼저 <code>시트</code> 를 부르셔야 번호를 압니다."
    digits = "".join(ch for ch in arg if ch.isdigit())
    if not digits:
        return "번호를 못 읽었습니다."
    n = int(digits)
    if not 1 <= n <= len(last["items"]):
        return "1~%d 중에서 골라 주세요." % len(last["items"])

    it = last["items"][n - 1]
    picks = st.setdefault("picks", [])
    picks.append({"t": time.strftime("%Y-%m-%d %H:%M"), "src": last["src"],
                  "label": last["label"], "title": it.get("title"),
                  "url": item_url(it), "done": False})
    return ("✅ <b>%d번</b> 찜했습니다\n%s\n\n"
            "<i>만드는 것은 PC 에서 합니다 — 앉으시면 '찜한 거 만들자' 하시면 됩니다.</i>"
            % (n, tg.esc(str(it.get("title") or ""))))


def cmd_picks(arg, st):
    live = [p for p in st.get("picks", []) if not p.get("done")]
    if not live:
        return "찜해 둔 게 없습니다."
    lines = ["📌 <b>찜 %d건</b>" % len(live)]
    for i, p in enumerate(live[-10:], 1):
        t = tg.esc(str(p.get("title") or ""))
        u = p.get("url")
        lines.append("<b>%d.</b> %s\n     <i>%s · %s</i>"
                     % (i, ('<a href="%s">%s</a>' % (tg.esc(u), t)) if u else t,
                        tg.esc(p.get("label", "")), p.get("t", "")))
    return "\n".join(lines)


def cmd_store(arg, st):
    """창고는 둘이다 — 클립(ref_clip)과 메모·사진. 폰에선 한 화면으로 보여 준다."""
    clips = clip_todo()
    memos = [x for x in load(INBOX_DB, []) if not x.get("used")]
    if not clips and not memos:
        return "창고가 비었습니다."

    lines = []
    if clips:
        lines.append("🔗 <b>클립 %d건</b>" % len(clips))
        for i, x in enumerate(clips[-8:], 1):
            lines.append("<b>%d.</b> [%s] %s\n     <a href=\"%s\">%s</a>"
                         % (i, tg.esc(x.get("채널", "미정")), tg.esc(x.get("플랫폼", "")),
                            tg.esc(x.get("링크", "")), tg.esc(x.get("링크", "")[:70])))
    if memos:
        lines.append(("\n" if clips else "") + "📝 <b>메모 %d건</b>" % len(memos))
        for i, x in enumerate(memos[-8:], 1):
            txt = tg.esc((x.get("text") or "").strip()[:90]) or "(글 없음)"
            mark = {"photo": "🖼 ", "video": "🎬 ", "document": "📄 ",
                    "animation": "🎞 ", "voice": "🎤 "}.get(x.get("kind"), "")
            lines.append("<b>%d.</b> %s%s\n     <i>%s</i>"
                         % (i, mark, txt, x.get("t", "")))
    return "\n".join(lines)


def cmd_status(arg, st):
    lines = ["📊 <b>헌터가 마지막으로 돈 때</b>"]
    now = time.time()
    for key in ("econ", "comm", "jp", "jpcomm", "soccer", "golf"):
        spec = notify_hunt.SRC[key]
        p = notify_hunt.newest(spec["dir"], spec.get("file"))
        if not p:
            lines.append("  %s — <i>시트 없음</i>" % spec["label"])
            continue
        h = (now - os.path.getmtime(p)) / 3600
        sheet = load(p, {})
        n = len(sheet.get("items") or sheet.get("rows") or [])
        lines.append("  %s — %s · %d건"
                     % (spec["label"],
                        ("%d분전" % round(h * 60)) if h < 1 else ("%.0f시간전" % h), n))

    memos = len([x for x in load(INBOX_DB, []) if not x.get("used")])
    picks = len([p for p in st.get("picks", []) if not p.get("done")])
    try:
        made = len([f for f in os.listdir(DEST) if f.lower().endswith(".mp4")])
    except Exception:
        made = 0
    lines.append("\n🔗 클립 %d건 · 📝 메모 %d건 · 📌 찜 %d건 · 🎬 완성본 %d편"
                 % (len(clip_todo()), memos, picks, made))
    return "\n".join(lines)


def recent_mp4(n=5):
    try:
        fs = [os.path.join(DEST, f) for f in os.listdir(DEST)
              if f.lower().endswith(".mp4")]
    except Exception:
        return []
    return sorted(fs, key=os.path.getmtime, reverse=True)[:n]


def cmd_delivered(arg, st):
    fs = recent_mp4()
    if not fs:
        return "완성본 폴더가 비었습니다."
    idx = "".join(ch for ch in arg if ch.isdigit())
    if idx:                                   # '납품 2' → 그 영상을 폰으로 보낸다
        i = int(idx)
        if not 1 <= i <= len(fs):
            return "1~%d 중에서 골라 주세요." % len(fs)
        p = fs[i - 1]
        if tg.send_video(p, caption=tg.esc(os.path.basename(p))):
            return None                       # 영상이 곧 답이다
        return "보내지 못했습니다 (용량 상한 50MB) — %s" % tg.esc(os.path.basename(p))

    lines = ["🎬 <b>최근 완성본</b>"]
    for i, p in enumerate(fs, 1):
        lines.append("<b>%d.</b> %s\n     <i>%.1fMB · %s</i>"
                     % (i, tg.esc(os.path.basename(p)),
                        os.path.getsize(p) / 1048576,
                        time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p)))))
    lines.append("\n<i>보고 싶으시면 '납품 1' 처럼 번호를 주세요.</i>")
    return "\n".join(lines)


# ★여기 적힌 낱말만 명령이다. 나머지는 전부 소재로 간다.
VERBS = {
    "도움": cmd_menu, "메뉴": cmd_menu, "?": cmd_menu, "help": cmd_menu,
    "/start": cmd_menu, "/help": cmd_menu,
    "시트": cmd_sheet, "소재": cmd_sheet,
    "찜": cmd_picks, "찜목록": cmd_picks,
    "창고": cmd_store, "보관함": cmd_store,
    "상태": cmd_status, "현황": cmd_status,
    "납품": cmd_delivered, "완성본": cmd_delivered,
}


def dispatch(msg, st):
    """한 메시지를 답으로 바꾼다. None 이면 답할 것이 없거나 이미 따로 보냈다는 뜻이다."""
    text = (msg.get("text") or msg.get("caption") or "").strip()
    has_file = any(msg.get(k) for k in
                   ("photo", "video", "document", "animation", "voice"))
    if not text and not has_file:
        return None

    head = text.split()[0].lower() if text else ""
    rest = text[len(head):].strip() if head else ""

    # '3번' · '3' 처럼 번호만 온 것 — 찜이다
    bare = head.rstrip("번.")
    if bare.isdigit() and len(bare) <= 2 and not rest:
        return cmd_pick(bare, st)

    fn = VERBS.get(head)
    if fn and not has_file:
        return fn(rest, st)
    return stash(msg, text)          # 메뉴에 없으면 소재다


# ────────────────────────────── 한 바퀴 ──────────────────────────────

def run(once=False, dry=False):
    c = tg.cfg()
    if not c:
        return 1
    me = str(c["chat_id"])
    st = load(STATE, {})

    params = {"timeout": 0 if once else POLL_SEC,
              "allowed_updates": json.dumps(["message"])}
    if st.get("offset"):
        params["offset"] = st["offset"]

    ups = api("getUpdates", params, timeout=(20 if once else POLL_SEC + 20))
    if not ups:
        return 0

    for u in ups:
        st["offset"] = u["update_id"] + 1          # 먼저 밀어 둔다 — 죽어도 안 맴돈다
        msg = u.get("message")
        if not msg:
            continue
        # ★남의 말은 듣지 않는다. 봇 주소를 알아내 말을 걸어도 여기서 끝난다.
        if str((msg.get("chat") or {}).get("id")) != me:
            log("모르는 대화 %s — 무시" % (msg.get("chat") or {}).get("id"))
            continue
        try:
            out = dispatch(msg, st)
        except Exception as e:                      # 한 건이 죽어도 다음 건은 산다
            log("처리 실패: %s" % e)
            out = "처리하다 막혔습니다: %s" % tg.esc(str(e)[:120])
        if out:
            reply(out, dry)
        save(STATE, st)

    save(STATE, st)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="기다리지 않고 쌓인 것만")
    ap.add_argument("--dry", action="store_true", help="답장을 화면에만")
    ap.add_argument("--menu", action="store_true", help="메뉴만 찍는다")
    a = ap.parse_args()
    try:                                      # pythonw 에는 stdout 이 아예 없다
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if a.menu:
        print(cmd_menu("", {}))
        return 0
    if not take_lock():
        log("이미 돌고 있다 — 그냥 나간다")
        return 0
    try:
        return run(once=a.once, dry=a.dry)
    finally:
        drop_lock()


if __name__ == "__main__":
    sys.exit(main())
