import os
import requests
import datetime
import smtplib
from urllib.parse import unquote
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. 환경변수 설정
API_KEY = os.environ.get('DATA_GO_KR_API_KEY')
TEAMS_WEBHOOK_URL = os.environ.get('TEAMS_WEBHOOK_URL')
NAVER_EMAIL = os.environ.get('NAVER_EMAIL')
NAVER_PASSWORD = os.environ.get('NAVER_PASSWORD')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')

# 2. 핵심 검색 키워드
KEYWORDS = ['스쿨넷', '융합통신망', '교육망', '스마트기기']

SEARCH_DAYS = 180
CHUNK_DAYS = 30

API_SOURCES = [
    {
        "url": "http://apis.data.go.kr/1230000/OrderPlanInfoService02/getOrderPlanListInfoPPSSrch",
        "type_tag": "[발주계획]",
        "title_keys": ("bsnsNm", "bizNm", "bidNtceNm"),
        "inst_keys": ("orderInsttNm", "demandInsttNm", "opntInsttNm"),
        "url_keys": ("orderPlanDtlUrl", "bidNtceDtlUrl"),
        "date_keys": ("rgstDt", "registDt", "bidNtceBgngDt")
    },
    {
        "url": "http://apis.data.go.kr/1230000/HrcspatBsisBizInfoService03/getHrcspatBsisBizListInfoPPSSrch",
        "type_tag": "[사전규격]",
        "title_keys": ("prdctClsfcNoNm", "bsnsNm", "bidNtceNm"),
        "inst_keys": ("orderInsttNm", "demandInsttNm", "opntInsttNm"),
        "url_keys": ("bfSpecDtlUrl", "bidNtceDtlUrl"),
        "date_keys": ("opninRgstClseDt", "rgstDt", "registDt")
    },
    {
        "url": "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch",
        "type_tag": "[입찰공고-용역]",
        "title_keys": ("bidNtceNm",),
        "inst_keys": ("dminsttNm", "demandInsttNm", "opntInsttNm"),
        "url_keys": ("bidNtceDtlUrl",),
        "date_keys": ("bidNtceBgngDt", "rgstDt", "registDt")
    },
    {
        "url": "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch",
        "type_tag": "[입찰공고-물품]",
        "title_keys": ("bidNtceNm", "prdrstIdntNoNm"),
        "inst_keys": ("dminsttNm", "demandInsttNm", "opntInsttNm"),
        "url_keys": ("bidNtceDtlUrl",),
        "date_keys": ("bidNtceBgngDt", "rgstDt", "registDt")
    }
]


def _normalize_service_key(api_key):
    if not api_key: return ''
    return unquote(api_key)


def _first_value(item, keys):
    for key in keys:
        value = item.get(key)
        if value: return value
    return ''


def _parse_items(body):
    items = body.get('items')
    if not items or items == '': return []
    if isinstance(items, dict):
        item = items.get('item', items)
        if isinstance(item, list): return item
        return [item] if item else []
    if isinstance(items, list): return items
    return [items]


def _get_safe_date_chunks(total_days, chunk_days):
    """🌟 핵심 수정: 조달청 서버 폭발을 막기 위해 '오늘'을 제외하고 '어제'부터 과거로 6개월 계산"""
    # 2026년 현재 한국 시간 기준 시차 보정
    kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    # 오늘(6일)이 아닌 어제(7일)를 기점으로 잡음으로써 500 에러를 원천 차단
    kst_yesterday = kst_now - datetime.timedelta(days=1)

    chunks = []
    end_date = kst_yesterday
    remaining = total_days

    while remaining > 0:
        span = min(chunk_days, remaining)
        start_date = end_date - datetime.timedelta(days=span)

        chunks.append((
            start_date.strftime('%Y%m%d') + '0000',
            end_date.strftime('%Y%m%d') + '2359'
        ))
        end_date = start_date
        remaining -= span

    return chunks, kst_now.strftime('%Y%m%d')


def _fetch_source_items(source, start_dt, end_dt, service_key):
    base_url = source['url']
    full_url = f"{base_url}?serviceKey={service_key}&type=json&inqryDiv=1&inqryBgnDt={start_dt}&inqryEndDt={end_dt}&pageNo=1&numOfRows=999"

    response = requests.get(full_url, timeout=15)
    response.raise_for_status()
    data = response.json()
    header = data.get('response', {}).get('header', {})
    if header.get('resultCode') != '00':
        raise RuntimeError(header.get('resultMsg', '알 수 없는 API 오류'))
    return _parse_items(data.get('response', {}).get('body', {}))


def get_jodal_pblanc():
    service_key = _normalize_service_key(API_KEY)
    if not service_key:
        print("DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return [], []

    new_items = []
    ongoing_items = []
    seen_urls = set()

    # 안전한 어제 날짜 기준의 6개월 구간 생성
    date_chunks, today_str = _get_safe_date_chunks(SEARCH_DAYS, CHUNK_DAYS)

    for source in API_SOURCES:
        for start_dt, end_dt in date_chunks:
            try:
                items = _fetch_source_items(source, start_dt, end_dt, service_key)
            except Exception as e:
                print(f"API 조회 오류 우회 [{source['type_tag']} / {start_dt}~{end_dt}]: {e}")
                continue

            for item in items:
                if not isinstance(item, dict): continue

                title = _first_value(item, source['title_keys'])
                if not title: continue

                if any(kw in title for kw in KEYWORDS):
                    url_link = _first_value(item, source['url_keys']) or '#'
                    if url_link in seen_urls: continue
                    seen_urls.add(url_link)

                    inst = _first_value(item, source['inst_keys']) or '알수없음'
                    date_str = _first_value(item, source['date_keys'])

                    pblanc_data = {
                        'title': f"{source['type_tag']} {title}",
                        'url': url_link,
                        'inst': inst,
                        'date': date_str
                    }

                    if today_str in date_str.replace('-', '').replace('/', ''):
                        new_items.append(pblanc_data)
                    else:
                        ongoing_items.append(pblanc_data)

    print(f"검색 완료: 신규 {len(new_items)}건 / 누적 {len(ongoing_items)}건")
    return new_items, ongoing_items


def make_messenger_text(new_items, ongoing_items):
    msg = "📢 *[나라장터] 통합 모니터링 리포트*\n\n"
    if new_items:
        msg += "🔥 *오늘 새로 올라온 정보! [최신 업데이트]*\n"
        for idx, item in enumerate(new_items, 1):
            msg += f"{idx}. ✨ *[최신 업데이트] {item['title']}*\n   - 수요기관: {item['inst']}\n   - 등록일시: {item['date']}\n   - [상세 링크 클릭]({item['url']})\n\n"
    else:
        msg += "오늘 새로 등록된 최신 정보는 없습니다.\n\n"
    msg += "--------------------------------------------------\n"
    msg += "📅 *최근 6개월간 누적 리스트*\n\n"
    if ongoing_items:
        for idx, item in enumerate(ongoing_items, 1):
            msg += f"{idx}. *{item['title']}*\n   - 수요기관: {item['inst']} | 등록일: {item['date'][:10]}\n   - [상세 링크 클릭]({item['url']})\n\n"
    else:
        msg += "최근 6개월간 매칭된 정보가 없습니다.\n"
    return msg


def send_all(new_items, ongoing_items):
    if not new_items and not ongoing_items:
        print("검색된 공고가 없어 발송을 생략합니다.")
        return
    messenger_text = make_messenger_text(new_items, ongoing_items)
    if TEAMS_WEBHOOK_URL:
        try:
            requests.post(TEAMS_WEBHOOK_URL, json={"text": messenger_text}, timeout=10)
        except:
            pass
    if SLACK_TOKEN and SLACK_CHANNEL:
        try:
            requests.post("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                          json={"channel": SLACK_CHANNEL, "text": messenger_text}, timeout=10)
        except:
            pass
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = NAVER_EMAIL;
        msg['To'] = NAVER_EMAIL
        msg['Subject'] = f"🔔 [조달청 리포트] 신규 {len(new_items)}건 / 6개월 누적 {len(ongoing_items)}건이 있습니다."
        html = f"<h2>나라장터 키워드 매칭 종합 리포트 (6개월)</h2><p><b>조회 키워드:</b> {', '.join(KEYWORDS)}</p><hr><h3>🔥 오늘 새로 올라온 정보 [최신 업데이트]</h3>"
        if new_items:
            for item in new_items: html += f"<div style='background-color: #ffe6e6; padding: 10px; margin-bottom: 10px; border-left: 5px solid red;'><b>{item['title']}</b><br>수요기관: {item['inst']} | 등록일시: {item['date']}<br><a href='{item['url']}'>👉 바로가기</a></div>"
        else:
            html += "<p style='color: gray;'>오늘 등록된 최신 정보가 없습니다.</p>"
        html += "<br><h3>📅 최근 6개월간 진행 중인 정보</h3><table border='1' cellpadding='5' style='border-collapse:collapse; width:100%;'><tr style='background-color:#f2f2f2;'><th>구분 및 사업명</th><th>수요기관</th><th>등록일</th></tr>"
        if ongoing_items:
            for item in ongoing_items: html += f"<tr><td><a href='{item['url']}'>{item['title']}</a></td><td>{item['inst']}</td><td>{item['date'][:10]}</td></tr>"
        else:
            html += "<tr><td colspan='3' style='text-align:center; color:gray;'>내역이 없습니다.</td></tr>"
        html += "</table>";
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        try:
            server = smtplib.SMTP_SSL('smtp.naver.com', 465)
            server.login(NAVER_EMAIL, NAVER_PASSWORD);
            server.sendmail(NAVER_EMAIL, NAVER_EMAIL, msg.as_string());
            server.close()
            print("네이버 종합 메일 발송 완료")
        except:
            pass


if __name__ == "__main__":
    print("나라장터 전방위 통합 감시 로봇 구동 중...")
    new_list, ongoing_list = get_jodal_pblanc()
    send_all(new_list, ongoing_list)