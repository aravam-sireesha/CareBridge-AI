from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics.pairwise import cosine_similarity


CAREER_MODEL_VERSION = "career-hybrid-1.1.0"


class CareerRecommender:
    def __init__(self, path: str):
        bundle = joblib.load(path)
        self.encoder = bundle["encoder"]
        self.features = bundle["features"]
        self.version = bundle["model_version"]
        if self.version != CAREER_MODEL_VERSION:
            raise ValueError("Career model artifact has missing or unsupported model_version metadata")
        if bundle.get("sklearn_version") != sklearn.__version__:
            raise ValueError("Career model artifact scikit-learn version does not match the installed version")

        profiles = bundle["profiles"]
        vectors = self.encoder.transform(profiles[self.features])
        self.vectors = vectors.toarray() if hasattr(vectors, "toarray") else vectors
        self.labels = profiles["Recommended_Career_Path"].to_numpy()

    def recommend(self, features: dict, top_n: int = 3) -> list[str]:
        frame = pd.DataFrame([features])[self.features]
        vector = self.encoder.transform(frame)
        vector = vector.toarray() if hasattr(vector, "toarray") else vector
        similarities = cosine_similarity(vector, self.vectors)[0]
        scores = {
            career: float(similarities[self.labels == career].mean())
            for career in np.unique(self.labels)
        }
        ranked = sorted(scores, key=scores.get, reverse=True)

        interest = features.get("Career_Interests")
        if interest in ranked:
            ranked.remove(interest)
            ranked.insert(0, interest)
        return ranked[:top_n]


def load_career_recommender() -> CareerRecommender | None:
    default_path = Path(__file__).resolve().parents[2] / "models" / "career_guidance_recommender.pkl"
    model_path = Path(__import__("os").environ.get("CAREER_MODEL_PATH", default_path))
    if not model_path.exists():
        return None
    return CareerRecommender(str(model_path))