import os
import smtplib
import json
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
import urllib.request
import urllib.parse
import subprocess

# 환경 변수 로드
API_KEY = os.environ.get('DATA_GO_KR_API_KEY')
TEAMS_WEBHOOK = os.environ.get('TEAMS_WEBHOOK_URL')
NAVER_EMAIL = os.environ.get('NAVER_EMAIL')
NAVER_PASSWORD = os.environ.get('NAVER_PASSWORD')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')

HISTORY_FILE = "last_g2b_data.txt"


def get_current_kst():
    return datetime.now(timezone(timedelta(hours=9)))


def get_g2b_data():
    kst_now = get_current_kst()
    print(f"🏛️ 나라장터 발주계획 검색 로봇 구동 중... (현재 한국 시간: {kst_now.strftime('%Y-%m-%d %H:%M')})")

    if not API_KEY:
        print("❌ 에러: DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return []

    pure_key = API_KEY.strip()
    decoded_key = urllib.parse.unquote(pure_key)
    encoded_key = urllib.parse.quote(decoded_key)

    # 🎯 명세서 4~5페이지 기준 정확한 발주계획 목록조회 오퍼레이션 엔드포인트
    api_types = [
        {
            "name": "발주계획(물품)",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListThng"
        },
        {
            "name": "발주계획(용역)",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc"
        }
    ]

    # 🎯 명세서 규격 엄격 적용:
    # 1. orderBgnYm / orderEndYm -> YYYYMM (6자리)
    # 2. inqryBgnDt / inqryEndDt -> YYYYMMDDHHmm (12자리)
    start_date_obj = kst_now - timedelta(days=40)

    order_bgn_ym = start_date_obj.strftime('%Y%m')
    order_end_ym = kst_now.strftime('%Y%m')

    inqry_bgn_dt = start_date_obj.strftime('%Y%m%d0000')
    inqry_end_dt = kst_now.strftime('%Y%m%d2359')

    # 사용자가 지정한 정확한 4대 핵심 키워드
    target_keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]
    collected_dict = {}

    for api in api_types:
        # 🎯 명세서 규격에 따른 필수 파라미터 조합 (inqryDiv=1 필수 적용)
        params = {
            "serviceKey": encoded_key,
            "type": "json",
            "pageNo": "1",
            "numOfRows": "1000",
            "inqryDiv": "1",
            "orderBgnYm": order_bgn_ym,
            "orderEndYm": order_end_ym,
            "inqryBgnDt": inqry_bgn_dt,
            "inqryEndDt": inqry_end_dt
        }

        param_string = "&".join([f"{k}={v}" for k, v in params.items()])
        full_url = f"{api['url']}?{param_string}"

        try:
            req = urllib.request.Request(
                full_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                response_body = response.read().decode('utf-8')

                if "INVALID_KEY" in response_body or "SERVICE_KEY" in response_body:
                    print(f"⚠️ {api['name']} API인증 오류 발생 (인증키를 확인하세요)")
                    continue

                data = json.loads(response_body)
                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                if isinstance(items, dict):
                    items = [items]
                elif not items:
                    continue

                for item in items:
                    # 🎯 [명세서 100% 일치 복구] 진짜 사업명 태그는 bizNm 입니다!
                    title = item.get('bizNm') or ""

                    # 4대 키워드 필터링
                    if title and any(kw in title for kw in target_keywords):
                        # 🎯 [명세서 100% 일치 복구] 기관명, 등록일, 금액, 통합번호 태그 매핑
                        org = item.get('orderInsttNm') or "공공기관"
                        date_val = item.get('nticeDt') or kst_now.strftime('%Y-%m-%d')
                        budget = item.get('sumOrderAmt') or "0"
                        url_code = item.get('orderPlanUntyNo') or ""

                        if date_val and len(date_val) >= 10:
                            date_val = date_val[:10]  # YYYY-MM-DD 포맷 분리

                        unique_key = f"{org}_{title}".strip()

                        try:
                            amt = int(float(budget))
                            budget_str = f"{amt:,}원" if amt < 100000000 else f"{amt / 100000000:.1f}억원"
                        except:
                            budget_str = "미정"

                        # 발주계획 상세조회 링크 생성
                        g2b_link = f"https://www.g2b.go.kr:8443/ep/preparation/plan/orderPlanDtl.do?prcmntPlanInfrntNo={url_code}" if url_code else "https://www.g2b.go.kr"

                        collected_dict[unique_key] = {
                            "category": api['name'],
                            "title": title,
                            "org": org,
                            "date": date_val,
                            "budget": budget_str,
                            "link": g2b_link,
                            "is_new": False
                        }
        except Exception as e:
            continue

    final_items = list(collected_dict.values())
    final_items.sort(key=lambda x: x['date'], reverse=True)
    return final_items


def load_and_compare(current_items):
    past_keys = set()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                past_keys = set(line.strip() for line in f.readlines() if line.strip())
        except:
            pass

    new_count = 0
    for item in current_items:
        current_key = f"{item['org']}_{item['title']}".strip()
        if past_keys and (current_key not in past_keys):
            item['is_new'] = True
            new_count += 1
            print(f"✨ [신규 발주계획 탐지] -> {item['title']} ({item['org']})")

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for item in current_items:
                f.write(f"{item['org']}_{item['title']}\n")

        subprocess.run(["git", "config", "--global", "user.name", "G2B-Bot"], capture_output=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@g2b.com"], capture_output=True)
        subprocess.run(["git", "add", HISTORY_FILE], capture_output=True)
        subprocess.run(["git", "commit", "-m", "🤖 발주계획 데이터 업데이트 동기화"], capture_output=True)
        subprocess.run(["git", "push"], capture_output=True)
    except:
        pass

    return current_items, new_count


def send_alerts(items, new_count):
    kst_now = get_current_kst()
    date_str = kst_now.strftime('%m/%d %H시')

    if not items:
        print("검색 완료: 조건에 일치하는 활성 발주계획이 조달청 서버에 존재하지 않습니다.")
        return

    print(f"\n====================================\n🔥 검색 성공! 총 {len(items)}건 화면 출력 및 가동 (신규공고: {new_count}건)")

    # Slack 알림
    if SLACK_TOKEN and SLACK_CHANNEL:
        import requests
        slack_text = f"🏛️ *나라장터 발주계획 실시간 수집 결과 ({date_str})*\n\n"
        for idx, item in enumerate(items, 1):
            badge = "🔴 *[NEW]* " if item['is_new'] else ""
            slack_text += f"{idx}. {badge}*[{item['category']}]* <{item['link']}|{item['title']}>\n   • 기관: {item['org']} | 등록일: {item['date']} | 예산: {item['budget']}\n"
        try:
            requests.post("https://slack.com/api/chat.postMessage",
                          headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                          json={"channel": SLACK_CHANNEL, "text": slack_text}, timeout=10)
        except:
            pass

    # 네이버 이메일 알림
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        msg[
            'Subject'] = f"🚨 [신규 발주 {new_count}건] 나라장터 지정 키워드 발주계획 안내" if new_count > 0 else f"✅ 나라장터 발주계획 종합 리포트 ({date_str})"
        msg['From'] = formataddr((str(Header('발주계획 알림봇', 'utf-8')), NAVER_EMAIL))
        msg['To'] = NAVER_EMAIL

        html_content = f"<h2>🏛️ 나라장터 지정 4대 키워드 발주계획 현황판 ({date_str})</h2><hr><br>"
        html_content += "<table border='1' style='border-collapse:collapse; width:100%; font-size:13px;'>"
        html_content += "<tr style='background-color:#f2f2f2; height:35px;'><th>번호</th><th>구분</th><th>발주계획사업명</th><th>발주기관</th><th>등록일자</th><th>조달예산액</th></tr>"

        for idx, item in enumerate(items, 1):
            bg_style = "style='background-color: #fff1f0;'" if item['is_new'] else ""
            badge_html = "<span style='background-color:#d9534f; color:white; padding:2px 4px; font-size:11px; border-radius:3px;'>신규</span> " if \
            item['is_new'] else ""

            html_content += f"<tr {bg_style}>" \
                            f"<td style='padding:10px; text-align:center;'>{idx}</td>" \
                            f"<td style='padding:10px; text-align:center;'>{item['category']}</td>" \
                            f"<td style='padding:10px;'>{badge_html}<a href='{item['link']}' style='color:#0066cc; font-weight:bold; text-decoration:none;'>{item['title']}</a></td>" \
                            f"<td style='padding:10px;'>{item['org']}</td>" \
                            f"<td style='padding:10px; text-align:center;'>{item['date']}</td>" \
                            f"<td style='padding:10px; color:blue; font-weight:bold;'>{item['budget']}</td>" \
                            f"</tr>"
        html_content += "</table>"

        msg.attach(MIMEText(html_content, 'html'))
        try:
            with smtplib.SMTP_SSL("smtp.naver.com", 465) as server:
                server.login(NAVER_EMAIL, NAVER_PASSWORD)
                server.sendmail(NAVER_EMAIL, [NAVER_EMAIL], msg.as_string())
        except:
            pass


if __name__ == "__main__":
    raw_items = get_g2b_data()
    compared_items, new_detected = load_and_compare(raw_items)
    send_alerts(compared_items, new_detected)