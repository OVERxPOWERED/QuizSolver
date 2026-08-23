"""AI Question Solver Engine supporting Google Gemini and NVIDIA NIM with automatic model fallback."""

import json
import re
import time
from typing import Any, Optional
from pydantic import BaseModel, Field
from config import config
from utils.helpers import clean_option_text, fuzzy_match_option, normalize_text
from utils.logger import log


class AISolution(BaseModel):
    selected_option_index: int = Field(description="0-based index of the chosen option")
    selected_option_text: str = Field(description="Exact text of the chosen option")
    confidence: float = Field(default=1.0, description="Confidence score between 0.0 and 1.0")
    explanation: str = Field(default="", description="Brief explanation justifying the choice")


SYSTEM_PROMPT = """You are an authoritative academic expert in Indian Higher Education, specialized in:
1. Indian Constitution: Articles, Parts, Schedules, Preamble, Fundamental Rights & Duties, Directive Principles, Parliamentary & Judicial procedures, and Amendments.
2. Indian Knowledge Systems (IKS): Vedic literature, Upanishads, Darshanas, ancient Indian Science, Mathematics (Sulba Sutras, Aryabhata, Brahmagupta), Ayurveda, Architecture (Vastu/Shilpa), and Metallurgy.
3. Outcome Based Education (OBE): Bloom's Taxonomy cognitive levels, Program Outcomes (POs), Program Specific Outcomes (PSOs), Course Outcomes (COs), Attainment computation, NAAC, and NBA accreditation criteria.

TASK:
Analyze the given multiple-choice / true-false academic question, examine all candidate options, and identify the single most factually accurate and syllabus-aligned answer.

OUTPUT FORMAT:
Respond ONLY with a valid JSON object in the following format (no extra text, no markdown backticks outside JSON):
{
  "selected_option_index": <0-based integer index of the correct option>,
  "selected_option_text": "<exact string of the selected option>",
  "confidence": <float between 0.0 and 1.0>,
  "explanation": "<one concise sentence explaining why this option is correct>"
}
"""


class AISolver:
    """Solves quiz questions using Gemini or NVIDIA NIM with resilient fallbacks."""

    def __init__(self):
        self.provider = config.AI_PROVIDER.lower()
        self._gemini_client = None
        self._nvidia_client = None

    def _get_gemini_client(self):
        if self._gemini_client is None:
            if not config.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is not configured in .env")
            from google import genai
            self._gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
        return self._gemini_client

    def _get_nvidia_client(self):
        if self._nvidia_client is None:
            if not config.NVIDIA_API_KEY:
                raise ValueError("NVIDIA_API_KEY is not configured in .env")
            from openai import OpenAI
            self._nvidia_client = OpenAI(
                base_url=config.NVIDIA_BASE_URL,
                api_key=config.NVIDIA_API_KEY,
                timeout=12.0,  # Strict 12s timeout to prevent hanging
            )
        return self._nvidia_client

    def _build_user_prompt(self, question: str, options: list[str], course_context: str = "") -> str:
        prompt = ""
        if course_context:
            prompt += f"Course Context: {course_context}\n\n"
        prompt += f"Question:\n{question}\n\nCandidate Options:\n"
        for idx, opt in enumerate(options):
            prompt += f"[{idx}] {opt}\n"
        prompt += "\nSelect the single correct option index and text based on official curriculum standards."
        return prompt

    def _parse_response_json(self, raw_text: str, options: list[str]) -> AISolution:
        """Robustly parse JSON response from LLM."""
        raw_text = raw_text.strip()
        cleaned_json = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
        cleaned_json = re.sub(r"^```\s*", "", cleaned_json)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json).strip()

        # Direct JSON parsing
        try:
            data = json.loads(cleaned_json)
            idx = int(data.get("selected_option_index", 0))
            text = str(data.get("selected_option_text", ""))

            if 0 <= idx < len(options):
                return AISolution(
                    selected_option_index=idx,
                    selected_option_text=options[idx],
                    confidence=float(data.get("confidence", 0.95)),
                    explanation=str(data.get("explanation", "")),
                )

            matched_idx = fuzzy_match_option(text, options)
            if matched_idx is not None:
                return AISolution(
                    selected_option_index=matched_idx,
                    selected_option_text=options[matched_idx],
                    confidence=float(data.get("confidence", 0.9)),
                    explanation=str(data.get("explanation", "")),
                )
        except Exception:
            pass

        # Fallback regex extraction
        match_idx = re.search(r'"selected_option_index":\s*(\d+)', raw_text)
        if match_idx:
            idx = int(match_idx.group(1))
            if 0 <= idx < len(options):
                return AISolution(
                    selected_option_index=idx,
                    selected_option_text=options[idx],
                    confidence=0.85,
                    explanation="Extracted via fallback regex",
                )

        # Fallback fuzzy matching
        fuzzy_idx = fuzzy_match_option(raw_text, options)
        if fuzzy_idx is not None:
            return AISolution(
                selected_option_index=fuzzy_idx,
                selected_option_text=options[fuzzy_idx],
                confidence=0.75,
                explanation="Extracted via fuzzy text match",
            )

        return AISolution(
            selected_option_index=0,
            selected_option_text=options[0] if options else "",
            confidence=0.5,
            explanation="Default fallback selection",
        )

    def _solve_gemini(self, question: str, options: list[str], course_context: str) -> AISolution:
        client = self._get_gemini_client()
        user_content = self._build_user_prompt(question, options, course_context)

        # Try configured model, then fallback models if capacity / unavailable
        candidate_models = [config.GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]
        # Remove duplicates while preserving order
        candidate_models = list(dict.fromkeys(candidate_models))

        last_err = None
        for model_name in candidate_models:
            try:
                t0 = time.time()
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_content,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "temperature": 0.1,
                        "response_mime_type": "application/json",
                    },
                )
                dt = time.time() - t0
                log.debug(f"Gemini ({model_name}) answered in {dt:.2f}s")
                return self._parse_response_json(response.text, options)
            except Exception as e:
                last_err = e
                err_str = str(e)
                if "high demand" in err_str or "UNAVAILABLE" in err_str or "404" in err_str:
                    log.warning(f"Model '{model_name}' busy or unavailable. Trying next model...")
                    continue
                else:
                    log.warning(f"Gemini error with '{model_name}': {e}. Trying next fallback...")

        raise RuntimeError(f"All Gemini models failed: {last_err}")

    def _solve_nvidia(self, question: str, options: list[str], course_context: str) -> AISolution:
        client = self._get_nvidia_client()
        user_content = self._build_user_prompt(question, options, course_context)

        t0 = time.time()
        response = client.chat.completions.create(
            model=config.NVIDIA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        dt = time.time() - t0
        log.debug(f"NVIDIA NIM ({config.NVIDIA_MODEL}) answered in {dt:.2f}s")
        raw_text = response.choices[0].message.content or ""
        return self._parse_response_json(raw_text, options)

    def solve_question(
        self, question: str, options: list[str], course_context: str = ""
    ) -> AISolution:
        """
        Solve question using configured provider with automatic multi-provider fallback.
        """
        if not options:
            raise ValueError("Cannot solve question with empty options list")

        primary_error = None
        # 1. Try primary configured provider
        if self.provider == "gemini":
            try:
                return self._solve_gemini(question, options, course_context)
            except Exception as e:
                primary_error = e
                log.error(f"Gemini API error: {e}")
                if config.NVIDIA_API_KEY:
                    log.info("Attempting automatic fallback to NVIDIA NIM...")
                    try:
                        return self._solve_nvidia(question, options, course_context)
                    except Exception as nv_e:
                        log.error(f"NVIDIA fallback error: {nv_e}")
        elif self.provider == "nvidia":
            try:
                return self._solve_nvidia(question, options, course_context)
            except Exception as e:
                primary_error = e
                log.error(f"NVIDIA NIM error: {e}")
                if config.GEMINI_API_KEY:
                    log.info("Attempting automatic fallback to Google Gemini...")
                    try:
                        return self._solve_gemini(question, options, course_context)
                    except Exception as gem_e:
                        log.error(f"Gemini fallback error: {gem_e}")

        # Final resilient fallback: select first option if all remote calls fail
        log.warning("All AI providers failed. Falling back to default option selection.")
        return AISolution(
            selected_option_index=0,
            selected_option_text=options[0],
            confidence=0.5,
            explanation="Safe fallback selection",
        )


solver = AISolver()
