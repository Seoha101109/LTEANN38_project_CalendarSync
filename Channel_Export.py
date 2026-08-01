#channel_export.py
import os
import msal
import requests
from dotenv import load_dotenv
import logging

load_dotenv()

TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')

logger = logging.getLogger("ScheduleBot")
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# 1. 토큰 발급 전용 함수로 분리
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
        logger.error("❌ [Token Error] 토큰 발급 실패:", token_result.get("error_description"))
        return None

    return token_result["access_token"]


# 2. 모든 메시지를 가져오도록 수정한 함수
def channel_export(TEAM_ID: str, CHANNEL_ID: str):
    access_token = get_graph_access_token()
    if not access_token:
        return []
    
    # 💡 $top=50으로 늘려 API 호출 횟수 최적화
    graph_url = f"https://graph.microsoft.com/v1.0/teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages?$top=50"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    all_messages = []

    # 💡 nextLink가 존재하는 동안 계속 다음 페이지를 가져오는 루프
    while graph_url:
        response = requests.get(graph_url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            messages = data.get("value", [])
            all_messages.extend(messages)
            
            # 다음 페이지 주소 갱신 (없으면 None이 되어 루프 종료)
            graph_url = data.get("@odata.nextLink")
        else:
            logger.error(f"❌ [Graph API Error] 데이터 접근 실패 ({response.status_code}): {response.text}")
            break

    logger.info(f"✨ [Success] 총 {len(all_messages)}개의 메시지를 채널에서 성공적으로 가져왔습니다.")
    return all_messages