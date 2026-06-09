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

    pure_key = API_KEY.strip()

    # 등록된 키워드 4개
    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]

    # 💡 [테스트용 절대 좌표] 스크린샷에 나온 5월~6월 데이터를 무조건 잡기 위한 날짜 세팅
    # 발주계획용 (최대 7일 제한 방어를 위해 타깃 주간인 5월 15일 ~ 5월 22일로 정밀 타격)
    start_day = "20260515"
    end_day = "20260522"

    # 입찰공고 및 사전규격용 (12자리 필수 서식 형식)
    start_dt = "202605100000"
    end_dt = "202606092359"

    collected_items = []

    api_configs = [
        # 1. 발주계획현황서비스
        {
            "name": "발주계획-물품",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListThng",
            "params": f"&insttInqryBgnDt={start_day}&insttInqryEndDt={end_day}"
        },
        {
            "name": "발주계획-용역",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc",
            "params": f"&insttInqryBgnDt={start_day}&insttInqryEndDt={end_day}"
        },
        # 2. 입찰공고정보서비스
        {
            "name": "입찰공고-용역",
            "url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        },
        {
            "name": "입찰공고-물품",
            "url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        },
        # 3. 사전규격
        {
            "name": "사전규격-물품",
            "url": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoThngPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        },
        {
            "name": "사전규격-용역",
            "url": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServcPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        }
    ]

    for api in api_configs:
        full_url = f"{api['url']}?serviceKey={pure_key}&type=json&pageNo=1&numOfRows=100{api['params']}"

        try:
            req = urllib.request.Request(
                full_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )

            with urllib.request.urlopen(req, timeout=25) as response:
                response_body = response.read().decode('utf-8')

                try:
                    data = json.loads(response_body)
                except:
                    continue

                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                if isinstance(items, dict):
                    items = [items]
                elif not items:
                    continue

                for item in items:
                    # 데이터 매핑 필드 다각화
                    title = item.get('orderPlanNm') or item.get('bidNtceNm') or item.get('prcureGoodsNm') or item.get(
                        'bsisBizNm') or ""
                    link = item.get('bidNtceDtlUrl') or "https://www.g2b.go.kr"
                    org = item.get('dminsttNm') or item.get('ntceInsttNm') or "공공기관"
                    date_val = item.get('ntceDt') or item.get('rgstDt') or item.get(
                        'orderPlanRgstDt') or datetime.now().strftime('%Y-%m-%d')

                    if any(kw in title for kw in keywords):
                        collected_items.append({
                            "category": api['name'],
                            "title": title,
                            "org": org,
                            "link": link,
                            "date": date_val
                        })

        except Exception as e:
            continue

    return collected_items


def send_alerts(items):
    if not items:
        print("검색 완료: 신규 0건 발견")
        print("검색된 신규 공고가 없어 알림 발송을 생략합니다.")
        return

    date_str = datetime.now().strftime('%m/%d')

    # 1. 팀즈 알림
    teams_text = f"### 🏛️ [{date_str}] 나라장터 인프라 검색 실시간 브리핑\n\n"
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

    # 2. 슬랙 알림
    if SLACK_TOKEN and SLACK_CHANNEL:
        import requests
        slack_text = f"🏛️ *[{date_str}] 나라장터 검색 결과*\n\n"
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
        msg['Subject'] = f"[{date_str}] 나라장터 인프라 통합 공고 리포트"
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
    if found_items:
        print(f"검색 완료: 신규 {len(found_items)}건 발견")
    send_alerts(found_items)