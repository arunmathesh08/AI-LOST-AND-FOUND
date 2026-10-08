import os
import logging
import numpy as np
from PIL import Image

logger = logging.getLogger("ai_service")

# Global singleton storage for models
_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None
_text_model = None
_initialized = False


def load_ai_models():
    """Load CLIP ViT-B-32 and sentence-transformers models once at startup."""
    global _clip_model, _clip_preprocess, _clip_tokenizer, _text_model, _initialized
    if _initialized:
        return

    logger.info("Initializing AI models...")

    # 1. Load Sentence Transformer (all-MiniLM-L6-v2)
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading sentence-transformers (all-MiniLM-L6-v2)...")
        _text_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("SentenceTransformer loaded successfully.")
    except Exception as e:
        logger.warning(f"Could not load SentenceTransformer: {e}. Fallback text vectorizer will be used.")
        _text_model = None

    # 2. Load open_clip CLIP ViT-B-32
    try:
        import torch
        import open_clip
        logger.info("Loading open_clip (ViT-B-32, laion2b_s34b_b79k)...")
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
        model.eval()
        _clip_model = model
        _clip_preprocess = preprocess
        _clip_tokenizer = open_clip.get_tokenizer("ViT-B-32")
        logger.info("CLIP model loaded successfully.")
    except Exception as e:
        logger.warning(f"Could not load open_clip: {e}. Fallback image vectorizer will be used.")
        _clip_model = None
        _clip_preprocess = None

    _initialized = True


def _fallback_text_embedding(text: str, dim: int = 384) -> list[float]:
    """Deterministic hash-based embedding fallback when neural weights are unavailable."""
    np.random.seed(abs(hash(text.lower())) % (2**32))
    vec = np.random.randn(dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    return (vec / (norm + 1e-9)).tolist()


def _fallback_image_embedding(image_path: str, dim: int = 512) -> list[float]:
    """Deterministic color/histogram embedding fallback when neural weights are unavailable."""
    try:
        with Image.open(image_path) as img:
            img_rgb = img.convert("RGB").resize((16, 16))
            arr = np.array(img_rgb).flatten().astype(np.float32)
            if len(arr) < dim:
                arr = np.pad(arr, (0, dim - len(arr)))
            else:
                arr = arr[:dim]
            norm = np.linalg.norm(arr)
            return (arr / (norm + 1e-9)).tolist()
    except Exception:
        return _fallback_text_embedding(os.path.basename(image_path), dim=dim)


def extract_text_embedding(text: str) -> list[float]:
    """Compute text embedding vector using all-MiniLM-L6-v2."""
    if not text or not text.strip():
        return []

    global _initialized
    if not _initialized:
        load_ai_models()

    if _text_model is not None:
        try:
            emb = _text_model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            return emb.tolist()
        except Exception as e:
            logger.error(f"Error extracting sentence embedding: {e}")

    return _fallback_text_embedding(text)


def extract_image_embedding(image_path: str) -> list[float]:
    """Compute image embedding vector using CLIP ViT-B-32."""
    if not image_path or not os.path.exists(image_path):
        return []

    global _initialized
    if not _initialized:
        load_ai_models()

    if _clip_model is not None and _clip_preprocess is not None:
        try:
            import torch
            with Image.open(image_path) as img:
                image_input = _clip_preprocess(img.convert("RGB")).unsqueeze(0)
                with torch.no_grad():
                    image_features = _clip_model.encode_image(image_input)
                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    return image_features.squeeze(0).cpu().numpy().tolist()
        except Exception as e:
            logger.error(f"Error extracting CLIP image embedding: {e}")

    return _fallback_image_embedding(image_path)


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity between two 1D vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)
    dot = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    sim = dot / (norm1 * norm2)
    # Cosine sim in [-1, 1], normalize to [0, 1] range for score breakdown
    return float(max(0.0, min(1.0, (sim + 1.0) / 2.0 if sim < 0 else sim)))


def compute_match_score(lost_item, found_item) -> dict:
    """
    Score formula:
    score = 0.4*image_sim + 0.4*text_sim + 0.1*(same category) + 0.1*(same location)
    If an image is missing, use text_sim only for that part:
    score = 0.8*text_sim + 0.1*(same category) + 0.1*(same location)
    """
    cat_match = 1.0 if (lost_item.category and found_item.category and lost_item.category.strip().lower() == found_item.category.strip().lower()) else 0.0
    
    # Fuzzy/case-insensitive location match
    loc_lost = (lost_item.location or "").strip().lower()
    loc_found = (found_item.location or "").strip().lower()
    loc_match = 0.0
    if loc_lost and loc_found:
        if loc_lost == loc_found or loc_lost in loc_found or loc_found in loc_lost:
            loc_match = 1.0

    txt_score = cosine_similarity(lost_item.txt_vec, found_item.txt_vec)
    has_both_images = bool(lost_item.img_vec and found_item.img_vec)
    
    if has_both_images:
        img_score = cosine_similarity(lost_item.img_vec, found_item.img_vec)
        final_score = (0.4 * img_score) + (0.4 * txt_score) + (0.1 * cat_match) + (0.1 * loc_match)
    else:
        img_score = 0.0
        final_score = (0.8 * txt_score) + (0.1 * cat_match) + (0.1 * loc_match)

    final_score = round(max(0.0, min(1.0, float(final_score))), 4)
    img_score = round(float(img_score), 4)
    txt_score = round(float(txt_score), 4)

    return {
        "score": final_score,
        "img_score": img_score,
        "txt_score": txt_score,
        "category_match": bool(cat_match),
        "location_match": bool(loc_match),
        "has_images": has_both_images
    }


def find_and_record_matches(db, target_item):
    """
    Compare the target item only with open items of the opposite type.
    Save matches with score >= 0.55; create a notification for both users if score >= 0.70.
    """
    from backend.models import Item, Match, Notification

    opposite_type = "found" if target_item.type == "lost" else "lost"
    candidates = db.query(Item).filter(
        Item.type == opposite_type,
        Item.status == "open",
        Item.id != target_item.id,
        Item.user_id != target_item.user_id  # do not match own items
    ).all()

    created_matches = []

    for candidate in candidates:
        lost_item = target_item if target_item.type == "lost" else candidate
        found_item = candidate if target_item.type == "lost" else target_item

        # Check if match already exists
        existing = db.query(Match).filter(
            Match.lost_id == lost_item.id,
            Match.found_id == found_item.id
        ).first()

        score_data = compute_match_score(lost_item, found_item)
        score = score_data["score"]

        if score >= 0.55:
            if existing:
                existing.score = score
                existing.img_score = score_data["img_score"]
                existing.txt_score = score_data["txt_score"]
                match_record = existing
            else:
                match_record = Match(
                    lost_id=lost_item.id,
                    found_id=found_item.id,
                    score=score,
                    img_score=score_data["img_score"],
                    txt_score=score_data["txt_score"],
                    status="suggested"
                )
                db.add(match_record)
                db.flush()

            created_matches.append(match_record)

            # Create notification for both users if score >= 0.70
            if score >= 0.70:
                pct = int(score * 100)
                msg_lost_owner = (
                    f"🎯 High confidence match ({pct}%) found for your lost item '{lost_item.title}'! "
                    f"Check your matches to view details and claim."
                )
                msg_found_owner = (
                    f"🎯 Potential owner found ({pct}% match) for the '{found_item.title}' you reported found!"
                )
                
                db.add(Notification(user_id=lost_item.user_id, message=msg_lost_owner))
                db.add(Notification(user_id=found_item.user_id, message=msg_found_owner))

    db.commit()
    return created_matches
