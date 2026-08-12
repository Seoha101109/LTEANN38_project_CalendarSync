import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from database import SessionLocal, engine, Base
import models

def parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str)

def import_essential_data(backup_file="db_essential_backup.json"):
    if not os.path.exists(backup_file):
        print(f"❌ 백업 파일({backup_file})이 존재하지 않습니다!")
        return

    # 새 DB에 테이블 자동 생성
    print("🔨 새 DB 테이블 생성 중...")
    Base.metadata.create_all(bind=engine)

    with open(backup_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        # 1. User 테이블 복원
        user_count = 0
        for u in data.get("users", []):
            existing = db.query(models.User).filter(models.User.user_id == u["user_id"]).first()
            if not existing:
                new_u = models.User(
                    user_id=u["user_id"],
                    conversation_id=u.get("conversation_id"),
                    service_url=u.get("service_url"),
                    grade=u.get("grade")
                )
                db.add(new_u)
                user_count += 1

        # 2. UserSyncState 테이블 복원
        sync_count = 0
        for s in data.get("user_sync_states", []):
            existing = db.query(models.UserSyncState).filter(models.UserSyncState.user_id == s["user_id"]).first()
            if not existing and s.get("last_synced_at"):
                new_s = models.UserSyncState(
                    user_id=s["user_id"],
                    last_synced_at=parse_iso_datetime(s["last_synced_at"])
                )
                db.add(new_s)
                sync_count += 1

        db.commit()
        print("🎉 필수 데이터(User + SyncState) 복원 완료!")
        print(f"📊 복원된 유저: {user_count}명 | SyncState: {sync_count}개")

    except Exception as e:
        db.rollback()
        print(f"❌ 복원 중 에러 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    import_essential_data()