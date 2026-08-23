"""Universal AI Reasoning & Code Synthesis Engine supporting Google Gemini and NVIDIA NIM."""

import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field
from config import config
from utils.helpers import clean_option_text, fuzzy_match_option, normalize_text
from utils.logger import log


class AISolution(BaseModel):
    selected_option_index: int = Field(default=0, description="0-based index of the chosen option")
    selected_option_text: str = Field(default="", description="Exact text of the chosen option")
    confidence: float = Field(default=1.0, description="Confidence score between 0.0 and 1.0")
    explanation: str = Field(default="", description="Brief explanation justifying the choice")


class AICodeSolution(BaseModel):
    language: str = Field(description="Target programming language (python, cpp, java, c, javascript)")
    code: str = Field(description="Pure, complete, and optimal source code")
    complexity_time: str = Field(default="O(N)", description="Time complexity analysis")
    complexity_space: str = Field(default="O(1)", description="Space complexity analysis")
    explanation: str = Field(default="", description="Brief summary of algorithmic approach")


GENERIC_QUIZ_SYSTEM_PROMPT = """You are a world-class academic expert and competitive test solver across all STEM fields, Computer Science, Law, and Humanities.

TASK:
Analyze the given multiple-choice / true-false / short-answer academic or coding question, examine all candidate options, and identify the single most factually accurate and optimal answer.

OUTPUT FORMAT:
Respond ONLY with a valid JSON object in the following format (no extra text, no markdown backticks outside JSON):
{
  "selected_option_index": <0-based integer index of the correct option>,
  "selected_option_text": "<exact string of the selected option>",
  "confidence": <float between 0.0 and 1.0>,
  "explanation": "<one concise sentence explaining why this option is correct>"
}
"""

CODING_SYSTEM_PROMPT = """You are a competitive programming Grandmaster and expert software engineer.
You excel at writing optimal, bug-free, and production-ready code in Python, C++, Java, C, JavaScript, and SQL.

RULES:
1. Handle ALL constraints, corner cases (empty inputs, large numbers, max limits, negative values).
2. Optimize for both Time Complexity and Space Complexity.
3. If starter boilerplate / function signature is provided, adhere strictly to the exact function signature and imports.
4. If standard I/O (stdin / stdout) is expected, implement fast I/O reading from `sys.stdin` or `cin`/`scanf`.
5. Return ONLY clean, executable code without markdown commentary inside the code block.

OUTPUT FORMAT:
Respond ONLY with a valid JSON object:
{
  "language": "<target language>",
  "code": "<complete raw source code string with newlines>",
  "complexity_time": "<e.g. O(N log N)>",
  "complexity_space": "<e.g. O(1)>",
  "explanation": "<one sentence explanation of algorithmic approach>"
}
"""

DEBUG_CODING_PROMPT = """You are an expert software debugger.
The provided code failed on test cases or encountered a compilation/runtime error.
Analyze the problem, current code, error output, and failed test cases (Expected vs Actual).
Provide the corrected, bug-free solution that passes all test cases.

OUTPUT FORMAT:
Respond ONLY with a valid JSON object:
{
  "language": "<target language>",
  "code": "<fixed complete raw source code string>",
  "complexity_time": "<e.g. O(N)>",
  "complexity_space": "<e.g. O(1)>",
  "explanation": "<one sentence explaining the bug fix>"
}
"""


class AISolver:
    """Universal AI Problem & Code Solver with automatic multi-model fallbacks."""

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
                timeout=15.0,
            )
        return self._nvidia_client

    def _clean_json_str(self, raw_text: str) -> str:
        """Strip markdown fences from JSON output."""
        raw_text = raw_text.strip()
        cleaned = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        return cleaned

    def _clean_code_output(self, code_str: str) -> str:
        """Extract pure code if LLM enclosed it in markdown."""
        code_str = code_str.strip()
        match = re.search(r"```(?:\w+)?\n([\s\S]*?)```", code_str)
        if match:
            return match.group(1).strip()
        return code_str

    # ==========================================
    # 1. Academic & General Quiz Solver
    # ==========================================

    def _build_quiz_prompt(self, question: str, options: list[str], context: str = "") -> str:
        prompt = ""
        if context:
            prompt += f"Context: {context}\n\n"
        prompt += f"Question:\n{question}\n\nCandidate Options:\n"
        for idx, opt in enumerate(options):
            prompt += f"[{idx}] {opt}\n"
        prompt += "\nSelect the single correct option index and text based on verified academic standards."
        return prompt

    def _parse_quiz_json(self, raw_text: str, options: list[str]) -> AISolution:
        cleaned = self._clean_json_str(raw_text)
        try:
            data = json.loads(cleaned)
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

        # Fallback regex
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

    # Alias for backward compatibility
    _parse_response_json = _parse_quiz_json

    def solve_question(
        self, question: str, options: list[str], course_context: str = ""
    ) -> AISolution:
        """Universal MCQ solver with multi-model auto fallback."""
        if not options:
            raise ValueError("Cannot solve question with empty options list")

        user_content = self._build_quiz_prompt(question, options, course_context)

        # 1. Try Gemini
        if self.provider == "gemini" or config.GEMINI_API_KEY:
            try:
                client = self._get_gemini_client()
                for model in [config.GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]:
                    try:
                        res = client.models.generate_content(
                            model=model,
                            contents=user_content,
                            config={
                                "system_instruction": GENERIC_QUIZ_SYSTEM_PROMPT,
                                "temperature": 0.1,
                                "response_mime_type": "application/json",
                            },
                        )
                        return self._parse_quiz_json(res.text, options)
                    except Exception as e:
                        if "high demand" in str(e) or "UNAVAILABLE" in str(e) or "404" in str(e):
                            continue
            except Exception as e:
                log.warning(f"Gemini quiz solver error: {e}")

        # 2. Try NVIDIA NIM
        if config.NVIDIA_API_KEY:
            try:
                client = self._get_nvidia_client()
                res = client.chat.completions.create(
                    model=config.NVIDIA_MODEL,
                    messages=[
                        {"role": "system", "content": GENERIC_QUIZ_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                    max_tokens=256,
                )
                raw_text = res.choices[0].message.content or ""
                return self._parse_quiz_json(raw_text, options)
            except Exception as e:
                log.warning(f"NVIDIA quiz solver error: {e}")

        return AISolution(selected_option_index=0, selected_option_text=options[0], confidence=0.5)

    # ==========================================
    # 2. Coding & Algorithm Solver
    # ==========================================

    def solve_coding_problem(
        self,
        title: str,
        description: str,
        input_format: str = "",
        output_format: str = "",
        constraints: str = "",
        sample_cases: str = "",
        starter_code: str = "",
        language: str = "python",
    ) -> AICodeSolution:
        """Synthesize complete, optimal code for any algorithmic / programming challenge."""
        prompt = f"# Problem: {title}\n\n## Description:\n{description}\n\n"
        if input_format:
            prompt += f"## Input Format:\n{input_format}\n\n"
        if output_format:
            prompt += f"## Output Format:\n{output_format}\n\n"
        if constraints:
            prompt += f"## Constraints:\n{constraints}\n\n"
        if sample_cases:
            prompt += f"## Sample Test Cases:\n{sample_cases}\n\n"
        if starter_code:
            prompt += f"## Existing Starter Template / Signature:\n```{language}\n{starter_code}\n```\n\n"
        prompt += f"Target Language: {language}\nWrite the complete, bug-free, optimal solution."

        log.info(f"Generating [bold cyan]{language.upper()}[/bold cyan] solution for '{title}'...")

        # 1. Try Gemini
        if config.GEMINI_API_KEY:
            try:
                client = self._get_gemini_client()
                for model in ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]:
                    try:
                        res = client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config={
                                "system_instruction": CODING_SYSTEM_PROMPT,
                                "temperature": 0.1,
                                "response_mime_type": "application/json",
                            },
                        )
                        data = json.loads(self._clean_json_str(res.text))
                        return AICodeSolution(
                            language=language,
                            code=self._clean_code_output(data.get("code", "")),
                            complexity_time=data.get("complexity_time", "O(N)"),
                            complexity_space=data.get("complexity_space", "O(1)"),
                            explanation=data.get("explanation", ""),
                        )
                    except Exception as e:
                        if "high demand" in str(e) or "UNAVAILABLE" in str(e):
                            continue
            except Exception as e:
                log.warning(f"Gemini coding solver error: {e}")

        # 2. Try NVIDIA NIM
        if config.NVIDIA_API_KEY:
            try:
                client = self._get_nvidia_client()
                res = client.chat.completions.create(
                    model=config.NVIDIA_MODEL,
                    messages=[
                        {"role": "system", "content": CODING_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=2048,
                )
                raw = res.choices[0].message.content or ""
                data = json.loads(self._clean_json_str(raw))
                return AICodeSolution(
                    language=language,
                    code=self._clean_code_output(data.get("code", "")),
                    complexity_time=data.get("complexity_time", "O(N)"),
                    complexity_space=data.get("complexity_space", "O(1)"),
                    explanation=data.get("explanation", ""),
                )
            except Exception as e:
                log.error(f"NVIDIA coding solver error: {e}")

        raise RuntimeError("Failed to generate code solution from all configured AI providers.")

    def debug_code_solution(
        self,
        problem_description: str,
        current_code: str,
        error_logs: str,
        failed_test_case: str = "",
        language: str = "python",
    ) -> AICodeSolution:
        """Self-debug failing code by analyzing compiler error / failed test outputs."""
        prompt = (
            f"# Problem Description:\n{problem_description}\n\n"
            f"# Current Failing Code ({language}):\n```{language}\n{current_code}\n```\n\n"
            f"# Execution Error / Compiler Feedback:\n{error_logs}\n\n"
        )
        if failed_test_case:
            prompt += f"# Failed Test Case (Expected vs Actual):\n{failed_test_case}\n\n"
        prompt += f"Fix the bug and provide the corrected complete {language} solution."

        log.info(f"Self-debugging [bold yellow]{language.upper()}[/bold yellow] solution...")

        if config.GEMINI_API_KEY:
            try:
                client = self._get_gemini_client()
                res = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=prompt,
                    config={
                        "system_instruction": DEBUG_CODING_PROMPT,
                        "temperature": 0.1,
                        "response_mime_type": "application/json",
                    },
                )
                data = json.loads(self._clean_json_str(res.text))
                return AICodeSolution(
                    language=language,
                    code=self._clean_code_output(data.get("code", "")),
                    complexity_time=data.get("complexity_time", "O(N)"),
                    complexity_space=data.get("complexity_space", "O(1)"),
                    explanation=data.get("explanation", ""),
                )
            except Exception as e:
                log.warning(f"Gemini debug solver error: {e}")

        if config.NVIDIA_API_KEY:
            try:
                client = self._get_nvidia_client()
                res = client.chat.completions.create(
                    model=config.NVIDIA_MODEL,
                    messages=[
                        {"role": "system", "content": DEBUG_CODING_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=2048,
                )
                raw = res.choices[0].message.content or ""
                data = json.loads(self._clean_json_str(raw))
                return AICodeSolution(
                    language=language,
                    code=self._clean_code_output(data.get("code", "")),
                    complexity_time=data.get("complexity_time", "O(N)"),
                    complexity_space=data.get("complexity_space", "O(1)"),
                    explanation=data.get("explanation", ""),
                )
            except Exception as e:
                log.error(f"NVIDIA debug solver error: {e}")

        return AICodeSolution(language=language, code=current_code, explanation="Could not debug automatically.")


solver = AISolver()
