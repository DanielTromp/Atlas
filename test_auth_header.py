
from fastapi.testclient import TestClient
from infrastructure_atlas.api.app import app
from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.db.models import User, UserAPIKey
from infrastructure_atlas.application.security import hash_password
import secrets

def test_auth_header_middleware():
    client = TestClient(app)
    
    # Create user and key
    username = f"apikey_user_{secrets.token_hex(4)}"
    password = "password123"
    token = secrets.token_urlsafe(32)
    
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role="admin", 
            display_name="API Key User",
            is_active=True
        )
        db.add(user)
        db.flush() # get user.id
        
        key = UserAPIKey(
            user_id=user.id,
            provider="mcp",
            label="Test Key",
            secret=token
        )
        db.add(key)
        db.commit()
    
    print(f"Created user {username} with token {token}")
    
    # Test API access with Bearer token
    headers = {"Authorization": f"Bearer {token}"}
    
    # We use /auth/me because it relies on CurrentUserDep specificially
    # which relies on request.state.user being populated by the middleware
    resp = client.get("/auth/me", headers=headers)
    
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        if data["username"] == username:
            print("SUCCESS: Authenticated via Bearer token")
        else:
            print(f"FAIL: Authenticated but username mismatch: {data.get('username')}")
    else:
        print(f"FAIL: {resp.text}")
        
    # Also test a protected API route (e.g. vcenter list - though it might need mock service, let's stick to auth/me)

if __name__ == "__main__":
    test_auth_header_middleware()
