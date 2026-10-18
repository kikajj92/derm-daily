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

from prompts import (HEAD, RULES, FORMAT, BASIS, kb_label, tb_label, fmt_kichul, out_format, related_excerpt, related_textbook, tb_block)
from targets import extract_points, pick_targets, target_prompt, kcov_terms, TBIndex


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


def build_ctx(KB, tbmap, state, K, chname, rng, FZK=None):
    """Everything target_prompt needs (also used by assemble.py for the refill batch)."""
    P = extract_points(KB)
    FZ = {z["id"]: z for v in (FZK or {}).values() for z in v}
    return {"P": P, "FZ": FZ, "FZK": FZK or {}, "PT": {p["id"]: p for v in P.values() for p in v}, "CHUNK": {x["id"]: x for v in KB.values() for x in v},
            "TBMAP": tbmap or {}, "TBX": TBIndex(tbmap) if tbmap else None, "st": state, "K": K,
            "hist": state.get("hist", []), "chname": chname, "rng": rng, "kb_label": kb_label, "tb_label": tb_label}


def group_parts(plan_counts, cap=8):
    """Chapters -> batches of at most `cap` questions, neighbouring chapters together."""
    out, cur, cn = [], [], 0
    for c in sorted(plan_counts, key=int):
        need = plan_counts[c]
        while need > cap:
            if cur: out.append(cur); cur, cn = [], 0
            out.append([{"ch": int(c), "n": cap}]); need -= cap
        if not need: continue
        if cn and cn + need > cap:
            out.append(cur); cur, cn = [], 0
        cur.append({"ch": int(c), "n": need}); cn += need
        if cn >= cap - 1:
            out.append(cur); cur, cn = [], 0
    if cur: out.append(cur)
    return out


NOVEL_INTRO = ("\n이번 묶음은 \"아직 기출에 나오지 않은 내용\"이다. 지정 포인트는 기출에서 거의 다뤄지지 않은 곳에서 골랐다. "
               "그래도 정답은 그 질환·주제의 핵심 사실이어야 한다.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--photo", type=int, default=50, help="사진 문항 비율(%%): 기출 사진 변형 + 교과서 사진")
    ap.add_argument("--kphoto", type=int, default=25, help="그중 기출 사진 변형 최대 비율(%%)")
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

    KBF = load("kb"); K = load("kichul"); meta = load("meta"); KB = KBF["ch"]; state = load("state", {}) or {}
    TB = load("textbook")
    tbmap = {w["id"]: w for v in TB["ch"].values() for w in v} if TB else None
    if not tbmap:
        print("NOTE: textbook text not available (DD_SRCKEY not set) — prompts will use the notes only")
    KMAP = {k["id"]: k for k in K}
    CH = meta["chapters"]
    chname = lambda c: CH.get(str(c), f"Chapter {c}")
    rng = random.Random("plan:" + eid)
    plan = allocate(a.n, meta["raw"], rng)

    # 1) photo variants from real past-exam photos — each photo rests ≥4 days, at most 6 uses, and is asked from a new angle each time
    pu, plast, pask = state.get("photoUse", {}), state.get("photoLast", {}), state.get("photoAsk", {})
    def rested(k):
        d = plast.get(k["id"])
        return pu.get(k["id"], 0) < 6 and (not d or (datetime.date.fromisoformat(a.date) - datetime.date.fromisoformat(d)).days >= 4)
    photo_ok = [k for k in K if k.get("qi") and k.get("a") is not None and (k["o"][k["a"]] or "").strip() and k.get("ch") and rested(k)]
    rng2 = random.Random("photo:" + eid)
    rng2.shuffle(photo_ok)
    photo_ok.sort(key=lambda k: pu.get(k["id"], 0))
    cap = {c: math.ceil(n * 0.8) for c, n in plan.items()}
    K_photo = round(a.n * a.photo / 100)
    srcs = []
    for k in photo_ok:
        if len(srcs) >= min(K_photo, round(a.n * a.kphoto / 100)): break
        c = str(k["ch"])
        if cap.get(c, 0) > 0:
            cap[c] -= 1; srcs.append(k["id"])
    text_plan = dict(plan)
    for s in srcs:
        c = str(KMAP[s]["ch"]); text_plan[c] -= 1
        if text_plan[c] <= 0: del text_plan[c]

    # 1b) photos from the 피부과학 7판 textbook itself (clinical / histology figures), rest ≥7 days, ≤6 uses
    FIGS = load("figs") or []
    fu, fl = state.get("figUse", {}), state.get("figLast", {})
    def fig_ok(f):
        d = fl.get(f["id"])
        return f["files"] and fu.get(f["id"], 0) < 6 and (not d or (datetime.date.fromisoformat(a.date) - datetime.date.fromisoformat(d)).days >= 7)
    rngf = random.Random("tfig:" + eid)
    fpool = [f for f in FIGS if fig_ok(f) and cap.get(str(f["ch"]), 0) > 0]
    rngf.shuffle(fpool)
    fpool.sort(key=lambda f: fu.get(f["id"], 0))
    tfigs = []
    for f in fpool:
        if len(srcs) + len(tfigs) >= K_photo: break
        c = str(f["ch"])
        if cap.get(c, 0) > 0 and text_plan.get(c, 0) > 0:
            cap[c] -= 1; tfigs.append(f)
            text_plan[c] -= 1
            if text_plan[c] <= 0: del text_plan[c]

    # 2) split the text questions into 'not yet tested' and regular, per chapter
    rng3 = random.Random("novel:" + eid)
    K_novel = round(a.n * a.novel / 100)
    capn = {c: math.ceil(n * 0.5) for c, n in text_plan.items()}
    novel_plan, left = {}, K_novel
    while left > 0:
        ent = [c for c in capn if capn[c] > 0]
        if not ent: break
        tot = sum(text_plan[c] for c in ent); t = rng3.random() * tot; pick = ent[-1]
        for c in ent:
            t -= text_plan[c]
            if t <= 0: pick = c; break
        take = max(1, min(3, left, capn[pick]))
        novel_plan[pick] = novel_plan.get(pick, 0) + take; capn[pick] -= take; left -= take
    reg_plan = {c: n - novel_plan.get(c, 0) for c, n in text_plan.items() if n - novel_plan.get(c, 0) > 0}

    # 3) a specific target for every text question
    ctx = build_ctx(KB, tbmap, state, K, chname, random.Random("ctx:" + eid), KBF.get("fz"))
    kterms = kcov_terms(K)
    taken = set()
    TBW = {}
    for wid, w in (tbmap or {}).items():
        TBW.setdefault(re.match(r"\d+", wid).group(), []).append(w)
    def batches_for(pplan, mode):
        out = []
        for parts in group_parts(pplan):
            tg = []
            for p in parts:
                c = str(p["ch"])
                tg += pick_targets(p["ch"], p["n"], mode, ctx["P"].get(c, []), TBW.get(c, []), state, a.date,
                                   random.Random(f"{mode}:{eid}:{c}"), taken, kterms, ctx["FZK"].get(c, []))
            out.append((parts, tg))
        return out
    novel_b = batches_for(novel_plan, "novel")
    reg_b = batches_for(reg_plan, "regular")

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

    batches = []
    no = 0
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
            prev = pask.get(sid, [])
            blocks.append(f"원문항 {i + 1} [ID {k['id']}] — Ch {k['ch']} {chname(k['ch'])} — 이미지 {nums}\n{fmt_kichul(k)}"
                          + (f"\n\n[이 사진으로 이미 낸 문항 — 같은 것을 묻지 말고 다른 각도로]\n" + "\n".join(f"- {x}" for x in prev) if prev else "")
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
- [이 사진으로 이미 낸 문항]이 붙어 있으면 그 문항들과도 다른 것을 묻는다(정답이 같은 사실이면 버려진다).
- 원문항 아래에 [정리본 관련 부분]이 붙어 있으면, 새 문항이 묻는 포인트를 거기서 강조된 사실(【…】 밑줄·형광, **…** 굵게, (23기출) 같은 출제 표시)에서 고르고, "basis"에 그 강조 부분을 글자 그대로 복사한다. 붙어 있지 않으면 피부과학 7판의 핵심 내용으로 내고 basis는 빈 문자열로 둔다.
- 원문항 아래 [교과서 원문]은 가장 중요한 기준 교재인 「피부과학」 7판 본문(스캔 글자 인식본)이다. 정답·오답이 교과서와 맞는지 대조하고, 교과서와 다르면 교과서를 따른다. 더 필요하면 work/src/tb/chNN.txt(단원별 교과서 전문)를 Grep으로 찾는다.
- 질환은 원문항의 지문과 정답으로 확정한다. 사진에서 실제로 보이는 것과 모순되는 내용을 쓰지 않는다.
- 지문은 "다음 사진과 같은 …" 또는 증례 + "(사진 1, 2)" 형식으로 쓰고, 사진의 진단명을 지문에 쓰지 않는다. 사진 번호는 그 원문항의 사진 안에서 1부터 센다.
- 사진이 임상·조직·더모스코피 사진이 아니거나(도식, 교과서 글 캡처, 표 등) 진단을 확신할 수 없으면 그 원문항은 {{"src":"원문항ID","skip":true}} 한 줄만 쓴다.

{RULES}

{(chr(10) * 2).join(blocks)}

{out_format(len(grp), '{"src":"원문항ID","ch":단원번호,"topic":"핵심 개념 한 줄(25자 내외)","stem":"지문",' + FORMAT + BASIS + '}')}"""
        batches.append({"no": no, "kind": "photo", "srcs": grp, "rel": rel_ids, "want": len(grp), "chs": sorted({KMAP[s]["ch"] for s in grp}), "prompt": prompt})

    # --- textbook photo prompts (≤4 figures, ≤8 images per batch)
    groups, cur, ni = [], [], 0
    for f in tfigs:
        n_ = min(len(f["files"]), 4)
        if cur and (len(cur) >= 4 or ni + n_ > 8):
            groups.append(cur); cur, ni = [], 0
        cur.append(f); ni += n_
    if cur: groups.append(cur)
    fask = state.get("figAsk", {})
    TBX = ctx["TBX"]
    for grp in groups:
        no += 1; names = []; blocks = []
        for i, f in enumerate(grp):
            ims = f["files"][:4]
            first = len(names) + 1; names += ims
            nums = ", ".join(str(x) for x in range(first, first + len(ims)))
            dz = re.split(r"[.(:]", f["caption"])[0].strip() or f["caption"]
            dz = re.sub(r"\s*의?\s*(임상|조직|병리|피부|발진|소견|사진|더모스코피|면역형광).*$", "", dz).strip() or dz
            pk = {"stem": f["caption"], "o": [dz], "a": 0, "ex": ""}
            rc, rel = related_excerpt(KB, f["ch"], pk)
            num = f["fig"].split("-")
            ref = re.compile(r"(?:그림|그링|그럼)\s*" + num[0] + r"\s*-\s*" + num[1] + r"(?!\d)")
            wins = [w for w in TBW.get(str(f["ch"]), []) if ref.search(w["text"]) and not w["text"].lstrip().startswith("그림")]
            tw = wins[0] if wins else (TBX.best(f["ch"], f["caption"]) if TBX else None)
            prev = fask.get(f["id"], [])
            blocks.append(f"사진 {i + 1} [ID {f['id']}] — Ch {f['ch']} {chname(f['ch'])} — 이미지 {nums}\n"
                          f"[교과서 그림 설명 — 정답 확인용, 지문·보기에 그대로 쓰지 말 것] 피부과학 7판 p.{f['page']} 그림 {f['fig']}: {f['caption']}"
                          + (f"\n\n[이 사진으로 이미 낸 문항 — 같은 것을 묻지 말고 다른 각도로]\n" + "\n".join(f"- {x}" for x in prev) if prev else "")
                          + (f"\n\n{tb_block(tw)}" if tw else "") + (f"\n\n{rel}" if rel else ""))
        for nm in names:
            (W / "img" / nm).write_bytes(C.dec_bytes((ROOT / "secure" / "figs" / (nm + ".enc")).read_bytes()))
        img_list = "\n".join(f"- 이미지 {i + 1}: work/img/{nm}" for i, nm in enumerate(names))
        prompt = f"""{HEAD}

아래는 「피부과학」 7판 교과서에 실린 임상·조직 사진 {len(grp)}개다. 사진 파일은 work/img/ 에 있다. 사진을 Read 도구로 하나씩 직접 열어 본 뒤 작업한다.
{img_list}

[해야 할 일]
사진마다 그 사진을 그대로 보여 주는 새 문항을 1개씩 만든다. 최근 1차 시험은 피부 소견·조직 소견을 글 대신 사진으로 주고, 진단 다음 단계를 묻는다(위 2024 기출 예처럼).
- 질환은 [교과서 그림 설명]으로 확정한다. 사진에서 실제로 보이는 것과 모순되는 내용을 쓰지 않는다.
- 지문: 나이·성별·핵심 병력·필요한 검사 수치만 1–2문장으로 쓰고 "다음 사진과 같은 …" 또는 "(사진)"으로 사진을 가리킨다. 진단명과 그림 설명의 표현은 지문에 쓰지 않는다. 피부·조직 소견을 글로 다시 묘사하지 않는다.
- 묻는 것: 그 질환의 치료 방향(1차 치료·대체·금기), 경과·예후 인자·재발 인자, 합병증·동반 질환·동반 악성종양, 관련 자가항체·표적항원, 확진 검사·검사 기질, 원인 유전자 중 하나. 진단명 자체를 묻는 문항은 묶음에서 1개까지.
- 정답 근거는 붙어 있는 [교과서 원문]·[정리본 관련 부분]에서 고르고 "basis"에 그 문장을 글자 그대로 복사한다(정리본의 【…】·**…** 강조 부분이 있으면 우선). 더 필요하면 work/src/tb/chNN.txt(단원별 교과서 전문)를 Grep으로 찾는다. 교과서와 다르면 교과서를 따른다.
- 보기는 짧은 단답형 5개.
- [이 사진으로 이미 낸 문항]이 있으면 그것과 다른 것을 묻는다.
- 사진이 임상·조직·면역형광·더모스코피 사진이 아니거나(도식·표·글 캡처), 사진만으로는 그 질환을 떠올리기 어렵거나, 사진 안에 진단명을 알려 주는 글자가 보이면 {{"src":"사진ID","skip":true}} 한 줄만 쓴다.

{RULES}

{(chr(10) * 2).join(blocks)}

{out_format(len(grp), '{"src":"사진ID","ch":단원번호,"topic":"핵심 개념 한 줄(25자 내외)","stem":"지문",' + FORMAT + BASIS + '}')}"""
        batches.append({"no": no, "kind": "tphoto", "srcs": [f["id"] for f in grp], "want": len(grp), "chs": sorted({f["ch"] for f in grp}), "prompt": prompt})

    # --- targeted text prompts
    for kind, mode, blist in (("novel", "novel", novel_b), ("text", "regular", reg_b)):
        for parts, tg in blist:
            no += 1
            ctx["rng"] = random.Random(f"ex:{eid}:{no}")
            prompt = target_prompt(tg, ctx, mode, NOVEL_INTRO if mode == "novel" else "")
            batches.append({"no": no, "kind": kind, "parts": parts, "targets": tg, "want": len(tg), "chs": [p["ch"] for p in parts], "prompt": prompt})

    for b in batches:
        b["file"] = f"work/batches/{b['no']:02d}.md"
        b["out"] = f"work/out/{b['no']:02d}.jsonl"
        (ROOT / b["file"]).write_text(b.pop("prompt") + f"\n\n결과를 {b['out']} 파일에 JSON Lines로 저장한다(UTF-8, 한 줄에 객체 하나).\n")
    out = {"id": eid, "date": a.date, "n": a.n, "plan": plan, "taken": sorted(taken), "batches": batches}
    (W / "plan.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    kinds = {}
    for b in batches: kinds[b["kind"]] = kinds.get(b["kind"], 0) + b["want"]
    tgk = {}
    for b in batches:
        for t in b.get("targets", []): tgk[t["kind"]] = tgk.get(t["kind"], 0) + 1
    print(f"plan {eid}: {len(batches)} batches", kinds, "targets", tgk)


if __name__ == "__main__":
    main()
