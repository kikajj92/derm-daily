"""Prompt pieces shared by plan.py (daily batches) and assemble.py (refill batch)."""
import math, re

LET = "가나다라마"

HEAD = "당신은 대한피부과학회 피부과 전문의 자격시험 1차(필기) 출제위원이다. 기준 교재는 「피부과학」 제7판, 보조 교재는 Fitzpatrick's Dermatology 9th."

RULES = """[실제 1차 시험 형식]
- 5지선다 단일 최선답. 보기 정확히 5개, 정답 1개.
- 지문은 한국어, 질환명·약물·유전자·사이토카인·염색법 등 전문용어는 기출처럼 영어 그대로 섞어 쓴다.
- 최근(2024–2026) 기출 경향: 임상사진·조직병리 사진 문항이 가장 많다. 그 밖에 사이토카인·수용체·유전자 등 분자 기전, 생물학적 제제·JAK 억제제 등 최신 치료, 교과서 세부 수치(용량·파장·기간), 진단 기준, 병기(TNM 등), 감별진단.
- 금지: "모두 옳다/모두 틀리다/정답 없음" 보기, ㄱㄴㄷ 조합형, 보기 길이나 표현으로 정답이 드러나는 것, 교재마다 다르거나 논란이 있는 내용, 기출 문항을 그대로 베끼거나 숫자만 바꾼 것.
- 정확성이 최우선이다. 확실하지 않은 사실은 출제하지 않는다. 정답은 피부과학 7판(대한피부과학회)과 Fitzpatrick's Dermatology 9th 기준으로 하나만 성립해야 한다.
- 해설에서 보기를 가)·나) 같은 기호나 번호로 부르지 말고 보기 내용으로 부른다(보기 순서는 나중에 다시 정렬된다).

[난이도 — 실제 기출보다 쉬우면 안 된다]
- 목표 정답률 40–60%. 정리본을 한 번 훑은 전공의는 보기 두세 개 사이에서 헷갈리고, 강조된 세부까지 외운 사람만 확실히 맞히는 수준.
- 두 단계 사고를 요구한다. 증례형은 지문에 진단명을 쓰지 않고 임상·조직 소견으로 진단을 떠올리게 한 뒤, 그 질환의 세부(원인 유전자·단백, 특징적 조직·면역형광 소견, 1차 치료·금기, 동반 질환·합병증, 검사, 수치)를 묻는다. 진단명 자체를 묻는 문항은 묶음의 1/4 이하.
- 오답 보기는 '이웃 개념'에서 고른다: 같은 표·같은 목록에 있는 형제 질환의 유전자·소견, 같은 계열 약물의 다른 표적·부작용, 비슷한 조직 소견. 오답 하나하나가 다른 질환·다른 약에서는 맞는 사실이어서 대충 알면 끌리게 만든다. 아무도 고르지 않을 엉뚱한 보기, 범주가 다른 보기는 금지.
- 이런 쉬운 문항은 쓰지 않는다: 진단명을 주고 그 질환의 가장 유명한 연관 하나를 묻기(예: "건선에서 가장 중요한 사이토카인은?" → IL-17), 지문의 단어가 정답 보기에 그대로 나오는 것, 정의 첫 줄을 묻기, 소거법만으로 풀리는 것.
- 정답은 핵심 포인트로 한다(지엽적이면 안 된다): 그 질환·약을 공부한 사람이라면 반드시 알아야 할 사실—원인 유전자·단백, 대표 조직·면역형광 소견, 1차 치료·금기, 대표 동반 질환·합병증, 진단 기준·확진 검사, 시험에 반복되는 대표 수치—을 정답으로 삼는다. 강조 부분이 여럿이면 기출 표시가 있거나 질환의 중심이 되는 사실을 고른다.
- 난이도는 정답을 지엽적으로 만들어서가 아니라, 진단을 소견으로 떠올리게 하는 두 단계 사고와 그럴듯한 이웃 개념 오답으로 올린다. 곁가지 사실(부수적 분포·구조, 드문 통계 %, 사소한 기간·온도, 보조 기전, 부차적 경과 문장, 장비·안전 규정의 세부 조항)이나 HLA 아형 같은 암기용 잡지식을 정답으로 삼지 않는다.
- 겨냥할 축: 예외("…은 예외적으로"), 최다·최초·가장 흔한, 대표 수치(용량·파장·기간), 비교(A보다 B가 더), 금기·임신 중 선택, 1차 vs 2차 치료, 아형별 차이 — 단, 그 질환의 핵심에 속하는 것만.
- "옳지 않은 것은?/옳은 것은?" 형은 묶음당 2–3문항까지 쓰되, 보기 5개가 각각 서로 다른 세부 사실을 하나씩 담게 한다."""

NO_PHOTO = ('- 이 묶음에는 실제 사진이 없다. "(사진 1)", "다음 사진과 같은", "그림"처럼 사진을 보여 주는 듯한 표현은 절대 쓰지 않는다. '
            '피부 소견·조직 소견은 "…로 내원하였다. 진찰에서 …이 관찰되었고, 조직검사에서 …를 보였다"처럼 지문 문장 안에 자연스럽게 쓴다.')

EMPH_LEGEND = ("아래 [정리본 발췌]는 수험생이 피부과학 7판을 정리하며 중요한 곳에 표시해 둔 노트다. "
               "【…】는 밑줄·형광 표시, **…**는 굵게, (23기출)·(풀링21)처럼 연도가 붙은 표시는 실제로 출제됐던 곳이다. 이 표시들이 수험생이 중요하다고 본 출제 포인트다.")

TB_RULE = ("발췌마다 붙은 [교과서 원문]은 가장 중요한 기준 교재인 「피부과학」 7판 본문이다(스캔 글자 인식본이라 오타·줄바꿈 깨짐이 있을 수 있다). "
           "정답·수치·오답이 교과서와 맞는지 반드시 대조하고, 증례의 임상·조직 소견과 그럴듯한 오답은 교과서 본문에서 가져온다. "
           "정리본과 교과서가 다르면 교과서를 따르고, 확실하지 않으면 그 사실로는 출제하지 않는다. "
           "붙은 원문에 없는 내용은 work/src/tb/chNN.txt(단원별 교과서 전문)에서 Grep으로 찾아 확인할 수 있다.")

ANCHOR = f"""[출제 근거 — 정리본의 강조 부분에서만]
- {EMPH_LEGEND}
- 문항마다 정답의 핵심 사실을 이 강조 부분에서 고른다. 강조되지 않은 곳이나 발췌 밖의 지식으로 정답을 만들지 않는다. 증례 설정과 오답 보기에는 교과서 지식을 써도 된다.
- {TB_RULE}
- 문항을 발췌들에 고르게 나눈다. 한 발췌에 몰지 말고, 같은 강조 문장으로 두 문항을 내지 않는다. 한 묶음에서 같은 질환(또는 같은 기전)을 묻는 문항은 2개까지.
- "basis"에는 정답 근거가 된 강조 부분을 발췌에서 글자 그대로 복사한다(【 】·** 기호만 빼고 80자 이내). 검사 프로그램이 basis를 발췌와 대조해서, 발췌에 없는 basis를 가진 문항은 버린다."""

FORMAT = ('"options":["보기","보기","보기","보기","보기"],"answer":정답의 options 배열 위치(0부터),'
          '"explanation":"정답 근거 2–3문장 + 헷갈리는 오답 1–2개가 틀린 이유(그 오답은 어느 질환·약에 해당하는지). 총 4–6문장",'
          '"point":"한 줄 암기 포인트(연상법이 있으면 활용)",'
          '"ref":"피부과학 7판 ○장 ○○ / Fitzpatrick 9th ○○ (쪽수는 적지 말 것)"')

BASIS = ',"basis":"정답 근거인 정리본 강조 부분을 그대로 복사(80자 이내)"'


def kb_label(c):
    n = int(re.match(r"\d+", c["id"]).group())
    t = "" if re.fullmatch(r"Ch \d+", c.get("title", "")) else c.get("title", "")
    tail = " > ".join(x for x in (t, c.get("sub", "")) if x)
    return f"{'Fitzpatrick 보충 노트' if c['src'] == 'Fitz' else '정리본'} Ch {n}" + (f" · {tail}" if tail else "")


def fmt_kichul(k, with_ex=True):
    ans = f"{LET[k['a']]}) {k['o'][k['a']]}" + (" (복원, 불확실)" if k.get("u") else "") if k.get("a") is not None else "미상"
    s = f"[{k['y']}{' 풀링' if k['k'] == 'pool' else ''} 기출 · Ch {k['ch']}] {'(사진 문항) ' if k.get('img') else ''}{k['stem']}\n"
    s += "\n".join(f"{LET[i]}) {o}" for i, o in enumerate(k["o"]) if o) + f"\n정답: {ans}"
    if with_ex and k.get("ex"):
        s += "\n해설: " + k["ex"][:400]
    return s


def out_format(want, extra=""):
    return f"""[출력 형식]
문항마다 JSON 객체 한 줄(JSON Lines)로, 정확히 {want}줄. 앞뒤 설명, 마크다운, 코드펜스 없이 객체만 쓴다. 문자열 안 줄바꿈은 \\n.
{extra}"""


def tb_label(w):
    a, b = w["p"]
    return f"피부과학 7판 p.{a}{'–' + str(b) if b != a else ''}" + (f" · {w['h']}" if w.get("h") else "")


def tb_block(w, limit=2000):
    return f"[교과서 원문 — {tb_label(w)}]\n{w['text'][:limit]}"


def excerpt(c, tbmap=None, limit=3400, n_tb=2, seen=None):
    s = f"[발췌 {c['id']} — {kb_label(c)}]\n{c['text'][:limit]}"
    seen = set() if seen is None else seen
    wins = [tbmap[i] for i in (c.get("tb") or [])[:n_tb] if tbmap and i in tbmap and i not in seen]
    seen |= {w["id"] for w in wins}
    if wins:
        s += "\n\n" + "\n\n".join(tb_block(w) for w in wins)
    return s


def related_textbook(tbmap, ch, k):
    """Best textbook window for a past-exam item (photo variants)."""
    if not tbmap:
        return None
    ans = (k["o"][k["a"]] or "").strip() if k.get("a") is not None else ""
    body = " ".join([k.get("stem", ""), ans, k.get("ex", "")]).lower()
    terms = {w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", body)} | {w for w in re.findall(r"[가-힣]{3,}", body)}
    terms -= {"다음", "사진", "환자", "진단", "치료", "소견", "가장", "적절한", "옳은", "것은", "with", "from", "that", "this", "disease", "skin", "있는", "없는"}
    wins = [w for i, w in tbmap.items() if i.startswith(f"{int(ch)}t")]
    if not wins:
        return None
    df = {t: sum(1 for w in wins if t in w["text"].lower()) for t in terms}
    keys = _key_variants(ans)
    best, score = None, 0.0
    for w in wins:
        t = (w.get("h", "") + " " + w["text"]).lower()
        sc = sum(1 / df[x] for x in terms if df[x] and x in t) + (3 if any(x in t for x in keys) else 0)
        if sc > score:
            best, score = w, sc
    return best if score >= 2 else None


# ---------- choosing which parts of the notes a batch is built on ----------

def _weighted_pick(pool, k, rng, weight):
    pool, out = list(pool), []
    while pool and len(out) < k:
        ws = [weight(x) for x in pool]
        t = rng.random() * sum(ws)
        i = len(pool) - 1
        for j, w in enumerate(ws):
            t -= w
            if t <= 0:
                i = j; break
        out.append(pool.pop(i))
    return out


def n_chunks(n):
    """How many note excerpts a chapter with n questions gets."""
    return max(1, min(4, math.ceil(n / 2.5)))


def pick_note_chunks(KB, ch, k, rng, use, exclude=()):
    """Notes chunks weighted toward what the notes emphasise, rotating away from recently used ones."""
    arr = [x for x in KB.get(str(ch), []) if x["src"] == "정리본"]
    fresh = [x for x in arr if x["id"] not in exclude]
    pool = fresh if len(fresh) >= k else arr
    w = lambda x: (x.get("emph", 0) + 0.8) * (1.25 if x.get("mk") else 1.0) / (1 + use.get(x["id"], 0)) ** 1.5
    return _weighted_pick(pool, k, rng, w)


def pick_novel_chunks(KB, ch, rng, use, exclude=()):
    """For 'not yet tested' batches: an emphasised but little-tested notes chunk, sometimes plus a Fitz chunk."""
    notes = [x for x in KB.get(str(ch), []) if x["src"] == "정리본" and x["id"] not in exclude]
    fitz = [x for x in KB.get(str(ch), []) if x["src"] == "Fitz" and x["id"] not in exclude]
    w = lambda x: (x.get("emph", 0) + 0.8) * (1 - x.get("cov", 0)) ** 2 / (1 + use.get(x["id"], 0)) ** 1.5
    out = _weighted_pick(notes, 1, rng, w)
    if fitz and (rng.random() < 0.4 or not out):
        out += _weighted_pick(fitz, 1, rng, lambda x: (1 - x.get("cov", 0)) ** 2 / (1 + use.get(x["id"], 0)) ** 1.5)
    elif len(notes) > 1:
        out += _weighted_pick([x for x in notes if x not in out], 1, rng, w)
    return out


def _key_variants(ans):
    key = re.sub(r"\s*\(.*?\)\s*", " ", ans).strip().lower()
    out = [key] if len(key) >= 4 or re.fullmatch(r"[가-힣]{2,}", key) else []
    w = key.split()
    if len(w) == 2 and re.fullmatch(r"[a-z]+", w[0]) and len(w[1]) >= 5:
        out += [f"{w[0][0]}. {w[1]}", f"{w[0][0]}.{w[1]}", w[1]]
    return out


def related_excerpt(KB, ch, k, window=2600):
    """The part of the notes that discusses a past-exam item (for photo variants)."""
    ans = (k["o"][k["a"]] or "").strip() if k.get("a") is not None else ""
    body = " ".join([k.get("stem", ""), ans, k.get("ex", "")]).lower()
    terms = {w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", body)} | {w for w in re.findall(r"[가-힣]{3,}", body)}
    terms -= {"다음", "사진", "환자", "진단", "치료", "소견", "가장", "적절한", "옳은", "것은", "with", "from", "that", "this", "disease", "skin", "있는", "없는", "에서", "으로"}
    notes = [c for c in KB.get(str(ch), []) if c["src"] == "정리본"]
    df = {w: sum(1 for c in notes if w in c["text"].lower()) for w in terms}
    keys = _key_variants(ans)
    best, score, pos = None, 0.0, -1
    for c in notes:
        t = c["text"].lower()
        s = sum(1 / df[w] for w in terms if df[w] and w in t)
        p = next((t.find(x) for x in keys if x in t), -1)
        if p >= 0:
            s += 3
        if s > score:
            best, score, pos = c, s, p
    if not best or score < 2:
        return None, ""
    start = max(0, pos - 700) if pos >= 0 else 0
    txt = best["text"][start:start + window]
    return best, f"[정리본 관련 부분 — {kb_label(best)}]\n{'…' if start else ''}{txt}{'…' if start + window < len(best['text']) else ''}"


# ---------- the regular (notes-anchored) batch prompt ----------

def regular_prompt(parts, chunks, K, recent, chname, rng, intro="", tbmap=None):
    chs = [p["ch"] for p in parts]
    want = sum(p["n"] for p in parts)
    pool = [k for k in K if k["ch"] in chs]
    full = [k for k in pool if k.get("a") is not None and all(k["o"])]
    rng.shuffle(full)
    ex = full[:4]
    pool2 = list(pool); rng.shuffle(pool2)
    topics = [f"- {re.sub(r'\s+', ' ', k['stem'])[:90]}" for k in pool2[:30]]
    rec = [f"- (Ch {t['ch']}) {t['topic']}" for t in recent if str(t["ch"]) in {str(c) for c in chs}][-40:]
    n_case = round(want * 0.65); n_recall = want - n_case
    by_ch = {}
    for c in chunks:
        by_ch.setdefault(int(re.match(r"\d+", c["id"]).group()), []).append(c)
    seen = set()
    notes_txt = "\n\n".join(excerpt(c, tbmap, seen=seen) for c in chunks)
    anchor = ANCHOR if tbmap else ANCHOR.replace("\n- " + TB_RULE, "")
    return f"""{HEAD}
{intro}
[이번 묶음에서 출제할 문항 — 총 {want}문항]
{chr(10).join(f"- Chapter {p['ch']}. {chname(p['ch'])}: {p['n']}문항 (발췌 {', '.join(c['id'] for c in by_ch.get(p['ch'], [])) or '없음'}에서)" for p in parts)}

{anchor}

[정리본 발췌{' + 교과서 원문' if tbmap else ''}]
{notes_txt}

{RULES}

[문항 유형 배분]
- 증례형 {n_case}문항: 나이·성별·병력·경과와 함께 피부 소견(부위·모양·색·분포·배열), 필요하면 조직검사 소견(염색·층별 소견)이나 검사 수치를 지문 안에 문장으로 서술하고, 진단 다음 단계를 묻는다. 증례형 중 절반 이상은 조직검사 소견을 지문에 포함한다.
- 지식형 {n_recall}문항: 강조된 기전·유전자·수용체·약리·수치·예외를 직접 묻거나 "옳지 않은 것은?" 형으로 여러 세부를 한꺼번에 묻는다.
{NO_PHOTO}

[이 단원들의 실제 기출 예시 — 형식·난이도 참고용, 복제 금지]
{chr(10).join(chr(10) + fmt_kichul(k) for k in ex) or '(예시 없음)'}

[이 단원들에서 기출된 주제 — 같은 개념을 다른 각도로 묻는 것은 좋지만 같은 문항은 금지]
{chr(10).join(topics) or '(없음)'}
{('[최근 며칠 이미 낸 주제 — 반복 피하기]' + chr(10) + chr(10).join(rec)) if rec else ''}

{out_format(want, '{"ch":단원번호,"topic":"핵심 개념 한 줄(25자 내외)","type":"case|recall","stem":"지문",' + FORMAT + BASIS + '}')}"""


# ---------- checking a question against the excerpts it was written from ----------

def _norm(s):
    return re.sub(r"[\s【】*·,.()\[\]:;~\-→/'\"]+", "", str(s)).lower()


def _toks(s):
    return set(re.findall(r"[a-z][a-z0-9\-]{2,}|\d+(?:\.\d+)?|[가-힣]{2,}", str(s).lower()))


def anchor_of(basis, chunks):
    """Return the chunk the basis was copied from, or None."""
    b = str(basis or "").strip()
    if len(_norm(b)) < 4 or not chunks:
        return None
    nb = _norm(b)
    for c in chunks:
        nt = _norm(c["text"])
        if nb in nt or (len(nb) > 24 and nb[:24] in nt):
            return c
    bt = _toks(b)
    if not bt:
        return None
    best = max(chunks, key=lambda c: len(bt & _toks(c["text"])))
    return best if len(bt & _toks(best["text"])) / len(bt) >= 0.6 else None
