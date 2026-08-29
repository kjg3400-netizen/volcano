# -*- coding: utf-8 -*-
"""축구·골프 주제 정의 — 질의·갈래·차단.

`hunt.py` 가 엔진이고 여기가 주제다. 채널을 하나 더 붙이려면 TOPICS 에 항목을 쓴다.
엔진은 `ref_chipchip/hunt.py`(2026-08-21, 다른 세션) 를 그대로 본떴다.

★배수는 아직 **실측이 아니다.** 칩칩은 같은 클립 71쌍을 대조해 뽑았지만
  축구·골프는 그 대조를 아직 안 했다. 지금 값은 사장님이 말씀하신 채널 성격
  (`축구=신기·논란·댓글폭발·판정잘못` · `골프=신기하고 재밌는 것, 제일 좋은 건 아이템`)
  에 맞춘 것이다. 회차가 쌓이면 `--calib` 로 채널 카탈로그를 재서 갈아끼운다.
"""

# ── ★★FIFA 는 무조건 뺀다 (사장님 지시 2026-08-21) ──────────────────────────
#   대회(월드컵)와 게임(EA FC·구 FIFA) **둘 다**다. 한쪽만 막으면 반이 샌다.
#   ※`world cup` 을 넣으면 진짜 월드컵 경기 클립도 빠지는데, 그게 곧 FIFA 대회라 맞다.
FIFA = [
    # 대회
    "fifa", "world cup", "worldcup", "월드컵", "ワールドカップ",
    "confederations cup", "club world cup",
    # 게임 — EA FC 는 FIFA 의 후신이라 같이 막는다
    "ea fc", "ea sports", "fc 24", "fc 25", "fc 26", "fc24", "fc25", "fc26",
    "ultimate team", "fut ", "pro clubs", "career mode",
    "efootball", "pes 20", "konami",
]
# 게임 화면 일반 — 이 채널들은 실사 클립만 쓴다. CG 가 섞이면 톤이 죽는다.
# ★`switch`·`mod ` 는 뺐다 — `switch positions`·`model` 같은 진짜 축구 말에 걸린다.
GAME = [
    "gameplay", "game play", "ps5", "ps4", "xbox", "nintendo",
    "modded", "football manager", "dream league", "video game", "videogame",
    "roblox", "minecraft", "animation", "cartoon", "cgi",
]

# ★다른 종목 — 축구에서 제일 크게 샜던 자리다 (실기 2026-08-21).
#   영국 로케일로 박아도 `football` 이 든 NFL 채널(`HangTime NFL`)이 들어오고,
#   `match abandoned` 같은 종목 공통 표현으로 크리켓이 딸려 온다.
OTHER_SPORT = [
    # 미식축구 — `football` 을 그대로 쓰므로 로케일로는 절대 안 갈린다
    "nfl", "american football", "quarterback", "touchdown", "super bowl",
    "college football", "ncaa", "gridiron", "punt return",
    # 크리켓 — `match`·`over`·`innings` 가 축구 낱말과 겹친다
    "cricket", "wicket", "batsman", "batter", "bowler", "ipl ", "test match",
    "t20", "odi ", "bcci",
    # 그 밖
    "rugby", "scrum", "nba", "basketball", "mlb", "baseball", "nhl",
    "ice hockey", "afl ", "aussie rules", "tennis", "ufc", "wwe",
    "formula 1", "f1 ", "motogp", "nascar",
    # ★`boxing` 을 맨낱말로 넣지 마라 — 골프의 `unboxing new driver` 가 통째로 걸린다
    "boxing match", "boxing ring",
]


# ★야구 전용 타종목 목록 — 위의 OTHER_SPORT 를 그대로 쓰면 안 된다.
#   거기엔 `baseball`·`mlb` 가 들어 있어 야구를 통째로 막고,
#   크리켓 낱말로 넣어 둔 `batter` 는 **야구의 타자**라 정타를 다 죽인다.
OTHER_SPORT_BB = [k for k in OTHER_SPORT if k not in ("mlb", "baseball", "batter")] + [
    # 축구·골프 — 사장님의 다른 채널이라 섞이면 안 된다
    "soccer", "premier league", "champions league", "la liga",
    "golf", "pga", "hole in one", "birdie", "tee shot",
]
# 야구 게임 화면 — 실사만 쓴다
GAME_BB = GAME + [
    "mlb the show", "the show 24", "the show 25", "out of the park",
    "baseball 9", "super mega baseball", "backyard baseball",
]


TOPICS = {
    # ──────────────────────────────────────────────────────────────────────
    "축구": {
        "key": "soccer",
        "label": "짹짹 · 神ショーツ",
        # ★★`gl=GB` 다. 칩칩은 US 로 박지만 축구에서 US 로 가면 `football` 이
        #   **미식축구(NFL)** 로 나온다. 영국 로케일이면 football=축구이고
        #   한국 결과도 안 올라와 목적을 둘 다 만족한다.
        "gl": "GB",
        "hl": "en",
        # 한국·일본 원본은 뺀다 — 짹짹(한국)·神ショーツ(일본) 양쪽에 나가므로
        # 그 나라 클립은 시청자가 이미 본 것이다. 칩칩과 같은 이유다.
        "skip_kana": True,
        "drop": FIFA + GAME + OTHER_SPORT,
        "drop_why": "FIFA·게임·타종목",
        # ★질의를 넓힐 때 절대 잃으면 안 되는 낱말. `bizarre moment football match` 가
        #   `bizarre` 까지 깎여 자동차·크리켓 채널을 물어 왔다 (실기 2026-08-21)
        "anchor": "football",
        # ★일일 실행은 **검증본(`--best`)** 이다. 신작 사냥은 약했다 (실기 2026-08-21) —
        #   풀이 재포장 채널 위주라 갓 올라온 편은 평범하고, 짹짹 자신이 재포장 채널이라
        #   **이미 사람이 본 클립**을 다시 포장하는 쪽이 맞는다.
        #   실제로 신작 사냥 1위가 조회 97만인데 검증본 1위는 1억 5,300만이었다
        "daily_mode": "best",
        # ★축구는 **재포장 채널도 후보로 본다.** 춤과 다르다 — 원본 화면이 중계권자
        #   것이라 '허락받을 원본 채널' 이 애초에 없고, 짹짹 자체가 같은 자리에 있다.
        #   레이더로만 돌릴 것은 중계·구단 공식 계정(✖)뿐이다
        "radar_marks": ["✖"],

        "queries": [
            # 판정·논란 — 채널이 제일 원하는 축이다 (`판정잘못`·`댓글폭발`)
            "referee controversy football", "worst refereeing decision",
            "var controversy goal", "red card controversy",
            "offside controversy goal", "handball penalty controversy",
            "disallowed goal controversy", "referee gets it wrong",
            "penalty decision outrage", "referee changes his mind",
            # 골키퍼 — 짹짹 전문 소재 (jjack_spec 의 `축구·골키퍼 소재`)
            "goalkeeper incredible save", "goalkeeper howler goal",
            "goalkeeper scores last minute", "goalkeeper saves penalty shootout",
            "keeper rushes out disaster", "goalkeeper injured outfield player goes in",
            # 사건·난입 — 경기 옆에서 벌어지는 일. 칩칩 실측의 '사건·반전' 과 같은 축
            "fan invades pitch", "pitch invader stopped",
            "players brawl on pitch", "mass confrontation football",
            "object thrown from crowd football", "match abandoned chaos",
            "manager sent off touchline", "tunnel bust up football",
            # 신기·황당 — `신기한거`
            "strangest moment in football", "weirdest football rule",
            "bizarre moment football match", "never seen before football",
            "rarest thing in football", "football match interrupted by animal",
            "floodlight failure match", "wrong kit colour clash",
            # 실수·자책
            "own goal unbelievable", "worst miss ever football",
            "defender howler costly", "penalty run up fail",
        ],
        "queries_ko": [
            "축구 오심 논란", "축구 판정 논란", "var 논란",
            "골키퍼 슈퍼세이브", "골키퍼 실수", "축구 난입",
            "축구 몸싸움", "축구 황당 장면", "축구 자책골",
        ],

        # 주제 맥락 — 풀이 새는 것을 막는다. 없으면 점수를 크게 깎는다.
        # ★두루뭉술한 낱말을 빼는 게 넣는 것보다 중요하다 (실기 2026-08-21) —
        #   `defender` 는 랜드로버, `pitch` 는 야구·영업, `match`·`manager`·`squad`·
        #   `corner` 는 어느 종목에나 있다. `var` 는 `various` 에 걸려 `var ` 로 둔다.
        "context": [
            "축구", "골키퍼", "심판", "오심", "페널티", "프리킥", "자책골",
            "football", "soccer", "goalkeeper", "keeper", "goalie", "referee",
            "var ", "penalty", "free kick", "freekick", "offside", "own goal",
            "red card", "yellow card", "striker", "midfielder", "winger",
            "premier league", "la liga", "serie a", "bundesliga", "ligue 1",
            "champions league", "uefa", "efl", "fa cup", "derby",
            "goal", "goalscorer", "footy", "ftbl", "pitch invasion", "nutmeg",
        ],

        # ★순서가 결과를 바꾼다. 좁은 것부터 본다 (shapes.py 와 같은 함정)
        "shapes": [
            ("판정·논란", 1.35, [
                "referee", "ref ", " ref", "var", "offside", "handball",
                "disallowed", "controversy", "controversial", "wrong decision",
                "outrage", "robbed", "should have been", "red card", "sent off",
                "penalty decision", "오심", "심판", "판정", "논란"]),
            ("사건·난입", 1.30, [
                "invade", "invader", "pitch invasion", "brawl", "fight",
                "confrontation", "bust up", "abandoned", "thrown", "throws",
                "crowd trouble", "chaos", "riot", "flare", "streaker",
                "interrupted", "stopped by", "난입", "몸싸움", "중단"]),
            ("골키퍼", 1.20, [
                "goalkeeper", "keeper", "goalie", "shot stopper", "save",
                "saves", "shootout", "골키퍼", "선방", "세이브"]),
            # ★최상급만 넣으면 대부분 `기타` 로 빠진다 — `Rare Moments in Football`
            #   `Strange Moments in Football` 이 배수를 못 받았다 (실기 2026-08-21).
            #   원급도 같이 넣어야 갈래가 붙는다
            ("신기·황당", 1.20, [
                "strangest", "strange", "weirdest", "weird", "bizarre",
                "never seen", "rarest", "rare", "unusual", "odd", "craziest",
                "unbelievable", "you won't believe", "wtf", "what happened",
                "animal", "dog on", "cat on", "floodlight", "rule you didn't",
                "iq moment", "0 iq", "신기", "황당", "희귀"]),
            ("실수·자책", 1.10, [
                "own goal", "howler", "blunder", "worst miss", "sitter",
                "fail", "disaster", "embarrassing", "자책골", "실수"]),
            ("묘기·기술", 0.85, [
                "skills", "skill", "freestyle", "trick", "nutmeg", "panna",
                "rabona", "bicycle kick", "wonder goal", "screamer",
                "compilation", "best goals", "묘기", "기술"]),
        ],

        # 채널 갈래 — 소스로 쓸 수 있나
        "kinds": [
            ("미디어·중계", "✖", [
                "sky sports", "bt sport", "tnt sport", "espn", "bein",
                "cbs sports", "nbc sport", "itv", "bbc", "dazn", "premier league",
                "laliga", "bundesliga", "serie a", "uefa", "ligue1", "ligue 1",
                "official", "tv", "방송", "중계", "스포츠"]),
            ("재포장", "⚑", [
                "짤", "유머", "모음", "픽업", "순삭", "스낵", "meme", "shorts",
                "clips", "highlight", "compilation", "daily", "hub", "central",
                "zone", "planet", "world of", "best of", "viral"]),
            ("구단·단체", "◎", [
                "fc ", " fc", "cf ", "united", "city", "academy", "아카데미",
                "club", "club", "school", "football club", "youth", "u21", "u18"]),
        ],
    },

    # ──────────────────────────────────────────────────────────────────────
    "골프": {
        "key": "golf",
        "label": "짧뷰",
        # 골프는 미국이 본진이다. 용어도 미국식이라 US 가 맞다
        "gl": "US",
        "hl": "en",
        # 짧뷰는 한국 채널 하나뿐이라 **일본 원본은 막지 않는다.** 한국 것만 뺀다
        "skip_kana": True,
        "drop": GAME + OTHER_SPORT + ["pga tour 2k", "golf clash", "wgt golf"],
        "drop_why": "게임·타종목",
        "anchor": "golf",
        # 골프도 같다 — 짧뷰가 재포장 채널이다. 검증본 1위가 1억 2,100만이었다
        "daily_mode": "best",
        # 골프는 진짜 창작자 채널이 많다(장비 리뷰어·레슨). 재포장은 레이더로 둔다
        "radar_marks": ["⚑", "✖"],

        "queries": [
            # ★아이템·장비 — 사장님이 `제일 좋은 건 아이템` 이라 하셨다. 제일 두껍게 깐다
            "weird golf club invention", "illegal golf club test",
            "strangest golf gadget", "golf training aid test",
            "vintage golf club vs modern", "longest driver ever made",
            "worlds most expensive golf club", "custom golf club build",
            "banned golf ball test", "golf gadget that actually works",
            "cheapest vs most expensive golf clubs", "3d printed golf club",
            "giant golf club", "tiny golf club test",
            # 신기·희귀
            "rarest shot in golf", "impossible golf shot",
            "golf ball lands in the weirdest place", "hole in one reaction",
            "albatross golf", "golf ball stuck in tree",
            "one in a million golf moment",
            # 동물·돌발 — 골프장은 이게 자주 터진다
            "alligator on golf course", "animal steals golf ball",
            "wildlife on golf course", "bear on golf course",
            # 실수·해프닝
            "golf club snaps mid swing", "golf cart fail",
            "golfer loses his temper", "worst golf shot ever",
            "golf ball hits golfer",
            # 규칙·판정
            "weird golf rule explained", "golf rules violation penalty",
            "unplayable lie ruling", "golf rules argument",
            # 묘기·기록
            "golf trick shot", "longest drive record", "fastest swing speed",
        ],
        "queries_ko": [
            "골프 신기한 장비", "골프 희귀 장면", "홀인원 반응",
            "골프 클럽 부러짐", "골프장 동물", "골프 규칙 논란",
        ],

        # ★맨낱말을 넣으면 안 되는 것이 축구보다 많다 — `driver`(자동차) · `iron`(다리미)
        #   · `green`(색) · `course`(of course) · `tee`(티셔츠) · `chip`(과자) ·
        #   `range`(범위) · `slice`(조각) · `swing`(그네). 전부 두 낱말로 묶었다.
        "context": [
            "골프", "홀인원", "퍼터", "아이언", "웨지", "티샷", "그린",
            "golf", "golfer", "fairway", "putt", "putter", "birdie", "bogey",
            "hole in one", "hole-in-one", "bunker", "caddie", "caddy",
            "pga", "lpga", "golf course", "golf club", "golf ball", "golf cart",
            "tee shot", "tee box", "driving range", "albatross", "eagle putt",
            "handicap", "shank", "wedge shot", "back nine", "front nine",
            "par 3", "par 4", "par 5", "clubhouse", "swing speed", "mulligan",
        ],

        "shapes": [
            # ★사장님이 제일 좋다 하신 축이라 가장 높게 둔다
            # ★사장님이 제일 좋다 하신 축이다. `I made a…`·`I built…` 꼴을 꼭 넣어라 —
            #   1억 조회 `I made a universal desktop golf game` 이 `기타` 로 빠졌었다
            ("아이템·장비", 1.35, [
                "club", "clubs", "driver", "putter", "iron", "wedge", "shaft",
                "gadget", "gear", "equipment", "invention", "invented",
                "training aid", "training aide", "sleeve", "remote control",
                "3d print", "custom", "prototype", "banned", "illegal",
                "vintage", "expensive", "cheap", "vs modern", "tested",
                "i made", "i built", "diy", "unboxing", "review",
                "장비", "클럽", "드라이버", "퍼터", "아이언"]),
            ("동물·돌발", 1.25, [
                "alligator", "gator", "bear", "deer", "snake", "bird",
                "monkey", "kangaroo", "fox", "animal", "wildlife", "steals",
                "동물", "돌발"]),
            ("신기·희귀", 1.20, [
                "rarest", "rare", "impossible", "one in a million", "weirdest",
                "weird", "strangest", "strange", "odd", "craziest", "luckiest",
                "unbelievable", "hole in one", "hole-in-one", "albatross",
                "stuck in", "lands in", "never seen", "pov", "prank",
                "$", "million", "신기", "희귀", "홀인원"]),
            ("실수·해프닝", 1.10, [
                "fail", "snaps", "breaks", "temper", "angry", "throws club",
                "worst", "hits", "cart", "disaster", "실수", "해프닝"]),
            ("규칙·판정", 1.05, [
                "rule", "rules", "penalty", "ruling", "unplayable", "drop",
                "disqualified", "규칙", "판정", "실격"]),
            ("묘기·기록", 0.90, [
                "trick shot", "trickshot", "longest drive", "record",
                "swing speed", "compilation", "묘기", "기록"]),
        ],

        "kinds": [
            ("미디어·투어", "✖", [
                "pga tour", "lpga", "european tour", "dp world", "golf channel",
                "sky sports", "espn", "masters", "the open", "usga", "r&a",
                "방송", "중계"]),
            ("재포장", "⚑", [
                "짤", "유머", "모음", "픽업", "순삭", "스낵", "meme", "clips",
                "highlight", "compilation", "daily", "viral", "best of",
                "shorts", "hub", "zone"]),
            ("브랜드·용품", "◎", [
                "titleist", "callaway", "taylormade", "ping", "mizuno",
                "cobra", "srixon", "cleveland", "odyssey", "bridgestone",
                "golf galaxy", "2nd swing", "club champion", "fitting",
                "golfworks", "academy", "아카데미", "골프존", "용품", "샵",
                "shop", "store"]),
        ],
    },

    # ──────────────────────────────────────────────────────────────────────
    "야구": {
        "key": "baseball",
        "label": "야구 (한국판·일본판)",
        # MLB 가 소재의 중심이라 미국 로케일이다. KBO·NPB 는 한글·가나로 걸러진다.
        "gl": "US",
        "hl": "en",
        # ★한국판·일본판을 둘 다 내므로 한글·가나를 다 뺀다 (축구와 같다)
        "skip_kana": True,
        "drop": GAME_BB + OTHER_SPORT_BB,
        "drop_why": "게임·타종목",
        "anchor": "baseball",
        # 축구·골프와 같은 이유 — 재포장 채널이 쓸 소재는 이미 사람이 본 것이라야 한다
        "daily_mode": "best",
        # 중계 화면이 중계권자 것이라 '허락받을 원본 채널' 이 없다. 축구와 같은 판단.
        "radar_marks": ["✖"],

        "queries": [
            # 판정·논란 — 채널이 제일 원하는 축
            "umpire controversial call baseball", "worst umpire call ever",
            "blown call baseball", "replay review overturned baseball",
            "check swing controversy", "umpire ejects manager argument",
            "umpire gets it wrong", "baseball call reversed",
            # 희한한 플레이 — 실제 회차가 여기서 나왔다 (협살·인사이드파크)
            "rundown baseball crazy", "weirdest play in baseball",
            "rarest play in baseball", "never seen before baseball",
            "bizarre baseball moment", "baseball rule nobody knows",
            "triple play rare", "inside the park home run",
            "obstruction call baseball", "balk call explained",
            # 수비·묘기
            "incredible catch baseball", "diving catch outfield",
            "outfielder robs home run", "catcher blocks the plate",
            "barehanded play infield", "double play turned amazing",
            # 사건·난입 — 경기 옆에서 벌어지는 일
            "fan interference baseball", "fan runs on field baseball",
            "bench clearing brawl baseball", "game delayed animal on field",
            "object thrown on field baseball", "bat flip drama",
            # 황당·웃긴
            "funniest baseball moments", "baseball blooper unbelievable",
            "fan catches ball one handed", "mascot baseball funny",
        ],
        "queries_ko": [
            "야구 오심 논란", "야구 판정 논란", "야구 비디오판독",
            "야구 호수비", "야구 협살", "야구 난입",
            "야구 벤치클리어링", "야구 황당 장면", "야구 진기명기",
        ],

        # 주제 맥락 — 없으면 점수를 크게 깎는다 (버리진 않는다)
        # ★두루뭉술한 낱말을 넣지 마라 — `pitch`·`base`·`run`·`catch` 는 어디에나 있다
        "context": [
            "야구", "투수", "타자", "포수", "심판", "오심", "홈런", "번트",
            "도루", "병살", "협살", "만루", "이닝", "선발", "마무리",
            "baseball", "pitcher", "catcher", "umpire", "home run", "homer",
            "strikeout", "strike out", "bunt", "stolen base", "double play",
            "triple play", "infield", "outfield", "shortstop", "dugout",
            "bullpen", "inning", "grand slam", "walk off", "walkoff",
            "fastball", "curveball", "slider", "changeup", "mound",
            "mlb", "npb", "kbo", "world series", "little league",
        ],

        # ★순서가 결과를 바꾼다. 좁은 것부터 본다
        "shapes": [
            ("판정·논란", 1.35, [
                "umpire", "blown call", "controversial call", "wrong call",
                "replay review", "overturned", "reversed", "check swing",
                "ejected", "ejects", "ejection", "argues", "argument",
                "robbed", "controversy", "obstruction", "balk",
                "오심", "심판", "판정", "논란", "비디오판독"]),
            ("사건·난입", 1.30, [
                "fan interference", "runs on field", "brawl", "bench clearing",
                "fight", "thrown", "throws at", "interrupted", "delayed",
                "streaker", "chaos", "ejected fan",
                "난입", "몸싸움", "벤치클리어링", "중단"]),
            ("수비·묘기", 1.20, [
                "catch", "diving", "robs", "robbed", "double play",
                "triple play", "barehanded", "throw out", "guns down",
                "no look", "behind the back",
                "호수비", "선방", "묘기", "협살"]),
            ("신기·황당", 1.15, [
                "weirdest", "strangest", "bizarre", "rarest", "rare",
                "never seen", "unbelievable", "you won't believe",
                "rule", "first time", "inside the park",
                "황당", "신기", "진기명기", "처음"]),
        ],

        # 채널 표시 — 축구·골프와 같은 뼈대
        "kinds": [
            ("방송", "✖", [
                "mlb", "espn", "fox sports", "mlb network", "bally sports",
                "nbc sports", "tbs", "sportsnet", "npb", "kbo",
                "official", "broadcast", "방송", "중계"]),
            ("재포장", "⚑", [
                "짤", "유머", "모음", "픽업", "순삭", "스낵", "meme", "clips",
                "highlight", "compilation", "daily", "viral", "best of",
                "shorts", "hub", "zone"]),
            ("브랜드·용품", "◎", [
                "rawlings", "wilson", "louisville slugger", "marucci",
                "easton", "mizuno", "victus", "axe bat", "batting cage",
                "academy", "아카데미", "용품", "샵", "shop", "store"]),
        ],
    },
}


def get(name):
    """이름으로 주제를 찾는다. 별칭도 받는다."""
    alias = {"soccer": "축구", "football": "축구", "짹짹": "축구", "jjack": "축구",
             "golf": "골프", "짧뷰": "골프", "nono": "골프",
             "baseball": "야구", "yagu": "야구", "yakyu": "야구"}
    n = alias.get(name.strip().lower(), name.strip())
    if n not in TOPICS:
        raise SystemExit(f"모르는 주제: {name}   (쓸 수 있는 것: {', '.join(TOPICS)})")
    return n, TOPICS[n]
