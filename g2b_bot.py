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

                # 데이터가 있을 경우 변수 분석을 위해 상위 3개만 샘플로 로그 출력
                if items:
                    print(f"🔍 [{api['name']}] 데이터 필드 분석 샘플 (상위 3건):")
                    for idx, sample in enumerate(items[:3]):
                        print(
                            f"   ↳ 샘플[{idx}]: 공고명(bidPblancNm)='{sample.get('bidPblancNm')}', 품명(prcureGoodsNm)='{sample.get('prcureGoodsNm')}', 계획명(orderPlanNm)='{sample.get('orderPlanNm')}'")

                for item in items:
                    # ⭐ 명세서 기반 진짜 변수명 매핑 파이프라인 수립
                    title = item.get('bidPblancNm') or item.get('prcureGoodsNm') or item.get('orderPlanNm') or item.get(
                        'bidNtceNm') or ""
                    link = item.get('bidNtceDtlUrl') or "https://www.g2b.go.kr"
                    org = item.get('dminsttNm') or item.get('ntceInsttNm') or item.get('orderPlanInsttNm') or "공공기관"
                    date_val = item.get('ntceDt') or item.get('rgstDt') or item.get(
                        'orderPlanRgstDt') or datetime.now().strftime('%Y-%m-%d')

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


if __name__ == "__main__":
    found_items = get_g2b_data()
    print(f"\n====================================\n검색 완료: 최종 {len(found_items)}건 검출됨")
    send_alerts(found_items)