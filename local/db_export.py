import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from database import SessionLocal
import models

def export_essential_data():
    db = SessionLocal()
    backup_data = {
        "users": [],
        "user_sync_states": []
    }

    try:
        # 1. User 테이블 추출
        users = db.query(models.User).all()
        for u in users:
            backup_data["users"].append({
                "user_id": u.user_id,
                "conversation_id": getattr(u, "conversation_id", None),
                "service_url": getattr(u, "service_url", None),
                "grade": getattr(u, "grade", None),
            })

        # 2. UserSyncState 테이블 추출
        if hasattr(models, "UserSyncState"):
            sync_states = db.query(models.UserSyncState).all()
            for s in sync_states:
                backup_data["user_sync_states"].append({
                    "user_id": s.user_id,
                    "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
                })

        # JSON 파일 저장
        backup_file = "db_essential_backup.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        print(f"✅ 필수 데이터 백업 완료! ({backup_file})")
        print(f"📊 유저: {len(backup_data['users'])}명 | SyncState: {len(backup_data['user_sync_states'])}개")

    except Exception as e:
        print(f"❌ 백업 중 에러 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    export_essential_data()