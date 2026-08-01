import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
TENANT_ID = os.environ.get("TENANT_ID")

# 테스트용 Service URL 및 Conversation ID
TEST_SERVICE_URL = "https://smba.trafficmanager.net/amer/"
TEST_CONVERSATION_ID = os.environ.get("CONVERSATION_ID")

ANNOUNCEMENT_TEXT = (
    "📢 **[TeamsSync 공지사항]**\n\n"
    "약관 및 개인정보 처리방침이 업데이트되었습니다. 1:1 봇 대화방을 통해 안내드립니다!"
)

async def get_bot_token(http_client: httpx.AsyncClient) -> str | None:
    """Bot Framework 토큰 발급 함수 (상세 에러 출력 포함)"""
    # 표준 Bot Framework 토큰 발급 엔드포인트
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    
    payload = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'https://api.botframework.com/.default'
    }
    
    try:
        response = await http_client.post(url, data=payload, timeout=10.0)
        
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            print(f"❌ [Bot Token Error {response.status_code}]")
            print(f"📄 상세 응답 내용: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ [Network/Token Exception]: {e}")
        return None


async def send_announcement(
    http_client: httpx.AsyncClient, 
    service_url: str, 
    conversation_id: str, 
    bot_token: str, 
    message_text: str
):
    """Teams 1:1 대화방 메시지 전송 함수"""
    if not service_url.endswith('/'):
        service_url += '/'
        
    endpoint = f"{service_url}v3/conversations/{conversation_id}/activities"
    
    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "type": "message",
        "text": message_text
    }
    
    try:
        res = await http_client.post(endpoint, json=payload, headers=headers, timeout=10.0)
        
        if res.status_code in [200, 201, 202]:
            print("🎉 [성공] Teams 1:1 대화방으로 공지 메시지가 정상 발송되었습니다!")
            return res.json()
        else:
            print(f"❌ [발송 실패] 코드: {res.status_code}, 내용: {res.text}")
            return None
    except Exception as e:
        print(f"❌ [Send Message Exception]: {e}")
        return None


async def main():
    async with httpx.AsyncClient() as http_client:
        token = await get_bot_token(http_client)
        if token and TEST_CONVERSATION_ID:
            await send_announcement(
                http_client=http_client,
                service_url=TEST_SERVICE_URL,
                conversation_id=TEST_CONVERSATION_ID,
                bot_token=token,
                message_text=ANNOUNCEMENT_TEXT
            )
        else:
            print("⚠️ 토큰 발급에 실패했거나 CONVERSATION_ID가 .env에 세팅되지 않았습니다.")

if __name__ == "__main__":
    asyncio.run(main())