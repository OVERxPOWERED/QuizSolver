```python
"""
Integration tests for core automation components.

Tests cover:
- BrowserManager lifecycle (start/stop, context isolation, error recovery)
- QuestionParser with real HTML fixtures
- AISolver with mocked LLM responses
- QuizRunner end-to-end flow
- CodingRunner code execution
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import pytest_asyncio

# Import core components
from core.browser_manager import BrowserManager
from core.question_parser import QuestionParser
from core.ai_solver import AISolver
from core.quiz_runner import QuizRunner
from core.coding_runner import CodingRunner
from core.telemetry import TelemetryCollector, TelemetryEvent


# =============================================================================
# FIXTURES AND TEST DATA
# =============================================================================

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "quiz_pages"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


def create_html_fixtures():
    """Create realistic HTML fixtures for quiz pages."""
    
    # Multiple Choice Quiz Page
    multiple_choice_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Python Basics Quiz</title>
</head>
<body>
    <div class="quiz-container">
        <h1 class="quiz-title">Python Fundamentals Assessment</h1>
        <div class="question" data-question-id="q1" data-type="multiple_choice">
            <div class="question-text">
                <p>What is the output of the following code?</p>
                <pre><code>x = [1, 2, 3]
y = x
y.append(4)
print(x)</code></pre>
            </div>
            <div class="options">
                <label class="option">
                    <input type="radio" name="q1" value="a"> [1, 2, 3]
                </label>
                <label class="option">
                    <input type="radio" name="q1" value="b"> [1, 2, 3, 4]
                </label>
                <label class="option">
                    <input type="radio" name="q1" value="c"> [4, 1, 2, 3]
                </label>
                <label class="option">
                    <input type="radio" name="q1" value="d"> Error
                </label>
            </div>
            <div class="explanation" style="display:none;">
                Lists are mutable and assignment creates a reference, not a copy.
            </div>
        </div>
        
        <div class="question" data-question-id="q2" data-type="multiple_choice">
            <div class="question-text">
                <p>Which of the following is NOT a valid Python identifier?</p>
            </div>
            <div class="options">
                <label class="option">
                    <input type="radio" name="q2" value="a"> _variable
                </label>
                <label class="option">
                    <input type="radio" name="q2" value="b"> variable_1
                </label>
                <label class="option">
                    <input type="radio" name="q2" value="c"> 1variable
                </label>
                <label class="option">
                    <input type="radio" name="q2" value="d"> variableName
                </label>
            </div>
        </div>
        
        <div class="question" data-question-id="q3" data-type="multiple_choice">
            <div class="question-text">
                <p>What does the 'yield' keyword do in Python?</p>
            </div>
            <div class="options">
                <label class="option">
                    <input type="radio" name="q3" value="a"> Returns a value and exits the function
                </label>
                <label class="option">
                    <input type="radio" name="q3" value="b"> Creates a generator that can be iterated
                </label>
                <label class="option">
                    <input type="radio" name="q3" value="c"> Raises an exception
                </label>
                <label class="option">
                    <input type="radio" name="q3" value="d"> Imports a module
                </label>
            </div>
        </div>
    </div>
    <button id="submit-btn" class="submit-button">Submit Quiz</button>
</body>
</html>
"""
    
    # True/False Quiz Page
    true_false_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Computer Science True/False</title>
</head>
<body>
    <div class="quiz-container">
        <h1 class="quiz-title">CS Theory: True or False</h1>
        
        <div class="question" data-question-id="tf1" data-type="true_false">
            <div class="question-text">
                <p>A binary search tree always maintains O(log n) height.</p>
            </div>
            <div class="options">
                <label class="option">
                    <input type="radio" name="tf1" value="true"> True
                </label>
                <label class="option">
                    <input type="radio" name="tf1" value="false"> False
                </label>
            </div>
        </div>
        
        <div class="question" data-question-id="tf2" data-type="true_false">
            <div class="question-text">
                <p>In Python, tuples are immutable but lists are mutable.</p>
            </div>
            <div class="options">
                <label class="option">
                    <input type="radio" name="tf2" value="true"> True
                </label>
                <label class="option">
                    <input type="radio" name="tf2" value="false"> False
                </label>
            </div>
        </div>
        
        <div class="question" data-question-id="tf3" data-type="true_false">
            <div class="question-text">
                <p>HTTP is a stateful protocol.</p>
            </div>
            <div class="options">
                <label class="option">
                    <input type="radio" name="tf3" value="true"> True
                </label>
                <label class="option">
                    <input type="radio" name="tf3" value="false"> False
                </label>
            </div>
        </div>
    </div>
</body>
</html>
"""
    
    # Coding Challenge Page
    coding_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Coding Challenge: Two Sum</title>
</head>
<body>
    <div class="quiz-container">
        <h1 class="quiz-title">Algorithm Challenge</h1>
        
        <div class="question" data-question-id="code1" data-type="coding">
            <div class="question-text">
                <h2>Two