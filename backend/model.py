"""
ReviewTrust AI – Model Prediction Module
==========================================
Loads the pre-trained AdaBoost classifier and TF-IDF vectorizer once at
module import time, then exposes predict_reviews() for the FastAPI endpoint.

DO NOT retrain here – training is done exclusively via train_model.py.
"""

import joblib
from pathlib import Path
from typing import List, Dict

# ─── Resolve paths relative to this file ─────────────────────────────────────
_BASE_DIR        = Path(__file__).parent
_MODEL_PATH      = _BASE_DIR / "models" / "fake_review_model.pkl"
_VECTORIZER_PATH = _BASE_DIR / "models" / "vectorizer.pkl"


def _load_artifacts():
    """Load model + vectorizer; raise a clear error if not yet trained."""
    if not _MODEL_PATH.exists() or not _VECTORIZER_PATH.exists():
        raise FileNotFoundError(
            "Trained model not found. Run  'python train_model.py'  first.\n"
            f"  Expected model      : {_MODEL_PATH}\n"
            f"  Expected vectorizer : {_VECTORIZER_PATH}"
        )
    print(f"[model.py] Loading model from      : {_MODEL_PATH}")
    print(f"[model.py] Loading vectorizer from : {_VECTORIZER_PATH}")
    mdl = joblib.load(_MODEL_PATH)
    vec = joblib.load(_VECTORIZER_PATH)
    print("[model.py] Model and vectorizer loaded.\n")
    return mdl, vec


# Eager load – happens ONCE when the FastAPI worker starts
model, vectorizer = _load_artifacts()


def predict_reviews(reviews: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Classify each review as 'fake' or 'genuine'.

    Parameters
    ----------
    reviews : list of dicts, each containing key 'review_text'
        e.g. [{"review_text": "Amazing product!!"}, ...]

    Returns
    -------
    list of dicts  –  [{"review": "...", "prediction": "fake|genuine"}, ...]
    """
    if not reviews:
        return []

    texts = [r["review_text"] for r in reviews]
    X     = vectorizer.transform(texts)
    preds = model.predict(X)

    return [
        {"review": text, "prediction": str(pred)}
        for text, pred in zip(texts, preds)
    ]
