"""Question targets: every question in a text batch is assigned ONE specific thing to test,
so consecutive sets don't keep circling back to the same facts.

  - "pt" — one emphasised line of the notes (【밑줄】, **굵게**, (23기출) marks), with its parent headings
  - "tb" — one passage of the 피부과학 7판 textbook (used for chapters whose notes are thin, and for
           'not yet tested' questions)

Usage is tracked in state.json (ptUse/ptLast, tbUse/tbLast/tbAsked, grpLast, hist) so a target
cools down after it is used and the same disease isn't hit on consecutive days.
"""
import datetime, math, re

KMARK = re.compile(r"\((?:\d{2} ?)?(?:기출|풀링|전평)|(?:기출|풀링|전평) ?\d{2}")
EMPH = re.compile(r"【[^】]{2,}】|\*\*[^*]{2,}\*\*")
CORE = re.compile(r"원인|유전자|돌연변이|mutation|gene|단백|항원|antigen|조직|병리|면역형광|DIF|IIF|염색|치료|1차|first|금기|동반|합병|진단|검사|기준|criteria|m/c|가장 흔|특징|호발|pathogno", re.I)
PT_COOL, TB_COOL, GRP_COOL, FZ_COOL = 21, 14, 3, 14   # days


def _plain(s):
    return re.sub(r"[【】*]", "", s).strip()


HEADLIKE = re.compile(r"^(?:\d{1,2}|[A-Za-z]|[ivx]{1,4}|\(\d{1,2}\))[.)]?\s")


GENERIC = re.compile(r"^(원인|치료|진단|임상|증상|조직|예후|역학|정의|분류|검사|병인|발생|경과|감별|합병|빈도|특징|기타|개요|서론|관리|예방|임상적|병리|역사|종류|약물|부작용|기전|임상 ?양상|Treatment|Diagnosis|Clinical|Etiology|Pathogenesis|Histo)", re.I)


def _is_heading(plain):
    """A numbered short line naming a disease/section (no fact in it)."""
    return (bool(HEADLIKE.match(plain)) and len(plain) <= 48 and ":" not in plain
            and not re.search(r"(다|함|음|됨|임|편|향|있음|없음|경향)\.?\s*$", plain))


def extract_points(KB):
    """ch -> list of points {id, ch, chunk, line, ctx, grp, imp}"""
    pts = {}
    for c, arr in KB.items():
        out = []
        for x in arr:
            if x["src"] != "정리본":
                continue
            stack, k, near = [], 0, x["title"]
            for ln in x["text"].split("\n"):
                if not ln.strip():
                    continue
                ind = len(ln) - len(ln.lstrip(" "))
                s = ln.strip()
                pl = _plain(s)
                while stack and stack[-1][0] >= ind:
                    stack.pop()
                if _is_heading(pl) and re.search(r"[가-힣A-Za-z]{2}", pl):
                    h = re.sub(r"^\S+\s+", "", pl)[:45]
                    if not GENERIC.match(h):
                        near = h
                elif (EMPH.search(s) or KMARK.search(s)) and len(re.sub(r"\W", "", pl)) >= 6 and not re.search(r"Chapter \d+", pl):
                    chain = [_plain(t)[:50] for _, t in stack if not _plain(t).startswith(near)]
                    ctx = " > ".join([near] + chain[-2:])
                    marked = bool(KMARK.search(s) or any(KMARK.search(t) for _, t in stack[-2:]))
                    imp = 1.0 + (2.0 if marked else 0) + (0.8 if "【" in s else 0) + (0.6 if CORE.search(pl + " " + ctx) else 0)
                    out.append({"id": f"{x['id']}.{k}", "ch": int(c), "chunk": x["id"], "line": s[:260], "ctx": ctx,
                                "grp": f"{c}:{near}", "imp": round(imp, 2)})
                    k += 1
                stack.append((ind, s))
        pts[str(c)] = out
    return pts


def _days(since, today):
    if not since:
        return 999
    return (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(since)).days


def _pick(pool, k, rng, weight):
    pool, out = list(pool), []
    while pool and len(out) < k:
        ws = [max(weight(x), 1e-6) for x in pool]
        t = rng.random() * sum(ws)
        i = len(pool) - 1
        for j, w in enumerate(ws):
            t -= w
            if t <= 0:
                i = j; break
        out.append(pool.pop(i))
    return out


def kcov_terms(K):
    body = " ".join(k["stem"] + " " + " ".join(o or "" for o in k["o"]) + " " + (k.get("ex") or "") for k in K).lower()
    return set(re.findall(r"[a-z][a-z0-9\-]{3,}", body)) | set(re.findall(r"[가-힣]{3,}", body))


def coverage(text, terms):
    t = text.lower()
    w = set(re.findall(r"[a-z][a-z0-9\-]{3,}", t)) | set(re.findall(r"[가-힣]{3,}", t))
    return len(w & terms) / len(w) if w else 0.0


def pick_targets(ch, n, mode, P, TBW, st, today, rng, taken, kterms, FZ=()):
    """Choose n targets for chapter ch. mode: 'regular' (core, emphasised points) or 'novel' (little-tested).
    P: points of this chapter, TBW: textbook windows of this chapter, st: state, taken: ids already chosen today."""
    ptLast, ptUse = st.get("ptLast", {}), st.get("ptUse", {})
    tbLast, tbUse = st.get("tbLast", {}), st.get("tbUse", {})
    grpLast = st.get("grpLast", {})
    okP = [p for p in P if p["id"] not in taken and _days(ptLast.get(p["id"]), today) >= PT_COOL]
    okT = [w for w in TBW if w["id"] not in taken and _days(tbLast.get(w["id"]), today) >= TB_COOL and len(w["text"]) > 500]
    # how many come from the textbook: more when the notes for this chapter are thin
    # the 7판 textbook itself carries about half of the text questions (more for 'not yet tested'),
    # so its content is covered broadly; the notes' emphasised lines carry the rest
    frac_tb = 0.5 if mode == "regular" else 0.7
    if len(okP) < 4 * n:
        frac_tb = max(frac_tb, 0.7)
    # Fitzpatrick tables (comparison tables are a frequent exam source) where the notes have them
    fzLast, fzUse = st.get("fzLast", {}), st.get("fzUse", {})
    okF = [z for z in FZ if z["id"] not in taken and _days(fzLast.get(z["id"]), today) >= FZ_COOL]
    n_fz = min(len(okF), max(1, round(n * 0.2)) if n >= 3 else (1 if okF and rng.random() < 0.35 else 0))
    n_tb = min(len(okT), round((n - n_fz) * frac_tb)) if TBW else 0
    n_pt = min(len(okP), n - n_fz - n_tb)
    n_tb = min(len(okT), n - n_fz - n_pt)
    out = []
    for z in _pick(okF, n_fz, rng, lambda z: 1 / (1 + fzUse.get(z["id"], 0)) ** 3):
        out.append({"kind": "fz", "id": z["id"], "ch": ch}); taken.add(z["id"])

    def wp(p):
        w = p["imp"] / (1 + ptUse.get(p["id"], 0)) ** 2
        if _days(grpLast.get(p["grp"]), today) < GRP_COOL:
            w *= 0.25
        if mode == "novel":
            w *= (1 - coverage(p["line"] + " " + p["ctx"], kterms)) ** 2 + 0.05
        return w

    grps = set()
    for _ in range(n_pt):
        pool = [p for p in okP if p["grp"] not in grps and p["id"] not in taken] or [p for p in okP if p["id"] not in taken]
        got = _pick(pool, 1, rng, wp)
        if not got:
            break
        p = got[0]
        alt = _pick([q for q in okP if q["grp"] != p["grp"] and q["id"] not in taken and q["id"] != p["id"]], 1, rng, wp)
        out.append({"kind": "pt", "id": p["id"], "ch": ch, "alt": alt[0]["id"] if alt else None})
        taken.add(p["id"]); grps.add(p["grp"])
        if alt:
            taken.add(alt[0]["id"])

    def wt(w):
        cv = coverage(w["text"], kterms)
        base = (0.5 + cv) if mode == "regular" else (1.05 - cv) ** 2
        return base / (1 + tbUse.get(w["id"], 0)) ** 3
    sect = lambda w: (w.get("h") or "").split(" > ")[0][:30]
    secs = set()
    for _ in range(n_tb):   # different textbook sections within one batch
        pool = [w for w in okT if w["id"] not in taken and sect(w) not in secs] or [w for w in okT if w["id"] not in taken]
        got = _pick(pool, 1, rng, wt)
        if not got:
            break
        out.append({"kind": "tb", "id": got[0]["id"], "ch": ch})
        taken.add(got[0]["id"]); secs.add(sect(got[0]))
    # top up if the pools ran dry: least-used textbook passages first, then least-used points
    while len(out) < n:
        restT = [w for w in TBW if w["id"] not in taken and len(w["text"]) > 500]
        if restT:
            w = _pick(restT, 1, rng, lambda w: 1 / (1 + tbUse.get(w["id"], 0)) ** 3)[0]
            out.append({"kind": "tb", "id": w["id"], "ch": ch}); taken.add(w["id"]); continue
        rest = [p for p in P if p["id"] not in taken]
        if not rest:
            break
        p = _pick(rest, 1, rng, lambda p: p["imp"] / (1 + ptUse.get(p["id"], 0)) ** 2)[0]
        out.append({"kind": "pt", "id": p["id"], "ch": ch, "alt": None}); taken.add(p["id"])
    rng.shuffle(out)
    return out


# ---------- prompt for a batch of targeted questions ----------

def _tok(s):
    s = s.lower()
    ko = re.sub(r"[^가-힣]", "", s)
    return set(re.findall(r"[a-z][a-z0-9\-]{2,}", s)) | {ko[i:i + 2] for i in range(len(ko) - 1)}


class TBIndex:
    """Find the textbook passage that discusses a note line."""
    def __init__(self, tbmap):
        self.by_ch = {}
        for wid, w in (tbmap or {}).items():
            self.by_ch.setdefault(int(re.match(r"\d+", wid).group()), []).append((w, _tok(w.get("h", "") + " " + w["text"])))
        self.idf = {}
        for c, arr in self.by_ch.items():
            df = {}
            for _, t in arr:
                for x in t: df[x] = df.get(x, 0) + 1
            self.idf[c] = {x: math.log(1 + len(arr) / n) for x, n in df.items()}

    def best(self, ch, text):
        arr = self.by_ch.get(int(ch))
        if not arr:
            return None
        q = _tok(text); idf = self.idf[int(ch)]
        sc = max(((sum(idf.get(x, 0) for x in q & t), w) for w, t in arr), key=lambda x: x[0])
        return sc[1] if sc[0] > 3 else None


def region(chunk_text, line, before=900, after=700):
    """The part of a notes chunk around one line, with that line marked ▶."""
    pos = chunk_text.find(line[:60])
    if pos < 0:
        return chunk_text[:before + after]
    a = chunk_text.rfind("\n", 0, max(0, pos - before)) + 1
    b = chunk_text.find("\n", pos + len(line) + after)
    b = len(chunk_text) if b < 0 else b
    end = chunk_text.find("\n", pos)
    end = len(chunk_text) if end < 0 else end
    return ("…" if a > 0 else "") + chunk_text[a:pos] + "▶ " + chunk_text[pos:end] + chunk_text[end:b] + ("…" if b < len(chunk_text) else "")


def target_prompt(targets, ctx, mode, intro=""):
    """targets: [{kind,id,ch,alt}], ctx: dict(PT, CHUNK, TBMAP, TBX, st, K, hist, chname, rng, kb_label, tb_label, P)."""
    from prompts import HEAD, RULES, NO_PHOTO, EMPH_LEGEND, TB_RULE, FORMAT, fmt_kichul, out_format
    PT, CHUNK, TBMAP, TBX, st = ctx["PT"], ctx["CHUNK"], ctx["TBMAP"], ctx["TBX"], ctx["st"]
    want = len(targets)
    chs = sorted({t["ch"] for t in targets})
    asked = st.get("tbAsked", {})
    blocks, shown = [], {}
    for i, t in enumerate(targets, 1):
        if t["kind"] == "pt":
            p = PT[t["id"]]; c = CHUNK[p["chunk"]]
            b = (f"[포인트 {i}] tid={p['id']} · Ch {p['ch']} {ctx['chname'](p['ch'])} · 정리본\n"
                 f"위치: {p['ctx']}\n출제할 강조 사실: {p['line']}\n\n[정리본 — {ctx['kb_label'](c)} (▶가 출제할 줄)]\n{region(c['text'], p['line'])}")
            w = TBX.best(p["ch"], p["line"] + " " + p["ctx"]) if TBX else None
            if w:
                b += f"\n\n[교과서 원문 — {ctx['tb_label'](w)}]\n" + (f"(포인트 {shown[w['id']]}에 붙은 원문과 같음)" if w["id"] in shown else w["text"][:2000])
                shown.setdefault(w["id"], i)
            if t.get("alt") and t["alt"] in PT:
                q = PT[t["alt"]]
                b += f"\n\n예비 포인트 tid={q['id']} (지정 포인트가 곁가지라 핵심을 묻는 좋은 문항이 안 될 때만): {q['ctx']} — {q['line'][:200]}"
        elif t["kind"] == "fz":
            z = ctx["FZ"][t["id"]]
            prev = st.get("fzAsked", {}).get(z["id"], [])
            b = (f"[포인트 {i}] tid={z['id']} · Ch {t['ch']} {ctx['chname'](t['ch'])} · Fitzpatrick 표\n"
                 f"아래 Fitzpatrick 표(수험생 Fitz 보충 노트)에서 핵심 비교 사실 하나를 정답으로 삼는다. 같은 표의 다른 행·열(형제 질환·다른 약)이 그럴듯한 오답이 되게 한다. "
                 f"'(일반 지식)'·'집필 시점'·'[차이]' 표시가 있는 칸, 7판과 다를 수 있는 수치는 정답으로 쓰지 않는다."
                 + (f"\n이 표로 이미 낸 문항(같은 사실은 피한다): " + " / ".join(prev[-8:]) if prev else "")
                 + f"\n\n[Fitzpatrick 표 — {z['head']}]\n{z['text'][:2400]}")
        else:
            w = TBMAP[t["id"]]
            prev = asked.get(w["id"], [])
            b = (f"[포인트 {i}] tid={w['id']} · Ch {t['ch']} {ctx['chname'](t['ch'])} · 교과서 본문\n"
                 f"이 교과서 원문에서, 이 질환·주제를 공부한 사람이라면 꼭 알아야 할 핵심 사실 하나를 골라 정답으로 삼는다."
                 + (f"\n이 원문으로 이미 낸 문항(같은 사실은 피한다): " + " / ".join(prev[-8:]) if prev else "")
                 + f"\n\n[교과서 원문 — {ctx['tb_label'](w)}]\n{w['text'][:2400]}")
            shown.setdefault(w["id"], i)
        blocks.append(b)

    K = ctx["K"]
    pool = [k for k in K if k["ch"] in chs and k.get("a") is not None and all(k["o"])]
    ctx["rng"].shuffle(pool)
    ex = pool[:3]
    hist = [h for h in ctx["hist"] if h.get("ch") in chs][-60:]
    n_case = round(want * (0.6 if mode == "novel" else 0.65))
    return f"""{HEAD}
{intro}
[이번 묶음 — 총 {want}문항. 문항마다 출제할 포인트가 하나씩 정해져 있다]
매일 같은 내용이 반복되지 않도록, 문항마다 아래 [포인트 n]이 지정돼 있다. 문항 n은 [포인트 n]으로 쓴다(순서대로 한 포인트에 한 문항). 지정되지 않은 다른 사실로 정답을 바꾸지 않는다.

[포인트 사용 규칙]
- 정리본 포인트: ▶ 표시 줄의 강조 사실(【…】 밑줄·형광, **…** 굵게, (23기출) 같은 출제 표시)이 정답의 핵심이다. {EMPH_LEGEND}
- 지정 포인트가 곁가지라 핵심을 묻는 좋은 문항이 안 되면, 그 포인트에 붙은 예비 포인트로 쓴다(tid에 예비 포인트 id).
- 교과서 본문 포인트: 원문에서 핵심 사실(원인·유전자, 대표 임상·조직 소견, 진단 검사, 1차 치료·금기, 대표 합병증·동반 질환 등) 하나를 골라 정답으로 삼는다. 이미 낸 문항과 같은 사실은 피한다.
- {TB_RULE}
- "tid"에는 실제로 쓴 포인트의 tid를, "basis"에는 정답 근거 문장을 정리본(▶ 줄의 강조 부분) 또는 교과서 원문에서 글자 그대로 복사한다(【 】·** 기호만 빼고 80자 이내). 검사 프로그램이 대조해서 맞지 않으면 버린다.
- 아래 [최근 이미 낸 문항]과 같은 사실을 정답으로 하는 문항은 버려진다.

{RULES}

[문항 유형 배분]
- 짧은 증례형 약 {n_case}문항: 나이·성별·핵심 병력·검사 수치를 1–2문장으로 주고(피부·조직 소견을 길게 묘사하지 않는다), 치료 방향·경과·예후 인자·동반 질환·자가항체·검사 같은 다음 단계를 묻는다. 진단명이 꼭 필요하면 지문에 써도 되지만, 그때는 더 깊은 세부를 묻는다.
- 나머지는 지식형: 포인트의 치료·약리·기전·유전자·수치·예외를 짧은 질문으로 직접 묻는다. 보기는 모두 단답형.
{NO_PHOTO}

{(chr(10) * 2).join(blocks)}

[이 단원들의 실제 기출 예시 — 형식·난이도 참고용, 복제 금지]
{chr(10).join(chr(10) + fmt_kichul(k) for k in ex) or '(예시 없음)'}

[최근 이미 낸 문항 — 주제 → 정답. 같은 사실을 정답으로 다시 내지 않는다]
{chr(10).join(f"- (Ch {h['ch']}) {h['t']} → {h.get('a', '')}" for h in hist) or '(없음)'}

{out_format(want, '{"tid":"쓴 포인트의 tid","ch":단원번호,"topic":"핵심 개념 한 줄(25자 내외)","type":"case|recall","stem":"지문",' + FORMAT + ',"basis":"정답 근거 문장을 그대로 복사(80자 이내)"}')}"""


def _bigrams(s):
    s = re.sub(r"\s+", "", str(s).lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def is_repeat(q, hist, today, days=30, thr=0.45):
    """Same fact asked again recently (topic+answer nearly identical, same chapter)?"""
    a = _bigrams(q["topic"] + " " + q["options"][q["answer"]])
    if not a:
        return False
    for h in hist:
        if h.get("ch") != q["ch"] or _days(h.get("d"), today) > days:
            continue
        b = _bigrams(h["t"] + " " + h.get("a", ""))
        if b and len(a & b) / len(a | b) >= thr:
            return True
    return False
