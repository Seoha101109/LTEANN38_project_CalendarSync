import os
import msal
import requests
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
TEAM_ID = os.getenv('TEAM_ID')
CHANNEL_ID = os.getenv('CHANNEL_ID')


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
    print("❌ [Token Error] 토큰 발급 실패:", token_result.get("error_description"))

access_token = token_result["access_token"]
    
graph_url = f"https://graph.microsoft.com/v1.0/teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

response = requests.get(graph_url, headers=headers)

if response.status_code == 200:
    messages = response.json().get("value", [])
    print(f"✨ [Success] {len(messages)}개의 메시지를 채널에서 가져왔습니다.")
    print(messages)
else:
    print(f"❌ [Graph API Error] 데이터 접근 실패 ({response.status_code}): {response.text}")