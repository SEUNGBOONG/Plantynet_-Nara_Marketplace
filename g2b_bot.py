import os
import requests
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. 환경변수 설정
API_KEY = os.environ.get('DATA_GO_KR_API_KEY')
TEAMS_WEBHOOK_URL = os.environ.get('TEAMS_WEBHOOK_URL')
NAVER_EMAIL = os.environ.get('NAVER_EMAIL')
NAVER_PASSWORD = os.environ.get('NAVER_PASSWORD')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')

# 2. 사장님의 핵심 검색 키워드 4개
KEYWORDS = ['스쿨넷', '융합통신망', '교육망', '스마트기기']


def get_jodal_pblanc():
    """조달청 1개월 제한을 우회하기 위해 30일씩 6번(총 180일) 쪼개서 싹 긁어오기"""
    now = datetime.datetime.now()
    today_str = now.strftime('%Y%m%d')

    new_items = []
    ongoing_items = []
    seen_urls = set()  # 중복 데이터 제거용 방어벽

    urls = [
        "http://apis.data.go.kr/1230000/OrderPlanInfoService02/getOrderPlanListInfoPPSSrch",  # 발주계획
        "http://apis.data.go.kr/1230000/HrcspatBsisBizInfoService03/getHrcspatBsisBizListInfoPPSSrch",  # 사전규격
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch",  # 입찰공고(용역)
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch"  # 입찰공고(물품)
    ]

    # 🌟 180일을 30일씩 6번 쪼개서 턴을 돕니다 (조달청 API 에러 회피)
    for i in range(6):
        start_day = (now - datetime.timedelta(days=(i + 1) * 30)).strftime('%Y%m%d')
        end_day = (now - datetime.timedelta(days=i * 30)).strftime('%Y%m%d')

        for url in urls:
            params = {
                'serviceKey': API_KEY,
                'numOfRows': '999',
                'pageNo': '1',
                'inqryDiv': '1',
                'inqryBgnDt': start_day + '0000',
                'inqryEndDt': end_day + '2359',
                'type': 'json'
            }

            try:
                response = requests.get(url, params=params, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('response', {}).get('body', {}).get('items', [])
                    if isinstance(items, list):
                        for item in items:
                            title = item.get('bidNtceNm') or item.get('bsnsNm') or item.get('prdrstIdntNoNm', '')
                            inst = item.get('demandInsttNm') or item.get('opntInsttNm', '알수없음')
                            url_link = item.get('bidNtceDtlUrl') or item.get('orderPlanDtlUrl') or item.get(
                                'bfSpecDtlUrl', '#')
                            bgng_dt_str = item.get('bidNtceBgngDt') or item.get('registDt') or item.get('rgstDt', '')

                            # 중복 검사 및 키워드 매칭
                            if url_link not in seen_urls and any(kw in title for kw in KEYWORDS):
                                seen_urls.add(url_link)

                                if "OrderPlan" in url:
                                    type_tag = "[발주계획]"
                                elif "HrcspatBsis" in url:
                                    type_tag = "[사전규격]"
                                else:
                                    type_tag = "[입찰공고]"

                                pblanc_data = {
                                    'title': f"{type_tag} {title}",
                                    'url': url_link,
                                    'inst': inst,
                                    'date': bgng_dt_str
                                }

                                # 오늘 등록된 건지 분기
                                if today_str in bgng_dt_str.replace('-', ''):
                                    new_items.append(pblanc_data)
                                else:
                                    ongoing_items.append(pblanc_data)
            except Exception as e:
                pass  # 에러는 조용히 넘어가고 다음 턴 진행

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
        except Exception as e:
            print(f"메일 실패: {e}")


if __name__ == "__main__":
    print("나라장터 전방위 통합 감시 로봇 구동 중...")
    new_list, ongoing_list = get_jodal_pblanc()
    send_all(new_list, ongoing_list)