import os
import requests
import smtplib
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from urllib.parse import unquote  # ⭐ 인증키 강제 디코딩용 모듈 추가

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

    # ⭐ 파이썬이 키를 자동 변환하는 것을 막기 위해 강제로 순수 raw 키로 해독
    # 인코딩/디코딩 키 어떤 걸 넣었어도 다 호환되도록 처리합니다.
    decoded_key = unquote(API_KEY)

    keywords = ["플랜티넷", "오피스가드", "정보보호 바우처", "유해사이트"]

    # 조달청 행정표준 실서버 표준 URL
    api_types = {
        "발주계획": "https://apis.data.go.kr/1230000/OrderPlanInfoService02/getOrderPlanListInfoPPSSrch",
        "사전규격": "https://apis.data.go.kr/1230000/HrcspatBsisBizInfoService03/getHrcspatBsisBizListInfoPPSSrch",
        "입찰공고-용역": "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch",
        "입찰공고-물품": "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch"
    }

    # 날짜 세팅 (안정적으로 최근 7일치만 조회)
    end_dt = datetime.now().strftime('%Y%m%d%H%M')
    start_dt = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d%H%M')

    collected_items = []

    for name, base_url in api_types.items():
        # ⭐ 파이썬 requests에 파라미터를 넘기지 않고, 미리 주소를 '문자열 그 자체'로 완성시켜 던짐
        # 과부하 방지를 위해 numOfRows=50으로 경량화
        full_url = f"{base_url}?serviceKey={decoded_key}&type=json&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}&pageNo=1&numOfRows=50"

        try:
            # 폰으로 주소창에 주소 직접 타이핑해서 들어가는 것과 똑같은 방식으로 요청
            res = requests.get(full_url, timeout=15)

            if res.status_code != 200:
                print(f"⚠️ [{name}] 서버 응답 오류 (Status Code: {res.status_code})")
                continue

            # 정부 서버가 간혹 에러를 JSON이 아닌 XML 텍스트로 보낼 때를 대비한 안전 장치
            try:
                data = res.json()
            except:
                print(f"⚠️ [{name}] 정부 서버가 이상한 데이터를 보냈습니다 (JSON 파싱 실패)")
                continue

            body = data.get('response', {}).get('body', {})
            items = body.get('items', [])

            if not items:
                continue

            for item in items:
                title = item.get('orderPlanNm') or item.get('bsisBizNm') or item.get('bidNtceNm') or ""
                link = item.get('bidNtceDtlUrl') or "https://www.g2b.go.kr"
                org = item.get('dminsttNm') or item.get('ntceInsttNm') or "공공기관"

                if any(kw in title for kw in keywords):
                    collected_items.append({
                        "category": name,
                        "title": title,
                        "org": org,
                        "link": link,
                        "date": item.get('ntceDt') or item.get('rgstDt') or datetime.now().strftime('%Y-%m-%d')
                    })
        except Exception as e:
            print(f"⚠️ [{name}] 통신 실패: {e}")
            continue

    return collected_items


def send_alerts(items):
    if not items:
        print("검색된 신규 공고가 없어 알림 발송을 생략합니다.")
        return

    date_str = datetime.now().strftime('%m/%d')

    # 1. 팀즈(Teams) 알림
    teams_text = f"### 🏛️ [{date_str}] 나라장터 보안 검색 실시간 브리핑\n\n"
    for item in items:
        teams_text += f"**[{item['category']}]** [{item['title']}]({item['link']})<br>└ *발주처: {item['org']} / 일시: {item['date']}*\n\n"

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

    # 2. 슬랙(Slack) 알림
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
        msg['To'] = NAVER_EMAIL

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