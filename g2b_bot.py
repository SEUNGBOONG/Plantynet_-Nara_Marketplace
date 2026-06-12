import json
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

API_BASE = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService"
HISTORY_FILE = "last_g2b_data.txt"

# 환경변수 로드
API_KEY = os.environ.get("DATA_GO_KR_API_KEY")
NAVER_EMAIL = os.environ.get("NAVER_EMAIL")
NAVER_PASSWORD = os.environ.get("NAVER_PASSWORD")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")

DEFAULT_KEYWORDS = ["스쿨넷", "융합통신망", "교육망", "스마트기기"]
SEARCH_DAYS = int(os.environ.get("G2B_SEARCH_DAYS", "40"))
ORDER_MONTHS_AHEAD = int(os.environ.get("G2B_ORDER_MONTHS_AHEAD", "12"))

ORDER_PLAN_ENDPOINTS = [
    ("발주계획(물품)", "getOrderPlanSttusListThngPPSSrch"),
    ("발주계획(공사)", "getOrderPlanSttusListCnstwkPPSSrch"),
    ("발주계획(용역)", "getOrderPlanSttusListServcPPSSrch"),
    ("발주계획(외자)", "getOrderPlanSttusListFrgcptPPSSrch"),
]


def get_current_kst():
    return datetime.now(timezone(timedelta(hours=9)))


def get_target_keywords():
    raw = os.environ.get("G2B_KEYWORDS", "")
    if raw.strip():
        return [kw.strip() for kw in raw.split(",") if kw.strip()]
    return DEFAULT_KEYWORDS


def normalize_service_key(api_key):
    return urllib.parse.quote(urllib.parse.unquote(api_key.strip()), safe="")


def build_order_plan_link(order_plan_unty_no):
    if not order_plan_unty_no:
        return "https://www.g2b.go.kr"
    encoded_no = urllib.parse.quote(order_plan_unty_no, safe="")
    return (
        "https://www.g2b.go.kr/pt/menu/selectSubFrame.do?"
        f"framesrc=/pt/ao/orderplan/orderPlanDetail.do?orderPlanUntyNo={encoded_no}"
    )


def format_budget(amount):
    try:
        amt = int(float(amount))
        if amt <= 0:
            return "미정"
        if amt < 100_000_000:
            return f"{amt:,}원"
        return f"{amt / 100_000_000:.1f}억원"
    except (TypeError, ValueError):
        return "미정"


def normalize_items(raw_items):
    if not raw_items:
        return []
    if isinstance(raw_items, list):
        return raw_items
    if isinstance(raw_items, dict):
        return [raw_items]
    return []


def parse_api_response(response_body):
    data = json.loads(response_body)
    header = data.get("response", {}).get("header", {})
    result_code = header.get("resultCode", "")
    result_msg = header.get("resultMsg", "")

    if result_code != "00":
        return [], f"{result_code}: {result_msg}"

    body = data.get("response", {}).get("body", {})
    items = normalize_items(body.get("items"))
    return items, None


def fetch_order_plans(endpoint, service_key, params):
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe="")
    url = f"{API_BASE}/{endpoint}?serviceKey={service_key}&{query}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; G2B-Bot/1.0)"},
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read().decode("utf-8")

    if "INVALID_KEY" in body or "SERVICE_KEY" in body:
        raise RuntimeError("공공데이터포털 API 인증키가 유효하지 않습니다.")

    return parse_api_response(body)


def fetch_all_pages(endpoint, service_key, base_params):
    all_items = []
    page_no = 1

    while True:
        params = dict(base_params)
        params["pageNo"] = page_no
        items, error = fetch_order_plans(endpoint, service_key, params)
        if error:
            raise RuntimeError(error)

        all_items.extend(items)
        if len(items) < base_params["numOfRows"]:
            break

        page_no += 1
        if page_no > 20:
            break

    return all_items


def get_date_ranges(kst_now):
    start_dt = kst_now - timedelta(days=SEARCH_DAYS)
    end_dt = kst_now

    order_start = start_dt.replace(day=1)
    order_end = end_dt + timedelta(days=ORDER_MONTHS_AHEAD * 31)
    order_end = order_end.replace(day=1)

    return {
        "orderBgnYm": order_start.strftime("%Y%m"),
        "orderEndYm": order_end.strftime("%Y%m"),
        "insttInptBgnDt": start_dt.strftime("%Y%m%d"),
        "insttInptEndDt": end_dt.strftime("%Y%m%d"),
        "inqryBgnDt": start_dt.strftime("%Y%m%d0000"),
        "inqryEndDt": end_dt.strftime("%Y%m%d2359"),
        "inqryDiv": "1"
    }


def matches_keyword(item, keyword):
    keyword_lower = keyword.lower()
    search_fields = [
        item.get("prcmntPlanPjctNm") or item.get("bizNm") or "",
        item.get("usgCntnts") or "",
        item.get("prdctClsfcNoNm") or "",
        item.get("specCntnts") or "",
    ]
    return any(keyword_lower in field.lower() for field in search_fields)


def get_g2b_data():
    kst_now = get_current_kst()
    keywords = get_target_keywords()
    print(
        f"나라장터 발주계획 검색 시작 "
        f"({kst_now.strftime('%Y-%m-%d %H:%M')}, 키워드: {', '.join(keywords)})"
    )

    if not API_KEY:
        print("에러: DATA_GO_KR_API_KEY 환경변수가 설정되지 않았습니다.")
        return [], ["API 인증키 미설정"]

    service_key = normalize_service_key(API_KEY)
    date_ranges = get_date_ranges(kst_now)
    collected = {}
    errors = []

    for category, endpoint in ORDER_PLAN_ENDPOINTS:
        for keyword in keywords:
            params = {
                "type": "json",
                "numOfRows": 100,
                "bizNm": keyword,
                **date_ranges,
            }

            try:
                items = fetch_all_pages(endpoint, service_key, params)
                print(f"  [{category}] '{keyword}' 서버 조회 성공 -> {len(items)}건")
            except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
                message = f"[{category}] '{keyword}' 조회 실패: {exc}"
                print(f"  {message}")
                errors.append(message)
                continue

            for item in items:
                if not matches_keyword(item, keyword):
                    continue

                title = item.get("prcmntPlanPjctNm") or item.get("bizNm") or ""
                org = item.get("orderInsttNm") or "공공기관"
                date_val = item.get("insttInptDt") or item.get("nticeDt") or kst_now.strftime("%Y-%m-%d")
                if len(date_val) >= 10:
                    date_val = date_val[:10]

                order_plan_no = item.get("prcmntPlanInfrntNo") or item.get("orderPlanUntyNo") or ""
                unique_key = f"{order_plan_no or org}_{title}".strip()

                collected[unique_key] = {
                    "category": category,
                    "title": title,
                    "org": org,
                    "date": date_val,
                    "budget": format_budget(item.get("totPrcmntAmt") or item.get("sumOrderAmt")),
                    "link": build_order_plan_link(order_plan_no),
                    "keyword": keyword,
                    "is_new": False,
                }

    final_items = list(collected.values())
    final_items.sort(key=lambda x: x["date"], reverse=True)
    return final_items, errors


def load_and_compare(current_items):
    past_keys = set()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                past_keys = {line.strip() for line in f if line.strip()}
        except OSError:
            pass

    new_count = 0
    for item in current_items:
        current_key = f"{item['org']}_{item['title']}".strip()
        if not past_keys or current_key not in past_keys:
            item["is_new"] = True
            new_count += 1
            print(f"[신규] {item['title']} ({item['org']})")

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for item in current_items:
                f.write(f"{item['org']}_{item['title']}\n")
    except OSError as exc:
        print(f"히스토리 저장 실패: {exc}")

    return current_items, new_count


def build_html_report(items, errors, new_count, date_str):
    if errors and not items:
        html = (
            f"<h2>나라장터 발주계획 조회 오류 ({date_str})</h2>"
            "<p>API 조회 중 문제가 발생했습니다.</p><ul>"
        )
        for error in errors:
            html += f"<li>{error}</li>"
        html += "</ul>"
        return html

    html = (
        f"<h2>나라장터 키워드 발주계획 리포트 ({date_str})</h2>"
        f"<p>총 <b>{len(items)}</b>건 (신규 {new_count}건)</p>"
    )

    if errors:
        html += "<p style='color:#d9534f;'><b>일부 조회 오류</b></p><ul>"
        for error in errors:
            html += f"<li>{error}</li>"
        html += "</ul>"

    if not items:
        html += "<p>조건에 맞는 발주계획이 없습니다.</p>"
        return html

    html += (
        "<table border='1' style='border-collapse:collapse; width:100%; "
        "font-size:13px; text-align:left;'>"
        "<tr style='background-color:#f2f2f2; height:35px;'>"
        "<th>번호</th><th>구분</th><th>키워드</th><th>발주계획사업명</th>"
        "<th>발주기관</th><th>등록일</th><th>예산</th></tr>"
    )

    for idx, item in enumerate(items, 1):
        bg_style = "style='background-color:#fff1f0;'" if item["is_new"] else ""
        badge = (
            "<span style='background:#d9534f;color:#fff;padding:2px 5px;"
            "font-size:11px;border-radius:3px;margin-right:5px;font-weight:bold;'>NEW</span> "
            if item["is_new"]
            else ""
        )
        html += (
            f"<tr {bg_style}>"
            f"<td style='padding:8px;text-align:center;'>{idx}</td>"
            f"<td style='padding:8px;text-align:center;'>{item['category']}</td>"
            f"<td style='padding:8px;text-align:center;'>{item['keyword']}</td>"
            f"<td style='padding:8px;'>{badge}"
            f"<a href='{item['link']}' style='color:#0066cc;font-weight:bold;"
            f"text-decoration:none;'>{item['title']}</a></td>"
            f"<td style='padding:8px;'>{item['org']}</td>"
            f"<td style='padding:8px;text-align:center;'>{item['date']}</td>"
            f"<td style='padding:8px;color:blue;font-weight:bold;'>{item['budget']}</td>"
            f"</tr>"
        )

    html += "</table>"
    return html


def send_naver_email(subject, html_content):
    if not NAVER_EMAIL or not NAVER_PASSWORD:
        print("네이버 메일 설정이 없어 메일을 보내지 않습니다.")
        return False

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = formataddr((str(Header("발주계획 알림봇", "utf-8")), NAVER_EMAIL))
    msg["To"] = NAVER_EMAIL
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.naver.com", 465) as server:
            server.login(NAVER_EMAIL, NAVER_PASSWORD)
            server.sendmail(NAVER_EMAIL, [NAVER_EMAIL], msg.as_string())
        print(f"네이버 메일 발송 완료: {NAVER_EMAIL}")
        return True
    except smtplib.SMTPException as exc:
        print(f"네이버 메일 발송 실패: {exc}")
        return False


def send_teams_alert(items, new_count, date_str, errors):
    if not TEAMS_WEBHOOK_URL:
        print("MS Teams 웹훅 URL이 설정되지 않아 알림을 건너뜁니다.")
        return

    # 🎯 [신형 팀즈 워크플로우 규격 반영] MessageCard 포맷 구조화
    if errors and not items:
        title = f"🚨 나라장터 발주계획 조회 오류 ({date_str})"
        text = "\n".join([f"- {e}" for e in errors])
    else:
        title = f"📋 나라장터 발주계획 리포트 ({date_str})"
        text = f"**총 {len(items)}건 수집 / 신규 {new_count}건**\n\n"
        for idx, item in enumerate(items[:20], 1):
            badge = "🔥[NEW] " if item["is_new"] else ""
            text += (
                f"{idx}. {badge}[{item['category']}] [{item['title']}]({item['link']})  \n"
                f"   - **기관**: {item['org']} | **등록일**: {item['date']} | **예산**: {item['budget']}  \n"
                f"   - **키워드**: {item['keyword']}\n\n"
            )

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "0078D7",
        "title": title,
        "text": text
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        TEAMS_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            response.read()
        print("MS Teams 알림 발송 완료")
    except Exception as exc:
        print(f"MS Teams 알림 발송 중 오류 발생: {exc}")


def send_alerts(items, new_count, errors):
    kst_now = get_current_kst()
    date_str = kst_now.strftime("%m/%d %H시")

    if errors and not items:
        subject = f"[오류] 나라장터 발주계획 조회 실패 ({date_str})"
    elif new_count > 0:
        subject = f"[NEW {new_count}건] 나라장터 발주계획 알림 ({date_str})"
    else:
        subject = f"나라장터 발주계획 리포트 ({date_str})"

    html = build_html_report(items, errors, new_count, date_str)

    # 1. 메일 발송
    send_naver_email(subject, html)
    # 2. 새로운 팀즈 워크플로우에 맞춤 발송
    send_teams_alert(items, new_count, date_str, errors)

    if items:
        print(f"검색 완료: {len(items)}건 (신규 {new_count}건)")
    elif errors:
        print("검색 실패: API 조회 중 오류가 발생했습니다.")
    else:
        print("검색 완료: 조건에 맞는 발주계획이 없습니다.")


if __name__ == "__main__":
    raw_items, api_errors = get_g2b_data()
    compared_items, new_detected = load_and_compare(raw_items)
    send_alerts(compared_items, new_detected, api_errors)