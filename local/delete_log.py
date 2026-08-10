import os
import sys
from dotenv import load_dotenv

# 1. 프로젝트 최상위 루트 경로 계산 (local/.. -> 루트)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2. sys.path에 루트 추가 (database, models import 가능하게 함)
sys.path.append(project_root)

# 3. 루트에 있는 .env 파일 위치를 명시하여 로드
env_path = os.path.join(project_root, ".env")
load_dotenv(dotenv_path=env_path)

# 4. 이제 database와 models import (env 로드 완료 후 실행)
from database import SessionLocal
import models

# 타겟 사용자 익명 ID 목록
target_user_ids = ["d1f0eada"] 

db = SessionLocal()

try:
    for user_id in target_user_ids:
        # 해당 유저의 가장 최근 auto_polling_sync 로그 조회
        latest_log = (
            db.query(models.CalendarEventLog)
            .filter(
                models.CalendarEventLog.user_id == user_id,
                models.CalendarEventLog.change_type == "auto_polling_sync"
            )
            .order_by(models.CalendarEventLog.last_updated_time.desc())
            .first()
        )

        if latest_log:
            print(f"🗑️ [삭제 대상] User: {user_id} | Time: {latest_log.last_updated_time} | Resource: {latest_log.resource_id}")
            db.delete(latest_log)
            print(f"✅ User {user_id}의 최근 Sync 로그 삭제 완료")
        else:
            print(f"⚠️ User {user_id}의 Sync 로그를 찾을 수 없습니다.")

    db.commit()
    print("🎉 모든 로그 삭제 처리가 완료되었습니다!")

except Exception as e:
    db.rollback()
    print(f"❌ 에러 발생: {e}")
finally:
    db.close()