# AI-Based Lost & Found Object Matching System

## 10-Line Plan
1. Initialize FastAPI backend with SQLite database and local uploads folder.
2. Define SQLAlchemy models for User, Item, Match, and Notification.
3. Implement JWT authentication with role-based access (user/admin).
4. Integrate CLIP ViT-B-32 (images) and all-MiniLM-L6-v2 (text) for embeddings.
5. Implement cosine similarity matching engine with weighted multimodal scoring.
6. Build CRUD & search API endpoints for reporting, claiming, and administration.
7. Implement human-in-the-loop claim verification using finder secret details.
8. Seed database with admin, demo users, 10 items (3 true match pairs), and images.
9. Build modern responsive Single-Page Application (SPA) frontend with Tailwind styling.
10. Verify backend functionality with a comprehensive test suite.

---

## 2-Step Run Instructions

### Step 1: Start Backend
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Seed demo data (creates admin@demo.com, user1@demo.com, user2@demo.com, items & images)
python backend/seed.py

# 3. Run the FastAPI server
uvicorn backend.main:app --reload --port 8000
```

### Step 2: Open Frontend
- Open `frontend/index.html` directly in any modern browser, OR serve it via:
```bash
# Optional static server:
npx serve frontend -p 3000
```
- Access the web interface at `http://localhost:3000` (or double-click `frontend/index.html`).

---

## Default Credentials
- **Admin**: `admin@demo.com` / `admin123`
- **User 1**: `user1@demo.com` / `user123`
- **User 2**: `user2@demo.com` / `user234`
