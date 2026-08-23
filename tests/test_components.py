"""Unit tests for text processing, database caching, and AI response parsing."""

import json
import pytest
from pathlib import Path
from core.ai_solver import AISolver
from core.database import QuestionBankDB
from utils.helpers import clean_option_text, compute_question_hash, fuzzy_match_option, normalize_text


def test_text_normalization():
    raw = "  Which   article of the Indian   Constitution guarantees “Right to Equality”?  \n"
    norm = normalize_text(raw)
    assert norm == 'Which article of the Indian Constitution guarantees "Right to Equality"?'


def test_question_hashing():
    q1 = "What is the capital of India?"
    q2 = "  what is the  capital of india? "
    assert compute_question_hash(q1) == compute_question_hash(q2)


def test_clean_option_text():
    assert clean_option_text("a. Article 14") == "Article 14"
    assert clean_option_text("B) Article 19") == "Article 19"
    assert clean_option_text("Select one: Article 21") == "Article 21"


def test_fuzzy_match_option():
    options = ["Article 14 to 18", "Article 19 to 22", "Article 23 to 24", "Article 25 to 28"]
    
    # Exact match
    assert fuzzy_match_option("Article 14 to 18", options) == 0
    # Letter match
    assert fuzzy_match_option("b. Article 19 to 22", options) == 1
    # Substring match
    assert fuzzy_match_option("19 to 22", options) == 1
    # Number/letter match
    assert fuzzy_match_option("C", options) == 2


def test_database_caching(tmp_path: Path):
    db_file = tmp_path / "test_quiz.db"
    db = QuestionBankDB(db_path=db_file)

    q_text = "Who is known as the Father of the Indian Constitution?"
    options = ["Mahatma Gandhi", "Dr. B.R. Ambedkar", "Jawaharlal Nehru", "Sardar Patel"]

    # Save initial AI answer
    db.save_answer(
        question_text=q_text,
        options=options,
        selected_answer="Dr. B.R. Ambedkar",
        selected_index=1,
        course_name="Indian Constitution",
        quiz_name="Quiz 1",
        verified=False,
    )

    cached = db.get_answer(q_text)
    assert cached is not None
    assert cached["selected_answer"] == "Dr. B.R. Ambedkar"
    assert cached["selected_index"] == 1
    assert cached["verified"] is False

    # Update with verified answer
    db.save_answer(
        question_text=q_text,
        options=options,
        selected_answer="Dr. B.R. Ambedkar",
        selected_index=1,
        course_name="Indian Constitution",
        quiz_name="Quiz 1",
        verified=True,
    )

    cached2 = db.get_answer(q_text)
    assert cached2["verified"] is True
    assert db.count_questions() == 1


def test_ai_solver_parsing():
    solver = AISolver()
    options = ["Bloom's Taxonomy", "Gagne's 9 Events", "Kirkpatrick Model", "ADDIE Model"]

    # 1. Clean JSON
    json_text = json.dumps({
        "selected_option_index": 0,
        "selected_option_text": "Bloom's Taxonomy",
        "confidence": 0.99,
        "explanation": "Bloom's taxonomy defines cognitive levels in OBE.",
    })
    sol1 = solver._parse_response_json(json_text, options)
    assert sol1.selected_option_index == 0
    assert sol1.selected_option_text == "Bloom's Taxonomy"

    # 2. Markdown fenced JSON
    fenced_text = f"```json\n{json_text}\n```"
    sol2 = solver._parse_response_json(fenced_text, options)
    assert sol2.selected_option_index == 0

    # 3. Text fallback
    raw_text = "The correct answer is B. Gagne's 9 Events"
    sol3 = solver._parse_response_json(raw_text, options)
    assert sol3.selected_option_index == 1
