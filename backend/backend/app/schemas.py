from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, FiniteFloat, field_validator, model_validator


class NeedCreate(BaseModel):
    org_id: Optional[int] = None
    category: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=0)
    urgency: Optional[Literal["low", "medium", "high", "critical"]] = "medium"
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    required_by: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=200)
    beneficiaries: Optional[int] = Field(default=None, ge=0, le=100000)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class NeedUpdate(BaseModel):
    category: Optional[str] = Field(default=None, min_length=1, max_length=200)
    quantity: Optional[int] = Field(default=None, ge=0)
    urgency: Optional[Literal["low", "medium", "high", "critical"]] = None
    status: Optional[Literal["pending", "open", "fulfilled", "closed"]] = None
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    required_by: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=200)
    beneficiaries: Optional[int] = Field(default=None, ge=0, le=100000)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class NeedOut(BaseModel):
    # Columns are nullable in PostgreSQL (rows inserted by hand/SQL often leave them empty),
    # so the output model must tolerate NULLs instead of failing the whole list with a 500.
    id: int
    org_id: Optional[int] = None
    category: Optional[str] = None
    quantity: Optional[int] = None
    urgency: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    organization_name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    required_by: Optional[datetime] = None
    location: Optional[str] = None
    beneficiaries: Optional[int] = None
    fulfilled_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    class Config:
        from_attributes = True


class OrganizationCreate(BaseModel):
    name: str
    contact: Optional[str] = None


class OrganizationVerification(BaseModel):
    verified: bool


class OrganizationOut(BaseModel):
    id: int
    name: str
    contact: Optional[str] = None
    verified: bool = False
    created_at: Optional[datetime] = None

    @field_validator("verified", mode="before")
    @classmethod
    def _none_is_unverified(cls, value):
        return bool(value) if value is not None else False

    class Config:
        from_attributes = True


class DonorCreate(BaseModel):
    name: str
    contact: Optional[str] = None
    preferences: Optional[str] = None
    location: Optional[str] = None


class DonorOut(BaseModel):
    id: int
    name: str
    contact: Optional[str] = None
    preferences: Optional[str] = None
    location: Optional[str] = None

    class Config:
        from_attributes = True


class VolunteerCreate(BaseModel):
    name: str
    contact: Optional[str] = None
    skills: Optional[str] = None
    availability: Optional[str] = None
    location: Optional[str] = None


class VolunteerOut(BaseModel):
    id: int
    name: str
    contact: Optional[str] = None
    skills: Optional[str] = None
    availability: Optional[str] = None
    location: Optional[str] = None

    class Config:
        from_attributes = True


class ChildCreate(BaseModel):
    org_id: Optional[int] = None
    age: int = Field(ge=0, le=25)
    interests: Optional[str] = Field(default=None, max_length=2000)
    skills: Optional[str] = Field(default=None, max_length=2000)
    academic_performance: Optional[str] = Field(default=None, max_length=2000)


class ChildOut(BaseModel):
    id: int
    org_id: Optional[int] = None
    age: Optional[int] = None
    interests: Optional[str] = None
    skills: Optional[str] = None
    academic_performance: Optional[str] = None

    class Config:
        from_attributes = True


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Literal["organization", "donor", "volunteer", "admin"] = "organization"
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    organization_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    contact: Optional[str] = Field(default=None, max_length=300)
    location: Optional[str] = Field(default=None, max_length=200)
    skills: Optional[str] = Field(default=None, max_length=2000)
    preferences: Optional[str] = Field(default=None, max_length=2000)
    availability: Optional[str] = Field(default=None, max_length=300)

    @field_validator("role", mode="before")
    @classmethod
    def prevent_public_admin_assignment(cls, value):
        return "organization" if value == "admin" else value

    @model_validator(mode="after")
    def require_role_profile(self):
        if self.role in ("donor", "volunteer") and not self.name:
            raise ValueError("name is required for donor and volunteer accounts")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    new_password: str = Field(min_length=12, max_length=128)


class UserRoleUpdate(BaseModel):
    role: Literal["admin", "organization", "donor", "volunteer"]


class UserOut(BaseModel):
    id: int
    email: str
    role: Optional[str] = "organization"
    display_name: Optional[str] = None
    organization_id: Optional[int] = None
    donor_id: Optional[int] = None
    volunteer_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class LoginResponse(Token):
    user: UserOut


class DonationCreate(BaseModel):
    donor_id: Optional[int] = None
    need_id: Optional[int] = None
    amount: Optional[FiniteFloat] = Field(default=None, ge=0)
    resource_description: Optional[str] = Field(default=None, max_length=4000)


class DonationOut(BaseModel):
    id: int
    donor_id: Optional[int]
    need_id: Optional[int]
    amount: Optional[float]
    resource_description: Optional[str]
    timestamp: Optional[datetime]
    donor_name: Optional[str] = None
    need_name: Optional[str] = None

    class Config:
        from_attributes = True


class AssistantAsk(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class KnowledgeEntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20000)
    source: Optional[str] = Field(default=None, max_length=500)


class KnowledgeEntryOut(BaseModel):
    id: int
    title: Optional[str]
    content: Optional[str]
    source: Optional[str]
    embedding_model: Optional[str] = None

    class Config:
        from_attributes = True


class CareerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    age: int = Field(alias="Age", ge=14, le=100)
    gender: str = Field(alias="Gender", min_length=1, max_length=50)
    field_of_study: str = Field(alias="Field_of_Study", min_length=1, max_length=100)
    year_of_study: int = Field(alias="Year_of_Study", ge=0, le=20)
    university_location: str = Field(alias="University_Location", min_length=1, max_length=100)
    gpa: float = Field(alias="GPA", ge=0, le=4)
    relevant_coursework: int = Field(alias="Relevant_Coursework", ge=0, le=1)
    prior_employment: int = Field(alias="Prior_Employment", ge=0, le=1)
    employment_type: str = Field(alias="Employment_Type", min_length=1, max_length=100)
    entrepreneurial_experience: int = Field(alias="Entrepreneurial_Experience", ge=0, le=1)
    startup_participation: int = Field(alias="Startup_Participation", ge=0, le=1)
    career_interests: Literal["Tech", "Finance", "Business", "Design", "Healthcare"] = Field(alias="Career_Interests")
    entrepreneurial_aspirations: str = Field(alias="Entrepreneurial_Aspirations", min_length=1, max_length=100)


class CareerFeedbackCreate(BaseModel):
    decision: Literal["accepted", "modified", "rejected"]
    chosen_career: Optional[str] = Field(default=None, min_length=1, max_length=100)
    comment: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def chosen_career_required_for_acceptance(self):
        if self.decision in ("accepted", "modified") and not self.chosen_career:
            raise ValueError("chosen_career is required for accepted or modified decisions")
        return self

class CareerProfileOut(BaseModel):
    child_id: int
    profile_id: int


class CareerRecommendationOut(BaseModel):
    recommendation_id: int
    candidates: list[str]
    model_version: str
    note: str


class FraudScoreRequest(BaseModel):
    features: dict[str, FiniteFloat]


class FraudScoreOut(BaseModel):
    fraud_probability: float
    flagged: bool
    threshold: float
    model_version: str


class AdminRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    designation: Optional[str] = Field(default=None, max_length=200)
    invite_code: str = Field(default="", max_length=200)


class SuggestionReview(BaseModel):
    decision: Literal["approved", "contacted", "rejected"]


class AdminSetup(BaseModel):
    """First administrator of a new installation, created with the one-time setup token from backend/.env."""
    setup_token: str = Field(min_length=1, max_length=500)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    designation: Optional[str] = Field(default=None, max_length=200)


class AdminCreate(BaseModel):
    """An existing administrator creates another administrator (no invite code needed)."""
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    designation: Optional[str] = Field(default=None, max_length=200)


class AdminActive(BaseModel):
    is_active: bool


class AdminDonorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: Optional[str] = Field(default=None, max_length=200)
    preferences: Optional[str] = Field(default=None, max_length=1000)
    location: Optional[str] = Field(default=None, max_length=200)
    organization_id: Optional[int] = None


class AdminDonorPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    contact: Optional[str] = Field(default=None, max_length=200)
    preferences: Optional[str] = Field(default=None, max_length=1000)
    location: Optional[str] = Field(default=None, max_length=200)
    organization_id: Optional[int] = None
    clear_organization: bool = False
