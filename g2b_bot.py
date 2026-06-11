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

    # 🎯 문서에 정의된 발주계획현황서비스 PPSSrch 검색 엔드포인트 주소
    api_types = [
        {
            "name": "발주계획(용역)",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServcPPSSrch"
        },
        {
            "name": "발주계획(물품)",
            "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListThngPPSSrch"
        }
    ]

    # 문서 규격: 게시시작일자/게시종료일자는 YYYYMMDD 8자리 포맷
    end_day = kst_now.strftime('%Y%m%d')
    start_day = (kst_now - timedelta(days=40)).strftime('%Y%m%d')

    # 🎯 요청하신 딱 4가지 핵심 키워드 고정
    target_keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]
    collected_dict = {}

    for api in api_types:
        # 최근 등록된 데이터 최대 1000건 확보 (조달청 한글 파라미터 검색 버그 완전 우회)
        full_url = f"{api['url']}?serviceKey={encoded_key}&type=json&pageNo=1&numOfRows=1000&insttInptBgnDt={start_day}&insttInptEndDt={end_day}"

        try:
            req = urllib.request.Request(
                full_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                response_body = response.read().decode('utf-8')

                if "INVALID_KEY" in response_body or "SERVICE_KEY" in response_body:
                    print(f"⚠️ {api['name']} API인증 오류 발생")
                    continue

                data = json.loads(response_body)
                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                if isinstance(items, dict):
                    items = [items]
                elif not items:
                    continue

                for item in items:
                    # 🎯 [핵심 교정] 문서에 기술된 정확한 프로젝트명(사업명) 태그 맵핑
                    title = item.get('prcmntPlanPjctNm') or ""

                    # 딱 4개 키워드 매칭 수행
                    if title and any(kw in title for kw in target_keywords):
                        # 🎯 [핵심 교정] 문서에 명시된 발주기관명 및 데이터 태그 맵핑
                        org = item.get('orderInsttNm') or "공공기관"
                        date_val = item.get('insttInptDt') or kst_now.strftime('%Y-%m-%d')
                        budget = item.get('totPrcmntAmt') or "0"
                        url_code = item.get('prcmntPlanInfrntNo') or ""

                        if date_val and len(date_val) >= 10:
                            date_val = date_val[:10]  # YYYY-MM-DD 형태로 규격화

                        unique_key = f"{org}_{title}".strip()

                        try:
                            amt = int(float(budget))
                            budget_str = f"{amt:,}원" if amt < 100000000 else f"{amt / 100000000:.1f}억원"
                        except:
                            budget_str = "미정"

                        # 발주계획 상세조회 페이지 연결 링크 생성
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
            print(f"✨ [신규 발주계획 발견] -> {item['title']} ({item['org']})")

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for item in current_items:
                f.write(f"{item['org']}_{item['title']}\n")

        subprocess.run(["git", "config", "--global", "user.name", "G2B-Bot"], capture_output=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@g2b.com"], capture_output=True)
        subprocess.run(["git", "add", HISTORY_FILE], capture_output=True)
        subprocess.run(["git", "commit", "-m", "🤖 [시스템] 발주계획 데이터 동기화"], capture_output=True)
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

    # Slack 전송
    if SLACK_TOKEN and SLACK_CHANNEL:
        import requests
        slack_text = f"🏛️ *나라장터 발주계획 4대 키워드 종합 현황판 ({date_str} 기준)*\n\n"
        for idx, item in enumerate(items, 1):
            badge = "🔴 *[★신규★]* " if item['is_new'] else ""
            slack_text += f"{idx}. {badge}*[{item['category']}]* <{item['link']}|{item['title']}>\n   • 발주기관: {item['org']} | 등록일: {item['date']} | 예산: {item['budget']}\n"
        try:
            requests.post("https://slack.com/api/chat.postMessage",
                          headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                          json={"channel": SLACK_CHANNEL, "text": slack_text}, timeout=10)
        except:
            pass

    # 네이버 이메일 전송
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        msg[
            'Subject'] = f"🚨 [신규 발주계획 {new_count}건!] 나라장터 실시간 검색 리포트" if new_count > 0 else f"[현황판] 나라장터 지정 키워드 발주계획 리포트 ({date_str})"
        msg['From'] = formataddr((str(Header('발주계획 감시봇', 'utf-8')), NAVER_EMAIL))
        msg['To'] = NAVER_EMAIL

        html_content = f"<h2>🏛️ 나라장터 지정 4대 키워드 발주계획 현황판 ({date_str})</h2><hr><br>"
        html_content += "<table border='1' style='border-collapse:collapse; width:100%; text-align:left; font-size:13px.'>"
        html_content += "<tr style='background-color:#f2f2f2; height:35px;'><th>번호</th><th>구분</th><th>발주계획사업명(링크)</th><th>발주기관</th><th>등록일자</th><th>조달예산액</th></tr>"

        for idx, item in enumerate(items, 1):
            bg_style = "style='background-color: #fff1f0;'" if item['is_new'] else ""
            badge_html = "<span style='background-color:#d9534f; color:white; padding:2px 5px; font-size:11px; border-radius:3px; margin-right:5px;'>신규</span> " if \
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