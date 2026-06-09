import os
import requests
import smtplib
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr

# 환경 변수 및 GitHub Secrets 로드
API_KEY = os.environ.get('DATA_GO_KR_API_KEY')
TEAMS_WEBHOOK = os.environ.get('TEAMS_WEBHOOK_URL')
NAVER_EMAIL = os.environ.get('NAVER_EMAIL')
NAVER_PASSWORD = os.environ.get('NAVER_PASSWORD')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')


def get_g2b_data():
    print("나라장터 전방위 통합 감시 로봇 구동 중...")

    if not API_KEY:
        print("❌ 에러: DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return []

    # 검색할 핵심 키워드 리스트
    keywords = ["플랜티넷", "오피스가드", "정보보호 바우처", "유해사이트"]

    # 공공데이터포털 조달청 API 주소 정의
    # 과부하 방지를 위해 numOfRows를 999에서 100으로 줄임
    api_types = {
        "발주계획": "http://apis.data.go.kr/1230000/OrderPlanInfoService02/getOrderPlanListInfoPPSSrch",
        "사전규격": "http://apis.data.go.kr/1230000/HrcspatBsisBizInfoService03/getHrcspatBsisBizListInfoPPSSrch",
        "입찰공고-용역": "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch",
        "입찰공고-물품": "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch"
    }

    # 날짜 세팅 (최근 30일치 데이터 조회)
    end_dt = datetime.now().strftime('%Y%m%d%H%M')
    start_dt = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d%H%M')

    collected_items = []

    for name, base_url in api_types.items():
        # ⭐ 핵심 해결책: requests가 키를 변조하지 못하도록 URL 뒤에 생자(Raw)로 붙여버립니다.
        full_url = f"{base_url}?serviceKey={API_KEY}&type=json&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}&pageNo=1&numOfRows=100"

        try:
            # 주소 자체에 키가 있으므로 params 옵션을 쓰지 않고 그대로 요청합니다.
            res = requests.get(full_url, timeout=15)

            if res.status_code != 200:
                print(f"⚠️ [{name}] 서버 응답 이상 (Status Code: {res.status_code})")
                continue

            data = res.json()
            body = data.get('response', {}).get('body', {})
            items = body.get('items', [])

            if not items:
                continue

            # 키워드 필터링
            for item in items:
                # API 종류별로 제목 필드명이 다름에 따른 처리
                title = item.get('orderPlanNm') or item.get('bsisBizNm') or item.get('bidNtceNm') or ""
                link = item.get('bidNtceDtlUrl') or "https://www.g2b.go.kr"
                org = item.get('dminsttNm') or item.get('ntceInsttNm') or "공공기관"

                # 키워드가 제목에 포함되어 있는지 확인
                if any(kw in title for kw in keywords):
                    collected_items.append({
                        "category": name,
                        "title": title,
                        "org": org,
                        "link": link,
                        "date": item.get('ntceDt') or item.get('rgstDt') or datetime.now().strftime('%Y-%m-%d')
                    })
        except Exception as e:
            print(f"⚠️ [{name}] 데이터 처리 중 건너뜀 원인: {e}")
            continue

    return collected_items


def send_alerts(items):
    if not items:
        print("검색된 신규 공고가 없어 알림 발송을 생략합니다.")
        return

    date_str = datetime.now().strftime('%m/%d')

    # 1. 팀즈(Teams) 마크다운 본문 작성
    teams_text = f"### 🏛️ [{date_str}] 나라장터 보안 검색 실시간 브리핑\n\n"
    for item in items:
        teams_text += f"**[{item['category']}]** [{item['title']}]({item['link']})<br>└ *발주처: {item['org']} / 일시: {item['date']}*\n\n"

    # 팀즈 전송
    if TEAMS_WEBHOOK:
        payload = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "body": [{"type": "TextBlock", "text": teams_text, "wrap": True}],
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4"
                }
            }]
        }
        try:
            requests.post(TEAMS_WEBHOOK, data=json.dumps(payload), headers={'Content-Type': 'application/json'},
                          timeout=10)
            print("✅ 팀즈 알림 전송 완료")
        except Exception as e:
            print(f"❌ 팀즈 전송 에러: {e}")

    # 2. 슬랙(Slack) 전송
    if SLACK_TOKEN and SLACK_CHANNEL:
        slack_text = f"🏛️ *[{date_str}] 나라장터 보안 검색 결과*\n\n"
        for item in items:
            slack_text += f"• *[{item['category']}]* <{item['link']}|{item['title']}> ({item['org']})\n"

        try:
            requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                json={"channel": SLACK_CHANNEL, "text": slack_text},
                timeout=10
            )
            print("✅ 슬랙 알림 전송 완료")
        except Exception as e:
            print(f"❌ 슬랙 전송 에러: {e}")

    # 3. 네이버 메일 전송
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        msg['Subject'] = f"[{date_str}] 나라장터 보안 통합 공고 리포트"
        msg['From'] = formataddr((str(Header('나라장터 봇', 'utf-8')), NAVER_EMAIL))
        msg['To'] = NAVER_EMAIL  # 일단 수신인도 본인으로 설정

        html_content = f"<h2>🏛️ 나라장터 검색 브리핑 ({date_str})</h2><hr><ul>"
        for item in items:
            html_content += f"<li><b>[{item['category']}]</b> <a href='{item['link']}'>{item['title']}</a><br>발주: {item['org']} | 날짜: {item['date']}</li><br>"
        html_content += "</ul>"

        msg.attach(MIMEText(html_content, 'html'))
        try:
            with smtplib.SMTP_SSL("smtp.naver.com", 465) as server:
                server.login(NAVER_EMAIL, NAVER_PASSWORD)
                server.sendmail(NAVER_EMAIL, [NAVER_EMAIL], msg.as_string())
            print("✅ 네이버 메일 발송 완료")
        except Exception as e:
            print(f"❌ 메일 전송 에러: {e}")


if __name__ == "__main__":
    found_items = get_g2b_data()
    print(f"검색 완료: 신규 {len(found_items)}건 발견")
    send_alerts(found_items)