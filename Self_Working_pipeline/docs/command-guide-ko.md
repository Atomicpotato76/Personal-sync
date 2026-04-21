# Hermes Pipeline Command Guide

`Self_Working_pipeline`를 나중에 다시 열어도 바로 따라갈 수 있게
자주 쓰는 명령만 순서대로 정리한 문서입니다.

## 1. 먼저 폴더 이동

```powershell
cd C:\Users\skyhu\Documents\AI_projects\Self_Working_pipeline
```

가장 안전한 실행 방식은 아래처럼 `python -m apps.cli.main` 뒤에
실제 명령을 붙여서 실행하는 형태입니다.

```powershell
python -m apps.cli.main plan --request-file .\proposal.md
python -m apps.cli.main status 123abc456def
python -m apps.cli.main directions 123abc456def
```

`hermes-pipeline ...`가 잡히면 그걸 써도 되지만,
안 될 때는 항상 `python -m apps.cli.main ...`를 쓰면 됩니다.

중요:
`<command>` 같은 표기는 설명용 자리표시자일 뿐이고,
PowerShell에 그대로 입력하면 안 됩니다.

## 2. 새 작업 시작

### 짧은 문장으로 시작

```powershell
python -m apps.cli.main plan "만들고 싶은 작업 설명"
```

### 제안서 `.md` 파일로 시작

```powershell
python -m apps.cli.main plan --request-file .\proposal.md
```

또는 파일 경로를 바로 넣어도 됩니다.

```powershell
python -m apps.cli.main plan .\proposal.md
```

참고:
제안서가 너무 길면 내부에서 자동으로 핵심만 추린 축약본을 만들어
플래너에 넘깁니다. 원본 파일 내용 자체가 바뀌는 것은 아닙니다.

출력에서 꼭 확인할 값은 아래 2개입니다.

- `run_id`
- `plan_path`

이후 명령은 전부 `run_id`를 기준으로 움직입니다.

## 3. 현재 상태 보기

한 번만 보기:

```powershell
python -m apps.cli.main status <run_id>
```

예시:

```powershell
python -m apps.cli.main status 123abc456def
```

쉬운말 요약만 보기:

```powershell
python -m apps.cli.main summary <run_id>
```

같은 명령 프롬프트 창에서 계속 새로고침하며 보기:

```powershell
python -m apps.cli.main watch <run_id>
```

예시:

```powershell
python -m apps.cli.main watch 123abc456def
```

중지는 `Ctrl+C`입니다.

## 4. 다음 진행 방향 저장

### 직접 문장으로 저장

```powershell
python -m apps.cli.main feedback <run_id> "다음 단계에서는 사용법을 더 쉽게"
```

### `.md` 파일로 저장

```powershell
python -m apps.cli.main feedback <run_id> --comment-file .\next-direction.md
```

이 내용은 현재 계획에 "추가된 사항"으로 기록되고,
계획서 버전도 새로 저장됩니다.

## 5. 승인하기

### 계획 시작 승인

```powershell
python -m apps.cli.main approve <run_id> --stage plan
```

### 중간 체크포인트 승인

```powershell
python -m apps.cli.main approve <run_id> --stage checkpoint
```

### 최종 패키징 전 승인

```powershell
python -m apps.cli.main approve <run_id> --stage merge
```

승인 메모를 직접 적고 싶으면:

```powershell
python -m apps.cli.main approve <run_id> --stage checkpoint "다음은 UI보다 안정성 우선"
```

승인 메모를 `.md` 파일로 넣고 싶으면:

```powershell
python -m apps.cli.main approve <run_id> --stage checkpoint --comment-file .\approval-notes.md
```

## 6. 다음 단계 실행

승인 후 다음 멈춤 지점까지 진행:

```powershell
python -m apps.cli.main run <run_id>
```

이 명령은 끝까지 무한 실행되는 구조가 아닙니다.
다음 승인 지점이나 테스트 지점까지 가면 멈춥니다.

## 7. 자동 저장된 방향 제안 보기

수정이 끝나거나 멈춤 포인트에 도달하면
"다음엔 어떤 방향으로 가면 좋은지"를 자동으로 저장합니다.

최신 방향 제안만 보기:

```powershell
python -m apps.cli.main directions <run_id>
```

`status`와 `watch`에도 최신 방향 제안이 같이 나옵니다.

## 8. 작업물 저장 위치 보기

현재 런의 주요 경로를 바로 확인:

```powershell
python -m apps.cli.main artifacts <run_id>
```

주요 저장 위치는 아래와 같습니다.

### 계획서

- 현재 계획 JSON: `plans/<run_id>/plan_bundle.json`
- 사람이 읽는 계획 요약: `plans/<run_id>/summary.md`
- 버전별 계획서: `plans/<run_id>/versions/`

### 방향 제안

- 최신 방향 제안 JSON: `plans/<run_id>/directions/latest_direction.json`
- 최신 방향 제안 MD: `plans/<run_id>/directions/latest_direction.md`
- 누적 방향 기록: `plans/<run_id>/directions/direction_*.json`

### 실제 작업물

- 생성된 작업 폴더: `outputs/<run_id>/workspace/`
- 리서치 마크다운 리포트: `outputs/<run_id>/workspace/reports/`
- 리서치 근거 JSON: `outputs/<run_id>/workspace/research_evidence/`
- 실행 결과 로그: `outputs/<run_id>/executions/`
- 리뷰 결과: `outputs/<run_id>/reviews/`
- 테스트 로그와 리포트: `outputs/<run_id>/tests/`
- 최종 패키지와 매니페스트: `outputs/<run_id>/package/`

Research 모드에서는 `research_evidence/*.json` 파일이 생성되고 검증됩니다.

## 9. 기본 점검

시크릿 노출 같은 기본 점검:

```powershell
python -m apps.cli.main doctor
```

## 10. 가장 자주 쓰는 흐름

### 제안서 파일로 시작해서 진행

```powershell
python -m apps.cli.main plan --request-file .\proposal.md
python -m apps.cli.main approve <run_id> --stage plan
python -m apps.cli.main run <run_id>
python -m apps.cli.main status <run_id>
python -m apps.cli.main directions <run_id>
```

### Research 모드 최소 실행 예시

```powershell
$env:PIPELINE_MODE="research"
python -m apps.cli.main plan --request-file .\proposal.md
python -m apps.cli.main approve <run-id> --stage plan
python -m apps.cli.main run <run-id>
```

### 방향 수정 후 다음 단계 진행

```powershell
python -m apps.cli.main feedback <run_id> --comment-file .\next-direction.md
python -m apps.cli.main approve <run_id> --stage checkpoint
python -m apps.cli.main run <run_id>
```

### 마지막 마무리

```powershell
python -m apps.cli.main approve <run_id> --stage merge
python -m apps.cli.main run <run_id>
python -m apps.cli.main artifacts <run_id>
```

## 11. 기억할 핵심

- 시작은 `plan`
- 제안서는 문자열이나 `.md` 파일 둘 다 가능
- 방향 수정도 문자열이나 `.md` 파일 둘 다 가능
- 승인 후 `run`
- 진행 상황은 `status` 또는 `watch`
- 방향 제안은 `directions`
- 결과물 위치는 `artifacts`
