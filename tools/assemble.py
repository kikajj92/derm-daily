#!/usr/bin/env python3
"""Validate the batch outputs, then either ask for a refill or publish the exam.

  DD_PASS=... python3 tools/assemble.py            # check; writes work/refill.md if questions are missing (exit 3)
  DD_PASS=... python3 tools/assemble.py --final    # build, encrypt to data/exams/<date>.enc, update index + state

Rules match the app: exactly 5 distinct options, a valid answer index, options sorted the way
the printed exam sorts them (numbers naturally, then letters, then Hangul), answer re-mapped.
"""
import argparse, datetime, json, re, sys, unicodedata
from pathlib import Path
import random
import ddcrypt as C
from prompts import kb_label, tb_label, anchor_of
from targets import pick_targets, target_prompt, kcov_terms, is_repeat

ROOT = C.ROOT
W = ROOT / "work"
LET = "가나다라마"


def clean_opt(x):
    return re.sub(r"^\s*(?:[가나다라마]|[1-5]|[①-⑤]|[A-Ea-e])\s*[\)\.]\s*", "", str(x or "")).strip()


def nat_key(s):
    s = unicodedata.normalize("NFC", s).casefold()
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", s)]


def normalize(o, allowed):
    if not isinstance(o, dict) or o.get("skip"):
        return None
    opts = [clean_opt(x) for x in (o.get("options") or [])]
    if len(opts) != 5 or any(not x for x in opts) or len({x.lower() for x in opts}) != 5:
        return None
    if max(len(x) for x in opts) > 45:   # current exam style: short answer options only
        return None
    a = o.get("answer")
    if isinstance(a, str):
        t = a.strip()
        a = LET.index(t[0]) if t and t[0] in LET else (int(t) if t.isdigit() else None)
    if not isinstance(a, int) or not 0 <= a <= 4:
        return None
    stem = str(o.get("stem") or "").strip()
    if len(stem) < 8:
        return None
    try:
        ch = int(o.get("ch"))
    except Exception:
        ch = allowed[0]
    if ch not in allowed:
        ch = allowed[0]
    correct = opts[a]
    srt = sorted(opts, key=nat_key)
    figs = [{"kind": str(f.get("kind") or "사진")[:12], "desc": str(f.get("desc")).strip()} for f in (o.get("figures") or []) if isinstance(f, dict) and f.get("desc")][:4]
    return {
        "ch": ch, "topic": str(o.get("topic") or "")[:80],
        "type": "photo" if figs else (o.get("type") if o.get("type") in ("case", "recall", "photo") else "recall"),
        "stem": stem, "figs": figs, "options": srt, "answer": srt.index(correct),
        "explanation": str(o.get("explanation") or "").strip(), "point": str(o.get("point") or "").strip(),
        "ref": str(o.get("ref") or "").strip(), "basis": str(o.get("basis") or "").strip()[:200],
    }


def read_jsonl(path):
    out = []
    if not path.exists():
        return out
    txt = path.read_text(errors="replace")
    for line in txt.splitlines():
        line = line.strip().rstrip(",")
        if line.startswith("{") and line.endswith("}"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    if not out:  # tolerate pretty-printed objects
        for m in re.finditer(r"\{(?:[^{}]|\{[^{}]*\})*\}", txt, re.S):
            try:
                out.append(json.loads(m.group()))
            except Exception:
                pass
    return out


def load_src(name, default=None):
    p = W / "src" / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args()
    plan = json.loads((W / "plan.json").read_text())
    Klist = load_src("kichul"); K = {k["id"]: k for k in Klist}
    meta = load_src("meta")
    KBF = load_src("kb"); KB = KBF["ch"]
    st = load_src("state", {}) or {}
    TB = load_src("textbook")
    tbmap = {w["id"]: w for v in TB["ch"].values() for w in v} if TB else {}
    kbmap = {x["id"]: x for c in KB.values() for x in c}
    import plan as PL
    CH = meta["chapters"]
    chname = lambda c: CH.get(str(c), f"Chapter {c}")
    ctx = PL.build_ctx(KB, tbmap, st, Klist, chname, random.Random("refill-ex:" + plan["id"]), KBF.get("fz"))
    FZ = ctx["FZ"]
    PT = ctx["PT"]
    FIGS = {f["id"]: f for f in (load_src("figs") or [])}
    hist = st.get("hist", [])
    today = plan["date"]
    qs, seen, report = [], set(), []
    drops = {"anchor": 0, "repeat": 0, "target": 0}
    used_tids = set()
    batches = list(plan["batches"])
    if (W / "out" / "refill.jsonl").exists() and plan.get("refill"):
        batches.append(plan["refill"])
    for b in batches:
        objs = read_jsonl(ROOT / b["out"])
        allowed = {}
        for t in b.get("targets", []):
            allowed[t["id"]] = t
            if t.get("alt"): allowed[t["alt"]] = {"kind": "pt", "id": t["alt"], "ch": t["ch"]}
        got, drop = [], {"anchor": 0, "repeat": 0, "target": 0}
        for o in objs:
            if b["kind"] == "photo":
                sid = str(o.get("src") or "")
                if sid not in b["srcs"] or o.get("skip") or any(q.get("srcKid") == sid for q in got):
                    continue
                k = K[sid]
                q = normalize({**o, "ch": k["ch"], "figures": []}, [k["ch"]])
                if q:
                    q["type"] = "photo"; q["imgs"] = k["qi"][:4]; q["srcKid"] = sid
                    rel = kbmap.get((b.get("rel") or {}).get(sid, ""))
                    hit = anchor_of(q["basis"], [rel]) if rel else None
                    if hit: q["kbRef"] = [kb_label(hit)]
                    else: q["basis"] = ""
            elif b["kind"] == "tphoto":
                sid = str(o.get("src") or "")
                if sid not in b["srcs"] or sid not in FIGS or o.get("skip") or any(q.get("figId") == sid for q in got):
                    continue
                f = FIGS[sid]
                q = normalize({**o, "ch": f["ch"], "figures": []}, [f["ch"]])
                if q:
                    q["type"] = "photo"; q["imgs"] = f["files"][:4]; q["figId"] = sid
                    q["kbRef"] = [f"피부과학 7판 p.{f['page']} 그림 {f['fig']}"]
            else:
                q = normalize({**o, "figures": []}, b["chs"])
                if q and re.search(r"사진|그림", q["stem"]):
                    q = None
                if q and allowed:
                    tid = str(o.get("tid") or "").strip()
                    t = allowed.get(tid)
                    if not t or tid in used_tids:
                        q = None; drop["target"] += 1
                    else:
                        if t["kind"] == "pt" and tid in PT: src = [kbmap[PT[tid]["chunk"]]]
                        elif t["kind"] == "fz" and tid in FZ: src = [{"id": tid, "text": FZ[tid]["text"]}]
                        else: src = [{"id": tid, "text": tbmap[tid]["text"]}] if tid in tbmap else []
                        if not anchor_of(q["basis"], src):   # answer not traceable to the target it claims
                            q = None; drop["anchor"] += 1
                        else:
                            q["tid"] = tid; q["ch"] = t["ch"]
                            q["kbRef"] = ([kb_label(kbmap[PT[tid]["chunk"]])] if t["kind"] == "pt" else
                                          [f"Fitzpatrick 표 · {FZ[tid]['head']}"] if t["kind"] == "fz" else [tb_label(tbmap[tid])])
                if q and b["kind"] == "novel":
                    q["novel"] = True
            if q and (is_repeat(q, hist, today) or is_repeat(q, [{"ch": x["ch"], "t": x["topic"], "a": x["options"][x["answer"]], "d": today} for x in qs + got], today)):
                q = None; drop["repeat"] += 1
            if not q or q["stem"] in seen or len(got) >= b["want"]:
                continue
            seen.add(q["stem"]); q["id"] = f"b{b['no']:02d}-{len(got):02d}"; got.append(q)
            if q.get("tid"): used_tids.add(q["tid"])
        for x in drop: drops[x] += drop[x]
        b["got"] = len(got)
        report.append(f"{b['out']}: {len(got)}/{b['want']} ({b['kind']})" + (f"  dropped {drop}" if any(drop.values()) else ""))
        qs += got
    by_ch = {}
    for q in qs:
        by_ch[str(q["ch"])] = by_ch.get(str(q["ch"]), 0) + 1
    short = plan["n"] - len(qs)
    missing = {}
    for c, n in sorted(plan["plan"].items(), key=lambda x: int(x[0])):
        m = min(n - by_ch.get(c, 0), short - sum(missing.values()))
        if m > 0: missing[c] = m
    print("\n".join(report))
    print(f"total {len(qs)}/{plan['n']}; missing by chapter: {missing}; dropped {drops}")

    if not a.final:
        if missing and not plan.get("refill"):
            parts = [{"ch": int(c), "n": n} for c, n in missing.items()]
            taken = set(plan.get("taken", [])) | used_tids
            kterms = kcov_terms(Klist)
            TBW = {}
            for wid, w in tbmap.items():
                TBW.setdefault(re.match(r"\d+", wid).group(), []).append(w)
            tg = []
            for p in parts:
                c = str(p["ch"])
                tg += pick_targets(p["ch"], p["n"], "regular", ctx["P"].get(c, []), TBW.get(c, []), st, today,
                                   random.Random(f"refill:{plan['id']}:{c}"), taken, kterms, ctx["FZK"].get(c, []))
            ctx["hist"] = hist + [{"ch": q["ch"], "t": q["topic"], "a": q["options"][q["answer"]], "d": today} for q in qs]
            intro = "\n이전 묶음에서 일부 문항이 빠져서 보충하는 묶음이다.\n"
            prompt = target_prompt(tg, ctx, "regular", intro)
            prompt += f"\n\n결과를 work/out/refill.jsonl 파일에 JSON Lines로 저장한다(UTF-8, 한 줄에 객체 하나).\n"
            (W / "refill.md").write_text(prompt)
            plan["refill"] = {"no": 99, "kind": "text", "parts": parts, "targets": tg, "want": len(tg), "chs": [p["ch"] for p in parts],
                              "file": "work/refill.md", "out": "work/out/refill.jsonl"}
            (W / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
            print("REFILL NEEDED: work/refill.md")
            sys.exit(3)
        print("OK — run with --final")
        return

    if len(qs) < plan["n"] * 0.6:
        sys.exit(f"only {len(qs)} questions — not publishing")
    qs.sort(key=lambda q: (q["ch"], q["id"]))
    random.Random("order:" + plan["id"]).shuffle(qs)   # 단원 순서 대신 섞어서 낸다(회차 id로 고정된 순서)
    idx_p = ROOT / "data" / "exams" / "index.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {"exams": []}
    taken = {e["id"] for e in idx["exams"]}
    if plan["id"] in taken and plan["id"].count("-") == 3:   # another run published this number first
        k = int(plan["id"].rsplit("-", 1)[1])
        while f"{plan['date']}-{k}" in taken: k += 1
        plan["id"] = f"{plan['date']}-{k}"
        (W / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
        print("number taken — publishing as", plan["id"])
    d = datetime.date.fromisoformat(plan["date"])
    sset = plan["id"].rsplit("-", 1)[-1] if plan["id"].count("-") == 3 else ""
    title = f"{d.month}월 {d.day}일 ({'월화수목금토일'[d.weekday()]})" + (f" {sset}회차" if sset else "")
    counts = {"photo": sum(1 for q in qs if q.get("srcKid") or q.get("figId")), "novel": sum(1 for q in qs if q.get("novel"))}
    counts["text"] = len(qs) - counts["photo"] - counts["novel"]
    exam = {"v": 1, "id": plan["id"], "date": plan["date"], "title": title, "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "plan": plan["plan"], "counts": counts, "questions": qs}
    for q in qs:   # textbook photos are published (with the site key) only when a question uses them
        for nm in (q.get("imgs") or []) if q.get("figId") else []:
            dst = ROOT / "data" / "img" / (nm + ".enc")
            if not dst.exists():
                dst.write_bytes(C.enc_bytes(C.dec_bytes((ROOT / "secure" / "figs" / (nm + ".enc")).read_bytes())))
    C.enc_json(exam, ROOT / "data" / "exams" / f"{plan['id']}.enc")
    idx["exams"] = [e for e in idx["exams"] if e["id"] != plan["id"]] + [{"id": plan["id"], "date": plan["date"], "n": len(qs), "file": f"data/exams/{plan['id']}.enc"}]
    idx["exams"].sort(key=lambda e: e["id"], reverse=True)
    idx["updated"] = exam["created"]
    idx_p.write_text(json.dumps(idx, ensure_ascii=False, indent=1))
    record(st, qs, PT, today)
    C.enc_json(st, ROOT / "secure" / "state.enc")
    print(f"published {plan['id']}: {len(qs)} questions {counts}")


def record(st, qs, PT, today):
    """Remember what was asked so later sets move on to other facts."""
    pu, plast, pask = st.setdefault("photoUse", {}), st.setdefault("photoLast", {}), st.setdefault("photoAsk", {})
    ptu, ptl, grp = st.setdefault("ptUse", {}), st.setdefault("ptLast", {}), st.setdefault("grpLast", {})
    tbu, tbl, tba = st.setdefault("tbUse", {}), st.setdefault("tbLast", {}), st.setdefault("tbAsked", {})
    hist = st.setdefault("hist", [])
    for q in qs:
        ans = q["options"][q["answer"]][:60]
        line = f"{q['topic']} → {ans}"
        if q.get("srcKid"):
            s = q["srcKid"]; pu[s] = pu.get(s, 0) + 1; plast[s] = today
            pask[s] = (pask.get(s, []) + [line])[-6:]
        if q.get("figId"):
            fu, fl, fa = st.setdefault("figUse", {}), st.setdefault("figLast", {}), st.setdefault("figAsk", {})
            s = q["figId"]; fu[s] = fu.get(s, 0) + 1; fl[s] = today
            fa[s] = (fa.get(s, []) + [line])[-6:]
        t = q.get("tid")
        if t and t in PT:
            ptu[t] = ptu.get(t, 0) + 1; ptl[t] = today; grp[PT[t]["grp"]] = today
        elif t and re.fullmatch(r"\d+z\d+", t):
            fu, fl, fa = st.setdefault("fzUse", {}), st.setdefault("fzLast", {}), st.setdefault("fzAsked", {})
            fu[t] = fu.get(t, 0) + 1; fl[t] = today; fa[t] = (fa.get(t, []) + [line])[-12:]
        elif t:
            tbu[t] = tbu.get(t, 0) + 1; tbl[t] = today
            tba[t] = (tba.get(t, []) + [line])[-12:]
        hist.append({"d": today, "ch": q["ch"], "t": q["topic"], "a": ans})
    cut = (datetime.date.fromisoformat(today) - datetime.timedelta(days=60)).isoformat()
    st["hist"] = [h for h in hist if h.get("d", "") >= cut][-6000:]
    st["topics"] = (st.get("topics", []) + [{"date": today, "ch": q["ch"], "topic": q["topic"]} for q in qs])[-1500:]


if __name__ == "__main__":
    main()
