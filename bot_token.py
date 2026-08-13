import os
import httpx
from dotenv import load_dotenv
from temp_http_client import safe_http_request
import logging

load_dotenv()

CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
TENANT_ID = os.environ.get("TENANT_ID")

# [LOGGER & ANONYMIZATION]
logger = logging.getLogger("ScheduleBot")
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

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
        response = await safe_http_request(http_client, "POST", url, data=payload, timeout=10.0)
        
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            logger.error(f"[Bot Token Error] Status: {response.status_code}, Body: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"[Network/Token Exception]: {e}",exc_info=True)
        return None