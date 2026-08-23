"""Universal Semantic Question & Option Parser for Any Quiz or Assessment Platform."""

import re
from typing import Optional
from bs4 import BeautifulSoup
from playwright.async_api import Locator, Page
from utils.helpers import clean_option_text, normalize_text
from utils.logger import log


class UniversalQuestion:
    def __init__(
        self,
        q_id: str,
        slot: int,
        q_type: str,
        text: str,
        options: list[str],
        element_locator: Locator,
        image_path: Optional[str] = None,
    ):
        self.q_id = q_id
        self.slot = slot
        self.q_type = q_type  # 'multichoice', 'checkbox', 'truefalse', 'text', 'dropdown'
        self.text = text
        self.options = options
        self.element_locator = element_locator
        self.image_path = image_path

    def __repr__(self):
        return f"<UniversalQuestion #{self.slot} ({self.q_type}): '{self.text[:40]}...' ({len(self.options)} options)>"


class UniversalQuestionParser:
    """Extracts questions and candidate choices from any web format."""

    @staticmethod
    async def parse_questions_from_page(page: Page) -> list[UniversalQuestion]:
        """Scan the current page and extract all question blocks."""
        questions: list[UniversalQuestion] = []

        # 1. Moodle Question Containers
        moodle_nodes = page.locator("div.que")
        if await moodle_nodes.count() > 0:
            return await UniversalQuestionParser._parse_moodle_questions(moodle_nodes)

        # 2. Google Forms Containers
        gform_nodes = page.locator(
            ".freebirdFormviewerComponentsQuestionBaseRoot, [role='listitem'], div[jsmodel='CP1oW']"
        )
        if await gform_nodes.count() > 0:
            return await UniversalQuestionParser._parse_google_form_questions(gform_nodes)

        # 3. Canvas & Blackboard Containers
        canvas_nodes = page.locator(".quiz_sortable_question, .question_holder, .takeQuestionDiv")
        if await canvas_nodes.count() > 0:
            return await UniversalQuestionParser._parse_canvas_questions(canvas_nodes)

        # 4. Universal Fallback: fieldsets, radiogroups, question cards
        generic_nodes = page.locator(
            "fieldset, [role='radiogroup'], .question-item, .quiz-question, .form-group:has(input[type='radio'])"
        )
        if await generic_nodes.count() > 0:
            return await UniversalQuestionParser._parse_generic_questions(generic_nodes)

        return []

    @staticmethod
    async def _parse_moodle_questions(nodes: Locator) -> list[UniversalQuestion]:
        questions = []
        count = await nodes.count()
        for idx in range(count):
            node = nodes.nth(idx)
            q_class = await node.get_attribute("class") or ""
            q_id = await node.get_attribute("id") or f"q_{idx+1}"

            q_type = "multichoice"
            if "truefalse" in q_class:
                q_type = "truefalse"
            elif "shortanswer" in q_class:
                q_type = "text"

            q_text_el = node.locator("div.qtext")
            if await q_text_el.count() == 0:
                continue
            q_text = normalize_text(await q_text_el.first.inner_text())

            options = []
            option_nodes = node.locator("div.answer div.r0, div.answer div.r1, div.answer label")
            for opt_idx in range(await option_nodes.count()):
                cleaned = clean_option_text(await option_nodes.nth(opt_idx).inner_text())
                if cleaned and cleaned not in options:
                    options.append(cleaned)

            questions.append(
                UniversalQuestion(
                    q_id=q_id,
                    slot=idx + 1,
                    q_type=q_type,
                    text=q_text,
                    options=options,
                    element_locator=node,
                )
            )
        return questions

    @staticmethod
    async def _parse_google_form_questions(nodes: Locator) -> list[UniversalQuestion]:
        questions = []
        count = await nodes.count()
        for idx in range(count):
            node = nodes.nth(idx)
            # Question title
            title_el = node.locator("[role='heading'], .freebirdFormviewerComponentsQuestionBaseTitle")
            if await title_el.count() == 0:
                continue
            q_text = normalize_text(await title_el.first.inner_text())

            # Options
            options = []
            opt_labels = node.locator("label, [role='radio'], [role='checkbox'], span.dir='auto'")
            for opt_idx in range(await opt_labels.count()):
                txt = clean_option_text(await opt_labels.nth(opt_idx).inner_text())
                if txt and txt not in options and txt != q_text:
                    options.append(txt)

            q_type = "checkbox" if await node.locator("[role='checkbox']").count() > 0 else "multichoice"
            questions.append(
                UniversalQuestion(
                    q_id=f"gform_q_{idx+1}",
                    slot=idx + 1,
                    q_type=q_type,
                    text=q_text,
                    options=options,
                    element_locator=node,
                )
            )
        return questions

    @staticmethod
    async def _parse_canvas_questions(nodes: Locator) -> list[UniversalQuestion]:
        questions = []
        count = await nodes.count()
        for idx in range(count):
            node = nodes.nth(idx)
            text_el = node.locator(".question_text, .text")
            q_text = normalize_text(await text_el.first.inner_text()) if await text_el.count() > 0 else ""

            options = []
            opt_nodes = node.locator(".answer_label, .answer, label")
            for opt_idx in range(await opt_nodes.count()):
                txt = clean_option_text(await opt_nodes.nth(opt_idx).inner_text())
                if txt and txt not in options:
                    options.append(txt)

            questions.append(
                UniversalQuestion(
                    q_id=f"canvas_q_{idx+1}",
                    slot=idx + 1,
                    q_type="multichoice",
                    text=q_text,
                    options=options,
                    element_locator=node,
                )
            )
        return questions

    @staticmethod
    async def _parse_generic_questions(nodes: Locator) -> list[UniversalQuestion]:
        questions = []
        count = await nodes.count()
        for idx in range(count):
            node = nodes.nth(idx)
            legend = node.locator("legend, h2, h3, h4, .question-title, strong").first
            q_text = normalize_text(await legend.inner_text()) if await legend.count() > 0 else f"Question {idx+1}"

            options = []
            opt_labels = node.locator("label, .form-check-label, input[type='radio'] + span")
            for opt_idx in range(await opt_labels.count()):
                txt = clean_option_text(await opt_labels.nth(opt_idx).inner_text())
                if txt and txt not in options:
                    options.append(txt)

            questions.append(
                UniversalQuestion(
                    q_id=f"gen_q_{idx+1}",
                    slot=idx + 1,
                    q_type="multichoice",
                    text=q_text,
                    options=options,
                    element_locator=node,
                )
            )
        return questions
