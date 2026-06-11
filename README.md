# Plantynet_-Nara_Marketplace

나라장터 **발주계획**을 키워드로 검색하고, 결과를 네이버 메일로 보내는 봇입니다.

## 필요한 API

공공데이터포털(data.go.kr)에서 아래 서비스 활용신청 후 인증키를 발급받으세요.

- **나라장터 발주계획현황서비스** (`OrderPlanSttusService`)

## 환경 변수

`.env.example`을 참고해 GitHub Secrets 또는 로컬 환경변수를 설정합니다.

| 변수 | 필수 | 설명 |
|------|------|------|
| `DATA_GO_KR_API_KEY` | O | 공공데이터포털 인증키 |
| `NAVER_EMAIL` | O | 수신/발신 네이버 메일 |
| `NAVER_PASSWORD` | O | 네이버 SMTP 앱 비밀번호 |
| `G2B_KEYWORDS` | X | 검색 키워드 (쉼표 구분, 기본: 스쿨넷,융합통신망,교육망,스마트기기) |
| `G2B_SEARCH_DAYS` | X | 게시일 조회 범위(일, 기본 40) |
| `G2B_ORDER_MONTHS_AHEAD` | X | 발주년월 미래 범위(월, 기본 12) |

## 로컬 실행

```powershell
pip install -r requirements.txt
$env:DATA_GO_KR_API_KEY="발급받은키"
$env:NAVER_EMAIL="your@naver.com"
$env:NAVER_PASSWORD="앱비밀번호"
py g2b_bot.py
```

## GitHub Actions

`main` 브랜치에 push 후, Actions 탭에서 **G2B Notice Checker** 워크플로를 수동 실행(`workflow_dispatch`)하거나 스케줄(한국 09/12/15/18시)에 따라 자동 실행됩니다.

## 조회 실패 시 확인사항

1. **발주계획현황서비스** 활용신청 및 승인 여부
2. 인증키가 디코딩/인코딩 키 중 올바른 형식인지
3. GitHub Secrets에 `DATA_GO_KR_API_KEY`, `NAVER_EMAIL`, `NAVER_PASSWORD` 등록 여부
4. 네이버 메일 **SMTP 사용** 및 **2단계 인증 + 앱 비밀번호** 설정 여부
