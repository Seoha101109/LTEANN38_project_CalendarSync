from database import Base, engine

def resetdb():
    # 모든 테이블 삭제 후 다시 생성
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    print("🔥 모든 테이블을 삭제하고 재생성했습니다.")