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

    # 인증키 공백 제거
    pure_key = API_KEY.strip()

    # 우리가 모니터링할 핵심 키워드 리스트
    keywords = ["플랜티넷", "오피스가드", "정보보호 바우처", "유해사이트"]

    # 검색 기간 설정 (최근 7일치)
    end_dt = datetime.now().strftime('%Y%m%d%H%M')
    start_dt = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d%H%M')

    # 단기 조회를 위한 단순 일자 서식 (발주계획용 YYYYMMDD)
    end_day = datetime.now().strftime('%Y%m%d')
    start_day = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')

    collected_items = []

    # 스크린샷 가이드라인 기반 3대 서비스 명세 정의
    # 가이드라인에 명시된 필수 오퍼레이션과 도메인을 1대1로 정확히 조립했습니다.
    api_configs = [
        # 1. 발주계획현황서비스 (image_518ff9.png 기준)
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
        # 2. 입찰공고정보서비스 (image_518f7e.png 기준)
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
        # 3. 사전규격 (image_518bfe.png 기준)
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
        # 각 서비스 규격에 맞는 명세 기반 전체 주소 바인딩
        full_url = f"{api['url']}?serviceKey={pure_key}&type=json&pageNo=1&numOfRows=50{api['params']}"

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
                    # XML 에러 메시지나 보안 차단 텍스트가 반환되었을 때 우회하기 위함
                    print(f"⚠️ [{api['name']}] 데이터 해석 불가 (JSON 형식이 아님). 첫 100자: {response_body[:100]}")
                    continue

                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                # 데이터가 리스트 형태가 아닌 딕셔너리로 1건만 감싸서 오는 케이스 방어 코드
                if isinstance(items, dict):
                    items = [items]
                elif not items:
                    continue

                for item in items:
                    # 가이드 명세 기반의 통합 변수 추출 파이프라인
                    title = item.get('orderPlanNm') or item.get('bidNtceNm') or item.get('prcureGoodsNm') or ""
                    link = item.get('bidNtceDtlUrl') or "https://www.g2b.go.kr"
                    org = item.get('dminsttNm') or item.get('ntceInsttNm') or item.get('public기관') or "공공기관"
                    date_val = item.get('ntceDt') or item.get('rgstDt') or item.get(
                        'orderPlanRgstDt') or datetime.now().strftime('%Y-%m-%d')

                    # 키워드가 제목에 포함되어 있는지 검사
                    if any(kw in title for kw in keywords):
                        collected_items.append({
                            "category": api['name'],
                            "title": title,
                            "org": org,
                            "link": link,
                            "date": date_val
                        })

        except urllib.error.HTTPError as e:
            print(f"❌ [{api['name']}] 호출 실패 (HTTP Error {e.code}) - 주소 혹은 허가 요건을 재확인하세요.")
            continue
        except Exception as e:
            print(f"⚠️ [{api['name']}] 기타 통신 예외 발생: {e}")
            continue

    return collected_items


def send_alerts(items):
    if not items:
        print("검색 완료: 신규 0건 발견")
        print("검색된 신규 공고가 없어 알림 발송을 생략합니다.")
        return

    date_str = datetime.now().strftime('%m/%d')

    # 1. MS Teams 알림 메커니즘
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

    # 2. Slack 알림 메커니즘
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

    # 3. 네이버 이메일 알림 메커니즘
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
    if found_items:
        print(f"검색 완료: 신규 {len(found_items)}건 발견")
    send_alerts(found_items)