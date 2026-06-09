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
    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]

    # 5월~6월 데이터를 무조건 잡기 위한 테스트 날짜 조건
    start_day = "20260515"
    end_day = "20260522"
    start_dt = "202605100000"
    end_dt = "202606092359"

    api_configs = [
        {
            "name": "발주계획-용역",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc",
            "params": f"&insttInqryBgnDt={start_day}&insttInqryEndDt={end_day}"
        },
        {
            "name": "입찰공고-용역",
            "url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        },
        {
            "name": "사전규격-용역",
            "url": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServcPPSSrch",
            "params": f"&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}"
        }
    ]

    collected_items = []

    for api in api_configs:
        full_url = f"{api['url']}?serviceKey={pure_key}&type=json&pageNo=1&numOfRows=100{api['params']}"
        print(f"\n📡 [{api['name']}] 호출 시도 중...")

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

                print(f"📥 [{api['name']}] 데이터 수신 성공! 수신된 총 로우 데이터 수: {len(items)}건")

                # 변수 검증용 대문자 로그 샘플 출력
                if items:
                    print(f"🔍 [{api['name']}] 대문자 필드 데이터 분석 샘플 (상위 2건):")
                    for idx, sample in enumerate(items[:2]):
                        print(
                            f"   ↳ 샘플[{idx}]: BID_PBLANC_NM='{sample.get('BID_PBLANC_NM')}', PRCURE_GOODS_NM='{sample.get('PRCURE_GOODS_NM')}', ORDER_PLAN_NM='{sample.get('ORDER_PLAN_NM')}'")

                for item in items:
                    # ⭐ 조달청 JSON 실서버 규격인 대문자 필드명으로 전면 교체!
                    title = item.get('BID_PBLANC_NM') or item.get('PRCURE_GOODS_NM') or item.get(
                        'ORDER_PLAN_NM') or item.get('BID_NTCE_NM') or ""
                    link = item.get('BID_NTCE_DTL_URL') or "https://www.g2b.go.kr"
                    org = item.get('NTCE_INSTT_NM') or item.get('DMINSTT_NM') or item.get(
                        'ORDER_PLAN_INSTT_NM') or "공공기관"
                    date_val = item.get('NTCE_DT') or item.get('RGST_DT') or item.get(
                        'ORDER_PLAN_RGST_DT') or datetime.now().strftime('%Y-%m-%d')

                    if not title:
                        continue

                    # 키워드 검사
                    if any(kw in title for kw in keywords):
                        print(f"🎯 키워드 적중 발견! -> [{api['name']}] {title} ({org})")
                        collected_items.append({
                            "category": api['name'], "title": title, "org": org, "link": link, "date": date_val
                        })

        except Exception as e:
            print(f"🚨 [{api['name']}] 처리 중 오류 발생: {e}")

    return collected_items


def send_alerts(items):
    if not items:
        print("\n🏁 최종 결과: 키워드 필터링을 통과한 데이터가 없습니다.")
        return

    date_str = datetime.now().strftime('%m/%d')
    print(f"\n📢 알림 발송을 시작합니다! (총 {len(items)}건)")

    # Teams 알림
    if TEAMS_WEBHOOK:
        import requests
        teams_text = f"### 🏛️ [{date_str}] 나라장터 인프라 실시간 브리핑\n\n"
        for item in items:
            teams_text += f"**[{item['category']}]** [{item['title']}]({item['link']})<br>└ *발주처: {item['org']} / 일시: {item['date']}*\n\n"
        payload = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "body": [{"type": "TextBlock", "text": teams_text, "wrap": True}],
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.4"
                }
            }]
        }
        try:
            requests.post(TEAMS_WEBHOOK, json=payload, timeout=10); print("✅ 팀즈 전송 성공")
        except:
            print("❌ 팀즈 전송 실패")

    # Slack 알림
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

    # 네이버 메일 전송
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
    print(f"\n====================================\n검색 완료: 최종 {len(found_items)}건 검출됨")
    send_alerts(found_items)