# channel_export.py
import os
import msal
import httpx
from dotenv import load_dotenv
import logging

load_dotenv()

TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')

logger = logging.getLogger("ScheduleBot")

def get_graph_access_token():
    """MS Graph API 전용 App Access Token을 발급합니다."""
    authority_url = f"https://login.microsoftonline.com/{TENANT_ID}"

    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        authority=authority_url,
        client_credential=CLIENT_SECRET
    )

    scopes = ["https://graph.microsoft.com/.default"]
    token_result = app.acquire_token_for_client(scopes=scopes)

    if "access_token" not in token_result:
        logger.error(f"❌ [Token Error] 토큰 발급 실패: {token_result.get('error_description')}")
        return None

    return token_result["access_token"]


async def channel_export(TEAM_ID: str, CHANNEL_ID: str, access_token: str = None):
    """채널 내 모든 메시지를 비동기로 가져옵니다."""
    if not access_token:
        access_token = get_graph_access_token()
        
    if not access_token:
        return []
    
    graph_url = f"https://graph.microsoft.com/v1.0/teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages?$top=50"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    all_messages = []

    # 비동기 AsyncClient 사용
    async with httpx.AsyncClient(timeout=15.0) as client:
        while graph_url:
            response = await client.get(graph_url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                messages = data.get("value", [])
                all_messages.extend(messages)
                
                graph_url = data.get("@odata.nextLink")
            else:
                logger.error(f"❌ [Graph API Error] 데이터 접근 실패 ({response.status_code}): {response.text}")
                break

    logger.info(f"✨ [Success] 총 {len(all_messages)}개의 메시지를 채널({CHANNEL_ID})에서 가져왔습니다.")
    return all_messages