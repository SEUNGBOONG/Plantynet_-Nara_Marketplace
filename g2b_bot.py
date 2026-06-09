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

    # 확실한 조회를 위한 고정 날짜 설정
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
                status_code = response.getcode()
                response_body = response.read().decode('utf-8')

                print(f"📥 [{api['name']}] 응답 도착 (상태코드: {status_code})")

                # 조달청 에러코드(`NORMAL_SERVICE`가 아닌 경우)가 텍스트에 포함되어 있는지 강제 검사
                if "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in response_body or "인증되지 않은" in response_body:
                    print(f"❌ [{api['name']}] 서버 거절 사유: 공공데이터포털에 등록되지 않은 키이거나 동기화 실패 상태입니다.")
                    print(f"💬 [서버 메세지]: {response_body}")
                    continue

                if "INVALID_REQUEST_PARAMETER_ERROR" in response_body:
                    print(f"❌ [{api['name']}] 서버 거절 사유: 파라미터 규칙 요건 에러(날짜 서식 등 오류).")
                    print(f"💬 [서버 메세지]: {response_body}")
                    continue

                try:
                    data = json.loads(response_body)
                except Exception as json_err:
                    print(f"⚠️ [{api['name']}] JSON 변환 실패. (정부 서버가 XML 에러를 뱉었을 가능성 높음)")
                    print(f"💬 [서버 원본 내용]: {response_body[:400]}")
                    continue

                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                if isinstance(items, dict):
                    items = [items]

                print(f"📊 [{api['name']}] 받아온 전체 데이터 수: {len(items)}건")

                for item in items:
                    title = item.get('orderPlanNm') or item.get('bidNtceNm') or item.get('prcureGoodsNm') or item.get(
                        'bsisBizNm') or ""
                    link = item.get('bidNtceDtlUrl') or "https://www.g2b.go.kr"
                    org = item.get('dminsttNm') or item.get('ntceInsttNm') or "공공기관"
                    date_val = item.get('ntceDt') or item.get('rgstDt') or item.get(
                        'orderPlanRgstDt') or datetime.now().strftime('%Y-%m-%d')

                    if any(kw in title for kw in keywords):
                        print(f"🎯 키워드 적중! -> {title}")
                        collected_items.append({
                            "category": api['name'], "title": title, "org": org, "link": link, "date": date_val
                        })

        except urllib.error.HTTPError as e:
            err_detail = e.read().decode('utf-8')
            print(f"💥 [{api['name']}] 통신망 HTTP Error {e.code} 발생!")
            print(f"🔍 [상세 원인]: {err_detail[:300]}")
        except Exception as e:
            print(f"🚨 [{api['name']}] 예측하지 못한 시스템 예외 발생: {e}")

    return collected_items


def send_alerts(items):
    if not items:
        print("\n🏁 디버깅 결과: 매칭되는 데이터가 최종 단계에서 0건으로 확인되었습니다.")
        return

    date_str = datetime.now().strftime('%m/%d')
    print(f"\n📢 알림 전송 프로세스 시작... (총 {len(items)}건 발송 예정)")

    # Teams 알림
    if TEAMS_WEBHOOK:
        import requests
        teams_text = f"### 🏛️ [{date_str}] 나라장터 인프라 실시간 브리핑 (디버깅 검증)\n\n"
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
            requests.post(TEAMS_WEBHOOK, json=payload, timeout=10); print("✅ 팀즈 전송 시도 완료")
        except Exception as e:
            print(f"❌ 팀즈 전송 실패: {e}")


if __name__ == "__main__":
    found_items = get_g2b_data()
    print(f"\n====================================\n검색 완료: 최종 {len(found_items)}건 검출됨")
    send_alerts(found_items)