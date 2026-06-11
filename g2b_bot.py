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
    print(f"나라장터 본진 발주계획 정밀 분석 로봇 구동 중... (현재 한국 시간: {kst_now.strftime('%Y-%m-%d %H:%M')})")

    if not API_KEY:
        print("❌ 에러: DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return []

    pure_key = API_KEY.strip()
    # 인코딩된 키와 디코딩된 키의 변수 꼬임을 방지하기 위해 언인코딩 처리(필요시 조달청 대응)
    import urllib.parse
    unquoted_key = urllib.parse.unquote(pure_key)

    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]

    # 진짜 본진 API 주소
    api_types = [
        {"name": "나라장터 본진 발주계획",
         "url": "https://apis.data.go.kr/1230000/Bps_OrderPlanInfoService/getBpsOrderPlanInfoList"}
    ]

    end_day = kst_now.strftime('%Y-%m-%d')
    start_day = (kst_now - timedelta(days=31)).strftime('%Y-%m-%d')

    collected_dict = {}

    for api in api_types:
        # ⭐ [500 에러 전면 우회] 주소창(URL)에서 serviceKey를 완전 삭제 처리합니다!
        full_url = f"{api['url']}?type=json&pageNo=1&numOfRows=999&bgnDt={start_day}&endDt={end_day}"

        try:
            # ⭐ 대신 Headers 가방 안에 인증키를 숨겨서 전달하는 조달청 표준 보안 방식을 적용합니다.
            req = urllib.request.Request(
                full_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'accept': 'application/json',
                    'Authorization': unquoted_key  # 헤더 인증 주입
                }
            )

            # 만약 헤더 인증 거부 시를 대비한 백업 2차 타격 (URL 인코딩 유지 방식)
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    response_body = response.read().decode('utf-8')
            except:
                # 백업: 원래 방식으로 가되 키를 바르게 다시 인코딩해서 재시도
                backup_url = f"{api['url']}?serviceKey={pure_key}&type=json&pageNo=1&numOfRows=999&bgnDt={start_day}&endDt={end_day}"
                req_backup = urllib.request.Request(backup_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_backup, timeout=20) as response:
                    response_body = response.read().decode('utf-8')

            data = json.loads(response_body)
            body = data.get('response', {}).get('body', {})
            items = body.get('items', [])

            if isinstance(items, dict):
                items = [items]
            elif not items:
                continue

            for item in items:
                title = item.get('prcmntPlanNm') or ""
                org = item.get('orderInsttNm') or item.get('coopsInsttNm') or "공공기관"
                date_val = item.get('rgstDt') or kst_now.strftime('%Y-%m-%d')
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
        except Exception as e:
            print(f"⚠️ 본진 데이터 수집 중 에러 발생: {e}")
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
        print("검색 완료: 조건에 일치하는 발주 계획이 조달청 본진 API 서버에 존재하지 않습니다.")
        return

    new_alert_header = f"🚨 [★이전 보고 대비 신규 발주계획 {new_count}건 추가됨!★]" if new_count > 0 else "✅ 이전 보고 대비 새로 추가된 발주 없음"
    print(f"\n====================================\n정기 리포트 브리핑 가동: 총 {len(items)}건 송신 처리 ({new_alert_header})")

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