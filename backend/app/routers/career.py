from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..services.career_adapter import profile_to_features


router = APIRouter(prefix="/career", tags=["career"])


@router.get("/profiles/{child_id}")
def get_career_profile(
    child_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    child = db.get(models.Child, child_id)
    if child is None:
        raise HTTPException(status_code=404, detail="Child not found")
    if user["role"] != "admin" and child.org_id != user.get("organization_id"):
        raise HTTPException(status_code=404, detail="Child not found")
    profile = db.query(models.ChildProfile).filter(models.ChildProfile.child_id == child_id).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Career profile not found")
    return {"child_id": child_id, "profile_id": profile.id, "profile_data": profile.profile_data}


@router.get("/recommendations/{child_id}")
def list_recommendations(
    child_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    child = db.get(models.Child, child_id)
    if child is None:
        raise HTTPException(status_code=404, detail="Child not found")
    if user["role"] != "admin" and child.org_id != user.get("organization_id"):
        raise HTTPException(status_code=404, detail="Child not found")
    return [
        {
            "recommendation_id": rec.id,
            "child_id": rec.child_id,
            "candidates": rec.candidates,
            "model_version": rec.model_version,
            "created_at": rec.created_at,
            "feedback": (
                {
                    "decision": feedback.decision,
                    "chosen_career": feedback.chosen_career,
                    "comment": feedback.comment,
                    "created_at": feedback.created_at,
                }
                if (feedback := db.query(models.RecommendationFeedback)
                    .filter(models.RecommendationFeedback.recommendation_id == rec.id)
                    .first())
                else None
            ),
        }
        for rec in db.query(models.CareerRecommendation)
        .filter(models.CareerRecommendation.child_id == child_id)
        .order_by(models.CareerRecommendation.created_at.desc())
        .all()
    ]


@router.post("/profiles/{child_id}", response_model=schemas.CareerProfileOut, status_code=status.HTTP_201_CREATED)
def save_career_profile(
    child_id: int,
    payload: schemas.CareerProfile,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if child is None:
        raise HTTPException(status_code=404, detail="Child not found")

    profile = db.query(models.ChildProfile).filter(models.ChildProfile.child_id == child_id).first()
    if profile is None:
        profile = models.ChildProfile(child_id=child_id, profile_data=payload.model_dump(by_alias=True))
        db.add(profile)
    else:
        profile.profile_data = payload.model_dump(by_alias=True)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A career profile already exists for this child") from exc
    db.refresh(profile)
    return schemas.CareerProfileOut(child_id=child_id, profile_id=profile.id)


@router.post("/recommend/{child_id}", response_model=schemas.CareerRecommendationOut, status_code=status.HTTP_201_CREATED)
def recommend_career(
    child_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    profile = db.query(models.ChildProfile).filter(models.ChildProfile.child_id == child_id).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Child profile not found")

    recommender = getattr(request.app.state, "career_recommender", None)
    if recommender is None:
        raise HTTPException(status_code=503, detail="Career recommendation model is unavailable")

    features = profile_to_features(profile)
    candidates = recommender.recommend(features, top_n=3)
    if len(candidates) != 3:
        raise HTTPException(status_code=503, detail="Career recommendation model did not return three candidates")

    recommendation = models.CareerRecommendation(
        child_id=child_id,
        profile_id=profile.id,
        recommended_path=candidates[0],
        candidates=candidates,
        model_version=recommender.version,
        created_by=int(admin["id"]),
    )
    db.add(recommendation)
    db.commit()
    db.refresh(recommendation)
    return schemas.CareerRecommendationOut(
        recommendation_id=recommendation.id,
        candidates=candidates,
        model_version=recommendation.model_version,
        note="Suggestions only. An administrator makes the final decision.",
    )


@router.post("/{rec_id}/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(
    rec_id: int,
    payload: schemas.CareerFeedbackCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    recommendation = db.get(models.CareerRecommendation, rec_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if db.query(models.RecommendationFeedback.id).filter(
        models.RecommendationFeedback.recommendation_id == rec_id
    ).first():
        raise HTTPException(status_code=409, detail="Feedback already recorded for this recommendation")

    feedback = models.RecommendationFeedback(
        recommendation_id=rec_id,
        admin_id=int(admin["id"]),
        decision=payload.decision,
        chosen_career=payload.chosen_career,
        comment=payload.comment,
    )
    db.add(feedback)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Feedback already recorded for this recommendation") from exc
    db.refresh(feedback)
    return {"status": "saved", "feedback_id": feedback.id}