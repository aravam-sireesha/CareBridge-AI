from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="organization")
    token_version = Column(Integer, nullable=False, default=0)
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    password_changed_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime, nullable=True)
    notification_prefs = Column(JSON, nullable=True)  # {"in_app": true, "email": false, "push": false}
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    contact = Column(String)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    description = Column(Text)
    address = Column(String)
    registration_number = Column(String)
    website = Column(String)
    verification_status = Column(String, nullable=False, default="pending")  # draft|pending|verified|rejected
    verification_note = Column(Text)
    verification_submitted_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)


class Child(Base):
    __tablename__ = "children"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"))
    age = Column(Integer)
    interests = Column(Text)
    skills = Column(Text)
    academic_performance = Column(Text)


class ChildProfile(Base):
    __tablename__ = "child_profiles"
    __table_args__ = (UniqueConstraint("child_id", name="uq_child_profiles_child_id"),)

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=True)
    profile_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Need(Base):
    __tablename__ = "needs"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"))
    category = Column(String)
    quantity = Column(Integer)
    urgency = Column(String, default="medium")
    status = Column(String, default="pending")
    created_at = Column(DateTime, server_default=func.now())
    title = Column(String)
    description = Column(Text)
    required_by = Column(DateTime, nullable=True)
    location = Column(String)
    beneficiaries = Column(Integer)
    fulfilled_at = Column(DateTime, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)


class NeedAlert(Base):
    __tablename__ = "need_alerts"

    id = Column(Integer, primary_key=True)
    need_id = Column(Integer, ForeignKey("needs.id"), nullable=False)
    score = Column(Float, nullable=False)
    reasons = Column(JSON, nullable=False)
    model_version = Column(String, nullable=False)
    flagged_at = Column(DateTime, server_default=func.now())
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_decision = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)


class Donor(Base):
    __tablename__ = "donors"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    contact = Column(String)
    preferences = Column(Text)
    location = Column(String)


class Volunteer(Base):
    __tablename__ = "volunteers"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    contact = Column(String)
    skills = Column(Text)
    availability = Column(String)
    location = Column(String)
    interests = Column(Text)
    availability_slots = Column(JSON, nullable=True)  # [{"day": "sat", "start": "09:00", "end": "13:00"}]


class Donation(Base):
    __tablename__ = "donations"

    id = Column(Integer, primary_key=True)
    donor_id = Column(Integer, ForeignKey("donors.id"))
    need_id = Column(Integer, ForeignKey("needs.id"))
    amount = Column(Float)
    resource_description = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())
    kind = Column(String, nullable=False, default="money")        # money|goods|service
    status = Column(String, nullable=False, default="confirmed")  # pledged|in_transit|delivered|confirmed
    delivered_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    delivery_note = Column(String)


class DonationFlag(Base):
    __tablename__ = "donation_flags"

    id = Column(Integer, primary_key=True)
    donation_id = Column(Integer, ForeignKey("donations.id"), nullable=False)
    anomaly_score = Column(Float, nullable=False)
    reasons = Column(JSON, nullable=False)
    model_version = Column(String, nullable=False)
    flagged_at = Column(DateTime, server_default=func.now())
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_decision = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True)
    need_id = Column(Integer, ForeignKey("needs.id"))
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=True)
    score = Column(Float)
    reasons = Column(JSON, nullable=True, default=list)
    status = Column(String, default="pending_review")
    created_at = Column(DateTime, server_default=func.now())


class CareerRecommendation(Base):
    __tablename__ = "career_recommendations"

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"))
    profile_id = Column(Integer, ForeignKey("child_profiles.id"))
    recommended_path = Column(String)
    candidates = Column(JSON)
    model_version = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    generated_at = Column(DateTime, server_default=func.now())


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (UniqueConstraint("recommendation_id", name="uq_feedback_recommendation_id"),)

    id = Column(Integer, primary_key=True)
    recommendation_id = Column(Integer, ForeignKey("career_recommendations.id"), nullable=False)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(String, nullable=False)
    chosen_career = Column(String)
    comment = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True)
    title = Column(String)
    content = Column(Text)
    source = Column(String)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    embedding = Column(JSON)
    embedding_model = Column(String)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    sources = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Administrator(Base):
    """Profile row for every administrator account (one-to-one with users)."""
    __tablename__ = "administrators"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    full_name = Column(String, nullable=False)
    phone = Column(String)
    designation = Column(String)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime, nullable=True)
    totp_secret = Column(String, nullable=True)            # encrypted at rest
    totp_enabled = Column(Boolean, nullable=False, default=False)
    totp_last_step = Column(Integer, nullable=True)        # blocks re-use of a code
    recovery_codes = Column(JSON, nullable=True)           # sha256 hashes of unused one-time codes
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class DonorSuggestion(Base):
    """ML-ranked donor suggestion for one need. AI recommends; an administrator decides."""
    __tablename__ = "donor_suggestions"
    __table_args__ = (UniqueConstraint("need_id", "donor_id", name="uq_donor_suggestions_need_donor"),)

    id = Column(Integer, primary_key=True)
    need_id = Column(Integer, ForeignKey("needs.id"), nullable=False, index=True)
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=False, index=True)
    fit_score = Column(Float, nullable=False)        # how well the donor fits the need (0-1)
    urgency_score = Column(Float, nullable=False)    # how pressing the need is (0-1)
    priority_score = Column(Float, nullable=False)   # fit x urgency, used to order the queue (0-1)
    rank_in_need = Column(Integer, nullable=False, default=1)
    reasons = Column(JSON, nullable=False)
    features = Column(JSON, nullable=True)
    model_version = Column(String, nullable=False)
    status = Column(String, nullable=False, default="suggested")  # suggested|approved|contacted|rejected
    generated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class AuditLog(Base):
    """Append-only trail of security events and administrator decisions (transparency and trust)."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    actor_email = Column(String, nullable=True)
    actor_role = Column(String, nullable=True)
    action = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    detail = Column(JSON, nullable=True)
    ip = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)


class Resource(Base):
    """Materials, services or funds an organization or partner can provide."""
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="material")  # material|service|funds
    category = Column(String)
    quantity_total = Column(Integer, nullable=False, default=0)
    quantity_available = Column(Integer, nullable=False, default=0)
    unit = Column(String)
    description = Column(Text)
    status = Column(String, nullable=False, default="available")  # available|unavailable
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class ResourceAllocation(Base):
    """A resource assigned to a need. The AI proposes, an administrator approves, then it is delivered."""
    __tablename__ = "resource_allocations"

    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False, index=True)
    need_id = Column(Integer, ForeignKey("needs.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    score = Column(Float, nullable=True)
    reasons = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="proposed")  # proposed|approved|delivered|rejected|cancelled
    proposed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class VolunteerSuggestion(Base):
    """ML-ranked volunteer suggestion for one need. AI recommends; an administrator decides."""
    __tablename__ = "volunteer_suggestions"
    __table_args__ = (UniqueConstraint("need_id", "volunteer_id", name="uq_volunteer_suggestions_need_volunteer"),)

    id = Column(Integer, primary_key=True)
    need_id = Column(Integer, ForeignKey("needs.id"), nullable=False, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False, index=True)
    fit_score = Column(Float, nullable=False)
    urgency_score = Column(Float, nullable=False)
    priority_score = Column(Float, nullable=False)
    rank_in_need = Column(Integer, nullable=False, default=1)
    reasons = Column(JSON, nullable=False)
    features = Column(JSON, nullable=True)
    model_version = Column(String, nullable=False)
    status = Column(String, nullable=False, default="suggested")  # suggested|approved|contacted|rejected
    generated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Notification(Base):
    """In-app notification. Email and browser push are optional extras controlled by the user's preferences."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text)
    link = Column(String)
    is_read = Column(Boolean, nullable=False, default=False)
    emailed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)


class Event(Base):
    """A volunteering event or campaign run by an organization."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    location = Column(String)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=True)
    capacity = Column(Integer)
    skills_needed = Column(String)
    status = Column(String, nullable=False, default="open")  # open|full|closed|cancelled
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class VolunteerApplication(Base):
    """A volunteer's application to a need (task) or an event. Organization or administrator decides."""
    __tablename__ = "volunteer_applications"

    id = Column(Integer, primary_key=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False, index=True)
    need_id = Column(Integer, ForeignKey("needs.id"), nullable=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True, index=True)
    message = Column(Text)
    status = Column(String, nullable=False, default="applied")  # applied|accepted|declined|withdrawn|completed
    feedback_rating = Column(Integer)
    feedback_comment = Column(Text)
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class ServiceHour(Base):
    """Hours a volunteer served. Counted (and certified) only after an organization or administrator verifies them."""
    __tablename__ = "service_hours"

    id = Column(Integer, primary_key=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("volunteer_applications.id"), nullable=True)
    hours = Column(Float, nullable=False)
    performed_on = Column(DateTime, nullable=False)
    note = Column(String)
    status = Column(String, nullable=False, default="pending")  # pending|verified|rejected
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class RevokedToken(Base):
    """Access tokens that were signed out before they expired. Only the random token id is stored, never the token."""
    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, server_default=func.now(), nullable=False)
