import base64
from datetime import datetime
import json
import os
import re
from typing import List, Optional
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import httpx
import msal
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

load_dotenv()

TENANT_ID = os.environ.get("TENANT_ID")
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
TEAM_ID = os.environ.get('TEAM_ID')
CHANNEL_ID = os.environ.get('CHANNEL_ID')
USER_ID = os.environ.get("USER_ID")
USER_NAME = os.environ.get("USER_NAME")

# 보안을 위해 API 키는 os.environ 또는 dotenv를 이용하시는 것을 권장합니다.
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)


def get_graph_access_token():
    """MS Graph API 전용 App Access Token을 발급합니다."""
    authority_url = f"https://login.microsoftonline.com/{TENANT_ID}"

    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        authority=authority_url,
        client_credential=CLIENT_SECRET,
    )

    scopes = ["https://graph.microsoft.com/.default"]

    token_result = app.acquire_token_for_client(scopes=scopes)

    if "access_token" not in token_result:
        print(
            "❌ [Token Error] 토큰 발급 실패:",
            token_result.get("error_description"),
        )
        return None

    return token_result["access_token"]


class ScheduleItem(BaseModel):
    title: str = Field(description="일정 제목")
    start_time: str = Field(description="시작 시간 (ISO 8601 포맷)")
    end_time: str = Field(description="종료 시간 (ISO 8601 포맷)")
    summary: Optional[str] = Field(
        default=None,
        description="일정에 대한 핵심 요약 1~2줄 (예: 강당에서 과제연구기초 필수교육 진행, 자리는 공지 참고)",
    )
    location: Optional[str] = Field(
        default=None,
        description="일정 장소 (메시지에 장소가 명시된 경우만 작성, 예: 창의인재관 4층 강당, 운동장)",
    )
    is_for_all_grades: bool = Field(
        description="전체 학년(전교생) 대상 일정이면 True, 특정 학년만 대상이면 False"
    )
    target_grades: List[int] = Field(
        default=[],
        description="이 일정이 적용되는 학년 목록 (예: [1, 2], 특정 언급이 없거나 전교생 대상이면 빈 리스트)",
    )
    confidence: float = Field(description="일정 추출 신뢰도 (0.0 ~ 1.0)")
    
    @model_validator(mode='after')
    def validate_grades_logic(self):
        # target_grades에 데이터가 명시되어 있다면 is_for_all_grades는 무조건 False
        if self.target_grades:
            self.is_for_all_grades = False
        return self


class ExtractedSchedule(BaseModel):
    has_schedule: bool = Field(
        description="메시지 내에 유효한 일정 정보가 1개 이상 포함되어 있는지 여부"
    )
    source: Optional[str] = Field(
        default=None,
        description="일정 출처 또는 메시지 발신 출처 (예: 학년 공지, 학생회, 학급)",
    )
    schedules: List[ScheduleItem] = Field(
        default=[],
        description="메시지에서 추출된 일정 목록 (일정이 없으면 빈 리스트)",
    )


def analyze_message_with_gpt(
    message_payload: dict,
    graph_access_token: str = None,
    target_user_name: str = None,
) -> ExtractedSchedule:
    body_info = message_payload.get("body", {})
    raw_content = body_info.get("content", "")
    content_type = body_info.get("contentType", "text")

    image_base64_list = []
    clean_body = ""

    if content_type == "html" and raw_content:
        soup = BeautifulSoup(raw_content, "html.parser")

        # 동기(Sync) HTTP 클라이언트로 변경
        if graph_access_token:
            img_tags = soup.find_all("img")
            with httpx.Client() as http_client:
                headers = {"Authorization": f"Bearer {graph_access_token}"}
                for img in img_tags:
                    img_url = img.get("src")
                    if img_url and "hostedContents" in img_url:
                        try:
                            res = http_client.get(
                                img_url, headers=headers, follow_redirects=True
                            )
                            if res.status_code == 200:
                                b64_img = base64.b64encode(res.content).decode(
                                    "utf-8"
                                )
                                image_base64_list.append(b64_img)
                        except Exception:
                            continue

        clean_body = soup.get_text(separator=" ", strip=True)
    else:
        clean_body = raw_content

    attachment_texts = []
    for att in message_payload.get("attachments", []):
        att_content = att.get("content")
        if att_content:
            if isinstance(att_content, str):
                try:
                    parsed_att = json.loads(att_content)
                    if isinstance(parsed_att, dict) and "title" in parsed_att:
                        attachment_texts.append(
                            f"[공지 배너]: {parsed_att['title']}"
                        )
                    else:
                        attachment_texts.append(att_content)
                except json.JSONDecodeError:
                    attachment_texts.append(att_content)
            elif isinstance(att_content, dict) and "title" in att_content:
                attachment_texts.append(f"[공지 배너]: {att_content['title']}")

    if attachment_texts:
        clean_body = "\n".join(attachment_texts) + "\n" + clean_body


    from_info = message_payload.get("from") or {}
    user_info = from_info.get("user") or {}
    sender_name = user_info.get("displayName") or "알 수 없음"
    subject = message_payload.get("subject", "")
    created_at = message_payload.get("createdDateTime", "")
    web_url = message_payload.get("webUrl", "")
    message_id = message_payload.get("id", "")

    user_context = (
        f"- 현재 캘린더 주인 이름: {target_user_name}\n"
        if target_user_name
        else ""
    )
    system_prompt = '''너는 메신저 메시지와 이미지를 분석하여 사용자가 챙겨야 할 일정을 정확히 파악하고 extraction 객체 형태로 반환하는 AI 도우미야.

[0. 일정 추출 대상 (has_schedule = True)]
아래 항목 중 구체적인 연/월/일 마감/기간이 명시되어 있을 때만 `has_schedule = True`로 설정:
  1) 과제/보고서 제출 마감, 시험, 특강/세미나, 팀 프로젝트 미팅
  2) 각종 프로그램/행사/아카데미 신청 및 모집 기간
  3) 구글 폼/설문/투표 마감, 개인 메시지(DM)/메일 응답 마감일
  4) 성적 확인/정정 및 이의신청 기간, 개인 짐 정리 기간 등
- 단, 도서관 운영시간, 식당 메뉴, 단순 점검 등 일회성 이벤트가 아닌 단순 안내는 confidence를 낮춰줘.

[1. 예외 대상 (has_schedule = False)]
아래에 해당하면 키워드가 있더라도 무조건 `has_schedule = False` 처리:
- "추후 안내", "추후 공지" 등 구체적인 날짜나 마감 일시가 명시되지 않은 글.
- 본문에 언급되지 않은 대상을 AI가 스스로 추론하여 만들어낸 일정.

[2. 다중 일정 및 ALL-SCAN 처리]
- 하나의 메시지에 여러 일정(예: 1차 제출, 2차 제출)이 있거나, 번호(1., 2...)로 나열된 경우 누락 없이 각각 독립된 객체로 분리하여 `schedules` 배열에 담아줘.
- 예시: "6/5 발표, 6/12 보고서 제출" -> schedules에 2개 객체 생성

[3. 제목 및 분류 규칙]
- title 기본 형태: `[카테고리/과목] 핵심 내용` (예: [물리학] 물리학 성적 배부)
- 과목명이 본문에 있으면 최우선 카테고리로 지정.

[4. 마감 공지 처리 규칙]
- 시작일 없이 마감일만 있는 경우 ("~까지 제출"):
  1) start_time: 마감일 당일의 00:00:00Z로 설정.
  2) end_time: 특정 시각(예: 17시)이 지정된 경우 해당 시각을 반영하고, 시각 언급이 없으면 당일 23:59:59Z로 설정.
  3) title: 제목 끝에 반드시 '#마감' 태그 추가 (예: [1학년] 현송장학금 신청 마감#마감)

[5. 세부 추출 규칙]
- 상대적인 날짜 표현("내일까지", "이번주 금요일")을 해석할 때만 작성일(created_at)을 기준점으로 사용해줘.
- 시간을 특정할 수 없는 당일 일정은 하루 종일(All-day) 이벤트로 간주.
- 작성일을 날짜 계산에 사용하는 유일한 경우는 상대적인 날짜 표현이 있을 경우이며, 절대로 작성일을 시작일 또는 종료일로 판단해선 안돼.
- target_grades: 본문에 명시된 숫자만 입력 (고등학교 1, 2, 3학년 등). 명시되지 않았거나 전교생 대상인 경우 빈 리스트 `[]` 처리.

[추가 보완 지침]
- 마감 시간 정보: 본문에 "오전까지", "17시까지" 등 특정 시각이 지정된 경우 해당 시각을 end_time에 반영해 줘.
- 학년 입력 규격: target_grades에는 한국 학교 시스템 기준의 숫자만 입력해 줘. (고등학교의 경우 10, 11, 12가 아닌 1, 2, 3으로 표기)

[참고: 학교 교시별 시간표]
- 1교시(08:30~09:20), 2교시(09:30~10:20), 3교시(10:30~11:20), 4교시(11:30~12:20)
- 점심시간(12:20~13:10), 5교시(13:10~14:00), 6교시(14:10~15:00), 7교시(15:10~16:00)
'''

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
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_img}"},
            }
        )

    completion = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format=ExtractedSchedule,
        temperature=0,
    )

    return completion.choices[0].message.parsed


# ==========================================
# 실행부
# ==========================================

if __name__ == "__main__":
    msg = os.environ.get("raw_msg")
   
    access_token = get_graph_access_token()
    extracted_data: ExtractedSchedule = analyze_message_with_gpt(
        message_payload=msg,
        graph_access_token=access_token,
        target_user_name=f"{USER_NAME}",
    )
    print("=== GPT 최종 파싱 결과 ===")
    print(
        json.dumps(
            extracted_data.model_dump(), indent=2, ensure_ascii=False
        )
    )