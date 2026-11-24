from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, CheckConstraint
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
    # E-mail verification at sign-up. `pending` is set ONLY by self-registration when verification is switched on; accounts that
    # were created any other way (existing users, administrators' invitations) are never blocked. NULL means "not pending".
    email_verification_pending = Column(Boolean, nullable=True)
    email_verified_at = Column(DateTime, nullable=True)
    # Mobile number (E.164) and its verification, same NULL-means-not-pending rule as e-mail. Never returned by the user APIs.
    phone_e164 = Column(String, unique=True, nullable=True, index=True)
    phone_verification_pending = Column(Boolean, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
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


class OtpChallenge(Base):
    """A short one-time code sent to an account holder. Only a keyed hash of the code is stored, never the code."""
    __tablename__ = "otp_challenges"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    purpose = Column(String, nullable=False, default="password_reset")
    code_hash = Column(String, nullable=False)
    salt = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    used_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=False)
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
    # Optional position, set only by the donor (PUT /locations/me). Never returned to other users: they only
    # ever see a distance rounded up to whole km. NULL means "not shared".
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_updated_at = Column(DateTime, nullable=True)


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
    # Optional position and travel range, set only by the volunteer. Same privacy rule as Donor.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    service_radius_km = Column(Float, nullable=True)
    location_updated_at = Column(DateTime, nullable=True)
    # Weekly availability lives in `availability_slots` (validated by services/availability.py). Capacity is the weight of donated
    # items the volunteer can carry in one trip, SELF-DECLARED and not verified (it is not passenger seats).
    availability_timezone = Column(String, nullable=True)
    transport_mode = Column(String, nullable=True)
    carry_capacity_kg = Column(Float, nullable=True)


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


class DeliveryTask(Base):
    """One delivery from a donor to an organization's need, moved forward by explicit actions (services/delivery_flow.py)."""
    __tablename__ = "delivery_tasks"
    __table_args__ = (CheckConstraint("quantity >= 1", name="ck_delivery_quantity_positive"),)

    id = Column(Integer, primary_key=True)
    need_id = Column(Integer, ForeignKey("needs.id"), nullable=False, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=False, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    quantity = Column(Integer, nullable=False)
    item_description = Column(String(300))
    estimated_weight_kg = Column(Float, nullable=True)       # optional: lets us check a volunteer's declared carrying capacity
    status = Column(String, nullable=False, default="proposed", index=True)
    submitted_at = Column(DateTime)
    decided_at = Column(DateTime)
    decision_reason = Column(String(500))
    committed_at = Column(DateTime)
    offered_at = Column(DateTime)
    accepted_at = Column(DateTime)
    pickup_at = Column(DateTime)
    picked_up_at = Column(DateTime)
    in_transit_at = Column(DateTime)
    delivered_at = Column(DateTime)
    delivery_note = Column(String(500))
    confirmed_at = Column(DateTime)
    received_quantity = Column(Integer)
    receipt_note = Column(String(500))
    cancelled_at = Column(DateTime)
    cancel_reason = Column(String(500))
    exception_reason = Column(String(500))
    exception_from = Column(String)
    exception_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class DeliveryLocation(Base):
    """The volunteer's LATEST shared position for one delivery. One row per delivery, overwritten on every update (there is
    no movement history), and deleted when the delivery leaves the active stages. Exists only after the volunteer opts in."""
    __tablename__ = "delivery_locations"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("delivery_tasks.id"), nullable=False, unique=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    consented_at = Column(DateTime, nullable=False)
    stopped_at = Column(DateTime, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    accuracy_m = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=True)


class DeliveryEvent(Base):
    """Append-only history of a delivery: who did what, when, and why."""
    __tablename__ = "delivery_events"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("delivery_tasks.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    from_status = Column(String)
    to_status = Column(String, nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_role = Column(String)
    note = Column(String(500))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


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


class ChatConversation(Base):
    """One chat thread. Private to its owner: every query filters on user_id."""
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="New chat")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(12), nullable=False)          # user | assistant
    content = Column(Text, nullable=False, default="")
    sources = Column(JSON)                              # evidence shown with the answer (knowledge passages, live records)
    meta = Column(JSON)                                 # answer mode, model, timings, validation, interrupted flag
    feedback = Column(String(8))                        # up | down | null
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)


class AgentRun(Base):
    """A goal given to the agent: proposed plan -> human approval -> execution -> verified result. Kept as the run history."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    goal = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, index=True)   # awaiting_approval | running | completed | failed | rejected
    route = Column(JSON)
    plan = Column(JSON)
    planned_by = Column(String(16))
    steps = Column(JSON)
    answer = Column(Text)
    validation = Column(JSON)
    create_proposals = Column(Boolean, nullable=False, default=False)
    requires_approval = Column(Boolean, nullable=False, default=False)
    duration_ms = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class LLMUsage(Base):
    """One language-model request: who, which model, how long, did it work. No prompt or answer text is stored."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(16), nullable=False, default="chat")      # chat | test
    model = Column(String(120))
    prompt_chars = Column(Integer, nullable=False, default=0)
    completion_chars = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer)
    ok = Column(Boolean, nullable=False, default=True)
    error = Column(String(200))



class TrackingSession(Base):
    """One consented period of live location sharing for ONE delivery. Created when the assigned volunteer presses Start; the
    row is the record of what they agreed to (purpose, wording version, whether a movement trail may be kept, and until when).
    `DeliveryLocation` still holds the latest position; this table holds the lifecycle."""
    __tablename__ = "tracking_sessions"

    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, unique=True, index=True)          # the id the device sends as tracking_session_id
    task_id = Column(Integer, ForeignKey("delivery_tasks.id"), nullable=False, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False, index=True)
    status = Column(String(10), nullable=False, default="active")                    # active | paused | stopped | expired
    purpose = Column(String(60), nullable=False, default="delivery_tracking")
    consent_version = Column(String(20), nullable=False)
    consented_at = Column(DateTime, nullable=False)
    retain_history = Column(Boolean, nullable=False, default=False)                  # the volunteer agreed a trail may be kept
    expires_at = Column(DateTime, nullable=True)                                     # sharing cannot outlive this
    paused_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    last_seq = Column(Integer, nullable=False, default=-1)                           # duplicate / replay protection
    stale_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class LocationHistory(Base):
    """A movement trail point. Written ONLY when the session's volunteer opted in (`retain_history`), deleted by the retention
    job after LOCATION_RETENTION_DAYS, and readable only by administrators (every read is audited)."""
    __tablename__ = "location_history"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_location_history_session_seq"),)

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tracking_sessions.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("delivery_tasks.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy_m = Column(Float, nullable=True)
    heading = Column(Float, nullable=True)
    speed_mps = Column(Float, nullable=True)
    client_time = Column(DateTime, nullable=True)                                    # when the device says the fix was taken
    recorded_at = Column(DateTime, nullable=False, index=True)                       # server clock
    flagged = Column(Boolean, nullable=False, default=False)                         # physically implausible jump from the previous fix



class PushSubscription(Base):
    """One browser/device that a person chose to receive Web Push on. The subscription itself IS the consent: creating it required
    the browser permission prompt, and deleting it (or the person turning notifications off) stops all sending to that device.
    The endpoint is unique, so the same device can never receive a person's notices twice or another person's after sign-out."""
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint_hash = Column(String(64), nullable=False, unique=True)                  # sha256 of the endpoint URL (lookup key)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(String(200), nullable=False)
    auth = Column(String(100), nullable=False)
    user_agent = Column(String(200), nullable=True)
    failure_count = Column(Integer, nullable=False, default=0)                       # consecutive failures; the device is dropped after a few
    last_accepted_at = Column(DateTime, nullable=True)
    expired_at = Column(DateTime, nullable=True)                                     # the push service said the device is gone (404/410)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class NotificationEvent(Base):
    """What was attempted for one outbound (non in-app) notification, and what the PROVIDER answered. `accepted_by_provider` means
    the push service took the message (HTTP 201); it does NOT mean the person saw it, and nothing in the product says 'delivered'."""
    __tablename__ = "notification_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(12), nullable=False)                                     # push | email | sms | whatsapp
    kind = Column(String(20), nullable=False)
    title = Column(String(120), nullable=True)
    link = Column(String(300), nullable=True)
    status = Column(String(24), nullable=False, default="queued")                    # queued | accepted_by_provider | failed | no_subscription | suppressed
    attempts = Column(Integer, nullable=False, default=0)
    accepted_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(40), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, nullable=True)



class BackgroundJob(Base):
    """A durable log line per queued job, so "did the reminder go out, and if not why" has an answer. The queue itself lives in Redis;
    this table is the audit trail and is safe to prune."""
    __tablename__ = "background_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), nullable=False, unique=True, index=True)
    name = Column(String(60), nullable=False, index=True)
    status = Column(String(12), nullable=False, default="queued")                    # queued | running | retrying | succeeded | dead
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    last_error = Column(String(80), nullable=True)                                   # an error CLASS or code, never a message that could hold personal data
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class StoredDocument(Base):
    """Metadata for a file kept in PRIVATE object storage (verification documents, delivery proof). The file itself is never served
    from this app: reads use short-lived signed URLs. A document is NOT verification: an administrator must review it."""
    __tablename__ = "stored_documents"

    id = Column(Integer, primary_key=True)
    owner_type = Column(String(16), nullable=False)                                  # organization | volunteer | delivery
    owner_id = Column(Integer, nullable=False)
    kind = Column(String(30), nullable=False)
    object_key = Column(String(200), nullable=False, unique=True)                    # random, unguessable; never the original file name
    original_name = Column(String(120), nullable=True)
    content_type = Column(String(60), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    review_status = Column(String(12), nullable=False, default="pending")            # pending | approved | rejected
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(String(300), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class PaymentTransaction(Base):
    """A Razorpay order and what is known about its payment. Payments are OFF unless PAYMENTS_ENABLED=true; do not enable them before the
    legal, tax and FCRA reviews are complete. Status changes only through a verified signature or a verified webhook."""
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    razorpay_order_id = Column(String(40), nullable=False, unique=True)
    razorpay_payment_id = Column(String(40), nullable=True, unique=True)
    receipt = Column(String(40), nullable=False, unique=True)
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    status = Column(String(12), nullable=False, default="created")                   # created | captured | failed | refunded
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, nullable=True)


class PaymentEvent(Base):
    """Every Razorpay webhook event id we have processed. The unique id makes a re-delivered webhook a harmless no-op."""
    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(80), nullable=False, unique=True)
    event_type = Column(String(40), nullable=False)
    razorpay_order_id = Column(String(40), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
