from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
import models
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/users", tags=["Users"])

@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
def delete_user_data(user_id: str, db: Session = Depends(get_db)):
    """
    개인정보 처리방침에 따른 특정 사용자 및 연관 데이터 완전 삭제
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="존재하지 않는 사용자입니다."
        )
    

    # DB에서 유저 삭제 (cascade 설정에 의해 연관된 일정 등도 함께 삭제됨)
    db.delete(user)
    db.commit()
    
    return {
        "status": "success", 
        "message": f"User ID {user_id} 사용자 및 관련 개인정보가 성공적으로 삭제되었습니다."
    }
    
if __name__ == "__main__":
    db = SessionLocal()
    user_id = os.environ.get("USER_ID")
    try:
        delete_user_data(user_id, db)
    finally:
        db.close()