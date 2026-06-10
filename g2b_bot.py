import os
import smtplib
import json
from datetime import datetime, timedelta
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


def get_g2b_data():
    print("나라장터 발주계획 상시 감시 및 변경 추적 로봇 구동 중...")

    if not API_KEY:
        print("❌ 에러: DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return []

    pure_key = API_KEY.strip()
    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]

    api_types = [
        {"name": "발주계획(용역)",
         "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc"},
        {"name": "발주계획(물품)",
         "url": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListThng"}
    ]

    # 조달청 7일 조회 제한 우회를 위해 최근 28일을 4개 구간으로 분할
    date_ranges = []
    today = datetime.now()
    for i in range(4):
        end_day = (today - timedelta(days=i * 7)).strftime('%Y%m%d')
        start_day = (today - timedelta(days=(i + 1) * 7 - 1)).strftime('%Y%m%d')
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
                        date_val = item.get('orderPlanRgstDt') or datetime.now().strftime('%Y-%m-%d')
                        budget = item.get('asignBdgtAmt') or "0"

                        if date_val:
                            date_val = date_val.split()[0]

                        if title and any(kw in title for kw in keywords):
                            # 기관명과 제목 조합으로 고유 키 생성
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
                                "is_new": False  # 기본값은 신규 아님
                            }
            except:
                continue

    final_items = list(collected_dict.values())
    final_items.sort(key=lambda x: x['date'], reverse=True)
    return final_items


def load_and_compare(current_items):
    """이전 실행 데이터와 비교하여 신규 추가 항목을 마킹하고 기록을 업데이트합니다."""
    past_keys = set()

    # 1. 과거 기록 읽어오기
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                past_keys = set(line.strip() for line in f.readlines() if line.strip())
            print(f"📂 기억 보관소 로드 완료 (이전 등록 데이터 수: {len(past_keys)}건)")
        except Exception as e:
            print(f"⚠️ 기억 보관소 로드 실패: {e}")
    else:
        print("ℹ️ 기존 기억 보관소 파일이 없습니다. 첫 실행으로 인식합니다.")

    # 2. 신규 여부 비교 체크
    new_count = 0
    for item in current_items:
        current_key = f"{item['org']}_{item['title']}".strip()
        if past_keys and (current_key not in past_keys):
            item['is_new'] = True
            new_count += 1
            print(f"✨ [신규 발주 발견] -> {item['title']} ({item['org']})")

    # 첫 실행인 경우 전부 신규라 알림이 도배되는 것을 막기 위해 가드 가동
    if not past_keys:
        print("💡 첫 구동이므로 전체 목록을 기준점으로 보관합니다. (다음 시간부터 신규 마킹 활성화)")

    # 3. 최신 데이터로 기억 보관소 파일 갱신
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for item in current_items:
                f.write(f"{item['org']}_{item['title']}\n")

        # GitHub Actions 내부 저장소에 파일 상태 자동 커밋/푸시 실행
        subprocess.run(["git", "config", "--global", "user.name", "G2B-Bot"], capture_output=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@g2b.com"], capture_output=True)
        subprocess.run(["git", "add", HISTORY_FILE], capture_output=True)
        subprocess.run(["git", "commit", "-m", "🤖 [🤖 시스템] 발주 기록 보관소 실시간 갱신"], capture_output=True)
        subprocess.run(["git", "push"], capture_output=True)
        print("💾 최신 발주 리스트를 저장소 기억 보관소에 동기화 완료했습니다.")
    except Exception as e:
        print(f"⚠️ 저장소 자동 갱신 실패 (권한 제한 등): {e}")

    return current_items, new_count


def send_alerts(items, new_count):
    date_str = datetime.now().strftime('%m/%d %H시')
    if not items:
        print("검색 완료: 조건에 맞는 한 달 치 발주 계획이 존재하지 않습니다.")
        return

    # 신규 건수가 있을 때 헤더 문구 다이내믹 변경
    new_alert_header = f"🚨 [★1시간 전 대비 신규 {new_count}건 추가됨!★]" if new_count > 0 else "✅ 1시간 전 대비 변동사항 없음"
    print(f"\n📢 [현황판 브리핑 시작] {new_alert_header} (총 {len(items)}건 송신)")

    # 1. MS Teams 브리핑 양식
    teams_text = f"### 🏛️ 나라장터 발주계획 종합 현황판 ({date_str} 기준)\n"
    teams_text += f"**{new_alert_header}**\n"
    teams_text += f"*※ 최근 4주일간 등록된 4대 핵심 키워드 전체 리스트입니다.*\n\n<hr>\n\n"

    for idx, item in enumerate(items, 1):
        badge = "🔴 **[★신규 추가공고★]** " if item['is_new'] else ""
        teams_text += f"{idx}. {badge}**[{item['category']}] {item['title']}**\n"
        teams_text += f"└ *발주기관: {item['org']} / 등록일: {item['date']} / 예산: {item['budget']}*\n\n"

    if TEAMS_WEBHOOK:
        import requests
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
            requests.post(TEAMS_WEBHOOK, json=payload, timeout=10)
        except:
            pass

    # 2. 네이버 이메일 현황판 양식
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        subject_title = f"🚨 [신규발주 {new_count}건!!] 나라장터 핵심 발주계획 리포트" if new_count > 0 else f"[현황판] 나라장터 발주계획 종합 리포트 ({date_str})"
        msg['Subject'] = subject_title
        msg['From'] = formataddr((str(Header('발주계획 감시봇', 'utf-8')), NAVER_EMAIL))
        msg['To'] = NAVER_EMAIL

        html_content = f"<h2>🏛️ 나라장터 핵심 발주계획 종합 현황판 ({date_str})</h2>"
        html_content += f"<p style='font-size:14px; color:#d9534f;'><b>{new_alert_header}</b></p>"
        html_content += "<p style='color:#666;'>최근 4주일 동안 나라장터에 등록된 4대 핵심 키워드 정밀 분석 결과입니다.</p><hr><br>"
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
        html_content += "</table><br><br>※ 본 브리핑은 1시간 간격 업데이트 추적 시스템에 의해 발송됩니다."

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
    print(f"\n====================================\n최근 한 달 데이터 정밀 매칭 완료: 총 {len(compared_items)}건 데이터 정렬")
    send_alerts(compared_items, new_detected)