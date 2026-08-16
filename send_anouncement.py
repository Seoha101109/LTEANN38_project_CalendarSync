import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import httpx

from database import SessionLocal
import models
from bot_token import get_bot_token
from temp_http_client import safe_http_request  # 기존 작성한 HTTP 안전 요청 함수
import hashlib
from typing import Optional

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def get_anonymous_id(identity_string: Optional[str]) -> str:
    """실명, 유저 ID, 이메일 등을 SHA-256 해시 기반 8자리 익명 ID로 변환 (로그 개인정보 보호)"""
    if not identity_string:
        return "anon_unknown"
    return hashlib.sha256(identity_string.encode()).hexdigest()[:8]

SERVICE_URL = os.environ.get("SERVICE_URL")

# --- 1. 유저별 오늘 일정 조회 (MS Graph API) ---
async def fetch_today_events(http_client: httpx.AsyncClient, user_id, access_token: str) -> list:
    """사용자의 오늘(00:00 ~ 23:59 KST) 일정 목록을 조회합니다."""
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    
    start_of_day = now_kst.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end_of_day = now_kst.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

    url = f"https://graph.microsoft.com/v1.0/users/{user_id}/calendarView?startDateTime={start_of_day}&endDateTime={end_of_day}"
    headers = {"Authorization": f"Bearer {access_token}"}
    anon_user_id = get_anonymous_id(user_id)
    try:
        res = await safe_http_request(http_client, "GET", url, headers=headers)
        if res and res.status_code == 200:
            events = res.json().get("value", [])
            return [f"- {e.get('subject')} ({e.get('start', {}).get('dateTime')[11:16]}~)" for e in events]
    except Exception as e:
        logger.error(f"일정 조회 실패 ({anon_user_id}): {e}")
    return []


# --- 2. Teams 1:1 메시지 전송 ---
async def send_teams_message(http_client: httpx.AsyncClient, conversation_id: str, bot_token: str, message_text: str):
    if not SERVICE_URL:
        return
        
    service_url = SERVICE_URL if SERVICE_URL.endswith('/') else SERVICE_URL + '/'
    endpoint = f"{service_url}v3/conversations/{conversation_id}/activities"
    headers = {'Authorization': f'Bearer {bot_token}', 'Content-Type': 'application/json'}
    payload = {"type": "message", "text": message_text}

    try:
        await safe_http_request(http_client, "POST", endpoint, json=payload, headers=headers, timeout=10.0)
    except Exception as e:
        logger.error(f"Teams 알림 발송 실패: {e}")


# --- 3. 유저 1명 단위 비동기 처리 파이프라인 ---
async def process_user_daily_notification(http_client: httpx.AsyncClient, user, bot_token: str):
    conv_id = getattr(user, 'conversation_id', None)
    access_token = getattr(user, 'access_token', None) # DB에 저장된 유저 토큰

    if not conv_id or not access_token:
        return

    # 1. 오늘 일정 가져오기
    events = await fetch_today_events(http_client, user, access_token)
    
    # 2. 메시지 본문 구성
    if events:
        
        event_str = "\n".join(events)
        msg = f"**[오늘의 일정 알림]**\n{event_str}"
    else:
        msg = "**[오늘의 일정 알림]**\n\n오늘은 등록된 일정이 없습니다. 즐거운 하루 되세요!"

    # 3. Teams 메시지 발송
    await send_teams_message(http_client, conv_id, bot_token, msg)


# --- 4. 메인 스케줄러 바인딩용 함수 ---
async def run_daily_schedule_job(global_http_client: httpx.AsyncClient):
    """매일 정시에 실행될 작업 메인 진입점"""
    logger.info("⏰ [Daily Scheduler] 오늘 일정 알림 발송 작업을 시작합니다.")
    
    db = SessionLocal()
    try:
        all_users = db.query(models.User).all() if hasattr(models, 'User') else []
        bot_token = await get_bot_token(global_http_client)
        
        if not bot_token:
            logger.error("Bot 토큰 발급 실패로 알림 발송 중단")
            return

        # asyncio.gather로 전체 유저 병렬(Parallel) 처리
        tasks = [
            process_user_daily_notification(global_http_client, user, bot_token)
            for user in all_users
        ]
        await asyncio.gather(*tasks)
        logger.info(f"🎉 총 {len(all_users)}명 유저 대상 일일 알림 발송 완료")
        
    finally:
        db.close()