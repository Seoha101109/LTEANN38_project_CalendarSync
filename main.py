import os
import json
import base64
import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import asyncio
import time

from contextlib import asynccontextmanager
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, Response, BackgroundTasks
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import desc
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

import database
import models
from database import engine, SessionLocal, get_db
from calender_service import add_notice_to_calendar
from Channel_Export import channel_export, get_graph_access_token
from reset import resetdb


# ------------------------------------------------------------------
# 🪵 [LOGGER & ANONYMIZATION]
# ------------------------------------------------------------------
logger = logging.getLogger("ScheduleBot")
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def get_anonymous_id(identity_string: Optional[str]) -> str:
    """실명, 유저 ID, 이메일 등을 SHA-256 해시 기반 8자리 익명 ID로 변환 (로그 개인정보 보호)"""
    if not identity_string:
        return "anon_unknown"
    return hashlib.sha256(identity_string.encode()).hexdigest()[:8]

# -----------------------------------------------------------------
# Reset DB
# -----------------------------------------------------------------
if os.environ.get("RESET_DB", "false").lower() == "true":
    logger.warning("⚠️ [WARNING] DB 초기화를 진행합니다.")
    resetdb()

# ==============================================================================
# ⚙️ [HYPERPARAMETERS & CONFIGURATION]
# ==============================================================================
POLLS_PER_HOUR = int(os.getenv("POLLS_PER_HOUR", "6"))
POLLING_INTERVAL_MINUTES = 60 // POLLS_PER_HOUR
SCHEDULER_CRON_MINUTES = ",".join(str(i) for i in range(0, 60, POLLING_INTERVAL_MINUTES))

INITIAL_SYNC_LOOKBACK_DAYS = int(os.getenv("INITIAL_SYNC_LOOKBACK_DAYS", "7"))
DUPLICATE_WEBHOOK_DEBOUNCE_SECONDS = int(os.getenv("DUPLICATE_WEBHOOK_DEBOUNCE_SECONDS", "30"))
LLM_CONFIDENCE_THRESHOLD = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7"))
DEFAULT_USER_GRADE = int(os.getenv("DEFAULT_USER_GRADE", "1"))
# ==============================================================================

load_dotenv()
database.Base.metadata.create_all(bind=engine)

RECENT_SYNC_REQUESTS = {}

client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=0
    )
scheduler = AsyncIOScheduler()

#FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        auto_polling_sync_job, 
        'cron', 
        minute=SCHEDULER_CRON_MINUTES,
        misfire_grace_time=60,
        coalesce=True
    )
    scheduler.add_job(
        cleanup_inactive_users_job,
        'cron',
        hour=3,
        minute=0,
        misfire_grace_time=3600,
        coalesce=True
    )
    scheduler.start()

    yield  # <-- 서버가 정상 구동되는 시점

    scheduler.shutdown()


app = FastAPI(title="Teams Calendar Auto-Polling & Extract API", lifespan=lifespan)

# ------------------------------------------------------------------
# [Helper] 이메일 앞 2자리 추출을 통한 학년 자동 계산 함수
# ------------------------------------------------------------------
def calculate_grade_from_email(email: Optional[str], current_year: int) -> Optional[int]:
    """
    이메일 아이디의 앞 2자리 숫자를 입학 연도로 판단하여 학년을 계산합니다.
    예: '24abc@school.hs.kr', 2026년 기준 -> 2026 - 2024 + 1 = 3학년
    """
    if not email:
        return None
    
    username = email.split('@')[0]
    match = re.match(r'^(\d{2})', username)
    if match:
        entry_year_suffix = int(match.group(1))
        # 2000년대 입학생 기준 (필요시 1900년대 처리 추가 가능)
        entry_year = 2000 + entry_year_suffix
        grade = current_year - entry_year + 1
        
        # 정상적인 학년 범주(1~6학년)에 있는 경우만 반환
        if 1 <= grade <= 6:
            return grade
    return None

# ------------------------------------------------------------------
# [Pydantic Schemas] OpenAI Structured Output용 구조체
# ------------------------------------------------------------------
class ScheduleItem(BaseModel):
    title: str = Field(description="일정 제목")
    start_time: str = Field(description="시작 시간 (ISO 8601 포맷)")
    end_time: str = Field(description="종료 시간 (ISO 8601 포맷)")
    summary: Optional[str] = Field(
        default=None, 
        description="일정에 대한 핵심 요약 1~2줄 (예: 강당에서 과제연구기초 필수교육 진행, 자리는 공지 참고)"
    )
    location: Optional[str] = Field(
        default=None, 
        description="일정 장소 (메시지에 장소가 명시된 경우만 작성, 예: 창의인재관 4층 강당, 운동장)"
    )
    is_for_all_grades: bool = Field(
        description="전체 학년(전교생) 대상 일정이면 True, 특정 학년만 대상이면 False"
    )
    target_grades: List[int] = Field(
        default=[], 
        description="이 일정이 적용되는 학년 목록 (예: [1, 2], 특정 언급이 없거나 전교생 대상이면 빈 리스트)"
    )
    confidence: float = Field(description="일정 추출 신뢰도 (0.0 ~ 1.0)")
    
    @model_validator(mode='after')
    def validate_grades_logic(self):
        # target_grades에 데이터가 명시되어 있다면 is_for_all_grades는 무조건 False
        if self.target_grades:
            self.is_for_all_grades = False
        return self


class ExtractedSchedule(BaseModel):
    has_schedule: bool = Field(description="메시지 내에 유효한 일정 정보가 1개 이상 포함되어 있는지 여부")
    source: Optional[str] = Field(
        default=None, 
        description="일정 출처 또는 메시지 발신 출처 (예: 학년 공지, 학생회, 학급)"
    )
    schedules: List[ScheduleItem] = Field(
        default=[], 
        description="메시지에서 추출된 일정 목록 (일정이 없으면 빈 리스트)"
    )

# ------------------------------------------------------------------
# [Graph API Helper]
# ------------------------------------------------------------------
async def get_user_channels_from_graph(user_id: str, access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    discovered_channels = []

    async with httpx.AsyncClient() as http_client:
        teams_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/joinedTeams"
        try:
            teams_res = await http_client.get(teams_url, headers=headers)
            if teams_res.status_code != 200:
                logger.error(f"❌ [Graph API Error] 팀 목록 조회 실패 (Status: {teams_res.status_code})")
                return []

            teams = teams_res.json().get("value", [])

            for team in teams:
                team_id = team.get("id")
                team_name = team.get("displayName", "알 수 없는 팀")
                
                channels_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels"
                ch_res = await http_client.get(channels_url, headers=headers)

                if ch_res.status_code == 200:
                    channels = ch_res.json().get("value", [])
                    for ch in channels:
                        discovered_channels.append({
                            "team_id": team_id,
                            "team_name": team_name,
                            "channel_id": ch.get("id"),
                            "channel_name": ch.get("displayName")
                        })
                else:
                    logger.warning(f"팀 채널 조회 실패 ({ch_res.status_code})")

        except Exception as e:
            logger.error(f"❌ [Graph API Exception] 팀/채널 탐지 중 에러 발생: {e}")

    return discovered_channels
    
# ------------------------------------------------------------------
# [AI Helper Function] OpenAI GPT-4o-mini 멀티모달 분석
# ------------------------------------------------------------------
async def analyze_message_with_gpt(
    message_payload: dict, 
    graph_access_token: str = None, 
    target_user_name: str = None
) -> ExtractedSchedule:
    body_info = message_payload.get("body", {})
    raw_content = body_info.get("content", "")
    content_type = body_info.get("contentType", "text")

    image_base64_list = []
    clean_body = ""

    if content_type == "html" and raw_content:
        soup = BeautifulSoup(raw_content, "html.parser")
        
        if graph_access_token:
            img_tags = soup.find_all("img")
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                headers = {"Authorization": f"Bearer {graph_access_token}"}
                for img in img_tags:
                    img_url = img.get("src")
                    if img_url and "hostedContents" in img_url:
                        try:
                            res = await http_client.get(img_url, headers=headers, follow_redirects=True)
                            if res.status_code == 200:
                                b64_img = base64.b64encode(res.content).decode('utf-8')
                                image_base64_list.append(b64_img)
                        except Exception as e:
                            logger.warning(f"이미지 다운로드 실패: {e}")

        clean_body = soup.get_text(separator=" ", strip=True)
    else:
        clean_body = raw_content

    attachment_texts = []
    for att in message_payload.get("attachments", []):
        att_content = att.get("content")
        if att_content:
            if isinstance(att_content, str):
                try:
                    # JSON 형태의 배너 텍스트 파싱 (예: {"title": "[공지]단어시험..."})
                    parsed_att = json.loads(att_content)
                    if isinstance(parsed_att, dict) and "title" in parsed_att:
                        attachment_texts.append(f"[공지 배너]: {parsed_att['title']}")
                    else:
                        attachment_texts.append(att_content)
                except json.JSONDecodeError:
                    attachment_texts.append(att_content)
            elif isinstance(att_content, dict) and "title" in att_content:
                attachment_texts.append(f"[공지 배너]: {att_content['title']}")

    if attachment_texts:
        clean_body = "\n".join(attachment_texts) + "\n" + clean_body
    
    clean_body = clean_body[:2000]
    
    from_info = message_payload.get("from") or {}
    user_info = from_info.get("user") or {}
    sender_name = user_info.get("displayName") or "알 수 없음"
    subject = message_payload.get("subject", "")
    created_at = message_payload.get("createdDateTime", "")
    web_url = message_payload.get("webUrl", "")
    message_id = message_payload.get("id", "")

    user_context = f"- 현재 캘린더 주인 이름: {target_user_name}\n" if target_user_name else ""

    system_prompt = """너는 메신저 메시지와 이미지를 분석하여 사용자가 챙겨야 할 일정을 정확히 파악하고 extraction 객체 형태로 반환하는 AI 도우미야.

[0. 일정 추출 대상 (has_schedule = True)]
- 과제/보고서 제출 마감, 시험, 특강/세미나, 팀 프로젝트 미팅, 각종 프로그램/행사/아카데미 신청 및 모집 기간
- 구글 폼/설문/투표 마감, 개인 짐 정리, 성적 확인 및 정정 기간, 이의신청 기간 등 '사용자의 행동이 필요한 모든 마감/기간'은 중요하므로 has_schedule=True로 설정하고 confidence 높여.
- 단, 도서관 운영시간, 식당 메뉴, 단순 점검 등 일반 공지는 confidence를 낮춰줘 (교육/행사 안내는 정상 감지).

[1. 예외 대상(has_schedule = False)]
- **일정 제외 대상(매우 중요)**: "추후 안내", "추후 공지" 등 **구체적인 연/월/일(예: 8월 16일)이나 제출 마감 일시가 명시되지 않은 단순 안내글**은 "제출", "마감", "필요" 이런 핵심 키워드가 있어도 절대로 추출에서 제외(has_schedule=False).

[2. 다중 일정 처리]
- 하나의 메시지에 여러 일정(예: 1차 제출, 2차 제출, 최종 발표)이 있으면 각각 독립된 객체로 분리하여 `schedules` 배열에 담아 줘.
- 예시: "6/5 발표, 6/12 보고서 제출" -> schedules에 2개 객체 생성

[3. 제목 및 분류 규칙]
- 제목(`title`) 기본 형태: `[카테고리/과목] 핵심 내용` (예: [물리학] 물리학 성적 배부`)
- 제목이나 본문에 과목명이 포함되어 있으면 과목명을 최우선 구분자로 사용.

[4. 단일 마감 공지 처리 (매우 중요)]
- 본문에 시작일이 명시되지 않고 "~까지 모집/제출/신청" 등의 마감 표현만 있는 경우:
  1) start_time: end_time과 동일한 연/월/일의 00:00:00Z로 설정 (작성일 절대 금지!)
  2) end_time: 마감일 당일의 23:59:59Z로 설정
  3) title: 제목 끝에 반드시 '#마감' 태그 추가 ([1학년] 현송장학금 신청 마감#마감)
  
[5. 세부 추출 규칙]
- 일시(`start_time`, `end_time`): 시간을 모르는 당일 일정은 하루 종일(All-day) 이벤트로 처리.
- 작성일을 날짜 계산에 사용하는 유일한 경우는 상대적인 날짜 표현이 있을 경우이며, 절대로 작성일을 시작일 또는 종료일로 판단해선 안돼.
- **학년 판단 기준(매우 중요)**: 특정 학년(1학년, 신입생, 졸업반 등) 명시 시 반드시 'target_grades'에 명시된 학년 입력, 명시된 학년 없거나 전교생 대상이면 'target_grades'는 [] 처리.
- 수신자 검증: 이미지/본문에 캘린더 주인과 다른 타인의 이름이 지정된 개인 일정이면 무조건 has_schedule=False 처리.
- 과거 날짜 처리: 마감일이 메시지 작성일보다 과거라도 테스트/아카이빙 용도일 수 있으므로 감지에서 제외하거나 confidence를 낮추지 마.

[추가 보완 지침]
1. 마감 시간 정보: 본문에 "오전까지", "17시까지" 등 특정 시각이 지정된 경우 해당 시각을 end_time에 반영해 줘.
2. *누락 방지 (ALL-SCAN)(중요)*: 메시지 내에 번호(1., 2., 3...)나 항목별로 나열된 여러 개의 일정 또는 여러개의 시간대를 가진 일정들이 존재할 경우, 단 하나도 빠뜨리지 말고 모두 독립된 일정 객체로 추출하세요.
3. 학년 입력 규격: target_grades에는 한국 학교 시스템 기준의 숫자만 입력하세요. (고등학교의 경우 10, 11, 12가 아닌 1, 2, 3으로 표기)

[참고: 학교 교시별 시간표]
- 1교시(08:30~09:20), 2교시(09:30~10:20), 3교시(10:30~11:20), 4교시(11:30~12:20)
- 점심시간(12:20~13:10), 5교시(13:10~14:00), 6교시(14:10~15:00), 7교시(15:10~16:00)
"""

    user_text_prompt = f"""[유저 정보]
{user_context}
[메시지 메타데이터]
- 작성자: {sender_name}
- 작성 일시: {created_at}
- 메시지 ID: {message_id}
- Web URL: {web_url}

[메시지 내용]
- 제목: {subject}
- 본문: {clean_body}
"""

    user_content = [{"type": "text", "text": user_text_prompt}]
    for b64_img in image_base64_list:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64_img}", "detail": "auto"}
        })
    
    completion = await client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        response_format=ExtractedSchedule,
        temperature=0
    )
        
    return completion.choices[0].message.parsed


# ------------------------------------------------------------------
# [User Sync Logic] 유저 동기화 & 학년 동적 필터링 적용
# ------------------------------------------------------------------
async def sync_single_user(user_id: str, now_utc: datetime):
    db = SessionLocal()
    anon_user_id = get_anonymous_id(user_id)
    try:
        user = db.query(models.User).filter(models.User.user_id == user_id).first()
        if not user:
            return 0

        access_token = get_graph_access_token()
        
        target_email = None
        target_user_name = None
        
        # MS Graph API로부터 유저 메일 및 이름 조회
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            profile_res = await http_client.get(
                f"https://graph.microsoft.com/v1.0/users/{user_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if profile_res.status_code == 200:
                pdata = profile_res.json()
                target_email = pdata.get("mail") or pdata.get("userPrincipalName")
                target_user_name = pdata.get("displayName")

        calculated_grade = calculate_grade_from_email(target_email, now_utc.year)
        user_grade = getattr(user, "grade", None) or calculated_grade or DEFAULT_USER_GRADE

        if getattr(user, "grade", None) is None and calculated_grade:
            user.grade = calculated_grade
            db.commit()

        logger.info(f"👤 [Sync 시작] User({anon_user_id}), 학년: {user_grade}")
        
        last_log = (
            db.query(models.CalendarEventLog)
            .filter(
                models.CalendarEventLog.user_id == anon_user_id,
                models.CalendarEventLog.change_type == "auto_polling_sync"
            )
            .order_by(desc(models.CalendarEventLog.last_updated_time))
            .first()
        )

        if last_log and last_log.last_updated_time:
            log_time = last_log.last_updated_time
            if log_time.tzinfo is None:
                log_time = log_time.replace(tzinfo=timezone.utc)
            last_sync_time = log_time
        else:
            last_sync_time = now_utc - timedelta(days=INITIAL_SYNC_LOOKBACK_DAYS)

        user_channels = await get_user_channels_from_graph(user.user_id, access_token)
        if not user_channels:
            return 0

        gpt_semaphore = asyncio.Semaphore(3)
            
        async def analyze_single_message(msg):
            try:
                async with gpt_semaphore:
                    result = await analyze_message_with_gpt(
                        message_payload=msg,
                        graph_access_token=access_token,
                        target_user_name=target_user_name
                    )
                    await asyncio.sleep(1)
                    return result
            except Exception as e:
                logger.error(f"❌ 메시지 분석 최종 실패 (ID: {msg.get('id')}): {e}")
                return None

        # 3. 채널 1개를 처리하는 비동기 함수 (개수 Return 구조로 변경)
        async def process_channel(ch) -> int:
            channel_written = 0
            
            # 🚨 [수정 1] 동기 함수를 안전하게 비동기 스레드로 실행하여 이벤트 루프 차단 방지
            raw_messages = await channel_export(ch["team_id"], ch["channel_id"], access_token)
            if not raw_messages:
                return 0

            new_messages = []
            for msg in raw_messages:
                created_str = msg.get("createdDateTime")
                if created_str:
                    msg_time = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if msg_time > last_sync_time:
                        new_messages.append(msg)

            if not new_messages:
                return 0

            logger.info(f"📩 User({anon_user_id}) 채널({ch.get('channel_name', '알수없음')}) 신규 메시지 {len(new_messages)}개 발견! 분석 시작...")

            msg_tasks = [analyze_single_message(msg) for msg in new_messages]
            
            # 🚨 [수정 2] return_exceptions=True 적용하여 1개 실패해도 전체가 멈추지 않도록 설정
            extracted_data_list = await asyncio.gather(*msg_tasks, return_exceptions=True)

            logger.info(f"🔍 [디버그] LLM 응답 수신완료: 총 {len(extracted_data_list)}개 객체")

            for idx, extracted_data in enumerate(extracted_data_list):
                # 🚨 [수정 3] debug -> info로 변경하여 강제 출력
                if not extracted_data or isinstance(extracted_data, Exception):
                    logger.info(f"👉 [{idx+1}번 메시지 스킵] LLM 응답 없음 또는 예외 발생: {extracted_data}")
                    continue

                if not (getattr(extracted_data, 'has_schedule', False) and getattr(extracted_data, 'schedules', [])):
                    logger.info(f"👉 [{idx+1}번 메시지 탈락] 일정 없음 (has_schedule=False)")
                    continue

                for schedule_item in extracted_data.schedules:
                    if schedule_item.confidence < LLM_CONFIDENCE_THRESHOLD:
                        logger.info(f"⚠️ [{idx+1}번 메시지 탈락] 신뢰도 미달: {schedule_item.confidence} < {LLM_CONFIDENCE_THRESHOLD}")
                        continue

                    is_target_empty = not schedule_item.target_grades  # 타겟 학년이 명시 안 됨 = 전체 공지

                    is_grade_matching = (
                        schedule_item.is_for_all_grades
                        or is_target_empty
                        or (user_grade in schedule_item.target_grades)
                    )

                    if not is_grade_matching:
                        logger.info(f"⚠️ [{idx+1}번 메시지 탈락] 학년 불일치: 타겟({schedule_item.target_grades}) vs 유저({user_grade})")
                        continue

                    schedule_dict = schedule_item.model_dump()
                    schedule_dict["source"] = extracted_data.source

                    try:
                        add_notice_to_calendar(target_email, schedule_dict)
                        channel_written += 1
                        logger.info(f"✅ [{idx+1}번 메시지 성공] 캘린더 등록 완료: {schedule_item.title}")
                    except Exception as cal_err:
                        logger.error(f"❌ [{idx+1}번 메시지 실패] add_notice_to_calendar 예외: {cal_err}", exc_info=True)

            return channel_written

        # ------------------------------------------------------------------
        # 4. 메인 실행부: 결과 안전하게 합산
        # ------------------------------------------------------------------
        channel_tasks = [process_channel(ch) for ch in user_channels]
        results = await asyncio.gather(*channel_tasks, return_exceptions=True)

        # 예외 객체를 제외하고 숫자만 합산
        written_count = sum(r for r in results if isinstance(r, int))

        log_entry = models.CalendarEventLog(
            user_id=anon_user_id,
            change_type="auto_polling_sync",
            resource_id=f"written_items_{written_count}",
            last_updated_time=now_utc,
        )
        db.add(log_entry)
        db.commit()

        logger.info(f"✅ [Sync 완료] User({anon_user_id}): 총 {written_count}건 등록")
        return written_count

    except Exception as e:
        db.rollback()
        logger.error(f"❌ [Sync Exception 🚨] User({anon_user_id}) 동기화 중 에러 발생: {e}", exc_info=True)
        return 0
    finally:
        db.close()
        
# ------------------------------------------------------------------
# [FastAPI Router & Scheduler Tasks]
# ------------------------------------------------------------------
@app.post("/api/messages")
async def teams_event_webhook(
    request: Request, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    data = await request.json()
    activity_type = data.get("type")
    now_utc = datetime.now(timezone.utc)
    
    if (activity_type == "installationUpdate" and data.get("action") == "add") or (activity_type == "conversationUpdate" and data.get("membersAdded")):
        from_user = data.get("from", {})
        user_id = from_user.get("aadObjectId") or from_user.get("id")
        user_conversation = data.get("conversation") or {}
        user_conversation_id = user_conversation.get("id")
        service_url = data.get("serviceUrl")
        
        if user_id:
            anon_user_id = get_anonymous_id(user_id)
            now = datetime.now(timezone.utc).timestamp()
            last_sync_time = RECENT_SYNC_REQUESTS.get(user_id, 0)
            
            if now - last_sync_time < DUPLICATE_WEBHOOK_DEBOUNCE_SECONDS:
                logger.info(f"⚠️ [중복 이벤트 감지] User({anon_user_id}) 요청 무시")
                return {"status": "ok", "message": "duplicate_event_ignored"}

            RECENT_SYNC_REQUESTS[user_id] = now
            existing_user = db.query(models.User).filter(models.User.user_id == user_id).first()

            if not existing_user:
                new_user = models.User(user_id=user_id, conversation_id=user_conversation_id, service_url=service_url)
                db.add(new_user)
                logger.info(f"🎉 신규 설치 감지: User({anon_user_id}) 등록 완료")
            else:
                if user_conversation_id:
                    existing_user.conversation_id = user_conversation_id
                if service_url:
                    existing_user.service_url = service_url
                logger.info(f"🔄 앱 재설치 감지: User({anon_user_id})")

            install_log = models.CalendarEventLog(
                user_id=anon_user_id,
                change_type="app_installed",
                resource_id=data.get("id")
            )
            db.add(install_log)
            db.commit()

            background_tasks.add_task(sync_single_user, user_id, now_utc)

    return {"status": "ok"}

async def auto_polling_sync_job():
    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)
        logger.info(f"🔄 백그라운드 폴링 스케줄러 실행 시각: {now_utc.strftime('%H:%M:%S UTC')}")

        all_users = db.query(models.User).all() if hasattr(models, 'User') else []
        if not all_users:
            return

        #group_index = 0
        group_index = (now_utc.minute // POLLING_INTERVAL_MINUTES) % POLLS_PER_HOUR
        target_users = [
            user for idx, user in enumerate(all_users)
            if idx % POLLS_PER_HOUR == group_index
        ]

        tasks = [sync_single_user(user.user_id, now_utc) for user in target_users]
        await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        db.close()

# ------------------------------------------------------------------
# [Cron Job] 6개월 이상 휴면 계정 자동 파기 (개인정보보호법 준수)
# ------------------------------------------------------------------
async def cleanup_inactive_users_job():
    """
    마지막 동기화(auto_polling_sync) 시점이 6개월 전인 유저 데이터(models.User)를 DB에서 완전 삭제합니다.
    (CalendarEventLog는 해시 처리되어 있으므로 영구 보존 가능)
    """
    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)
        six_months_ago = now_utc - timedelta(days=180)
        
        logger.info("🧹 [개인정보 자동 파기 스케줄러] 휴면 계정 청소 작업 시작...")

        # 1. 최근 6개월 이내 동기화 로그가 있는 유저 ID 목록 (해시 ID 목록)
        active_anon_user_ids = (
            db.query(models.CalendarEventLog.user_id)
            .filter(
                models.CalendarEventLog.change_type == "auto_polling_sync",
                models.CalendarEventLog.last_updated_time >= six_months_ago
            )
            .distinct()
            .all()
        )
        # 튜플 리스트를 집합(set) 형태로 변환
        active_anon_set = {row[0] for row in active_anon_user_ids}

        # 2. 전체 유저 중 6개월간 활동 기록이 없는 유저 선별 후 삭제
        all_users = db.query(models.User).all()
        deleted_count = 0

        for user in all_users:
            user_anon_id = get_anonymous_id(user.user_id)
            
            # 활성 유저 목록에 해시 ID가 없다면 6개월 이상 휴면 유저로 판단
            if user_anon_id not in active_anon_set:
                db.delete(user)
                deleted_count += 1

        if deleted_count > 0:
            db.commit()
            logger.info(f"🚮 [개인정보 파기 완료] 6개월 이상 휴면 계정 {deleted_count}건 완전 삭제됨")
        else:
            logger.info("✨ [개인정보 파기 완료] 파기 대상 휴면 계정 없음")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ [개인정보 파기 에러] 휴면 계정 삭제 중 오류 발생: {e}", exc_info=True)
    finally:
        db.close()

@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return {"status": "healthy", "message": "Auto-polling Server is running!"}

@app.post("/extract")
async def extract_data(input_data: dict):
    """외부 직접 테스트용 엔드포인트"""
    try:
        return await analyze_message_with_gpt(input_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    