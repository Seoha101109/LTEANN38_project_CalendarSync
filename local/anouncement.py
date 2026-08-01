import requests
import os
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.environ.get("TENANT_ID")
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")

def get_bot_token():
    url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
    payload = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'https://api.botframework.com/.default' # Graph가 아닌 Bot Framework scope
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json()['access_token']

def send_announcement(service_url: str, conversation_id: str, bot_token: str, message_text: str):
    # serviceUrl 끝에 '/' 처리
    if not service_url.endswith('/'):
        service_url += '/'
        
    # 메시지 전송 엔드포인트 조립
    endpoint = f"{service_url}v3/conversations/{conversation_id}/activities"
    
    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "type": "message",
        "text": message_text
    }
    
    res = requests.post(endpoint, json=payload, headers=headers)
    
    if res.status_code in [200, 201, 202]:
        print("🎉 [성공] Teams 1:1 대화방으로 공지 메시지가 정상 발송되었습니다!")
        return res.json()
    else:
        print(f"❌ [실패] 코드: {res.status_code}, 내용: {res.text}")
        return None
    
# --- 수집한 데이터 세팅 ---
# 웹훅 로그에서 같이 들어온 serviceUrl (없으면 일단 아래 표준 URL 테스트)
TEST_SERVICE_URL = "https://smba.trafficmanager.net/amer/" 

#conversation.id
TEST_CONVERSATION_ID = os.environ.get("CONVERSATION_ID")

ANNOUNCEMENT_TEXT = "📢 **[TeamsSync 공지사항]**\n\n약관 및 개인정보 처리방침이 업데이트되었습니다. 1:1 봇 대화방을 통해 안내드립니다!"

# --- 실행 ---
token = get_bot_token()
send_announcement(
    service_url=TEST_SERVICE_URL,
    conversation_id=TEST_CONVERSATION_ID,
    bot_token=token,
    message_text=ANNOUNCEMENT_TEXT
)