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
    print(f"🏛️ 나라장터 실시간 [입찰공고] 추적 로봇 가동... (한국 시간: {kst_now.strftime('%Y-%m-%d %H:%M')})")

    if not API_KEY:
        print("❌ 에러: DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return []

    pure_key = API_KEY.strip()
    decoded_key = urllib.parse.unquote(pure_key)
    encoded_key = urllib.parse.quote(decoded_key)

    # 🎯 [치트키] 조달청 한글 검색 버그를 피하기 위해, 서버에는 키워드를 던지지 않고 날짜로만 조회합니다!
    api_types = [
        {
            "name": "입찰공고(용역)",
            "url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
        },
        {
            "name": "입찰공고(물품)",
            "url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch"
        }
    ]

    # 🎯 [정확한 파라미터 맵핑] PPSSrch API의 진짜 날짜 규격은 inqryBgnDt와 inqryEndDt 입니다!
    # 시/분까지 정확히 12자리를 요구합니다. (YYYYMMDDHHMM)
    end_day = kst_now.strftime('%Y%m%d2359')
    start_day = (kst_now - timedelta(days=40)).strftime('%Y%m%d0000')

    keywords = ["스쿨넷", "융합통신망", "교육망", "스마트기기", "스마트패드", "노트북"]
    collected_dict = {}

    for api in api_types:
        # 데이터 유실을 막기 위해 넉넉하게 1000건을 한 번에 요청합니다.
        full_url = f"{api['url']}?serviceKey={encoded_key}&type=json&pageNo=1&numOfRows=1000&inqryBgnDt={start_day}&inqryEndDt={end_day}"

        try:
            req = urllib.request.Request(
                full_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                response_body = response.read().decode('utf-8')

                if "INVALID_KEY" in response_body or "SERVICE_KEY" in response_body:
                    print(f"⚠️ {api['name']} 인증키 거부 현상 발생, 토큰 형식을 점검하세요.")
                    continue

                data = json.loads(response_body)
                body = data.get('response', {}).get('body', {})
                items = body.get('items', [])

                if isinstance(items, dict):
                    items = [items]
                elif not items:
                    continue

                for item in items:
                    title = item.get('bidNtceNm') or ""

                    # 🎯 조달청 서버 대신 파이썬이 완벽하게 키워드를 필터링합니다.
                    if title and any(kw in title for kw in keywords):
                        org = item.get('dminsttNm') or item.get('ntceInsttNm') or "공공기관"
                        date_val = item.get('bidNtceDt') or kst_now.strftime('%Y-%m-%d')
                        budget = item.get('bdgtAmt') or item.get('presmptPrce') or "0"
                        url_code = item.get('bidNtceNo') or ""

                        if date_val:
                            date_val = date_val.split()[0]

                        unique_key = f"{org}_{title}".strip()

                        try:
                            amt = int(float(budget))
                            budget_str = f"{amt:,}원" if amt < 100000000 else f"{amt / 100000000:.1f}억원"
                        except:
                            budget_str = "미정"

                        g2b_link = f"https://www.g2b.go.kr:8443/ep/invitation/publish/bidInfoDtl.do?bidNo={url_code}&bidChgNo=00" if url_code else "https://www.g2b.go.kr"

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
            print(f"❌ {api['name']} 통신 에러: {e}")
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
            print(f"✨ [새로운 공고 발견] -> {item['title']} ({item['org']})")

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for item in current_items:
                f.write(f"{item['org']}_{item['title']}\n")

        subprocess.run(["git", "config", "--global", "user.name", "G2B-Bot"], capture_output=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@g2b.com"], capture_output=True)
        subprocess.run(["git", "add", HISTORY_FILE], capture_output=True)
        subprocess.run(["git", "commit", "-m", "🤖 [시스템] 공고 기록 보관소 동기화"], capture_output=True)
        subprocess.run(["git", "push"], capture_output=True)
    except:
        pass

    return current_items, new_count


def send_alerts(items, new_count):
    kst_now = get_current_kst()
    date_str = kst_now.strftime('%m/%d %H시')

    if not items:
        print("검색 완료: 현재 나라장터 입찰공고 서버에 조건에 일치하는 활성 공고가 없습니다.")
        return

    new_alert_header = f"🚨 [★이전 보고 대비 신규 입찰공고 {new_count}건 추가됨!★]" if new_count > 0 else "✅ 이전 보고 대비 새로 추가된 공고 없음"
    print(f"\n====================================\n정기 리포트 브리핑 가동: 총 {len(items)}건 송신 처리 ({new_alert_header})")

    # Slack 브리핑 전송
    if SLACK_TOKEN and SLACK_CHANNEL:
        import requests
        slack_text = f"🏛️ *나라장터 실시간 입찰공고 종합 현황판 ({date_str} 기준)*\n"
        slack_text += f"*{new_alert_header}*\n\n"
        for idx, item in enumerate(items, 1):
            badge = "🔴 *[★신규추가★]* " if item['is_new'] else ""
            slack_text += f"{idx}. {badge}*[{item['category']}]* <{item['link']}|{item['title']}>\n   • 발주기관: {item['org']} | 공고일: {item['date']} | 예산: {item['budget']}\n"
        try:
            requests.post("https://slack.com/api/chat.postMessage",
                          headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                          json={"channel": SLACK_CHANNEL, "text": slack_text}, timeout=10)
        except:
            pass

    # 네이버 이메일 현황판 전송
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        subject_title = f"🚨 [신규공고 {new_count}건!] 나라장터 실시간 입찰공고 리포트" if new_count > 0 else f"[현황판] 나라장터 입찰공고 종합 리포트 ({date_str})"
        msg['Subject'] = subject_title
        msg['From'] = formataddr((str(Header('입찰공고 감시봇', 'utf-8')), NAVER_EMAIL))
        msg['To'] = NAVER_EMAIL

        html_content = f"<h2>🏛️ 나라장터 실시간 입찰공고 종합 현황판 ({date_str})</h2>"
        html_content += f"<p style='font-size:14px; color:#d9534f;'><b>{new_alert_header}</b></p><hr><br>"
        html_content += "<table border='1' style='border-collapse:collapse; width:100%; text-align:left; font-size:13px;'>"
        html_content += "<tr style='background-color:#f2f2f2; height:35px;'><th>번호</th><th>구분</th><th>입찰공고사업명(링크)</th><th>수요기관</th><th>공고일자</th><th>배정예산</th></tr>"

        for idx, item in enumerate(items, 1):
            bg_style = "style='background-color: #fff1f0;'" if item['is_new'] else ""
            badge_html = "<span style='background-color:#d9534f; color:white; padding:2px 5px; font-size:11px; border-radius:3px; margin-right:5px;'>신규추가</span> " if \
            item['is_new'] else ""

            html_content += f"<tr {bg_style}>" \
                            f"<td style='padding:10px;'>{idx}</td>" \
                            f"<td style='padding:10px;'>{item['category']}</td>" \
                            f"<td style='padding:10px;'>{badge_html}<a href='{item['link']}' style='color:#0066cc; font-weight:bold; text-decoration:none;'>{item['title']}</a></td>" \
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