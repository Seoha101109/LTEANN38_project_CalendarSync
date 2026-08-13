import os
import sys
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from database import SessionLocal
import models

target_user = ["26edde9a", "d1f0eada"]
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
                print(f"{user_id} 사용자의 시간을 {time.strftime("%Y년 %m월 %d일 %H시 %M분")}으로 되돌림")
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