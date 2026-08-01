import google.generativeai as genai

from dotenv import load_dotenv
import os

# load .env
load_dotenv()


# 1. API 키 설정 및 앱 생성
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

print("🔍 내 API 키로 사용 가능한 모델 목록:")
# 구글 서버에 접속해서 사용 가능한 모델을 모두 가져와서 출력합니다.
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(f"- {m.name}")