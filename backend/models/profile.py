"""Pydantic schemas for candidate profile, sub-models, and job preferences."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class Education(BaseModel):
    """Educational qualification details."""

    institution: str
    degree: str
    field: str
    start_year: int
    end_year: Optional[int] = None
    cgpa: Optional[float] = None


class Project(BaseModel):
    """Personal or academic project details."""

    title: str
    bullets: List[str] = Field(default_factory=list)
    tech: List[str] = Field(default_factory=list)
    link: Optional[str] = None


class Experience(BaseModel):
    """Professional or internship experience details."""

    company: str
    role: str
    start_date: str
    end_date: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)


class Profile(BaseModel):
    """Structured candidate profile extracted from resume."""

    id: Optional[str] = "default_profile"
    name: str
    education: List[Education] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    projects: List[Project] = Field(default_factory=list)
    experience: List[Experience] = Field(default_factory=list)
    links: Dict[str, str] = Field(default_factory=dict)


class Preferences(BaseModel):
    """Candidate job search and filtering preferences."""

    id: str = "default_preferences"
    target_roles: List[str] = Field(default_factory=list)
    max_duration_months: int = Field(default=6, description="Max internship duration in months")
    preferred_locations: List[str] = Field(default_factory=list)
    remote_ok: bool = True
    emphasise_skills: List[str] = Field(default_factory=list)
    avoid_skills: List[str] = Field(default_factory=list)
    min_score_to_tailor: int = Field(default=70, description="Minimum score to auto-tailor resume")
    min_score_to_consider: int = Field(default=40, description="Minimum score to consider job")

    @model_validator(mode="after")
    def validate_thresholds(self) -> "Preferences":
        """Validate threshold constraints and positive duration."""
        if self.max_duration_months <= 0:
            raise ValueError("max_duration_months must be greater than 0")
        if not (0 <= self.min_score_to_consider <= 100):
            raise ValueError("min_score_to_consider must be between 0 and 100")
        if not (0 <= self.min_score_to_tailor <= 100):
            raise ValueError("min_score_to_tailor must be between 0 and 100")
        if self.min_score_to_consider >= self.min_score_to_tailor:
            raise ValueError("min_score_to_consider must be strictly less than min_score_to_tailor")
        return self
