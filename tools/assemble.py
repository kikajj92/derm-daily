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
from prompts import kb_label, anchor_of, n_chunks, pick_note_chunks, regular_prompt

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args()
    plan = json.loads((W / "plan.json").read_text())
    K = {k["id"]: k for k in json.loads((W / "src" / "kichul.json").read_text())}
    meta = json.loads((W / "src" / "meta.json").read_text())
    KB = json.loads((W / "src" / "kb.json").read_text())["ch"]
    kbmap = {x["id"]: x for c in KB.values() for x in c}
    qs, seen, report, unanchored = [], set(), [], 0
    batches = list(plan["batches"])
    if (W / "out" / "refill.jsonl").exists() and plan.get("refill"):
        batches.append(plan["refill"])
    for b in batches:
        objs = read_jsonl(ROOT / b["out"])
        chunks = [kbmap[i] for i in b.get("chunks", []) if i in kbmap]
        got, drop = [], 0
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
            else:
                q = normalize({**o, "figures": []}, b["chs"])
                if q and re.search(r"사진|그림", q["stem"]):
                    q = None
                if q and chunks:
                    hit = anchor_of(q["basis"], chunks)
                    if not hit:   # answer not traceable to the excerpts it was meant to come from
                        q = None; drop += 1
                    else:
                        q["kbRef"] = [kb_label(hit)]
                if q and b["kind"] == "novel":
                    q["novel"] = True
            if not q or q["stem"] in seen or len(got) >= b["want"]:
                continue
            seen.add(q["stem"]); q["id"] = f"b{b['no']:02d}-{len(got):02d}"; got.append(q)
        unanchored += drop
        if drop: report.append(f"  ↳ {drop} dropped: basis not found in excerpts")
        b["got"] = len(got)
        report.append(f"{b['out']}: {len(got)}/{b['want']} ({b['kind']})")
        qs += got
    by_ch = {}
    for q in qs:
        by_ch[str(q["ch"])] = by_ch.get(str(q["ch"]), 0) + 1
    missing = {c: n - by_ch.get(c, 0) for c, n in plan["plan"].items() if n - by_ch.get(c, 0) > 0}
    print("\n".join(report))
    print(f"total {len(qs)}/{plan['n']}; missing by chapter: {missing}; unanchored dropped: {unanchored}")

    if not a.final:
        if missing and not plan.get("refill"):
            parts = [{"ch": int(c), "n": n} for c, n in sorted(missing.items(), key=lambda x: int(x[0]))]
            want = sum(p["n"] for p in parts)
            CH = meta["chapters"]
            r = random.Random("refill:" + plan["id"])
            st = json.loads((W / "src" / "state.json").read_text()) if (W / "src" / "state.json").exists() else {}
            used = set(plan.get("used", []))
            chunks = []
            for p in parts:
                got = pick_note_chunks(KB, p["ch"], n_chunks(p["n"]), r, st.get("kbUse", {}), used)
                used |= {x["id"] for x in got}; chunks += got
            recent = [t for t in st.get("topics", []) if t.get("date", "") >= (datetime.date.fromisoformat(plan["date"]) - datetime.timedelta(days=21)).isoformat()]
            recent += [{"ch": q["ch"], "topic": q["topic"]} for q in qs]
            intro = "\n이전 묶음에서 일부 문항이 빠져서 보충하는 묶음이다. 오늘 이미 만든 주제(아래 '최근 며칠 이미 낸 주제'에 포함)와 겹치지 않게 한다.\n"
            prompt = regular_prompt(parts, chunks, list(K.values()), recent, lambda c: CH.get(str(c), f"Chapter {c}"), r, intro)
            prompt += f"\n\n결과를 work/out/refill.jsonl 파일에 JSON Lines로 저장한다(UTF-8, 한 줄에 객체 하나).\n"
            (W / "refill.md").write_text(prompt)
            plan["refill"] = {"no": 99, "kind": "text", "parts": parts, "want": want, "chs": [p["ch"] for p in parts], "chunks": [c["id"] for c in chunks],
                              "file": "work/refill.md", "out": "work/out/refill.jsonl"}
            (W / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
            print("REFILL NEEDED: work/refill.md")
            sys.exit(3)
        print("OK — run with --final")
        return

    if len(qs) < plan["n"] * 0.6:
        sys.exit(f"only {len(qs)} questions — not publishing")
    qs.sort(key=lambda q: (q["ch"], q["id"]))
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
    counts = {"photo": sum(1 for q in qs if q.get("srcKid")), "novel": sum(1 for q in qs if q.get("novel"))}
    counts["text"] = len(qs) - counts["photo"] - counts["novel"]
    exam = {"v": 1, "id": plan["id"], "date": plan["date"], "title": title, "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "plan": plan["plan"], "counts": counts, "questions": qs}
    C.enc_json(exam, ROOT / "data" / "exams" / f"{plan['id']}.enc")
    idx["exams"] = [e for e in idx["exams"] if e["id"] != plan["id"]] + [{"id": plan["id"], "date": plan["date"], "n": len(qs), "file": f"data/exams/{plan['id']}.enc"}]
    idx["exams"].sort(key=lambda e: e["id"], reverse=True)
    idx["updated"] = exam["created"]
    idx_p.write_text(json.dumps(idx, ensure_ascii=False, indent=1))
    st_p = W / "src" / "state.json"
    st = json.loads(st_p.read_text()) if st_p.exists() else {}
    pu, ku = st.setdefault("photoUse", {}), st.setdefault("kbUse", {})
    for q in qs:
        if q.get("srcKid"): pu[q["srcKid"]] = pu.get(q["srcKid"], 0) + 1
    for b in plan["batches"] + ([plan["refill"]] if plan.get("refill") else []):
        if b.get("got"):
            for cid in b.get("chunks", []): ku[cid] = ku.get(cid, 0) + 1
    st["topics"] = ([t for t in st.get("topics", []) if t.get("date") != plan["date"]] + [{"date": plan["date"], "ch": q["ch"], "topic": q["topic"]} for q in qs])[-1500:]
    C.enc_json(st, ROOT / "secure" / "state.enc")
    print(f"published {plan['id']}: {len(qs)} questions {counts}")


if __name__ == "__main__":
    main()
