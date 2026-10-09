# 매일 회차 만들기 — 예약 작업이 따르는 절차

이 저장소는 피부과 전문의 1차 시험 대비 개인용 모의고사 웹앱(GitHub Pages)이다. 매일 새벽 예약 작업이 이 문서대로 100문항짜리 회차를 하나 만들어 올린다. 입력으로 받는 값은 세 가지다.

- `DD_PASS` — 암호화 비밀번호
- `SET` — 회차 번호(1 또는 2)
- 날짜 — 오늘(Asia/Seoul). `plan.py`가 알아서 KST 오늘 날짜를 쓴다.

`secure/`·`data/`의 `.enc` 파일은 전부 암호화돼 있다. 복호화한 내용(`work/`)은 절대 커밋하지 않는다(.gitignore에 있음).

## 1. 준비

```bash
python3 -c "import cryptography" 2>/dev/null || pip install -q cryptography --break-system-packages
export DD_PASS=...            # 예약 작업 지시문에 적힌 값
python3 tools/ddcrypt.py unpack
python3 tools/plan.py --set $SET
```

`work/plan.json`과 `work/batches/NN.md`(묶음별 출제 지시문, 보통 20개 안팎)가 생긴다. 사진 묶음에 필요한 기출 사진은 `work/img/`에 풀린다. 이미 오늘 같은 회차가 `data/exams/index.json`에 있으면 아무것도 하지 말고 끝낸다.

## 2. 문항 쓰기 (가장 중요)

`work/batches/` 안의 지시문 하나하나가 독립된 작업이다. 각 지시문을 끝까지 읽고 그대로 따라 문항을 써서, 지시문 끝에 적힌 `work/out/NN.jsonl`에 JSON Lines로 저장한다.

- 속도를 위해 Agent 도구로 하위 에이전트를 4–6개 동시에 띄워 묶음을 나눠 맡긴다. 하위 에이전트에게 줄 지시 예: "work/batches/05.md와 work/batches/06.md를 각각 끝까지 읽고 지시대로 문항을 써서 지정된 출력 파일에 저장해. 사진 묶음이면 지시문에 적힌 work/img/ 파일을 Read 도구로 직접 열어 보고 써. 정확성이 최우선이고, 확실하지 않은 사실은 출제하지 마. 다 쓰면 각 파일의 줄 수만 보고해."
- 한 줄에 객체 하나, 줄 수는 지시문이 정한 개수. 문자열 안 줄바꿈은 `\n`.
- 품질 기준: 피부과학 7판(대한피부과학회) 기준으로 정답이 하나만 성립하고, 보기 5개가 모두 같은 범주의 그럴듯한 것. 해설은 정답 근거와 주요 오답이 틀린 이유. 의심스러운 문항은 버리고 새로 쓴다.

## 3. 검사와 보충

```bash
python3 tools/assemble.py
```

- 종료 코드 3이면 빠진 문항이 있다는 뜻이다. `work/refill.md`를 읽고 그대로 써서 `work/out/refill.jsonl`에 저장한 뒤 다시 실행한다(한 번만).
- 모자란 채로라도 60문항 이상이면 발행할 수 있다.

## 4. 발행

```bash
python3 tools/assemble.py --final
tools/publish.sh "회차 $(date +%F)-$SET"
```

`publish.sh`가 다른 회차와 동시에 올리다 충돌하면 최신 상태 위에 다시 만들어 올린다. 마지막 출력이 `pushed`면 끝. 몇 분 안에 GitHub Pages 사이트에 반영된다.

## 5. 보고

한두 문장으로: 만든 회차 id, 문항 수(사진 변형/미출제/일반), 버린 문항이 있었으면 그 이유.
