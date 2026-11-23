"""Configuration settings for Job-Search Copilot backend."""

from functools import lru_cache
from typing import Dict, List
from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ensure .env values take precedence over any stale OS environment variables
load_dotenv(override=True)

DEFAULT_SKILL_ALIASES: Dict[str, str] = {
    "reactjs": "React",
    "react.js": "React",
    "react": "React",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "py": "Python",
    "python3": "Python",
    "python": "Python",
    "golang": "Go",
    "go": "Go",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "docker": "Docker",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "fastapi": "FastAPI",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "git": "Git",
    "github": "GitHub",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
}


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    # LLM Settings
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    LLM_MODEL: str = "gemini-2.5-flash"

    # Embeddings & Vector Store
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    CHROMA_DIR: str = ".chroma"
    CHECKPOINT_DB_PATH: str = "data/checkpoints.sqlite"

    # Single-user default ID
    DEFAULT_PROFILE_ID: str = "default_profile"

    # MongoDB Settings
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "job_search_copilot"

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Matching Weights (must sum to 1.0)
    WEIGHT_REQUIRED_SKILLS: float = 0.50
    WEIGHT_PROJECT_SEMANTIC: float = 0.30
    WEIGHT_PREFERENCE_FIT: float = 0.20

    # Similarity Calibration Bounds
    SIM_LOW: float = 0.15
    SIM_HIGH: float = 0.60

    # Score Thresholds
    DEFAULT_MIN_SCORE_TO_CONSIDER: int = 40
    DEFAULT_MIN_SCORE_TO_TAILOR: int = 70
    MIN_COVERAGE_GATE: float = 0.25

    # Skill Aliases Mapping
    SKILL_ALIASES: Dict[str, str] = DEFAULT_SKILL_ALIASES

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_weights(self) -> "Settings":
        """Validate that component weights sum to 1.0 within float tolerance."""
        total = self.WEIGHT_REQUIRED_SKILLS + self.WEIGHT_PROJECT_SEMANTIC + self.WEIGHT_PREFERENCE_FIT
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"Matching weights must sum to 1.0 (got {total:.4f})")
        if self.SIM_LOW >= self.SIM_HIGH:
            raise ValueError("SIM_LOW must be strictly less than SIM_HIGH")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of the application settings."""
    return Settings()


def normalize_skill(skill: str) -> str:
    """Normalize a single skill string (trim whitespace, title case or map to canonical alias).

    Args:
        skill: Raw skill string extracted from resume or text.

    Returns:
        str: Canonical normalized skill name.
    """
    cleaned = skill.strip()
    if not cleaned:
        return ""
    key = cleaned.lower()
    settings = get_settings()
    if key in settings.SKILL_ALIASES:
        return settings.SKILL_ALIASES[key]
    return cleaned.title() if cleaned.islower() else cleaned


def normalize_skills(skills: List[str]) -> List[str]:
    """Deduplicate, clean, and map a list of skills using canonical aliases.

    Args:
        skills: Raw list of skill names.

    Returns:
        List[str]: Cleaned, deduplicated, and normalized list of skills preserving first seen order.
    """
    seen = set()
    normalized: List[str] = []
    for s in skills:
        norm = normalize_skill(s)
        if norm and norm.lower() not in seen:
            seen.add(norm.lower())
            normalized.append(norm)
    return normalized
