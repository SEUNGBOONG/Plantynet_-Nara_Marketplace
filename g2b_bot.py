import os
import smtplib
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
import urllib.request
import urllib.error

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

    # 설정하신 핵심 모니터링 키워드 4개
    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]

    # 💡 실전용 자동 스케줄링 세팅: 언제 돌려도 항상 '최근 14일치'를 실시간 추적합니다.
    end_dt = datetime.now().strftime('%Y%m%d%H%M')
    start_dt = (datetime.now() - timedelta(days=14)).strftime('%Y%m%d%H%M')

    end_day = datetime.now().strftime('%Y%m%d')
    start_day = (datetime.now() - timedelta(days=14)).strftime('%Y%m%d')

    api_configs = [
        # 1. 발주계획현황서비스 (용역)
        {
            "name": "발주계획-용역",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc",
            "params": f"&insttInqryBgnDt={start_day}&insttInqryEndDt={end_day}"
        },
        # 2. 입찰공고정보서비스 (용역)
        {
            "name": "입찰공고-용역",
            "url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        },
        # 3. 사전규격 (용역)
        {
            "name": "사전규격-용역",
            "url": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServcPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        }
    ]

    collected_items = []

    for api in api_configs:
        full_url = f"{api['url']}?serviceKey={pure_key}&type=json&pageNo=1&numOfRows=100{api['params']}"

        try:
            req = urllib.request.Request(
                full_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )

            with urllib.request.urlopen(req, timeout=25) as response:
                response_body = response.read().decode('utf-8')
                data = json.loads(response_body)

                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                if isinstance(items, dict):
                    items = [items]
                elif not items:
                    continue

                for item in items:
                    # ⭐ 로그 분석을 통해 완벽하게 매핑한 진짜 실서버 변수명 파이프라인!
                    title = item.get('bidNtceNm') or item.get('prdctClsfcNoNm') or item.get('orderPlanNm') or ""

                    # 링크 추출 (사전규격은 링크를 주지 않으므로 기본 나라장터 주소로 헷지)
                    link = item.get('bidNtceDtlUrl') or item.get('bidNtceUrl') or "https://www.g2b.go.kr"

                    # 기관명 추출 (실수요기관 우선)
                    org = item.get('rlDminsttNm') or item.get('ntceInsttNm') or item.get('orderInsttNm') or "공공기관"

                    # 날짜 추출
                    date_val = item.get('bidNtceDt') or item.get('rcptDt') or item.get('rgstDt') or ""
                    if date_val:
                        date_val = date_val.split()[0]  # 날짜 뒤에 붙은 시간 지우고 깔끔하게 YYYY-MM-DD 화
                    else:
                        date_val = datetime.now().strftime('%Y-%m-%d')

                    if not title:
                        continue

                    # 4대 키워드 필터링 검사
                    if any(kw in title for kw in keywords):
                        print(f"🎯 실시간 키워드 적중! -> [{api['name']}] {title} ({org})")
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
        print("검색 완료: 신규 0건 발견 (최근 14일 내 키워드 일치 공고 없음)")
        return

    date_str = datetime.now().strftime('%m/%d')
    print(f"\n📢 [알림 가동] 총 {len(items)}건의 매칭 공고 알림을 전송합니다.")

    # 1. MS Teams 알림
    teams_text = f"### 🏛️ [{date_str}] 나라장터 인프라 실시간 감시 브리핑\n\n"
    for item in items:
        teams_text += f"**[{item['category']}]** [{item['title']}]({item['link']})\n└ *발주처: {item['org']} / 등록일: {item['date']}*\n\n"

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
            requests.post(TEAMS_WEBHOOK, json=payload, timeout=10)
        except:
            pass

    # 2. Slack 알림
    if SLACK_TOKEN and SLACK_CHANNEL:
        import requests
        slack_text = f"🏛️ *[{date_str}] 나라장터 핵심 감시 결과*\n\n"
        for item in items:
            slack_text += f"• *[{item['category']}]* <{item['link']}|{item['title']}> ({item['org']}) - {item['date']}\n"
        try:
            requests.post("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                          json={"channel": SLACK_CHANNEL, "text": slack_text}, timeout=10)
        except:
            pass

    # 3. 네이버 이메일 전송
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        msg['Subject'] = f"[{date_str}] 나라장터 매칭 공고 알림 리포트"
        msg['From'] = formataddr((str(Header('나라장터 감시봇', 'utf-8')), NAVER_EMAIL))
        msg['To'] = NAVER_EMAIL
        html_content = f"<h2>🏛️ 나라장터 인프라 매칭 공고 ({date_str})</h2><hr><ul>"
        for item in items:
            html_content += f"<li><b>[{item['category']}]</b> <a href='{item['link']}'>{item['title']}</a><br>발주기관: {item['org']} | 등록일자: {item['date']}</li><br>"
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
    print(f"\n====================================\n검색 완료: 최종 {len(found_items)}건 매칭 성공")
    send_alerts(found_items)