#!/usr/bin/env python3
"""Plan today's mock exam and write one prompt file per batch.

  DD_PASS=... python3 tools/plan.py --set 1 [--date 2026-10-10] [--n 100] [--photo 30] [--novel 15]

Reads work/src/{kichul,meta,kb,state}.json (run `tools/ddcrypt.py unpack` first).
Writes work/plan.json, work/batches/NN.md and decrypts the photos each photo batch needs into work/img/.
Each batch prompt says which file its answer goes to (work/out/NN.jsonl).
"""
import argparse, datetime, json, math, random, re
from pathlib import Path
import ddcrypt as C

ROOT = C.ROOT
W = ROOT / "work"
LET = "가나다라마"

RULES = """[실제 1차 시험 형식]
- 5지선다 단일 최선답. 보기 정확히 5개, 정답 1개.
- 지문은 한국어, 질환명·약물·유전자·사이토카인·염색법 등 전문용어는 기출처럼 영어 그대로 섞어 쓴다.
- 최근(2024–2026) 기출 경향: 임상사진·조직병리 사진을 주고 묻는 문항이 가장 많다. 그 밖에 사이토카인·수용체·유전자 등 분자 기전, 생물학적 제제·JAK 억제제 등 최신 치료, 교과서 세부 수치(용량·파장·기간), 진단 기준, 병기(TNM 등), 감별진단.
- 난이도: 실제 기출 수준. 교과서를 정독한 4년차 전공의는 맞히지만 대충 알면 틀리는 정도. 오답 보기는 같은 범주의 그럴듯한 것(같은 계열 약물, 유사 질환, 관련 사이토카인)으로.
- 금지: "모두 옳다/모두 틀리다/정답 없음" 보기, ㄱㄴㄷ 조합형, 보기 길이나 표현으로 정답이 드러나는 것, 교재마다 다르거나 논란이 있는 내용, 기출 문항을 그대로 베끼거나 숫자만 바꾼 것. "옳지 않은 것은?" 형은 묶음당 2문항까지.
- 정확성이 최우선이다. 확실하지 않은 사실은 출제하지 않는다. 정답은 피부과학 7판(대한피부과학회)과 Fitzpatrick's Dermatology 9th 기준으로 하나만 성립해야 한다.
- 해설에서 보기를 가)·나) 같은 기호나 번호로 부르지 말고 보기 내용으로 부른다(보기 순서는 나중에 다시 정렬된다)."""

FORMAT = ('"options":["보기","보기","보기","보기","보기"],"answer":정답의 options 배열 위치(0부터),'
          '"explanation":"정답 근거 2–3문장 + 주요 오답 1–2개가 틀린 이유. 총 4–6문장",'
          '"point":"한 줄 암기 포인트(연상법이 있으면 활용)",'
          '"ref":"피부과학 7판 ○장 ○○ / Fitzpatrick 9th ○○ (쪽수는 적지 말 것)"')

HEAD = "당신은 대한피부과학회 피부과 전문의 자격시험 1차(필기) 출제위원이다. 기준 교재는 「피부과학」 제7판, 보조 교재는 Fitzpatrick's Dermatology 9th."


def load(name, default=None):
    p = W / "src" / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else default


def allocate(N, raw, rng):
    ent = [(c, w) for c, w in raw.items() if w > 0]
    tot = sum(w for _, w in ent)
    plan, fr, used = {}, [], 0
    for c, w in ent:
        x = w * N / tot
        f = math.floor(x)
        plan[c] = f; used += f; fr.append([c, x - f])
    left = N - used
    while left > 0 and fr:
        s = sum(f for _, f in fr); t = rng.random() * s; pick = len(fr) - 1
        for i, (_, f) in enumerate(fr):
            t -= f
            if t <= 0: pick = i; break
        plan[fr[pick][0]] += 1; fr.pop(pick); left -= 1
    return {c: n for c, n in plan.items() if n}


def fmt_kichul(k, with_ex=True):
    ans = f"{LET[k['a']]}) {k['o'][k['a']]}" + (" (복원, 불확실)" if k.get("u") else "") if k.get("a") is not None else "미상"
    s = f"[{k['y']}{' 풀링' if k['k'] == 'pool' else ''} 기출 · Ch {k['ch']}] {'(사진 문항) ' if k.get('img') else ''}{k['stem']}\n"
    s += "\n".join(f"{LET[i]}) {o}" for i, o in enumerate(k["o"]) if o) + f"\n정답: {ans}"
    if with_ex and k.get("ex"):
        s += "\n해설: " + k["ex"][:400]
    return s


def kb_label(c):
    return f"{'Fitzpatrick 보충 노트' if c['src'] == 'Fitz' else '정리본'} Ch {int(re.match(r'\d+', c['id']).group())} · {c['title']}{' > ' + c['sub'] if c.get('sub') else ''}"


def out_format(want, extra=""):
    return f"""[출력 형식]
문항마다 JSON 객체 한 줄(JSON Lines)로, 정확히 {want}줄. 앞뒤 설명, 마크다운, 코드펜스 없이 객체만 쓴다. 문자열 안 줄바꿈은 \\n.
{extra}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--photo", type=int, default=30)
    ap.add_argument("--novel", type=int, default=15)
    ap.add_argument("--set", type=int, default=1)
    a = ap.parse_args()
    eid = f"{a.date}-{a.set}"
    idx_p = ROOT / "data" / "exams" / "index.json"
    if idx_p.exists() and any(e["id"] == eid for e in json.loads(idx_p.read_text()).get("exams", [])):
        print(f"ALREADY EXISTS: {eid} — nothing to do"); return

    K = load("kichul"); meta = load("meta"); KB = load("kb")["ch"]; state = load("state", {}) or {}
    KMAP = {k["id"]: k for k in K}
    CH = meta["chapters"]
    chname = lambda c: CH.get(str(c), f"Chapter {c}")
    photo_use = state.get("photoUse", {}); kb_use = state.get("kbUse", {})
    recent = [t for t in state.get("topics", []) if t.get("date", "") >= (datetime.date.fromisoformat(a.date) - datetime.timedelta(days=21)).isoformat()]
    rng = random.Random("plan:" + eid)

    plan = allocate(a.n, meta["raw"], rng)

    # 1) photo variants from real past-exam photos
    photo_ok = [k for k in K if k.get("qi") and k.get("a") is not None and (k["o"][k["a"]] or "").strip() and k.get("ch")]
    rng2 = random.Random("photo:" + eid)
    rng2.shuffle(photo_ok)
    photo_ok.sort(key=lambda k: photo_use.get(k["id"], 0))
    cap = {c: math.ceil(n * 0.7) for c, n in plan.items()}
    K_photo = round(a.n * a.photo / 100)
    srcs = []
    for k in photo_ok:
        if len(srcs) >= K_photo: break
        c = str(k["ch"])
        if cap.get(c, 0) > 0:
            cap[c] -= 1; srcs.append(k["id"])
    text_plan = dict(plan)
    for s in srcs:
        c = str(KMAP[s]["ch"]); text_plan[c] -= 1
        if text_plan[c] <= 0: del text_plan[c]

    # 2) not-yet-tested questions grounded on the notes
    rng3 = random.Random("novel:" + eid)
    K_novel = round(a.n * a.novel / 100)
    capn = {c: math.ceil(n * 0.5) for c, n in text_plan.items() if KB.get(c)}
    alloc, left = {}, K_novel
    while left > 0:
        ent = [c for c in capn if capn[c] > 0]
        if not ent: break
        tot = sum(text_plan[c] for c in ent); t = rng3.random() * tot; pick = ent[-1]
        for c in ent:
            t -= text_plan[c]
            if t <= 0: pick = c; break
        take = max(1, min(3, left, capn[pick]))
        alloc[pick] = alloc.get(pick, 0) + take; capn[pick] -= take; left -= take
    novel = []
    for c, n in sorted(alloc.items(), key=lambda x: int(x[0])):
        cands = list(KB[c]); rng3.shuffle(cands)
        cands.sort(key=lambda x: (kb_use.get(x["id"], 0), x["cov"]))
        rem, ci = n, 0
        while rem > 0:
            take = min(rem, 5)
            novel.append({"ch": int(c), "n": take, "chunks": [x["id"] for x in cands[ci:ci + 2]]})
            ci += 2; rem -= take
        text_plan[c] -= n
        if text_plan[c] <= 0: del text_plan[c]

    # 3) regular batches (≤12 questions, chapters kept together)
    text_batches, cur, cn = [], [], 0
    def close():
        nonlocal cur, cn
        if cur: text_batches.append(cur)
        cur, cn = [], 0
    for c in sorted(text_plan, key=int):
        need = text_plan[c]
        while need > 12:
            close(); text_batches.append([{"ch": int(c), "n": 10}]); need -= 10
        if cn and cn + need > 12: close()
        cur.append({"ch": int(c), "n": need}); cn += need
        if cn >= 9: close()
    close()

    # photo batches: ≤4 sources, ≤8 images per batch
    photo_batches, curp, imgs = [], [], 0
    for s in srcs:
        n = min(len(KMAP[s]["qi"]), 4)
        if curp and (len(curp) >= 4 or imgs + n > 8):
            photo_batches.append(curp); curp, imgs = [], 0
        curp.append(s); imgs += n
    if curp: photo_batches.append(curp)

    for d in ("batches", "out", "img"):
        (W / d).mkdir(parents=True, exist_ok=True)
    for f in (W / "batches").glob("*.md"): f.unlink()

    def recent_lines(chs):
        return [f"- (Ch {t['ch']}) {t['topic']}" for t in recent if str(t["ch"]) in {str(c) for c in chs}][-40:]

    batches = []
    no = 0
    # --- photo prompts
    for grp in photo_batches:
        no += 1; names = []; blocks = []
        for i, sid in enumerate(grp):
            k = KMAP[sid]; ims = k["qi"][:4]
            first = len(names) + 1; names += ims
            nums = ", ".join(str(x) for x in range(first, first + len(ims)))
            blocks.append(f"원문항 {i + 1} [ID {k['id']}] — Ch {k['ch']} {chname(k['ch'])} — 이미지 {nums}\n{fmt_kichul(k)}")
        for nm in names:
            src = ROOT / "data" / "img" / (nm + ".enc")
            (W / "img" / nm).write_bytes(C.dec_bytes(src.read_bytes()))
        img_list = "\n".join(f"- 이미지 {i + 1}: work/img/{nm}" for i, nm in enumerate(names))
        prompt = f"""{HEAD}

아래에 실제 기출(수험생 복원) 문항 {len(grp)}개가 있고, 그 문항들의 사진 파일이 work/img/ 에 있다. 사진을 Read 도구로 하나씩 직접 열어 본 뒤 작업한다.
{img_list}

[해야 할 일]
원문항마다 같은 사진(들)을 그대로 다시 보여 주는 새 문항을 1개씩 만든다. 최근 기출은 임상사진과 조직병리 사진을 주고 묻는 문항이 많다.
- 원문항과 다른 것을 묻는다. 원문항이 진단을 물었다면 병인·원인 유전자·조직 소견·진단 검사·1차 치료·합병증·동반 질환·예후 중 하나로, 원문항이 치료나 기전을 물었다면 진단·감별진단·조직 소견 등으로 바꾼다.
- 질환은 원문항의 지문과 정답으로 확정한다. 사진에서 실제로 보이는 것과 모순되는 내용을 쓰지 않는다.
- 지문은 "다음 사진과 같은 …" 또는 증례 + "(사진 1, 2)" 형식으로 쓰고, 사진의 진단명을 지문에 쓰지 않는다. 사진 번호는 그 원문항의 사진 안에서 1부터 센다.
- 사진이 임상·조직·더모스코피 사진이 아니거나(도식, 교과서 글 캡처, 표 등) 진단을 확신할 수 없으면 그 원문항은 {{"src":"원문항ID","skip":true}} 한 줄만 쓴다.

{RULES}

{chr(10).join(blocks)}

{out_format(len(grp), '{"src":"원문항ID","ch":단원번호,"topic":"핵심 개념 한 줄(25자 내외)","stem":"지문",' + FORMAT + '}')}"""
        batches.append({"no": no, "kind": "photo", "srcs": grp, "want": len(grp), "chs": sorted({KMAP[s]["ch"] for s in grp}), "prompt": prompt})

    # --- novel prompts
    kbmap = {x["id"]: x for c in KB.values() for x in c}
    for nb in novel:
        no += 1
        chunks = [kbmap[i] for i in nb["chunks"] if i in kbmap]
        past = [f"- {re.sub(r'\s+', ' ', k['stem'])[:90]}" + (f" → {k['o'][k['a']]}" if k.get('a') is not None and k['o'][k['a']] else "") for k in K if k["ch"] == nb["ch"]][:60]
        rec = recent_lines([nb["ch"]])
        n_photo = round(nb["n"] * 0.4)
        chunk_txt = "\n\n".join(f"[출제 근거 {i + 1} — {kb_label(c)}]\n{c['text'][:3400]}" for i, c in enumerate(chunks))
        prompt = f"""{HEAD}

이번 묶음은 "아직 기출에 나오지 않은 내용"으로 Chapter {nb['ch']}. {chname(nb['ch'])} 새 문항 {nb['n']}개를 만든다. 아래 [출제 근거] 발췌는 수험생이 교과서를 정리한 노트(정리본)와 Fitzpatrick 9판 보충 노트다. 정답 근거는 반드시 이 발췌에 적힌 사실이어야 한다.

{chunk_txt}

[이 단원에서 이미 기출된 문항 — 같은 개념·같은 포인트는 피한다]
{chr(10).join(past) or '(없음)'}
{('[최근 이 앱에서 이미 낸 주제]' + chr(10) + chr(10).join(rec)) if rec else ''}

[출제 규칙]
- 발췌 속에서 위 기출 목록이 아직 묻지 않은 세부 사실을 고른다: 역학 수치, 드문 아형, 감별점, 검사·병리 소견, 원인 유전자·항원, 치료 순서·용량, 합병증 등.
- 정답은 발췌에 명시된 사실로만 정한다. 발췌에 없는 수치나 추론을 정답으로 만들지 않는다. 오답 보기는 같은 범주에서 그럴듯하게 만들되 교과서와 모순되지 않게 한다.
- 발췌에서 [차이]로 표시된 7판·Fitz 불일치 항목, "(일반 지식)" 표시 항목, 숫자가 서로 다르게 적힌 항목은 출제하지 않는다. 7판과 Fitz가 다를 수 있으면 정리본(7판) 기준.
- 발췌가 목록·표라도 문항은 실제 시험처럼 쓴다. 약 {n_photo}문항은 사진 제시형(figures에 임상·조직·더모스코피 소견 묘사, 진단명은 쓰지 않음), 나머지는 증례형이나 지식형.

{RULES}

{out_format(nb['n'], '{"ch":' + str(nb['ch']) + ',"topic":"핵심 개념 한 줄(25자 내외)","type":"photo|case|recall","stem":"지문","figures":[{"kind":"임상|조직|더모스코피|면역형광","desc":"사진 소견"}],' + FORMAT + ',"basis":"정답 근거가 된 발췌 내용 한 줄 요약(60자 이내)"}' + chr(10) + '사진 제시형이 아니면 "figures":[] 로 둔다.')}"""
        batches.append({"no": no, "kind": "novel", "ch": nb["ch"], "chunks": nb["chunks"], "kbRef": [kb_label(c) for c in chunks], "want": nb["n"], "chs": [nb["ch"]], "prompt": prompt})

    # --- regular prompts
    for parts in text_batches:
        no += 1
        chs = [p["ch"] for p in parts]; want = sum(p["n"] for p in parts)
        r = random.Random(f"text:{eid}:{no}")
        pool = [k for k in K if k["ch"] in chs]
        full = [k for k in pool if k.get("a") is not None and all(k["o"])]
        r.shuffle(full)
        ex = full[:5]
        pool2 = list(pool); r.shuffle(pool2)
        topics = [f"- {re.sub(r'\s+', ' ', k['stem'])[:90]}" for k in pool2[:36]]
        notes = []
        for p in parts:
            arr = [x for x in KB.get(str(p["ch"]), []) if x["src"] == "정리본"]
            if not arr: continue
            top = sorted(arr, key=lambda x: -x["cov"])[:max(3, math.ceil(len(arr) / 2))]
            c = top[r.randrange(len(top))]
            notes.append(f"[{kb_label(c)}]\n{c['text'][:2200]}")
        rec = recent_lines(chs)
        n_photo = round(want * 0.6); n_case = round(want * 0.25); n_recall = want - n_photo - n_case
        prompt = f"""{HEAD}

[이번 묶음에서 출제할 문항 — 총 {want}문항]
{chr(10).join(f"- Chapter {p['ch']}. {chname(p['ch'])}: {p['n']}문항" for p in parts)}

{RULES}

[문항 유형 배분 — 최근 기출은 사진 제시형 비중이 높다]
- 사진 제시형 {n_photo}문항: 실제 시험이라면 임상사진, 조직병리 사진(H&E, 특수염색, 면역형광), 더모스코피 사진을 제시하는 문항. 사진 대신 "figures" 배열에 각 사진에서 보이는 소견을 판독하듯 객관적으로 적는다. 진단명이나 정답을 직접 드러내는 단어는 쓰지 않는다.
  · 임상: 나이·부위·분포·배열·형태·색·크기 (예: "양쪽 정강이 앞면에 경계가 불분명한 압통성 적색 결절 여러 개, 궤양 없음")
  · 조직: 염색·배율·층별 소견 (예: "H&E ×200: 각질층 아래 표피 내 호산구로 찬 해면화, 진피 상부에 호산구 섞인 혈관주위 침윤")
  · 더모스코피: 구조·색·혈관 패턴
  사진 제시형 중 절반 이상은 조직병리 사진을 포함한다(임상+조직을 함께 제시해도 좋다). 지문에서는 "(사진 1)", "다음 조직 소견(사진 2)"처럼 지칭한다.
- 증례형(사진 없이 병력·검사 수치 제시) {n_case}문항
- 지식형(기전·유전자·수용체·약리·수치) {n_recall}문항

[이 단원들의 실제 기출 예시 — 형식·난이도만 참고, 복제 금지]
{chr(10).join(chr(10) + fmt_kichul(k) for k in ex) or '(예시 없음)'}

[이 단원들에서 기출된 주제 — 출제 비중 파악용. 같은 개념을 다른 각도로 묻는 것은 좋지만 같은 문항은 금지]
{chr(10).join(topics) or '(없음)'}
{('[최근 며칠 이미 낸 주제 — 반복 피하기]' + chr(10) + chr(10).join(rec)) if rec else ''}
{('[수험생 정리본 발췌 — 자주 출제되는 부분. 7판 기준 수치·용어를 확인하는 데 쓰고, 여기서 출제해도 된다]' + chr(10) + (chr(10) * 2).join(notes)) if notes else ''}

{out_format(want, '{"ch":단원번호,"topic":"핵심 개념 한 줄(25자 내외)","type":"photo|case|recall","stem":"지문","figures":[{"kind":"임상|조직|더모스코피|면역형광","desc":"사진 소견"}],' + FORMAT + '}' + chr(10) + '사진 제시형이 아니면 "figures":[] 로 둔다.')}"""
        batches.append({"no": no, "kind": "text", "parts": parts, "want": want, "chs": chs, "prompt": prompt})

    for b in batches:
        b["file"] = f"work/batches/{b['no']:02d}.md"
        b["out"] = f"work/out/{b['no']:02d}.jsonl"
        (ROOT / b["file"]).write_text(b.pop("prompt") + f"\n\n결과를 {b['out']} 파일에 JSON Lines로 저장한다(UTF-8, 한 줄에 객체 하나).\n")
    out = {"id": eid, "date": a.date, "n": a.n, "plan": plan, "batches": batches}
    (W / "plan.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    kinds = {}
    for b in batches: kinds[b["kind"]] = kinds.get(b["kind"], 0) + b["want"]
    print(f"plan {eid}: {len(batches)} batches", kinds)


if __name__ == "__main__":
    main()
