import os
import smtplib
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
import urllib.request
from urllib.parse import unquote

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

    # 깃허브 시크릿 키 공백 제거 처리
    pure_key = API_KEY.strip()

    keywords = ["플랜티넷", "오피스가드", "정보보호 바우처", "유해사이트"]

    # ⭐ 스크린샷 화면에 명시된 End Point와 승인된 서비스 3개만 정확히 매핑!
    api_types = {
        "발주계획": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListInfoPPSSrch",
        "사전규격": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getHrcspSsstndrdListInfoPPSSrch",
        "입찰공고": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoPPSSrch"
    }

    # 검색 기간 설정 (최근 7일치)
    end_dt = datetime.now().strftime('%Y%m%d%H%M')
    start_dt = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d%H%M')

    collected_items = []

    for name, base_url in api_types.items():
        # 변조 없는 순수 인증키 문자열 결합 방식 사용
        full_url = f"{base_url}?serviceKey={pure_key}&type=json&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}&pageNo=1&numOfRows=50"

        try:
            req = urllib.request.Request(
                full_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )

            with urllib.request.urlopen(req, timeout=20) as response:
                response_body = response.read().decode('utf-8')

                try:
                    data = json.loads(response_body)
                except:
                    # 에러 메시지가 올 경우 출력용
                    print(f"⚠️ [{name}] 응답 데이터 변환 실패: {response_body[:200]}")
                    continue

                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                if not items:
                    continue

                for item in items:
                    # 각 API별 제목, 링크, 기관명 매핑 정밀 정제
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
            print(f"⚠️ [{name}] 호출 중 오류 발생: {e}")
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
        import requests
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
        except:
            pass

    # 2. 슬랙(Slack) 알림
    if SLACK_TOKEN and SLACK_CHANNEL:
        import requests
        slack_text = f"🏛️ *[{date_str}] 나라장터 보안 검색 결과*\n\n"
        for item in items:
            slack_text += f"• *[{item['category']}]* <{item['link']}|{item['title']}> ({item['org']})\n"
        try:
            requests.post("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                          json={"channel": SLACK_CHANNEL, "text": slack_text}, timeout=10)
        except:
            pass

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
        except:
            pass


if __name__ == "__main__":
    found_items = get_g2b_data()
    print(f"검색 완료: 신규 {len(found_items)}건 발견")
    send_alerts(found_items)