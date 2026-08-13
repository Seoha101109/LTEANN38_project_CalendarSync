import os
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import SessionLocal
import models

target_user = ["26edde9a"]
kst=ZoneInfo("Asia/Seoul")
DEBUG_DATETIME = datetime(2026, 7, 4, 00, 00, 00, tzinfo=kst)
def edit_sync_state(target_user: list, time: datetime, db):
    try:
        for user_id in target_user:
            sync_state = db.query(models.UserSyncState).filter(models.UserSyncState.user_id == user_id).first()
            if not sync_state:
                print(f"{user_id} 사용자가 존재하지 않음")
            else:
                sync_state.last_synced_at = time
        db.commit()
    except Exception as e:
            db.rollback()
            print(f"에러 발생: {e}")
            
if __name__ == "__main__":
    db = SessionLocal()
    try:
        edit_sync_state(target_user, DEBUG_DATETIME,db)
    finally:
        db.close()