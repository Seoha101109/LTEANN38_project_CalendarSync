from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Render 환경변수에서 DATABASE_URL 가져오기
SQLALCHEMY_DATABASE_URL = os.getenv("DB_URL")

# Render가 제공하는 postgres:// 시작 주소를 postgresql:// 로 변경
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# DB 엔진 생성
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# DB 세션 의존성 함수 (FastAPI 라우터에서 사용)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()