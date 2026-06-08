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

# 2. 사장님이 픽하신 4대 핵심 키워드
KEYWORDS = ['스쿨넷', '융합통신망', '교육망', '스마트기기']


def get_jodal_pblanc():
    """최근 30일치 공고를 수집해서 오늘 기준 신규/진행중 분류하기"""
    now = datetime.datetime.now()
    today_str = now.strftime('%Y%m%d')

    # 30일 전 날짜 계산
    thirty_days_ago = (now - datetime.timedelta(days=30)).strftime('%Y%m%d')

    new_items = []  # 오늘(00:00 이후) 새로 등록된 공고
    ongoing_items = []  # 최근 30일간 등록되어 진행 중인 공고

    # 조달청 용역(Servc) 및 물품(Thng) 공고 API 주소
    urls = [
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch",
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch"
    ]

    for url in urls:
        params = {
            'serviceKey': API_KEY,
            'numOfRows': '300',  # 한 달 치를 여유롭게 가져오기 위해 300건 지정
            'pageNo': '1',
            'inqryDiv': '1',  # 공고게시일시 기준 조회
            'inqryBgnDt': thirty_days_ago + '0000',
            'inqryEndDt': today_str + '2359',
            'type': 'json'
        }

        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get('response', {}).get('body', {}).get('items', [])
                if isinstance(items, list):
                    for item in items:
                        title = item.get('bidNtceNm', '')

                        # 키워드가 포함되어 있는지 검사
                        if any(kw in title for kw in KEYWORDS):
                            bgng_dt_str = item.get('bidNtceBgngDt', '')  # 예: "2026-06-08 10:30:00"

                            pblanc_data = {
                                'title': title,
                                'url': item.get('bidNtceDtlUrl', '#'),
                                'inst': item.get('demandInsttNm', '알수없음'),
                                'date': bgng_dt_str
                            }

                            # 날짜 분류 (오늘 날짜 글자가 게시일시에 포함되어 있다면 신규)
                            if today_str in bgng_dt_str.replace('-', ''):
                                new_items.append(pblanc_data)
                            else:
                                ongoing_items.append(pblanc_data)
        except Exception as e:
            print(f"공고 조회 중 에러 발생: {e}")

    return new_items, ongoing_items


def make_teams_text(new_items, ongoing_items):
    """팀즈 채팅방 발송용 텍스트 포맷 구성"""
    msg = "📢 **[나라장터] 교육망/스마트기기 공고 모니터링 리포트**\n\n"

    if new_items:
        msg += "🔥 **오늘 새로 업데이트된 신규 공고!**\n"
        for idx, item in enumerate(new_items, 1):
            msg += f"{idx}. ✨ **[신규] {item['title']}**\n"
            msg += f"   - 수요기관: {item['inst']}\n"
            msg += f"   - 게시일시: {item['date']}\n"
            msg += f"   - [공고 상세 링크 클릭]({item['url']})\n\n"
    else:
        msg += "오늘 새로 등록된 신규 공고는 없습니다.\n\n"

    msg += "--------------------------------------------------\n"
    msg += "📅 **최근 30일간 진행 중인 공고 리스트**\n\n"

    if ongoing_items:
        for idx, item in enumerate(ongoing_items, 1):
            msg += f"{idx}. **{item['title']}**\n"
            msg += f"   - 수요기관: {item['inst']} | 게시일: {item['date'][:10]}\n"
            msg += f"   - [공고 상세 링크 클릭]({item['url']})\n\n"
    else:
        msg += "최근 30일간 진행 중인 공고가 없습니다.\n"

    return msg


def send_all(new_items, ongoing_items):
    """팀즈와 네이버 메일로 최종 발송하기"""
    if not new_items and not ongoing_items:
        print("검색된 공고가 없어 발송을 생략합니다.")
        return

    # [1] 팀즈 채팅방으로 쏘기
    teams_text = make_teams_text(new_items, ongoing_items)
    if TEAMS_WEBHOOK_URL:
        try:
            requests.post(TEAMS_WEBHOOK_URL, json={"text": teams_text}, timeout=10)
            print("팀즈 알림 전송 완료")
        except Exception as e:
            print(f"팀즈 전송 실패: {e}")

    # [2] 네이버 메일로 종합 리포트 쏘기
    if NAVER_EMAIL and NAVER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = NAVER_EMAIL
        msg['To'] = NAVER_EMAIL  # 나 자신에게 메일 보내기
        msg['Subject'] = f"🔔 [조달청 리포트] 신규 {len(new_items)}건 / 진행중 {len(ongoing_items)}건이 있습니다."

        # HTML 메일 본문 작성 (신규 공고는 연한 빨간색 박스로 강조)
        html = f"<h2>나라장터 키워드 매칭 종합 리포트</h2>"
        html += f"<p><b>조회 키워드:</b> {', '.join(KEYWORDS)}</p><hr>"

        html += "<h3>🔥 오늘 새로 업데이트된 공고 (신규)</h3>"
        if new_items:
            for item in new_items:
                html += f"<div style='background-color: #ffe6e6; padding: 10px; margin-bottom: 10px; border-left: 5px solid red;'>"
                html += f"<b>[신규] {item['title']}</b><br>"
                html += f"수요기관: {item['inst']} | 게시일시: {item['date']}<br>"
                html += f"<a href='{item['url']}'>👉 공고 바로가기</a></div>"
        else:
            html += "<p style='color: gray;'>오늘 등록된 신규 공고가 없습니다.</p>"

        html += "<br><h3>📅 최근 30일간 진행 중인 공고</h3><table border='1' cellpadding='5' style='border-collapse:collapse; width:100%;'>"
        html += "<tr style='background-color:#f2f2f2;'><th>공고명</th><th>수요기관</th><th>게시일</th></tr>"

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
    print("나라장터 알림 로봇 구동 중...")
    new_list, ongoing_list = get_jodal_pblanc()
    send_all(new_list, ongoing_list)