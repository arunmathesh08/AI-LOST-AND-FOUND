import os
import shutil
import uuid
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import (
    FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Query
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from backend.database import engine, Base, get_db
from backend.models import User, Item, Match, Notification, Feedback
from backend.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_current_admin
)
from backend.ai_service import (
    load_ai_models, extract_text_embedding, extract_image_embedding,
    find_and_record_matches
)

# Initialize database directory & uploads
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")
os.makedirs(UPLOADS_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables and preload AI models
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        try:
            cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(notifications)").fetchall()]
            if "item_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE notifications ADD COLUMN item_id INTEGER")
            if "finder_name" not in cols:
                conn.exec_driver_sql("ALTER TABLE notifications ADD COLUMN finder_name VARCHAR(100)")
        except Exception as e:
            print("DB migration check:", e)
    load_ai_models()
    yield


app = FastAPI(
    title="AI-Based Lost & Found Object Matching System",
    description="Multimodal CLIP + MiniLM AI-powered Lost and Found Matching Engine",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded images statically
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Load environment variables from .env if present
ENV_PATH = os.path.join(os.path.dirname(BASE_DIR), ".env")
if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k and v and k not in os.environ:
                        os.environ[k] = v
    except Exception as e:
        print("Notice: Error reading .env:", e)


@app.get("/api/config/public")
def get_public_config():
    """Returns safe public config (Supabase URL and Anon key) for frontend client initialization."""
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    if anon_key == "your_supabase_anon_key_here":
        anon_key = ""
    return {
        "supabase_url": os.getenv("SUPABASE_URL", "https://gdngcjfgajkjdjosgtlc.supabase.co"),
        "supabase_anon_key": anon_key
    }


@app.get("/", include_in_schema=False)
def serve_root():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return RedirectResponse(url="/docs")


@app.get("/supabase-config.js", include_in_schema=False)
@app.get("/app/supabase-config.js", include_in_schema=False)
def serve_supabase_config():
    cfg_file = os.path.join(FRONTEND_DIR, "supabase-config.js")
    if os.path.exists(cfg_file):
        return FileResponse(cfg_file, media_type="application/javascript")
    return {"error": "Not found"}


@app.get("/app", include_in_schema=False)
@app.get("/app/index.html", include_in_schema=False)
def serve_app():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return RedirectResponse(url="/")


# ==========================================
# PYDANTIC SCHEMAS
# ==========================================
class RegisterSchema(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginSchema(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str


class ClaimRequest(BaseModel):
    claim_answer: str


class VerifyRequest(BaseModel):
    action: str  # "approve" | "reject"


class FeedbackSchema(BaseModel):
    rating: int
    message: str


# ==========================================
# SERIALIZATION HELPERS (PRIVACY ENFORCING)
# ==========================================
def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role
    }


def serialize_item(item: Item, current_user: Optional[User] = None, include_contact: bool = False) -> dict:
    is_owner = current_user and (current_user.id == item.user_id)
    is_admin = current_user and (current_user.role == "admin")

    data = {
        "id": item.id,
        "user_id": item.user_id,
        "type": item.type,
        "title": item.title,
        "category": item.category,
        "description": item.description,
        "color": item.color,
        "brand": item.brand,
        "location": item.location,
        "date": item.date,
        "image_path": item.image_path,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "has_image": bool(item.image_path)
    }

    # Privacy: Never return secret_detail publicly.
    # Only the owner or admin can see it.
    if is_owner or is_admin:
        data["secret_detail"] = item.secret_detail
    else:
        data["has_secret_verification"] = bool(item.secret_detail)

    # Privacy: Contact info (email) is hidden in public APIs
    # Revealed only if explicitly authorized (e.g. after approved claim) or if admin/owner
    if include_contact or is_owner or is_admin:
        if item.user:
            data["contact"] = {
                "name": item.user.name,
                "email": item.user.email
            }
    else:
        if item.user:
            data["reporter_name"] = item.user.name

    return data


def serialize_match(match: Match, current_user: Optional[User] = None) -> dict:
    is_verified = (match.status == "verified")
    is_involved = current_user and (
        (match.lost_item and current_user.id == match.lost_item.user_id) or
        (match.found_item and current_user.id == match.found_item.user_id)
    )
    is_admin = current_user and (current_user.role == "admin")

    reveal_contact = is_verified and (is_involved or is_admin)

    return {
        "id": match.id,
        "score": match.score,
        "score_percentage": int(match.score * 100),
        "img_score": match.img_score,
        "txt_score": match.txt_score,
        "status": match.status,
        "claim_answer": match.claim_answer if (is_involved or is_admin) else None,
        "created_at": match.created_at.isoformat() if match.created_at else None,
        "lost_item": serialize_item(match.lost_item, current_user, include_contact=reveal_contact) if match.lost_item else None,
        "found_item": serialize_item(match.found_item, current_user, include_contact=reveal_contact) if match.found_item else None,
    }


# ==========================================
# AUTH ENDPOINTS
# ==========================================
@app.post("/api/auth/register")
def register(req: RegisterSchema, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already registered")

    user = User(
        name=req.name.strip(),
        email=req.email.lower().strip(),
        password_hash=hash_password(req.password),
        role="user"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": serialize_user(user)
    }


@app.post("/api/auth/login")
def login(req: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": serialize_user(user)
    }


@app.get("/api/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)


# ==========================================
# ITEMS ENDPOINTS
# ==========================================
@app.post("/api/items")
async def create_item(
    type: str = Form(...),
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    date: str = Form(...),
    color: Optional[str] = Form(None),
    brand: Optional[str] = Form(None),
    secret_detail: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if type not in ["lost", "found"]:
        raise HTTPException(status_code=400, detail="Type must be 'lost' or 'found'")

    # Save uploaded image if present (validation: jpg/png up to 5MB)
    image_rel_path = None
    saved_file_path = None

    if image and image.filename:
        filename = image.filename.lower()
        if not (filename.endswith(".jpg") or filename.endswith(".jpeg") or filename.endswith(".png")):
            raise HTTPException(status_code=400, detail="Only JPG and PNG images are accepted")

        # Check file size (max 5 MB)
        content = await image.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image size must be under 5 MB")

        ext = os.path.splitext(filename)[1]
        unique_name = f"{uuid.uuid4().hex}{ext}"
        saved_file_path = os.path.join(UPLOADS_DIR, unique_name)
        with open(saved_file_path, "wb") as f:
            f.write(content)
        image_rel_path = f"/uploads/{unique_name}"

    # Generate multimodal embeddings
    rich_text = f"{title} {category} {description} {color or ''} {brand or ''} {location}".strip()
    txt_vector = extract_text_embedding(rich_text)
    img_vector = extract_image_embedding(saved_file_path) if saved_file_path else []

    item = Item(
        user_id=current_user.id,
        type=type,
        title=title.strip(),
        category=category.strip(),
        description=description.strip(),
        color=color.strip() if color else None,
        brand=brand.strip() if brand else None,
        location=location.strip(),
        date=date.strip(),
        image_path=image_rel_path,
        secret_detail=secret_detail.strip() if (type == "found" and secret_detail) else None,
        status="open"
    )
    item.txt_vec = txt_vector
    item.img_vec = img_vector if img_vector else None

    db.add(item)
    db.commit()
    db.refresh(item)

    # Automatically run AI matching against existing open opposite items
    matches = find_and_record_matches(db, item)

    return {
        "item": serialize_item(item, current_user),
        "matches_found": len(matches)
    }


@app.get("/api/items")
def list_items(
    type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query("open"),
    db: Session = Depends(get_db)
):
    query = db.query(Item)

    if type:
        query = query.filter(Item.type == type)
    if category:
        query = query.filter(Item.category.ilike(f"%{category}%"))
    if status and status != "all":
        query = query.filter(Item.status == status)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                Item.title.ilike(search_pattern),
                Item.description.ilike(search_pattern),
                Item.location.ilike(search_pattern),
                Item.brand.ilike(search_pattern),
                Item.color.ilike(search_pattern)
            )
        )

    items = query.order_by(Item.created_at.desc()).all()
    return [serialize_item(item) for item in items]


@app.get("/api/items/{item_id}")
def get_item(
    item_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return serialize_item(item, current_user)


@app.get("/api/my-items")
def get_my_items(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    items = db.query(Item).filter(Item.user_id == current_user.id).order_by(Item.created_at.desc()).all()
    result = []
    for item in items:
        item_data = serialize_item(item, current_user)
        # Fetch ranked matches
        if item.type == "lost":
            matches = db.query(Match).filter(Match.lost_id == item.id).order_by(Match.score.desc()).all()
        else:
            matches = db.query(Match).filter(Match.found_id == item.id).order_by(Match.score.desc()).all()

        item_data["matches"] = [serialize_match(m, current_user) for m in matches]
        result.append(item_data)
    return result


@app.put("/api/items/{item_id}")
async def update_item(
    item_id: int,
    title: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    date: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    brand: Optional[str] = Form(None),
    secret_detail: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to edit this report")

    if title is not None:
        item.title = title.strip()
    if category is not None:
        item.category = category.strip()
    if description is not None:
        item.description = description.strip()
    if location is not None:
        item.location = location.strip()
    if date is not None:
        item.date = date.strip()
    if color is not None:
        item.color = color.strip() if color else None
    if brand is not None:
        item.brand = brand.strip() if brand else None
    if secret_detail is not None and item.type == "found":
        item.secret_detail = secret_detail.strip() if secret_detail else None

    # Recalculate text embedding
    rich_text = f"{item.title} {item.category} {item.description} {item.color or ''} {item.brand or ''} {item.location}".strip()
    item.txt_vec = extract_text_embedding(rich_text)

    db.commit()
    db.refresh(item)

    # Re-run matching
    matches = find_and_record_matches(db, item)

    return {
        "message": "Item updated successfully",
        "item": serialize_item(item, current_user),
        "matches_found": len(matches)
    }


@app.delete("/api/items/{item_id}")
def delete_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete this report")

    # Clean up image file if exists
    if item.image_path:
        filename = os.path.basename(item.image_path)
        file_path = os.path.join(UPLOADS_DIR, filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    db.delete(item)
    db.commit()
    return {"message": f"Report {item_id} deleted successfully"}


# ==========================================
# MATCHES & CLAIMS ENDPOINTS
# ==========================================
@app.get("/api/matches/{item_id}")
def get_matches_for_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.type == "lost":
        matches = db.query(Match).filter(Match.lost_id == item.id).order_by(Match.score.desc()).all()
    else:
        matches = db.query(Match).filter(Match.found_id == item.id).order_by(Match.score.desc()).all()

    return [serialize_match(m, current_user) for m in matches]


@app.post("/api/matches/{match_id}/claim")
def claim_match(
    match_id: int,
    req: ClaimRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Owner of lost item submits claim answering verification details."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    lost_item = match.lost_item
    found_item = match.found_item

    # Verify that current user is the owner of the lost item
    if lost_item.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the lost item owner can claim this match")

    match.status = "claimed"
    match.claim_answer = req.claim_answer.strip()
    db.commit()

    # Notify finder
    notify_msg = (
        f"📝 Claim submitted for '{found_item.title}'! The owner answered: '{match.claim_answer}'. "
        f"Please review and verify or reject in your dashboard."
    )
    db.add(Notification(user_id=found_item.user_id, message=notify_msg))
    db.commit()

    return {"message": "Claim submitted successfully", "match": serialize_match(match, current_user)}


@app.post("/api/matches/{match_id}/verify")
def verify_claim(
    match_id: int,
    req: VerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Finder or Admin approves or rejects the claim."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    found_item = match.found_item
    lost_item = match.lost_item

    is_finder = (found_item.user_id == current_user.id)
    is_admin = (current_user.role == "admin")

    if not (is_finder or is_admin):
        raise HTTPException(status_code=403, detail="Only the finder or admin can verify this claim")

    if req.action == "approve":
        match.status = "verified"
        lost_item.status = "returned"
        found_item.status = "returned"
        db.commit()

        # Send approval notifications with contact unlock info
        finder_user = found_item.user
        owner_user = lost_item.user

        msg_for_owner = (
            f"🎉 Your claim for '{lost_item.title}' has been APPROVED! "
            f"Finder contact: {finder_user.name} ({finder_user.email}). Reach out to arrange pickup."
        )
        msg_for_finder = (
            f"✅ You verified the claim for '{found_item.title}'. "
            f"Owner contact: {owner_user.name} ({owner_user.email})."
        )
        db.add(Notification(user_id=owner_user.id, message=msg_for_owner))
        db.add(Notification(user_id=finder_user.id, message=msg_for_finder))
        db.commit()

        return {"message": "Claim verified and items marked returned", "match": serialize_match(match, current_user)}

    elif req.action == "reject":
        match.status = "rejected"
        db.commit()

        msg_reject = f"❌ The claim for '{lost_item.title}' was rejected by the finder/admin."
        db.add(Notification(user_id=lost_item.user_id, message=msg_reject))
        db.commit()

        return {"message": "Claim rejected", "match": serialize_match(match, current_user)}

    else:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")


# ==========================================
# NOTIFICATIONS ENDPOINTS
# ==========================================
@app.post("/api/items/{item_id}/found-notice")
def send_found_notification(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.type != "lost":
        raise HTTPException(status_code=400, detail="Only lost item reports can receive found notifications")

    if item.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot report finding your own lost item")

    # Prevent duplicate notification if the same user clicks 'I Found This' multiple times
    existing = db.query(Notification).filter(
        Notification.user_id == item.user_id,
        Notification.item_id == item.id,
        Notification.finder_name == current_user.name
    ).first()

    if existing:
        return {
            "message": f"You have already sent a found notification to {item.user.name or 'the owner'} for '{item.title}'.",
            "already_notified": True,
            "owner_name": item.user.name if item.user else "Owner"
        }

    # Format notification message: "Someone may have found your lost Black Watch. Check the report for more details."
    finder_label = current_user.name.strip() if current_user.name else "Someone"
    msg = f"{finder_label} may have found your lost '{item.title}'. Check the report for more details."

    notification = Notification(
        user_id=item.user_id,
        item_id=item.id,
        finder_name=current_user.name,
        message=msg,
        is_read=False
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    return {
        "message": f"Notification sent to {item.user.name or 'the owner'} for '{item.title}'!",
        "item_id": item.id,
        "item_title": item.title,
        "owner_name": item.user.name if item.user else "Owner"
    }


@app.get("/api/notifications")
def get_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notes = db.query(Notification).filter(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).all()

    result = []
    for n in notes:
        item_data = None
        if n.item_id:
            item = db.query(Item).filter(Item.id == n.item_id).first()
            if item:
                item_data = {
                    "id": item.id,
                    "title": item.title,
                    "category": item.category,
                    "type": item.type,
                    "status": item.status,
                    "location": item.location,
                    "date": item.date,
                    "image_path": item.image_path
                }

        result.append({
            "id": n.id,
            "message": n.message,
            "is_read": n.is_read,
            "item_id": n.item_id,
            "finder_name": n.finder_name,
            "item": item_data,
            "created_at": n.created_at.isoformat() if n.created_at else None
        })

    return result


@app.put("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    note = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()
    if not note:
        raise HTTPException(status_code=404, detail="Notification not found")
    note.is_read = True
    db.commit()
    return {"message": "Notification marked as read"}


@app.put("/api/notifications/read-all")
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}


# ==========================================
# FEEDBACK & STORIES ENDPOINTS
# ==========================================
@app.post("/api/feedback")
def submit_feedback(
    req: FeedbackSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5 stars")
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Feedback message cannot be empty")

    fb = Feedback(
        user_id=current_user.id,
        rating=req.rating,
        message=req.message.strip()
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)

    return {
        "message": "Thank you! Your feedback has been submitted successfully.",
        "feedback": {
            "id": fb.id,
            "user_name": current_user.name,
            "rating": fb.rating,
            "message": fb.message,
            "created_at": fb.created_at.isoformat() if fb.created_at else None
        }
    }


@app.get("/api/feedback")
def get_feedbacks(db: Session = Depends(get_db)):
    feedbacks = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return [
        {
            "id": f.id,
            "user_name": f.user.name if f.user else "Community Member",
            "rating": f.rating,
            "message": f.message,
            "created_at": f.created_at.isoformat() if f.created_at else None
        }
        for f in feedbacks
    ]


# ==========================================
# ADMIN ENDPOINTS
# ==========================================
@app.get("/api/admin/stats")
def get_admin_stats(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    total_reports = db.query(func.count(Item.id)).scalar()
    total_lost = db.query(func.count(Item.id)).filter(Item.type == "lost").scalar()
    total_found = db.query(func.count(Item.id)).filter(Item.type == "found").scalar()
    total_matches = db.query(func.count(Match.id)).scalar()
    total_returned = db.query(func.count(Item.id)).filter(Item.status == "returned").scalar()
    total_users = db.query(func.count(User.id)).scalar()

    return {
        "total_reports": total_reports,
        "total_lost": total_lost,
        "total_found": total_found,
        "total_matches": total_matches,
        "total_returned": total_returned,
        "total_users": total_users
    }


@app.get("/api/admin/items")
def get_admin_items(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    items = db.query(Item).order_by(Item.created_at.desc()).all()
    # Admin sees contact info and secret detail
    return [serialize_item(item, current_user=admin, include_contact=True) for item in items]


@app.delete("/api/admin/items/{item_id}")
def delete_admin_item(
    item_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Clean up image file if exists
    if item.image_path:
        filename = os.path.basename(item.image_path)
        file_path = os.path.join(UPLOADS_DIR, filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    db.delete(item)
    db.commit()
    return {"message": f"Item {item_id} deleted successfully"}


@app.post("/api/admin/matches/{match_id}/verify")
def admin_verify_match(
    match_id: int,
    req: VerifyRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    return verify_claim(match_id=match_id, req=req, current_user=admin, db=db)
