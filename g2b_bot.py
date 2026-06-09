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


def get_g2b_data():
    print("나라장터 전방위 통합 감시 로봇 구동 중...")

    if not API_KEY:
        print("❌ 에러: DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return []

    pure_key = API_KEY.strip()
    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]

    # 5월~6월 테스트 날짜
    start_dt = "202605100000"
    end_dt = "202606092359"

    api_configs = [
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
        full_url = f"{api['url']}?serviceKey={pure_key}&type=json&pageNo=1&numOfRows=50{api['params']}"
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

                print(f"📥 [{api['name']}] 데이터 수신 성공 (수신 데이터 수: {len(items)}건)")

                if items and len(items) > 0:
                    sample_item = items[0]
                    print(f"🚨 [구조 해부] 조달청 서버가 보낸 실제 JSON Key 목록 전체:")
                    # 넘어온 데이터의 모든 Key 구조를 강제 출력
                    print(f"   ↳ {list(sample_item.keys())}")

                    # 샘플 데이터의 원본을 200자만 강제 출력하여 눈으로 확인
                    print(f"   ↳ 데이터 실제 값 일부: {str(sample_item)[:200]}")

                # 방어막 매핑 - 대소문자 무관하게 걸릴 수 있도록 다중 가드 배치
                for item in items:
                    title = (
                            item.get('bidPblancNm') or item.get('BID_PBLANC_NM') or
                            item.get('prcureGoodsNm') or item.get('PRCURE_GOODS_NM') or
                            item.get('bidNtceNm') or item.get('BID_NTCE_NM') or ""
                    )
                    link = item.get('bidNtceDtlUrl') or item.get('BID_NTCE_DTL_URL') or "https://www.g2b.go.kr"
                    org = item.get('ntceInsttNm') or item.get('NTCE_INSTT_NM') or "공공기관"
                    date_val = item.get('ntceDt') or item.get('NTCE_DT') or datetime.now().strftime('%Y-%m-%d')

                    if any(kw in str(title) for kw in keywords):
                        print(f"🎯 키워드 적중! -> {title}")
                        collected_items.append({
                            "category": api['name'], "title": title, "org": org, "link": link, "date": date_val
                        })

        except Exception as e:
            print(f"🚨 [{api['name']}] 처리 중 시스템 오류: {e}")

    return collected_items


if __name__ == "__main__":
    found_items = get_g2b_data()
    print(f"\n====================================\n검색 완료: 최종 {len(found_items)}건 검출됨")