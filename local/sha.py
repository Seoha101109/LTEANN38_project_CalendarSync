import hashlib
import os
from dotenv import load_dotenv

load_dotenv()

def generate_sha256(text: str) -> str:
    """텍스트를 SHA-256 해시값으로 변환합니다."""
    # hashlib은 바이트(bytes) 단위를 처리하므로 UTF-8로 인코딩 필요
    encoded_text = text.encode('utf-8')
    sha256_hash = hashlib.sha256(encoded_text)
    
    # 16진수 문자열로 반환
    return sha256_hash.hexdigest()

if __name__ == "__main__":
    target_string = os.environ.get("USER_ID")

    sha256_result = generate_sha256(target_string)

    print(f"원본 텍스트: {target_string}")
    print(f"SHA-256: {sha256_result}")