"""Helper functions for text cleaning, hashing, delays, and comparisons."""

import asyncio
import hashlib
import random
import re
from typing import Optional


def normalize_text(text: str) -> str:
    """Normalize text by stripping whitespace, standardizing quotes, and removing extra spaces."""
    if not text:
        return ""
    # Standardize unicode quotes and dashes
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("–", "-").replace("—", "-")
    # Collapse multiple whitespaces and newlines
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compute_question_hash(question_text: str) -> str:
    """Generate MD5 hash of normalized question text for database caching."""
    norm = normalize_text(question_text).lower()
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


async def human_delay(min_sec: float = 1.0, max_sec: float = 2.5) -> None:
    """Async sleep with randomized delay to emulate human reaction time."""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


def clean_option_text(text: str) -> str:
    """Strip common Moodle option prefixes like 'a. ', 'b. ', 'A) ', 'Option 1: '."""
    text = normalize_text(text)
    # Remove prefixes like 'a. ', 'B. ', 'c) ', 'd. '
    cleaned = re.sub(r"^[a-zA-Z0-9][\.\)]\s*", "", text)
    # Remove 'Select one:' or 'Select one or more:' artifacts
    cleaned = re.sub(r"^Select (one|all that apply|one or more):\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def fuzzy_match_option(ai_choice: str, available_options: list[str]) -> Optional[int]:
    """
    Find best matching option index given an AI textual response or index.
    Returns 0-based option index, or None if no clear match.
    """
    ai_choice_norm = normalize_text(ai_choice).lower()
    ai_choice_clean = clean_option_text(ai_choice).lower()

    # 1. Exact match with full or cleaned text
    for idx, opt in enumerate(available_options):
        opt_norm = normalize_text(opt).lower()
        opt_clean = clean_option_text(opt).lower()
        if ai_choice_norm == opt_norm or ai_choice_clean == opt_clean:
            return idx

    # 2. Substring match
    for idx, opt in enumerate(available_options):
        opt_clean = clean_option_text(opt).lower()
        if (len(ai_choice_clean) > 3 and ai_choice_clean in opt_clean) or (
            len(opt_clean) > 3 and opt_clean in ai_choice_clean
        ):
            return idx

    # 3. Check for single letter/number indicators (A, B, C, D / 1, 2, 3, 4)
    letter_map = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
    match = re.search(r"\b([a-eA-E]|[1-5])\b", ai_choice)
    if match:
        letter = match.group(1).lower()
        idx = letter_map.get(letter)
        if idx is not None and idx < len(available_options):
            return idx

    return None
