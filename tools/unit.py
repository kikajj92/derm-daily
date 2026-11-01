#!/usr/bin/env python3
"""Chapter question sets (단원별 문제집) for the 피부과학 7판 chapters.

  DD_PASS=… DD_SRCKEY=… python3 tools/unit.py prep  PLAN_DIR CH [CH…]   # write work/unit/batches/*.md (+ images to work/img)
  DD_PASS=… DD_SRCKEY=… python3 tools/unit.py check PLAN_DIR CH          # report missing units, write a refill batch if needed
  DD_PASS=… DD_SRCKEY=… python3 tools/unit.py publish PLAN_DIR CH        # build u{CH}-{part}.enc, update index + state

A plan (PLAN_DIR/chNN.json) lists the chapter's units (diseases/topics) in textbook order with
the number of questions, the angle of each question and the photos assigned to the unit.
"""
import datetime, json, math, random, re, sys
from pathlib import Path
import ddcrypt as C
from prompts import HEAD, RULES, FORMAT, kb_label, tb_label, fmt_kichul, out_format, related_excerpt
from targets import extract_points, TBIndex, region
from assemble import normalize, read_jsonl, record

ROOT = C.ROOT
W = ROOT / "work"
UW = W / "unit"
MAXQ, MAXIMG = 10, 8
# 기출 photos whose extracted images do not match the question (checked by eye)
BAD_PHOTO = {"2024-22"}

UNIT_RULES = """[단원별 문제집 규칙 — 위 규칙과 다르면 이 규칙이 우선]
- 이 문제집은 「피부과학」 7판 한 단원의 질환이 모두 한 번씩은 나오도록 만든다. 문항마다 지정된 [단위]와 [묻는 것]을 지킨다.
- 증례 위주: 나이·성별·병력·경과로 시작하는 증례로 쓴다. 지문에 그 질환의 진단명을 먼저 쓰지 않는다(소견을 보고 진단을 떠올리게 한다).
- 사진이 붙은 문항: 지문은 짧은 병력 + "다음 사진과 같은 …" 또는 "(사진)"으로 사진을 가리키고, 사진에 보이는 소견을 글로 다시 묘사하지 않는다.
- 사진이 없는 문항: 진단의 실마리가 되는 핵심 임상 소견(부위·모양·분포·경과)과, 필요하면 조직 소견·검사 수치를 1–3문장으로 준다. 길게 늘어놓지 않는다.
- 질환이 아닌 주제(피부 구조, 조직병리 용어, 면역 기전, 치료제, 시술 등)는 가능하면 짧은 임상 상황으로 시작하고, 자연스럽지 않으면 짧은 지식형으로 묻는다.
- 묻는 것은 [묻는 것]에 적힌 각도(치료 방향·경과·예후 인자·동반 질환·자가항체·검사·원인 유전자·조직 소견 등). 진단명 자체를 묻는 문항은 [묻는 것]이 진단일 때만.
- 드문 질환도 그 질환의 가장 핵심적인 특징(그 질환을 다른 질환과 가르는 사실)을 정답으로 한다. 곁가지 사실은 정답으로 삼지 않는다.
- 보기는 짧은 단답형 5개(대개 15자 안팎, 길어도 25자). 오답은 같은 단원의 이웃 질환·같은 계열 약·같은 검사의 다른 결과에서 고른다.
- 정답·수치·오답은 붙어 있는 [교과서 원문]과 대조하고, 필요하면 work/src/tb/chNN.txt(단원별 교과서 전문)를 Grep으로 찾는다. 정리본과 교과서가 다르면 교과서를 따른다. 확실하지 않으면 그 사실로 출제하지 않는다.
- "basis"에는 정답 근거 문장을 [교과서 원문] 또는 [정리본]에서 글자 그대로 복사한다(80자 이내)."""


def load(name, default=None):
    p = W / "src" / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else default


def ctx():
    KB = load("kb")["ch"]
    TB = load("textbook")
    tbmap = {w["id"]: w for v in TB["ch"].values() for w in v} if TB else {}
    K = {k["id"]: k for k in load("kichul")}
    FIGS = {f["id"]: f for f in (load("figs") or [])}
    P = extract_points(KB)
    return {"KB": KB, "tbmap": tbmap, "TBX": TBIndex(tbmap), "K": K, "FIGS": FIGS, "P": P,
            "CHUNK": {x["id"]: x for v in KB.values() for x in v}, "meta": load("meta")}


def plan_of(plan_dir, ch):
    return json.loads((Path(plan_dir) / f"ch{ch:02d}.json").read_text())


def slots_of(plan, X):
    """Expand units into question slots: (slot id, unit index, unit, angle, photo id or None)."""
    out = []
    for ui, u in enumerate(plan["units"]):
        n = max(1, int(u.get("n") or 1))
        photos = [p for p in (u.get("photos") or []) if p in X["FIGS"] or p in X["K"]]
        n = max(n, len(photos))
        angles = list(u.get("angles") or [])
        for k in range(n):
            out.append({"slot": f"{plan['ch']}-{ui:03d}-{k}", "ui": ui, "unit": u, "angle": angles[k] if k < len(angles) else (angles[-1] if angles else "핵심 특징"),
                        "photo": photos[k] if k < len(photos) else None})
    return out


def kname(name):
    return re.sub(r"\s*\(.*?\)\s*", "", name).strip()


def sources(ch, u, X, seen_tb):
    """Textbook passages + notes region for one unit."""
    out = []
    page = u.get("page")
    wins = [w for wid, w in X["tbmap"].items() if wid.startswith(f"{ch}t") and page and w["p"][0] <= page <= w["p"][1]]
    best = X["TBX"].best(ch, u["name"] + " " + " ".join(u.get("angles") or []))
    for w in (wins[:1] + ([best] if best else [])):
        if w and w["id"] not in seen_tb and len(out) < 2:
            seen_tb.add(w["id"])
            out.append(f"[교과서 원문 — {tb_label(w)}]\n{w['text'][:2200]}")
    kn = kname(u["name"])
    pts = [p for p in X["P"].get(str(ch), []) if kn and (kn in p["grp"] or kn in p["ctx"] or kn in p["line"])]
    if pts:
        p = pts[0]; c = X["CHUNK"][p["chunk"]]
        out.append(f"[정리본 — {kb_label(c)}]\n{region(c['text'], p['line'], 600, 1200)}")
    else:
        rc, rel = related_excerpt(X["KB"], ch, {"stem": u["name"], "o": [kn], "a": 0, "ex": ""})
        if rel:
            out.append(rel.replace("[정리본 관련 부분", "[정리본"))
    return out


def batches_of(plan, X):
    S = slots_of(plan, X)
    groups, cur, imgs = [], [], 0
    by_unit = {}
    for s in S:
        by_unit.setdefault(s["ui"], []).append(s)
    for ui in sorted(by_unit):
        ss = by_unit[ui]
        while ss:
            take = ss[:MAXQ]; ss = ss[MAXQ:]
            ni = sum(len(X["FIGS"][s["photo"]]["files"][:4]) if s["photo"] in X["FIGS"] else len(X["K"][s["photo"]]["qi"][:4]) if s["photo"] else 0 for s in take)
            if cur and (len(cur) + len(take) > MAXQ or imgs + ni > MAXIMG):
                groups.append(cur); cur, imgs = [], 0
            cur += take; imgs += ni
    if cur:
        groups.append(cur)
    return groups


def write_batch(ch, name, bno, slots, X, extra=""):
    (W / "img").mkdir(parents=True, exist_ok=True)
    names, blocks, seen_tb, done_units = [], [], set(), {}
    for i, s in enumerate(slots, 1):
        u = s["unit"]
        b = f"[문항 {i}] slot={s['slot']}\n단위: {u['name']}" + (f" (교과서 p.{u['page']})" if u.get("page") else "") + f"\n묻는 것: {s['angle']}"
        ph = s["photo"]
        if ph and ph in X["FIGS"]:
            f = X["FIGS"][ph]; ims = f["files"][:4]
            first = len(names) + 1; names += ims
            for nm in ims:
                (W / "img" / nm).write_bytes(C.dec_bytes((ROOT / "secure" / "figs" / (nm + ".enc")).read_bytes()))
            b += (f"\n사진: 이미지 {', '.join(str(x) for x in range(first, first + len(ims)))} (교과서 사진 — 반드시 Read로 열어 본다)"
                  f"\n[교과서 그림 설명 — 정답 확인용, 지문·보기에 그대로 쓰지 말 것] 피부과학 7판 p.{f['page']} 그림 {f['fig']}: {f['caption']}")
        elif ph and ph in X["K"]:
            k = X["K"][ph]; ims = k["qi"][:4]
            first = len(names) + 1; names += ims
            for nm in ims:
                (W / "img" / nm).write_bytes(C.dec_bytes((ROOT / "data" / "img" / (nm + ".enc")).read_bytes()))
            b += (f"\n사진: 이미지 {', '.join(str(x) for x in range(first, first + len(ims)))} (기출 사진 — 반드시 Read로 열어 본다)"
                  f"\n[이 사진이 나온 실제 기출 — 질환 확인용. 같은 문항을 베끼지 말고 [묻는 것]으로 새로 쓴다]\n{fmt_kichul(k)}")
        else:
            b += "\n사진: 없음 — 핵심 소견을 지문에 1–3문장으로 준다."
        if s["ui"] not in done_units:
            src = sources(ch, u, X, seen_tb)
            done_units[s["ui"]] = i
            if src:
                b += "\n\n" + "\n\n".join(src)
        else:
            b += f"\n(근거 자료는 문항 {done_units[s['ui']]}에 붙은 것과 같다)"
        blocks.append(b)
    img_list = "\n".join(f"- 이미지 {i + 1}: work/img/{nm}" for i, nm in enumerate(names)) or "(이 묶음에는 사진이 없다)"
    prompt = f"""{HEAD}

이번 묶음은 「피부과학」 7판 {ch}장 {name}의 단원별 문제집 일부다. 총 {len(slots)}문항. 아래 [문항 n]마다 정확히 한 문항씩 쓴다.
{extra}
사진 파일:
{img_list}

{UNIT_RULES}

{RULES}

{(chr(10) * 2).join(blocks)}

{out_format(len(slots), '{"slot":"문항의 slot 값 그대로","topic":"핵심 개념 한 줄(25자 내외)","stem":"지문",' + FORMAT + ',"basis":"정답 근거 문장을 그대로 복사(80자 이내)"}')}

결과를 work/unit/out/{bno}.jsonl 파일에 JSON Lines로 저장한다(UTF-8, 한 줄에 객체 하나)."""
    (UW / "batches").mkdir(parents=True, exist_ok=True)
    (UW / "batches" / f"{bno}.md").write_text(prompt)
    return {"id": bno, "ch": ch, "slots": [s["slot"] for s in slots], "photos": {s["slot"]: s["photo"] for s in slots if s["photo"]},
            "units": {s["slot"]: s["ui"] for s in slots}}


def prep(plan_dir, chs):
    X = ctx()
    (UW / "out").mkdir(parents=True, exist_ok=True)
    reg_p = UW / "registry.json"
    reg = json.loads(reg_p.read_text()) if reg_p.exists() else {}
    for ch in chs:
        plan = plan_of(plan_dir, ch)
        name = X["meta"]["chapters"][str(ch)]
        groups = batches_of(plan, X)
        reg[str(ch)] = [write_batch(ch, name, f"ch{ch:02d}_b{i + 1:02d}", g, X) for i, g in enumerate(groups)]
        print(f"ch{ch}: {len(plan['units'])} units, {sum(len(g) for g in groups)} questions, {len(groups)} batches, "
              f"{sum(1 for g in groups for s in g if s['photo'])} photo")
    reg_p.write_text(json.dumps(reg, ensure_ascii=False, indent=1))


def collect(ch, X, reg):
    """Valid questions of a chapter, keyed by slot."""
    got = {}
    for b in reg.get(str(ch), []):
        for o in read_jsonl(UW / "out" / f"{b['id']}.jsonl"):
            slot = str(o.get("slot") or "")
            if slot not in b["slots"] or slot in got:
                continue
            q = normalize({**o, "ch": ch, "figures": []}, [ch])
            if not q:
                continue
            ph = b["photos"].get(slot)
            if o.get("nophoto") or ph in BAD_PHOTO:
                ph = None  # writer/reviewer judged the photo not to show this unit's disease
            if ph and ph in X["FIGS"]:
                f = X["FIGS"][ph]; q.update(type="photo", imgs=f["files"][:4], figId=ph, kbRef=[f"피부과학 7판 p.{f['page']} 그림 {f['fig']}"])
            elif ph and ph in X["K"]:
                q.update(type="photo", imgs=X["K"][ph]["qi"][:4], srcKid=ph)
            elif re.search(r"사진|그림", re.sub(r"(방사선|X선|엑스선|흉부|CT|MRI)\s*사진", "", q["stem"])):
                continue
            else:
                q["type"] = "case"
            q["slot"] = slot; q["ui"] = b["units"][slot]
            got[slot] = q
    return got


def check(plan_dir, ch):
    X = ctx()
    reg = json.loads((UW / "registry.json").read_text())
    plan = plan_of(plan_dir, ch)
    got = collect(ch, X, reg)
    S = slots_of(plan, X)
    covered = {q["ui"] for q in got.values()}
    miss_units = [i for i in range(len(plan["units"])) if i not in covered]
    print(f"ch{ch}: {len(got)}/{len(S)} questions, units missing {len(miss_units)}")
    if miss_units and not any(b["id"].endswith("_r") for b in reg[str(ch)]):
        slots = [s for s in S if s["ui"] in miss_units and s["slot"].endswith("-0")]
        name = X["meta"]["chapters"][str(ch)]
        b = write_batch(ch, name, f"ch{ch:02d}_r", slots, X, "\n(앞선 묶음에서 빠진 질환을 보충하는 묶음이다.)\n")
        reg[str(ch)].append(b)
        (UW / "registry.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1))
        print("REFILL:", f"work/unit/batches/{b['id']}.md")
        sys.exit(3)


def publish(plan_dir, ch):
    X = ctx()
    reg = json.loads((UW / "registry.json").read_text())
    plan = plan_of(plan_dir, ch)
    got = collect(ch, X, reg)
    qs = sorted(got.values(), key=lambda q: q["slot"])
    if len(qs) < 20:
        sys.exit(f"ch{ch}: only {len(qs)} questions — not publishing")
    name = X["meta"]["chapters"][str(ch)]
    parts = 1 if len(qs) <= 55 else math.ceil(len(qs) / 50)
    size = math.ceil(len(qs) / parts)
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
    idx_p = ROOT / "data" / "exams" / "index.json"
    idx = json.loads(idx_p.read_text())
    idx["exams"] = [e for e in idx["exams"] if not (e.get("kind") == "unit" and e.get("ch") == ch)]
    for pi in range(parts):
        part = qs[pi * size:(pi + 1) * size]
        random.Random(f"unit:{ch}:{pi}").shuffle(part)
        for i, q in enumerate(part):
            q["id"] = f"u{ch:02d}-{pi + 1}-{i:03d}"
        for q in part:
            for nm in (q.get("imgs") or []) if q.get("figId") else []:
                dst = ROOT / "data" / "img" / (nm + ".enc")
                if not dst.exists():
                    dst.write_bytes(C.enc_bytes(C.dec_bytes((ROOT / "secure" / "figs" / (nm + ".enc")).read_bytes())))
        eid = f"u{ch:02d}-{pi + 1}"
        title = f"{ch}장 {name}" + (f" ({pi + 1}/{parts})" if parts > 1 else "")
        counts = {"photo": sum(1 for q in part if q.get("imgs")), "text": sum(1 for q in part if not q.get("imgs")), "novel": 0}
        exam = {"v": 1, "id": eid, "kind": "unit", "date": today, "title": title, "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "plan": {str(ch): len(part)}, "counts": counts, "questions": part}
        C.enc_json(exam, ROOT / "data" / "exams" / f"{eid}.enc")
        idx["exams"].append({"id": eid, "kind": "unit", "ch": ch, "part": pi + 1, "parts": parts, "date": today, "title": title,
                             "n": len(part), "photos": counts["photo"], "file": f"data/exams/{eid}.enc"})
    idx["exams"].sort(key=lambda e: e["id"], reverse=True)
    idx["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    idx_p.write_text(json.dumps(idx, ensure_ascii=False, indent=1))
    st = load("state", {}) or {}
    record(st, qs, {}, today)
    C.enc_json(st, ROOT / "secure" / "state.enc")
    (W / "src" / "state.json").write_text(json.dumps(st, ensure_ascii=False))
    covered = {q["ui"] for q in qs}
    print(f"published ch{ch}: {len(qs)} questions in {parts} part(s), photos {sum(1 for q in qs if q.get('imgs'))}, "
          f"units covered {len(covered)}/{len(plan['units'])}")


if __name__ == "__main__":
    cmd, plan_dir = sys.argv[1], sys.argv[2]
    chs = [int(x) for x in sys.argv[3:]]
    if cmd == "prep":
        prep(plan_dir, chs)
    elif cmd == "check":
        check(plan_dir, chs[0])
    elif cmd == "publish":
        publish(plan_dir, chs[0])
