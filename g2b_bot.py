import os
import smtplib
import json
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
import urllib.request
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
    """해외 깃허브 서버에서도 항상 정확한 한국 시간(KST)을 반환합니다."""
    return datetime.now(timezone(timedelta(hours=9)))


def get_g2b_data():
    kst_now = get_current_kst()
    print(f"나라장터 발주계획 정밀 분석 로봇 구동 중... (현재 한국 시간: {kst_now.strftime('%Y-%m-%d %H:%M')})")

    if not API_KEY:
        print("❌ 에러: DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return []

    pure_key = API_KEY.strip()
    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]

    # ❌ 입찰공고/사전규격 차단 ⭕ 오직 발주계획 데이터만 타격
    api_types = [
        {"name": "발주계획(용역)",
         "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc"},
        {"name": "발주계획(물품)",
         "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListThng"}
    ]

    # 💡 조달청 7일 제한을 풀고, 동기화 누락을 막기 위해 최근 91일(약 3달치)을 7일씩 13개 구간으로 쪼개서 전부 긁어옵니다.
    date_ranges = []
    for i in range(13):
        end_day = (kst_now - timedelta(days=i * 7)).strftime('%Y%m%d')
        start_day = (kst_now - timedelta(days=(i + 1) * 7 - 1)).strftime('%Y%m%d')
        date_ranges.append((start_day, end_day))

    collected_dict = {}

    for api in api_types:
        for start_day, end_day in date_ranges:
            full_url = f"{api['url']}?serviceKey={pure_key}&type=json&pageNo=1&numOfRows=100&insttInqryBgnDt={start_day}&insttInqryEndDt={end_day}"

            try:
                req = urllib.request.Request(
                    full_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req, timeout=20) as response:
                    response_body = response.read().decode('utf-8')
                    data = json.loads(response_body)
                    body = data.get('response', {}).get('body', {})
                    items = body.get('items', [])

                    if isinstance(items, dict):
                        items = [items]
                    elif not items:
                        continue

                    for item in items:
                        title = item.get('orderPlanNm') or ""
                        org = item.get('orderPlanInsttNm') or item.get('dminsttNm') or "공공기관"
                        date_val = item.get('orderPlanRgstDt') or kst_now.strftime('%Y-%m-%d')
                        budget = item.get('asignBdgtAmt') or "0"

                        if date_val:
                            date_val = date_val.split()[0]

                        # 키워드 매칭 검사
                        if title and any(kw in title for kw in keywords):
                            unique_key = f"{org}_{title}".strip()

                            try:
                                amt = int(budget)
                                budget_str = f"{amt:,}원" if amt < 100000000 else f"{amt / 100000000:.1f}억원"
                            except:
                                budget_str = "미정"

                            collected_dict[unique_key] = {
                                "category": api['name'],
                                "title": title,
                                "org": org,
                                "date": date_val,
                                "budget": budget_str,
                                "is_new": False
                            }
            except:
                continue

    final_items = list(collected_dict.values())
    # 날짜 최신순으로 정렬
    final_items.sort(key=lambda x: x['date'], reverse=True)
    return final_items


def load_and_compare(current_items):
    """이전 타임 발주 내역과 비교 분석하여 신규 등록 건에 특수 마킹을 진행합니다."""
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
            print(f"✨ [새로운 발주계획 추가 발견] -> {item['title']} ({item['org']})")

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for item in current_items:
                f.write(f"{item['org']}_{item['title']}\n")

        subprocess.run(["git", "config", "--global", "user.name", "G2B-Bot"], capture_output=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@g2b.com"], capture_output=True)
        subprocess.run(["git", "add", HISTORY_FILE], capture_output=True)
        subprocess.run(["git", "commit", "-m", "🤖 [시스템] 발주 기록 보관소 동기화"], capture_output=True)
        subprocess.run(["git", "push"], capture_output=True)
    except:
        pass

    return current_items, new_count


def send_alerts(items, new_count):
    kst_now = get_current_kst()
    date_str = kst_now.strftime('%m/%d %H시')

    if not items:
        print("검색 완료: 조건에 일치하는 발주 계획이 조달청 API 서버에 아직 존재하지 않습니다.")
        return

    new_alert_header = f"🚨 [★이전 보고 대비 신규 발주계획 {new_count}건 추가됨!★]" if new_count > 0 else "✅ 이전 보고 대비 새로 추가된 발주 없음"
    print(f"\n====================================\n정기 리포트 브리핑 가동: 총 {len(items)}건 송신 처리 ({new_alert_header})")

    # # 1. MS Teams 브리핑 전송 (잠시 보류)
    # teams_text = f"### 🏛️ 나라장터 발주계획 종합 현황판 ({date_str} 기준)\n"
    # teams_text += f"**{new_alert_header}**\n"
    # teams_text += f"*※ 최근 등록된 4대 핵심 키워드 발주계획 전체 현황판입니다.*\n\n"
    #
    # for idx, item in enumerate(items, 1):
    #     badge = "🔴 **[★신규 추가공고★]** " if item['is_new'] else ""
    #     teams_text += f"{idx}. {badge}**[{item['category']}] {item['title']}**\n"
    #     teams_text += f"└ *발주기관: {item['org']} / 등록일: {item['date']} / 예산: {item['budget']}*\n\n"
    #
    # if TEAMS_WEBHOOK:
    #     import requests
    #     payload = {
    #         "type": "message",
    #         "attachments": [{
    #             "contentType": "application/vnd.microsoft.card.adaptive",
    #             "content": {
    #                 "type": "AdaptiveCard",
    #                 "body": [{"type": "TextBlock", "text": teams_text, "wrap": True}],
    #                 "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.4"
    #             }
    #         }]
    #     }
    #     try: requests.post(TEAMS_WEBHOOK, json=payload, timeout=10)
    #     except: pass

    # 2. Slack 브리핑 전송
    if SLACK_TOKEN and SLACK_CHANNEL:
        import requests
        slack_text = f"🏛️ *나라장터 핵심 발주계획 종합 현황판 ({date_str} 기준)*\n"
        slack_text += f"*{new_alert_header}*\n\n"
        for idx, item in enumerate(items, 1):
            badge = "🔴 *[★신규추가★]* " if item['is_new'] else ""
            slack_text += f"{idx}. {badge}*[{item['category']}]* {item['title']}\n   • 발주기관: {item['org']} | 등록일: {item['date']} | 예산: {item['budget']}\n"
        try:
            requests.post("https://slack.com/api/chat.postMessage",
                          headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                          json={"channel": SLACK_CHANNEL, "text": slack_text}, timeout=10)
        except:
            pass

    # 3. 네이버 이메일 현황판 전송
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        subject_title = f"🚨 [신규발주 {new_count}건!!] 나라장터 발주계획 종합 리포트" if new_count > 0 else f"[현황판] 나라장터 발주계획 종합 리포트 ({date_str})"
        msg['Subject'] = subject_title
        msg['From'] = formataddr((str(Header('발주계획 감시봇', 'utf-8')), NAVER_EMAIL))
        msg['To'] = NAVER_EMAIL

        html_content = f"<h2>🏛️ 나라장터 핵심 발주계획 종합 현황판 ({date_str})</h2>"
        html_content += f"<p style='font-size:14px; color:#d9534f;'><b>{new_alert_header}</b></p><hr><br>"
        html_content += "<table border='1' style='border-collapse:collapse; width:100%; text-align:left; font-size:13px;'>"
        html_content += "<tr style='background-color:#f2f2f2; height:35px;'><th>번호</th><th>구분</th><th>발주사업명</th><th>수요기관</th><th>등록일자</th><th>배정예산</th></tr>"

        for idx, item in enumerate(items, 1):
            bg_style = "style='background-color: #fff1f0;'" if item['is_new'] else ""
            badge_html = "<span style='background-color:#d9534f; color:white; padding:2px 5px; font-size:11px; border-radius:3px; margin-right:5px;'>신규추가</span> " if \
            item['is_new'] else ""

            html_content += f"<tr {bg_style}>" \
                            f"<td style='padding:10px;'>{idx}</td>" \
                            f"<td style='padding:10px;'>{item['category']}</td>" \
                            f"<td style='padding:10px;'>{badge_html}<b>{item['title']}</b></td>" \
                            f"<td style='padding:10px;'>{item['org']}</td>" \
                            f"<td style='padding:10px;'>{item['date']}</td>" \
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