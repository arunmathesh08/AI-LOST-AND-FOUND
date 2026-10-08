import os
import sys
from PIL import Image, ImageDraw, ImageFont

# Set UTF-8 encoding for standard output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import engine, Base, SessionLocal
from backend.models import User, Item, Match, Notification
from backend.auth import hash_password
from backend.ai_service import (
    load_ai_models, extract_text_embedding, extract_image_embedding,
    find_and_record_matches
)

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)


def create_placeholder_image(filename: str, label: str, bg_color: tuple) -> str:
    """Ensure a realistic image or clean synthetic image exists."""
    filepath = os.path.join(UPLOADS_DIR, filename)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        return f"/uploads/{filename}"
    img = Image.new("RGB", (300, 300), color=bg_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 280, 280], outline=(255, 255, 255), width=3)
    draw.text((40, 140), label, fill=(255, 255, 255))
    img.save(filepath, "JPEG")
    return f"/uploads/{filename}"


def seed_database():
    print("[+] Initializing Database Schema...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    print("[+] Loading AI Models...")
    load_ai_models()

    db = SessionLocal()

    try:
        # 1. Create Users
        print("[+] Creating Demo Users...")
        admin = User(
            name="System Admin",
            email="admin@demo.com",
            password_hash=hash_password("admin123"),
            role="admin"
        )
        user1 = User(
            name="Alex Johnson",
            email="user1@demo.com",
            password_hash=hash_password("user123"),
            role="user"
        )
        user2 = User(
            name="Maya Patel",
            email="user2@demo.com",
            password_hash=hash_password("user234"),
            role="user"
        )
        demo_user1 = User(
            name="Demo User One",
            email="demo1@example.com",
            password_hash=hash_password("Demo@12345"),
            role="user"
        )
        demo_user2 = User(
            name="Demo User Two",
            email="demo2@example.com",
            password_hash=hash_password("Demo@12345"),
            role="user"
        )

        db.add_all([admin, user1, user2, demo_user1, demo_user2])
        db.commit()
        db.refresh(admin)
        db.refresh(user1)
        db.refresh(user2)
        db.refresh(demo_user1)
        db.refresh(demo_user2)

        # 2. Create Placeholder Images
        print("[+] Generating Placeholder Images...")
        img_iphone = create_placeholder_image("iphone15.jpg", "iPhone 15 Pro", (30, 60, 114))
        img_wallet = create_placeholder_image("wallet.jpg", "Fossil Wallet", (139, 69, 19))
        img_bottle = create_placeholder_image("bottle.jpg", "Hydro Flask", (218, 165, 32))
        img_headphones = create_placeholder_image("headphones.jpg", "Sony WH-1000XM5", (20, 20, 20))
        img_sunglasses = create_placeholder_image("sunglasses.jpg", "Ray-Ban Aviators", (70, 70, 70))
        img_watch1 = create_placeholder_image("apple_watch.jpg", "Apple Watch", (40, 40, 60))
        img_watch2 = create_placeholder_image("casio_watch.jpg", "Casio Vintage", (100, 110, 120))

        # 3. Create 10 Items (5 Lost, 5 Found with 3 True Pairs)
        print("[+] Creating 10 Items (with 3 True Pairs)...")
        raw_items = [
            # PAIR 1: iPhone 15 Pro (User 1 lost, User 2 found)
            {
                "user_id": user1.id,
                "type": "lost",
                "title": "iPhone 15 Pro Titanium Blue",
                "category": "Electronics",
                "description": "Lost my blue titanium iPhone 15 Pro with a clear silicone MagSafe case.",
                "color": "Blue",
                "brand": "Apple",
                "location": "Student Library 2nd Floor",
                "date": "2026-10-05",
                "image_rel": img_iphone,
                "secret_detail": None
            },
            {
                "user_id": user2.id,
                "type": "found",
                "title": "Apple iPhone 15 Pro Blue Case",
                "category": "Electronics",
                "description": "Found a blue iPhone 15 Pro left on a desk near the computer lab in the library.",
                "color": "Blue",
                "brand": "Apple",
                "location": "Student Library Desk 14",
                "date": "2026-10-05",
                "image_rel": img_iphone,
                "secret_detail": "Lockscreen wallpaper is a golden retriever puppy and passcode starts with 7."
            },

            # PAIR 2: Fossil Brown Wallet (User 2 lost, User 1 found)
            {
                "user_id": user2.id,
                "type": "lost",
                "title": "Brown Leather Fossil Wallet",
                "category": "Accessories",
                "description": "Lost genuine brown leather bi-fold Fossil wallet containing student ID card and cash.",
                "color": "Brown",
                "brand": "Fossil",
                "location": "Central Dining Cafeteria",
                "date": "2026-10-06",
                "image_rel": img_wallet,
                "secret_detail": None
            },
            {
                "user_id": user1.id,
                "type": "found",
                "title": "Brown Leather Bifold Wallet",
                "category": "Accessories",
                "description": "Found a brown Fossil wallet on a cafeteria table near the coffee station.",
                "color": "Brown",
                "brand": "Fossil",
                "location": "Campus Cafeteria",
                "date": "2026-10-06",
                "image_rel": img_wallet,
                "secret_detail": "Student ID initials are M.P. and contains a metro transit card."
            },

            # PAIR 3: Hydro Flask 32oz Yellow (User 1 lost, User 2 found)
            {
                "user_id": user1.id,
                "type": "lost",
                "title": "Hydro Flask 32oz Yellow Bottle",
                "category": "Personal",
                "description": "Bright sunflower yellow Hydro Flask bottle with climbing stickers.",
                "color": "Yellow",
                "brand": "Hydro Flask",
                "location": "University Gym Locker Room",
                "date": "2026-10-07",
                "image_rel": img_bottle,
                "secret_detail": None
            },
            {
                "user_id": user2.id,
                "type": "found",
                "title": "Yellow Hydro Flask Water Bottle",
                "category": "Personal",
                "description": "Found a 32oz yellow insulated water flask with mountain stickers at the gym bench.",
                "color": "Yellow",
                "brand": "Hydro Flask",
                "location": "University Gym",
                "date": "2026-10-07",
                "image_rel": img_bottle,
                "secret_detail": "Has a Yosemite National Park sticker and slight dent at bottom."
            },

            # UNMATCHED LOST ITEM 4: Sony Headphones
            {
                "user_id": user1.id,
                "type": "lost",
                "title": "Sony WH-1000XM5 Black Headphones",
                "category": "Electronics",
                "description": "Matte black over-ear noise cancelling headphones in grey zipper travel case.",
                "color": "Black",
                "brand": "Sony",
                "location": "Engineering Building Study Hall",
                "date": "2026-10-04",
                "image_rel": img_headphones,
                "secret_detail": None
            },

            # UNMATCHED LOST ITEM 5: Ray-Ban Sunglasses
            {
                "user_id": user2.id,
                "type": "lost",
                "title": "Ray-Ban Gold Aviator Sunglasses",
                "category": "Accessories",
                "description": "Classic gold frame green G-15 lens aviator sunglasses in brown leather case.",
                "color": "Gold",
                "brand": "Ray-Ban",
                "location": "North Parking Lot Zone C",
                "date": "2026-10-03",
                "image_rel": img_sunglasses,
                "secret_detail": None
            },

            # UNMATCHED FOUND ITEM 4: Apple Watch Midnight
            {
                "user_id": user1.id,
                "type": "found",
                "title": "Apple Watch Series 8 Midnight",
                "category": "Electronics",
                "description": "Found an Apple Watch 45mm midnight aluminum case with sport band on seat 12B.",
                "color": "Midnight Black",
                "brand": "Apple",
                "location": "Main Campus Auditorium",
                "date": "2026-10-02",
                "image_rel": img_watch1,
                "secret_detail": "Monogram 'K.R.' engraved on the rear sensor ring."
            },

            # UNMATCHED FOUND ITEM 5: Casio Digital Watch
            {
                "user_id": user2.id,
                "type": "found",
                "title": "Casio Vintage Silver Digital Watch",
                "category": "Accessories",
                "description": "Found vintage style stainless steel digital watch at the campus shuttle stop.",
                "color": "Silver",
                "brand": "Casio",
                "location": "Campus Shuttle Bus Stop 3",
                "date": "2026-10-01",
                "image_rel": img_watch2,
                "secret_detail": "Small scratch across the alarm indicator icon."
            },
        ]

        created_item_objs = []
        for d in raw_items:
            img_fs_path = os.path.join(os.path.dirname(UPLOADS_DIR), d["image_rel"].lstrip("/")) if d["image_rel"] else None
            rich_text = f"{d['title']} {d['category']} {d['description']} {d['color']} {d['brand']} {d['location']}"
            txt_vec = extract_text_embedding(rich_text)
            img_vec = extract_image_embedding(img_fs_path) if img_fs_path else []

            item = Item(
                user_id=d["user_id"],
                type=d["type"],
                title=d["title"],
                category=d["category"],
                description=d["description"],
                color=d["color"],
                brand=d["brand"],
                location=d["location"],
                date=d["date"],
                image_path=d["image_rel"],
                secret_detail=d["secret_detail"],
                status="open"
            )
            item.txt_vec = txt_vec
            item.img_vec = img_vec if img_vec else None

            db.add(item)
            db.commit()
            db.refresh(item)
            created_item_objs.append(item)

            # Match against earlier items
            find_and_record_matches(db, item)

        total_matches = db.query(Match).count()
        total_notifs = db.query(Notification).count()

        print(f"[SUCCESS] Seeding Complete!")
        print(f"   Users: 3 (Admin: admin@demo.com, Users: user1@demo.com, user2@demo.com)")
        print(f"   Items: {len(created_item_objs)} (5 Lost, 5 Found)")
        print(f"   Matches Created: {total_matches}")
        print(f"   Notifications: {total_notifs}")

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
