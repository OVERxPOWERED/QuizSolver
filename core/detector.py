"""Universal Platform, Assessment Mode, and Code Editor Auto-Detector."""

from typing import Literal, Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page
from utils.logger import log

PlatformType = Literal["moodle", "hackerrank", "leetcode", "coderunner", "google_forms", "canvas", "generic"]
AssessmentMode = Literal["quiz", "coding", "mixed", "unknown"]
EditorType = Literal["monaco", "codemirror", "ace", "textarea", "unknown"]


class PageContext:
    def __init__(
        self,
        platform: PlatformType,
        mode: AssessmentMode,
        editor_type: EditorType,
        title: str = "",
        url: str = "",
    ):
        self.platform = platform
        self.mode = mode
        self.editor_type = editor_type
        self.title = title
        self.url = url

    def __repr__(self):
        return f"<PageContext: platform={self.platform}, mode={self.mode}, editor={self.editor_type}>"


class UniversalDetector:
    """Detects platform, assessment mode, and editor types on any webpage."""

    @staticmethod
    async def detect_editor_type(page: Page) -> EditorType:
        """Detect what kind of code editor is present on the page."""
        # 1. Monaco Editor (VSCode Web - HackerRank, LeetCode, modern LMS)
        is_monaco = await page.evaluate(
            """() => {
                return !!(window.monaco && window.monaco.editor) || 
                       document.querySelector('.monaco-editor, .monaco-list, [data-mode-id]') !== null;
            }"""
        )
        if is_monaco:
            return "monaco"

        # 2. CodeMirror (v5 and v6)
        is_codemirror = await page.evaluate(
            """() => {
                return document.querySelector('.CodeMirror, .cm-editor, .cm-content') !== null;
            }"""
        )
        if is_codemirror:
            return "codemirror"

        # 3. ACE Editor (Cloud9, HackerEarth, CodeRunner)
        is_ace = await page.evaluate(
            """() => {
                return !!(window.ace && window.ace.edit) || 
                       document.querySelector('.ace_editor, .ace_text-input') !== null;
            }"""
        )
        if is_ace:
            return "ace"

        # 4. Standard textarea with code-related classes or names
        has_code_textarea = await page.locator(
            "textarea[id*='code'], textarea[name*='code'], textarea.vpl_editor, textarea.coderunner-answer, textarea"
        ).count() > 0
        if has_code_textarea:
            return "textarea"

        return "unknown"

    @staticmethod
    async def detect_platform(page: Page) -> PlatformType:
        """Detect the platform host type from URL and DOM signatures."""
        url = page.url.lower()

        if "hackerrank.com" in url:
            return "hackerrank"
        if "leetcode.com" in url:
            return "leetcode"
        if "docs.google.com/forms" in url or "forms.gle" in url:
            return "google_forms"
        if "instructure.com" in url or "/courses/" in url and "canvas" in url:
            return "canvas"
        if "acropolislms" in url or "moodle" in url or "/mod/quiz/" in url or "/mod/vpl/" in url:
            return "moodle"

        # DOM signature checks
        is_moodle = await page.locator("body.format-site, body.format-topics, .moodle-has-zindex, #page-mod-quiz-view").count() > 0
        if is_moodle:
            return "moodle"

        is_gform = await page.locator("form[action*='formResponse'], .freebirdFormviewerViewFormContent").count() > 0
        if is_gform:
            return "google_forms"

        return "generic"

    @staticmethod
    async def detect_assessment_mode(page: Page) -> AssessmentMode:
        """Detect whether the current page contains a quiz, coding task, or both."""
        editor_type = await UniversalDetector.detect_editor_type(page)
        
        # Check for quiz questions
        has_quiz_questions = await page.locator(
            "div.que, fieldset, [role='radiogroup'], [role='group'], .freebirdFormviewerComponentsQuestionBaseRoot, .question-item, .quiz-question"
        ).count() > 0

        # Check for Run/Submit code buttons
        has_code_buttons = await page.locator(
            "button:has-text('Run Code'), button:has-text('Submit Code'), button:has-text('Compile'), button:has-text('Test'), input[value*='Run'], input[value*='Evaluate']"
        ).count() > 0

        if editor_type != "unknown" and has_quiz_questions:
            return "mixed"
        elif editor_type != "unknown" or has_code_buttons:
            return "coding"
        elif has_quiz_questions:
            return "quiz"

        return "unknown"

    @classmethod
    async def analyze_page(cls, page: Page) -> PageContext:
        """Perform comprehensive page analysis and return context."""
        title = await page.title()
        url = page.url
        platform = await cls.detect_platform(page)
        editor_type = await cls.detect_editor_type(page)
        mode = await cls.detect_assessment_mode(page)

        log.info(f"Page Analysis: [bold cyan]Platform: {platform}[/bold cyan] | [bold yellow]Mode: {mode}[/bold yellow] | [bold magenta]Editor: {editor_type}[/bold magenta]")
        return PageContext(platform=platform, mode=mode, editor_type=editor_type, title=title, url=url)
