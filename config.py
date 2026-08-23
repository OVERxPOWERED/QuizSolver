"""Application configuration settings."""

import os
from pathlib import Path
from typing import Literal, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env file from project root
ROOT_DIR = Path(__file__).parent.resolve()
load_dotenv(ROOT_DIR / ".env")


class Config(BaseModel):
    # LMS Settings
    LMS_NETWORK: Literal["internet", "campus"] = Field(
        default=os.getenv("LMS_NETWORK", "internet").strip(),
        description="Network mode: 'internet' (47.29.0.163) or 'campus' (172.16.8.203)",
    )
    LMS_URL_INTERNET: str = Field(
        default=os.getenv("LMS_URL_INTERNET", "http://47.29.0.163/acropolislms").strip(),
        description="Base URL for Internet access",
    )
    LMS_URL_CAMPUS: str = Field(
        default=os.getenv("LMS_URL_CAMPUS", "http://172.16.8.203/acropolislms").strip(),
        description="Base URL for Campus LAN access",
    )
    LMS_USERNAME: str = Field(
        default=os.getenv("LMS_USERNAME", "").strip().lower(),
        description="Student enrollment number (lowercase)",
    )
    LMS_PASSWORD: str = Field(
        default=os.getenv("LMS_PASSWORD", "Student@123").strip(),
        description="LMS Login password",
    )

    # AI Provider Settings
    AI_PROVIDER: Literal["gemini", "nvidia", "openai_compatible"] = Field(
        default=os.getenv("AI_PROVIDER", "gemini"),
        description="Selected AI provider: gemini, nvidia, or openai_compatible",
    )
    GEMINI_API_KEY: str = Field(
        default=os.getenv("GEMINI_API_KEY", ""),
        description="Google Gemini API Key",
    )
    GEMINI_MODEL: str = Field(
        default=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
        description="Gemini Model name (e.g. gemini-3.5-flash-lite, gemini-3.5-flash, gemini-3.6-flash)",
    )

    NVIDIA_API_KEY: str = Field(
        default=os.getenv("NVIDIA_API_KEY", ""),
        description="NVIDIA NIM API Key",
    )
    NVIDIA_BASE_URL: str = Field(
        default=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        description="NVIDIA NIM Base URL",
    )
    NVIDIA_MODEL: str = Field(
        default=os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
        description="NVIDIA NIM model (e.g., meta/llama-3.3-70b-instruct, deepseek-ai/deepseek-r1)",
    )

    # Browser & Execution Settings
    HEADLESS: bool = Field(
        default=os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes"),
        description="Run browser in headless mode (default: False to watch live)",
    )
    SLOW_MO_MS: int = Field(
        default=int(os.getenv("SLOW_MO_MS", "300")),
        description="Playwright action delay in milliseconds",
    )
    HUMAN_DELAY_MIN: float = Field(
        default=float(os.getenv("HUMAN_DELAY_MIN", "1.0")),
        description="Minimum random delay before submitting/clicking options",
    )
    HUMAN_DELAY_MAX: float = Field(
        default=float(os.getenv("HUMAN_DELAY_MAX", "2.5")),
        description="Maximum random delay before submitting/clicking options",
    )
    AUTO_SUBMIT: bool = Field(
        default=os.getenv("AUTO_SUBMIT", "true").lower() in ("true", "1", "yes"),
        description="Automatically submit quiz or ask for manual confirmation",
    )

    # Coding & Assessment Settings
    CODING_LANGUAGE: str = Field(
        default=os.getenv("CODING_LANGUAGE", "python").strip().lower(),
        description="Target programming language for coding challenges (python, cpp, java, c, javascript, sql)",
    )
    ASSESSMENT_MODE: Literal["auto", "quiz", "coding", "mixed"] = Field(
        default=os.getenv("ASSESSMENT_MODE", "auto").strip().lower(),
        description="Mode: 'auto' (detects quiz vs code), 'quiz', 'coding', or 'mixed'",
    )
    TARGET_URL: Optional[str] = Field(
        default=os.getenv("TARGET_URL", "").strip() or None,
        description="Direct URL to any quiz, coding problem, or form",
    )

    # Target Courses (LMS mode)
    TARGET_COURSES: list[str] = [
        "Outcome Based Education",
        "Indian Constitution",
        "Indian Knowledge System",
    ]

    # Database
    DATABASE_PATH: Path = ROOT_DIR / "data" / "quiz_bank.db"

    @property
    def base_url(self) -> str:
        """Return the active LMS Base URL based on network setting."""
        return self.LMS_URL_CAMPUS if self.LMS_NETWORK == "campus" else self.LMS_URL_INTERNET

    @property
    def login_url(self) -> str:
        """Return the login endpoint URL."""
        return f"{self.base_url.rstrip('/')}/login/index.php"

    @property
    def my_courses_url(self) -> str:
        """Return the user's courses overview URL."""
        return f"{self.base_url.rstrip('/')}/my/courses.php"


config = Config()
