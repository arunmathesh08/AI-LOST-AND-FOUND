import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user", nullable=False)  # "user" | "admin"
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("Item", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(10), nullable=False)  # "lost" | "found"
    title = Column(String(150), nullable=False)
    category = Column(String(80), nullable=False)
    description = Column(Text, nullable=False)
    color = Column(String(50), nullable=True)
    brand = Column(String(80), nullable=True)
    location = Column(String(150), nullable=False)
    date = Column(String(50), nullable=False)
    image_path = Column(String(255), nullable=True)
    secret_detail = Column(Text, nullable=True)  # Found items only, never shown publicly
    status = Column(String(20), default="open", nullable=False)  # "open" | "claimed" | "returned"

    img_vec_raw = Column(Text, nullable=True)
    txt_vec_raw = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="items")
    lost_matches = relationship("Match", foreign_keys="Match.lost_id", back_populates="lost_item", cascade="all, delete-orphan")
    found_matches = relationship("Match", foreign_keys="Match.found_id", back_populates="found_item", cascade="all, delete-orphan")

    @property
    def img_vec(self):
        if self.img_vec_raw:
            try:
                return json.loads(self.img_vec_raw)
            except Exception:
                return None
        return None

    @img_vec.setter
    def img_vec(self, value):
        self.img_vec_raw = json.dumps(value) if value is not None else None

    @property
    def txt_vec(self):
        if self.txt_vec_raw:
            try:
                return json.loads(self.txt_vec_raw)
            except Exception:
                return None
        return None

    @txt_vec.setter
    def txt_vec(self, value):
        self.txt_vec_raw = json.dumps(value) if value is not None else None


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    lost_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    found_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    score = Column(Float, nullable=False)
    img_score = Column(Float, default=0.0)
    txt_score = Column(Float, default=0.0)
    status = Column(String(20), default="suggested", nullable=False)  # "suggested" | "claimed" | "verified" | "rejected"
    claim_answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lost_item = relationship("Item", foreign_keys=[lost_id], back_populates="lost_matches")
    found_item = relationship("Item", foreign_keys=[found_id], back_populates="found_matches")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)
    finder_name = Column(String(100), nullable=True)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="notifications")
    item = relationship("Item")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1 to 5
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
