import os
import sys
import pytest
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app
from backend.database import Base, engine, SessionLocal
from backend.models import User, Item, Match, Notification
from backend.auth import hash_password
from backend.ai_service import load_ai_models

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_db():
    load_ai_models()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Create default admin and users
        admin = User(name="Admin", email="admin@demo.com", password_hash=hash_password("admin123"), role="admin")
        u1 = User(name="Alice", email="alice@demo.com", password_hash=hash_password("pass123"), role="user")
        u2 = User(name="Bob", email="bob@demo.com", password_hash=hash_password("pass123"), role="user")
        db.add_all([admin, u1, u2])
        db.commit()
    finally:
        db.close()
    yield


def test_auth_flow():
    # 1. Register new user
    res = client.post("/api/auth/register", json={
        "name": "Charlie",
        "email": "charlie@demo.com",
        "password": "password123"
    })
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "charlie@demo.com"

    # 2. Login
    res_login = client.post("/api/auth/login", json={
        "email": "charlie@demo.com",
        "password": "password123"
    })
    assert res_login.status_code == 200
    token = res_login.json()["access_token"]

    # 3. Get profile
    res_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_me.status_code == 200
    assert res_me.json()["name"] == "Charlie"


def test_item_creation_and_matching_flow():
    # Login as Alice (User 1)
    res_alice = client.post("/api/auth/login", json={"email": "alice@demo.com", "password": "pass123"})
    alice_token = res_alice.json()["access_token"]

    # Login as Bob (User 2)
    res_bob = client.post("/api/auth/login", json={"email": "bob@demo.com", "password": "pass123"})
    bob_token = res_bob.json()["access_token"]

    # Alice posts lost item
    res_lost = client.post(
        "/api/items",
        data={
            "type": "lost",
            "title": "MacBook Air M2 Silver",
            "category": "Electronics",
            "description": "Silver 13-inch MacBook Air left on floor 3 study table",
            "location": "Science Library",
            "date": "2026-10-08",
            "color": "Silver",
            "brand": "Apple"
        },
        headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert res_lost.status_code == 200
    lost_data = res_lost.json()["item"]
    lost_id = lost_data["id"]

    # Bob posts found item (matching)
    res_found = client.post(
        "/api/items",
        data={
            "type": "found",
            "title": "Apple MacBook Air Silver Laptop",
            "category": "Electronics",
            "description": "Found a silver MacBook Air on 3rd floor science library desk",
            "location": "Science Library Floor 3",
            "date": "2026-10-08",
            "color": "Silver",
            "brand": "Apple",
            "secret_detail": "Lockscreen has a cosmic space wallpaper and sticker with initial A."
        },
        headers={"Authorization": f"Bearer {bob_token}"}
    )
    assert res_found.status_code == 200
    found_data = res_found.json()["item"]
    found_id = found_data["id"]

    # Check privacy: Public item listing must not reveal Bob's email or secret_detail
    public_items = client.get("/api/items").json()
    bob_public_item = next(i for i in public_items if i["id"] == found_id)
    assert "secret_detail" not in bob_public_item
    assert "contact" not in bob_public_item

    # Check Alice's matches
    res_my_items = client.get("/api/my-items", headers={"Authorization": f"Bearer {alice_token}"})
    assert res_my_items.status_code == 200
    my_lost = next(i for i in res_my_items.json() if i["id"] == lost_id)
    assert len(my_lost["matches"]) > 0
    match = my_lost["matches"][0]
    assert match["score"] >= 0.55
    match_id = match["id"]

    # Alice claims the match by answering secret question
    res_claim = client.post(
        f"/api/matches/{match_id}/claim",
        json={"claim_answer": "My lockscreen is a cosmic space nebula with initial A sticker."},
        headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert res_claim.status_code == 200
    assert res_claim.json()["match"]["status"] == "claimed"

    # Bob (finder) approves the claim
    res_verify = client.post(
        f"/api/matches/{match_id}/verify",
        json={"action": "approve"},
        headers={"Authorization": f"Bearer {bob_token}"}
    )
    assert res_verify.status_code == 200
    verified_match = res_verify.json()["match"]
    assert verified_match["status"] == "verified"
    # Contact info should now be revealed
    assert "contact" in verified_match["lost_item"]
    assert verified_match["lost_item"]["contact"]["email"] == "alice@demo.com"


def test_admin_dashboard_and_controls():
    # Login as Admin
    res_admin = client.post("/api/auth/login", json={"email": "admin@demo.com", "password": "admin123"})
    admin_token = res_admin.json()["access_token"]

    # Stats
    res_stats = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert "total_reports" in stats
    assert "total_matches" in stats
    assert "total_returned" in stats

    # Admin items list
    res_items = client.get("/api/admin/items", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_items.status_code == 200


if __name__ == "__main__":
    pytest.main(["-v", __file__])
