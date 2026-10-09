#!/usr/bin/env python3
"""Plan today's mock exam and write one prompt file per batch.

  DD_PASS=... python3 tools/plan.py [--set auto|1|2…] [--date 2026-10-10] [--n 100] [--photo 30] [--novel 15]

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

from prompts import (HEAD, RULES, FORMAT, BASIS, NO_PHOTO, EMPH_LEGEND, TB_RULE, kb_label, fmt_kichul, out_format, excerpt,
                     n_chunks, pick_note_chunks, pick_novel_chunks, related_excerpt, related_textbook, tb_block, regular_prompt)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--photo", type=int, default=30)
    ap.add_argument("--novel", type=int, default=15)
    ap.add_argument("--set", default="auto", help="회차 번호, auto면 오늘 비어 있는 다음 번호")
    a = ap.parse_args()
    idx_p = ROOT / "data" / "exams" / "index.json"
    have = {e["id"] for e in json.loads(idx_p.read_text()).get("exams", [])} if idx_p.exists() else set()
    if str(a.set) == "auto":
        k = 1
        while f"{a.date}-{k}" in have: k += 1
        a.set = k
    eid = f"{a.date}-{a.set}"
    if eid in have:
        print(f"ALREADY EXISTS: {eid} — nothing to do"); return

    K = load("kichul"); meta = load("meta"); KB = load("kb")["ch"]; state = load("state", {}) or {}
    TB = load("textbook")
    tbmap = {w["id"]: w for v in TB["ch"].values() for w in v} if TB else None
    if not tbmap:
        print("NOTE: textbook text not available (DD_SRCKEY not set) — prompts will use the notes only")
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
    novel, used_today = [], set()
    for c, n in sorted(alloc.items(), key=lambda x: int(x[0])):
        rem = n
        while rem > 0:
            take = min(rem, 5)
            picked = pick_novel_chunks(KB, c, rng3, kb_use, used_today)
            used_today |= {x["id"] for x in picked}
            novel.append({"ch": int(c), "n": take, "chunks": [x["id"] for x in picked]})
            rem -= take
        text_plan[c] -= n
        if text_plan[c] <= 0: del text_plan[c]

    # 3) regular batches (≤10 questions, chapters kept together)
    text_batches, cur, cn = [], [], 0
    def close():
        nonlocal cur, cn
        if cur: text_batches.append(cur)
        cur, cn = [], 0
    for c in sorted(text_plan, key=int):
        need = text_plan[c]
        while need > 10:
            close(); text_batches.append([{"ch": int(c), "n": 8}]); need -= 8
        if cn and cn + need > 10: close()
        cur.append({"ch": int(c), "n": need}); cn += need
        if cn >= 8: close()
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
    kbmap = {x["id"]: x for c in KB.values() for x in c}
    # --- photo prompts
    for grp in photo_batches:
        no += 1; names = []; blocks = []; rel_ids = {}
        for i, sid in enumerate(grp):
            k = KMAP[sid]; ims = k["qi"][:4]
            first = len(names) + 1; names += ims
            nums = ", ".join(str(x) for x in range(first, first + len(ims)))
            rc, rel = related_excerpt(KB, k["ch"], k)
            if rc: rel_ids[sid] = rc["id"]
            tw = related_textbook(tbmap, k["ch"], k)
            blocks.append(f"원문항 {i + 1} [ID {k['id']}] — Ch {k['ch']} {chname(k['ch'])} — 이미지 {nums}\n{fmt_kichul(k)}"
                          + (f"\n\n{rel}" if rel else "") + (f"\n\n{tb_block(tw)}" if tw else ""))
        for nm in names:
            src = ROOT / "data" / "img" / (nm + ".enc")
            (W / "img" / nm).write_bytes(C.dec_bytes(src.read_bytes()))
        img_list = "\n".join(f"- 이미지 {i + 1}: work/img/{nm}" for i, nm in enumerate(names))
        prompt = f"""{HEAD}

아래에 실제 기출(수험생 복원) 문항 {len(grp)}개가 있고, 그 문항들의 사진 파일이 work/img/ 에 있다. 사진을 Read 도구로 하나씩 직접 열어 본 뒤 작업한다.
{img_list}

[해야 할 일]
원문항마다 같은 사진(들)을 그대로 다시 보여 주는 새 문항을 1개씩 만든다. 최근 기출은 임상사진과 조직병리 사진을 주고 묻는 문항이 많다.
- 원문항과 다른 것을 묻는다. 원문항이 진단을 물었다면 병인·원인 유전자·조직 소견·진단 검사·1차 치료·합병증·동반 질환·예후 중 하나로, 원문항이 치료나 기전을 물었다면 진단·감별진단·조직 소견 등으로 바꾼다. 사진으로 진단을 떠올린 다음 한 단계 더 생각해야 풀리게 한다.
- 원문항 아래에 [정리본 관련 부분]이 붙어 있으면, 새 문항이 묻는 포인트를 거기서 강조된 사실(【…】 밑줄·형광, **…** 굵게, (23기출) 같은 출제 표시)에서 고르고, "basis"에 그 강조 부분을 글자 그대로 복사한다. 붙어 있지 않으면 피부과학 7판의 핵심 내용으로 내고 basis는 빈 문자열로 둔다.
- 원문항 아래 [교과서 원문]은 가장 중요한 기준 교재인 「피부과학」 7판 본문(스캔 글자 인식본)이다. 정답·오답이 교과서와 맞는지 대조하고, 교과서와 다르면 교과서를 따른다. 더 필요하면 work/src/tb/chNN.txt(단원별 교과서 전문)를 Grep으로 찾는다.
- 질환은 원문항의 지문과 정답으로 확정한다. 사진에서 실제로 보이는 것과 모순되는 내용을 쓰지 않는다.
- 지문은 "다음 사진과 같은 …" 또는 증례 + "(사진 1, 2)" 형식으로 쓰고, 사진의 진단명을 지문에 쓰지 않는다. 사진 번호는 그 원문항의 사진 안에서 1부터 센다.
- 사진이 임상·조직·더모스코피 사진이 아니거나(도식, 교과서 글 캡처, 표 등) 진단을 확신할 수 없으면 그 원문항은 {{"src":"원문항ID","skip":true}} 한 줄만 쓴다.

{RULES}

{(chr(10) * 2).join(blocks)}

{out_format(len(grp), '{"src":"원문항ID","ch":단원번호,"topic":"핵심 개념 한 줄(25자 내외)","stem":"지문",' + FORMAT + BASIS + '}')}"""
        batches.append({"no": no, "kind": "photo", "srcs": grp, "rel": rel_ids, "want": len(grp), "chs": sorted({KMAP[s]["ch"] for s in grp}), "prompt": prompt})

    # --- novel prompts
    for nb in novel:
        no += 1
        chunks = [kbmap[i] for i in nb["chunks"] if i in kbmap]
        past = [f"- {re.sub(r'\s+', ' ', k['stem'])[:90]}" + (f" → {k['o'][k['a']]}" if k.get('a') is not None and k['o'][k['a']] else "") for k in K if k["ch"] == nb["ch"]][:60]
        rec = recent_lines([nb["ch"]])
        n_case = round(nb["n"] * 0.6)
        seen = set()
        chunk_txt = "\n\n".join(excerpt(c, tbmap, seen=seen) for c in chunks)
        prompt = f"""{HEAD}

이번 묶음은 "아직 기출에 나오지 않은 내용"으로 Chapter {nb['ch']}. {chname(nb['ch'])} 새 문항 {nb['n']}개를 만든다. 아래 발췌는 수험생이 교과서를 정리한 노트(정리본)와, 있을 경우 Fitzpatrick 9판 보충 노트다. 정답 근거는 반드시 이 발췌에 적힌 사실이어야 한다.
{EMPH_LEGEND}

{chunk_txt}

[이 단원에서 이미 기출된 문항 — 같은 개념·같은 포인트는 피한다]
{chr(10).join(past) or '(없음)'}
{('[최근 이 앱에서 이미 낸 주제]' + chr(10) + chr(10).join(rec)) if rec else ''}

[출제 규칙]
- 정리본 발췌에서는 강조 부분(【…】, **…**) 가운데 위 기출 목록이 아직 묻지 않은 세부를 고른다. Fitzpatrick 보충 노트에서는 7판 정리본에 없는 세부 사실(아형, 감별점, 검사·병리 소견, 원인 유전자·항원, 치료 순서·용량, 합병증, 역학 수치)을 고른다.
- 정답은 발췌에 명시된 사실로만 정한다. 발췌에 없는 수치나 추론을 정답으로 만들지 않는다. 오답 보기는 같은 범주에서 그럴듯하게 만들되 교과서와 모순되지 않게 한다.{(chr(10) + '- ' + TB_RULE) if tbmap else ''}
- 발췌에서 [차이]로 표시된 7판·Fitz 불일치 항목, "(일반 지식)" 표시 항목, 숫자가 서로 다르게 적힌 항목은 출제하지 않는다. 7판과 Fitz가 다를 수 있으면 정리본(7판) 기준.
- "basis"에는 정답 근거가 된 발췌 문장(또는 강조 부분)을 글자 그대로 복사한다(80자 이내). 검사 프로그램이 발췌와 대조한다.
- 발췌가 목록·표라도 문항은 실제 시험처럼 쓴다. 약 {n_case}문항은 증례형(진단명을 쓰지 않고 소견으로 진단을 떠올리게 한 뒤 다음 단계를 묻기), 나머지는 지식형.
{NO_PHOTO}

{RULES}

{out_format(nb['n'], '{"ch":' + str(nb['ch']) + ',"topic":"핵심 개념 한 줄(25자 내외)","type":"case|recall","stem":"지문",' + FORMAT + ',"basis":"정답 근거 발췌 문장을 그대로 복사(80자 이내)"}')}"""
        batches.append({"no": no, "kind": "novel", "ch": nb["ch"], "chunks": nb["chunks"], "kbRef": [kb_label(c) for c in chunks], "want": nb["n"], "chs": [nb["ch"]], "prompt": prompt})

    # --- regular prompts: built on the parts of the notes the notes themselves emphasise
    for parts in text_batches:
        no += 1
        r = random.Random(f"text:{eid}:{no}")
        chunks = []
        for p in parts:
            got = pick_note_chunks(KB, p["ch"], n_chunks(p["n"]), r, kb_use, used_today)
            used_today |= {x["id"] for x in got}; chunks += got
        prompt = regular_prompt(parts, chunks, K, recent, chname, r, tbmap=tbmap)
        batches.append({"no": no, "kind": "text", "parts": parts, "chunks": [c["id"] for c in chunks], "want": sum(p["n"] for p in parts),
                        "chs": [p["ch"] for p in parts], "prompt": prompt})

    for b in batches:
        b["file"] = f"work/batches/{b['no']:02d}.md"
        b["out"] = f"work/out/{b['no']:02d}.jsonl"
        (ROOT / b["file"]).write_text(b.pop("prompt") + f"\n\n결과를 {b['out']} 파일에 JSON Lines로 저장한다(UTF-8, 한 줄에 객체 하나).\n")
    out = {"id": eid, "date": a.date, "n": a.n, "plan": plan, "used": sorted(used_today), "batches": batches}
    (W / "plan.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    kinds = {}
    for b in batches: kinds[b["kind"]] = kinds.get(b["kind"], 0) + b["want"]
    print(f"plan {eid}: {len(batches)} batches", kinds)


if __name__ == "__main__":
    main()
