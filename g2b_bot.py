import os
import requests
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. 깃허브에서 안전하게 읽어올 환경변수 설정
API_KEY = os.environ.get('DATA_GO_KR_API_KEY')
TEAMS_WEBHOOK_URL = os.environ.get('TEAMS_WEBHOOK_URL')
NAVER_EMAIL = os.environ.get('NAVER_EMAIL')
NAVER_PASSWORD = os.environ.get('NAVER_PASSWORD')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')

# 2. 사장님의 핵심 검색 키워드 4개
KEYWORDS = ['스쿨넷', '융합통신망', '교육망', '스마트기기']


def get_jodal_pblanc():
    """최근 6개월치 '발주계획'과 '입찰공고'를 모두 수집해서 분류하기"""
    now = datetime.datetime.now()
    today_str = now.strftime('%Y%m%d')
    six_months_ago = (now - datetime.timedelta(days=180)).strftime('%Y%m%d')

    new_items = []  # 오늘 새로 등록된 건 [최신 업데이트]
    ongoing_items = []  # 진행 중인 건

    # 🌟 사장님 화면에 맞춰 '발주계획(OrderPlan)' API 주소를 최상단에 전격 추가!
    urls = [
        "http://apis.data.go.kr/1230000/OrderPlanInfoService02/getOrderPlanListInfoPPSSrch",  # 발주계획 API
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch",  # 입찰공고(용역)
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch"  # 입찰공고(물품)
    ]

    for url in urls:
        params = {
            'serviceKey': API_KEY,
            'numOfRows': '999',
            'pageNo': '1',
            'inqryDiv': '1',
            'inqryBgnDt': six_months_ago + '0000',
            'inqryEndDt': today_str + '2359',
            'type': 'json'
        }

        try:
            response = requests.get(url, params=params, timeout=20)
            if response.status_code == 200:
                data = response.json()
                items = data.get('response', {}).get('body', {}).get('items', [])
                if isinstance(items, list):
                    for item in items:
                        # 발주계획과 입찰공고의 데이터 이름(태그명) 차이 해결
                        title = item.get('bidNtceNm') or item.get('bsnsNm', '')  # 사업명/공고명
                        inst = item.get('demandInsttNm', '알수없음')  # 수요기관
                        url_link = item.get('bidNtceDtlUrl') or item.get('orderPlanDtlUrl', '#')  # 상세링크

                        # 등록일시 추출 (발주계획은 'registDt', 입찰공고는 'bidNtceBgngDt')
                        bgng_dt_str = item.get('bidNtceBgngDt') or item.get('registDt', '')

                        # 구분표시 (발주계획인지 입찰공고인지 제목에 붙여주기)
                        type_tag = "[발주계획]" if "OrderPlan" in url else "[입찰공고]"
                        full_title = f"{type_tag} {title}"

                        # 키wl드가 포함되어 있는지 검사
                        if any(kw in title for kw in KEYWORDS):
                            pblanc_data = {
                                'title': full_title,
                                'url': url_link,
                                'inst': inst,
                                'date': bgng_dt_str
                            }

                            # 오늘 날짜 분기 처리
                            if today_str in bgng_dt_str.replace('-', ''):
                                new_items.append(pblanc_data)
                            else:
                                ongoing_items.append(pblanc_data)
        except Exception as e:
            print(f"조회 중 에러 발생: {e}")

    return new_items, ongoing_items


def make_messenger_text(new_items, ongoing_items):
    """팀즈 및 슬랙 발송용 메신저 텍스트 포맷 구성"""
    msg = "📢 *[나라장터] 교육망/스마트기기 공고 모니터링 리포트*\n\n"

    if new_items:
        msg += "🔥 *오늘 새로 올라온 공고! [최신 업데이트]*\n"
        for idx, item in enumerate(new_items, 1):
            msg += f"{idx}. ✨ *[최신 업데이트] {item['title']}*\n"
            msg += f"   - 수요기관: {item['inst']}\n"
            msg += f"   - 등록일시: {item['date']}\n"
            msg += f"   - [공고 상세 링크 클릭]({item['url']})\n\n"
    else:
        msg += "오늘 새로 등록된 최신 공고는 없습니다.\n\n"

    msg += "--------------------------------------------------\n"
    msg += "📅 *최근 6개월간 진행 중인 공고/발주 리스트*\n\n"

    if ongoing_items:
        for idx, item in enumerate(ongoing_items, 1):
            msg += f"{idx}. *{item['title']}*\n"
            msg += f"   - 수요기관: {item['inst']} | 등록일: {item['date'][:10]}\n"
            msg += f"   - [공고 상세 링크 클릭]({item['url']})\n\n"
    else:
        msg += "최근 6개월간 진행 중인 공고가 없습니다.\n"

    return msg


def send_all(new_items, ongoing_items):
    """팀즈, 네이버 메일, 슬랙으로 최종 발송하기"""
    if not new_items and not ongoing_items:
        print("검색된 공고가 없어 발송을 생략합니다.")
        return

    messenger_text = make_messenger_text(new_items, ongoing_items)

    # [1] 팀즈 채팅방으로 쏘기
    if TEAMS_WEBHOOK_URL:
        try:
            requests.post(TEAMS_WEBHOOK_URL, json={"text": messenger_text}, timeout=10)
            print("팀즈 알림 전송 완료")
        except Exception as e:
            print(f"팀즈 전송 실패: {e}")

    # [2] 슬랙 채널로 쏘기
    if SLACK_TOKEN and SLACK_CHANNEL:
        try:
            slack_url = "https://slack.com/api/chat.postMessage"
            headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}
            payload = {"channel": SLACK_CHANNEL, "text": messenger_text}
            res = requests.post(slack_url, headers=headers, json=payload, timeout=10)
            if res.json().get('ok'):
                print("슬랙 알림 전송 완료")
            else:
                print(f"슬랙 발송 실패(API 에러): {res.json()}")
        except Exception as e:
            print(f"슬랙 전송 실패: {e}")

    # [3] 네이버 메일로 종합 리포트 쏘기
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = NAVER_EMAIL
        msg['To'] = NAVER_EMAIL
        msg['Subject'] = f"🔔 [조달청 리포트] 신규 {len(new_items)}건 / 6개월 누적 {len(ongoing_items)}건이 있습니다."

        html = f"<h2>나라장터 키워드 매칭 종합 리포트 (6개월)</h2>"
        html += f"<p><b>조회 키워드:</b> {', '.join(KEYWORDS)}</p><hr>"

        html += "<h3>🔥 오늘 새로 올라온 공고 [최신 업데이트]</h3>"
        if new_items:
            for item in new_items:
                html += f"<div style='background-color: #ffe6e6; padding: 10px; margin-bottom: 10px; border-left: 5px solid red;'>"
                html += f"<b>[최신 업데이트] {item['title']}</b><br>"
                html += f"수요기관: {item['inst']} | 등록일시: {item['date']}<br>"
                html += f"<a href='{item['url']}'>👉 공고 바로가기</a></div>"
        else:
            html += "<p style='color: gray;'>오늘 등록된 최신 공고가 없습니다.</p>"

        html += "<br><h3>📅 최근 6개월간 진행 중인 공고/발주계획</h3><table border='1' cellpadding='5' style='border-collapse:collapse; width:100%;'>"
        html += "<tr style='background-color:#f2f2f2;'><th>구분 및 사업명</th><th>수요기관</th><th>등록일</th></tr>"

        if ongoing_items:
            for item in ongoing_items:
                html += f"<tr><td><a href='{item['url']}'>{item['title']}</a></td><td>{item['inst']}</td><td>{item['date'][:10]}</td></tr>"
        else:
            html += "<tr><td colspan='3' style='text-align:center; color:gray;'>진행 중인 공고가 없습니다.</td></tr>"
        html += "</table>"

        msg.attach(MIMEText(html, 'html', 'utf-8'))

        try:
            server = smtplib.SMTP_SSL('smtp.naver.com', 465)
            server.login(NAVER_EMAIL, NAVER_PASSWORD)
            server.sendmail(NAVER_EMAIL, NAVER_EMAIL, msg.as_string())
            server.close()
            print("네이버 종합 메일 발송 완료")
        except Exception as e:
            print(f"메일 발송 실패: {e}")


if __name__ == "__main__":
    print("나라장터 발주계획 통합 로봇 구동 중...")
    new_list, ongoing_list = get_jodal_pblanc()
    send_all(new_list, ongoing_list)