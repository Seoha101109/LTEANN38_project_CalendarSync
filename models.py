from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from database import Base
from datetime import datetime, timezone

class CalendarEventLog(Base):
    __tablename__ = "calendar_event_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)       # 사용자 ID (MS Graph / Teams User ID)
    change_type = Column(String)               # manual_refresh, tab_auto_sync_write 등
    resource_id = Column(String)               # 변경된 이벤트/게시물 ID
    
    # default와 index를 추가하여 파이썬 객체 참조 오류 및 조회 속도 개선!
    last_updated_time = Column(
        DateTime(timezone=True), 
        default=func.now(), 
        server_default=func.now(), 
        onupdate=func.now(),
        index=True
    )

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, index=True)  # Teams / Azure AAD Object ID
    grade = Column(Integer, nullable=True)     # 공지 필터링용 학년 정보 (개인 식별 불가능한 일반 서비스 데이터)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    conversation_id = Column(String, unique=True, index=True)
    service_url = Column(String, nullable=True)
    
class UserSyncState(Base):
    __tablename__ = "user_sync_states"

    user_id = Column(String, primary_key=True, index=True) # 익명 유저 ID
    last_synced_at = Column(DateTime(timezone=True), nullable=False) # 마지막 성공 동기화 시각
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))