import os
import httpx
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
TENANT_ID = os.environ.get("TENANT_ID")

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