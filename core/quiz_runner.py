"""Quiz execution engine: Question parsing, AI answering, option clicking, submission and learning."""

import re
from typing import Any, Optional
from bs4 import BeautifulSoup
from playwright.async_api import ElementHandle, Locator, Page
from config import config
from core.ai_solver import solver
from core.database import QuestionBankDB
from core.lms_client import LMSQuiz
from utils.helpers import clean_option_text, human_delay, normalize_text
from utils.logger import console, log


class ParsedQuestion:
    def __init__(
        self,
        q_id: str,
        slot: int,
        q_type: str,
        text: str,
        options: list[str],
        element_locator: Locator,
    ):
        self.q_id = q_id
        self.slot = slot
        self.q_type = q_type
        self.text = text
        self.options = options
        self.element_locator = element_locator

    def __repr__(self):
        return f"<Question #{self.slot} ({self.q_type}): '{self.text[:40]}...' ({len(self.options)} options)>"


class QuizRunner:
    """Automates quiz attempts, question resolution, submissions, and feedback extraction."""

    def __init__(self, page: Page, db: Optional[QuestionBankDB] = None):
        self.page = page
        self.db = db or QuestionBankDB()

    async def start_quiz_attempt(self, quiz: LMSQuiz, allow_reattempt: bool = False) -> bool:
        """Navigate to quiz, check if already completed, and initiate attempt if needed."""
        log.info(f"Opening quiz: [bold cyan]{quiz.title}[/bold cyan] ({quiz.url})")
        await self.page.goto(quiz.url, wait_until="domcontentloaded")
        await human_delay(1.0, 1.5)

        # Check if already completed with a perfect score (100%)
        content = await self.page.content()
        soup = BeautifulSoup(content, "lxml")
        full_text = soup.get_text(" ", strip=True)

        is_finished = "Finished" in full_text
        has_in_progress = "In progress" in full_text
        has_perfect_score = bool(re.search(r"(100\s*%|10\.00\s*/\s*10\.00|Highest grade:\s*10\.00\s*/\s*10\.00)", full_text, re.IGNORECASE))

        # If quiz has a verified 100% perfect score, skip it (unless --reattempt is explicitly passed)
        if has_perfect_score and not has_in_progress and not allow_reattempt:
            grade_match = re.search(r"Highest grade:\s*[\d\.]+\s*/\s*[\d\.]+", full_text)
            grade_str = grade_match.group(0) if grade_match else "100% (Perfect Score)"
            log.info(f"[bold green]✓ Quiz '{quiz.title}' is already completed with perfect score ({grade_str}). Skipping.[/bold green]")
            return False

        # If quiz was finished with <100%, log that we are re-attempting to maximize score
        if is_finished and not has_perfect_score:
            grade_match = re.search(r"Highest grade:\s*[\d\.]+\s*/\s*[\d\.]+", full_text)
            prev_grade = grade_match.group(0) if grade_match else "Previous attempt < 100%"
            log.info(f"[bold yellow]⚡ Quiz '{quiz.title}' ({prev_grade}) -> Re-attempting to achieve 100% score![/bold yellow]")

        # Look for attempt buttons
        attempt_selectors = [
            "button:has-text('Continue the last attempt')",
            "input[value*='Continue the last attempt']",
            "a:has-text('Continue the last attempt')",
            "button:has-text('Attempt quiz')",
            "input[value*='Attempt quiz']",
            "a:has-text('Attempt quiz now')",
            "a:has-text('Attempt quiz')",
            "button:has-text('Re-attempt quiz')",
            "input[value*='Re-attempt quiz']",
            "a:has-text('Re-attempt quiz')",
            "form.quizstartattemptform button[type='submit']",
            "form.quizstartattemptform input[type='submit']",
            ".singlebutton button",
        ]

        attempt_btn = None
        for sel in attempt_selectors:
            loc = self.page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                attempt_btn = loc.first
                btn_text = await attempt_btn.inner_text() if await attempt_btn.count() else "Submit"
                log.info(f"Found attempt button: '[bold yellow]{btn_text.strip()}[/bold yellow]'")
                break

        if not attempt_btn:
            if is_finished or quiz.status == "Done":
                log.info(f"[bold green]✓ Quiz '{quiz.title}' is already finished. Skipping.[/bold green]")
            else:
                log.warning("No active attempt button found on this quiz page. Quiz may be locked, completed, or closed.")
            return False

        await attempt_btn.click()
        await human_delay(1.0, 1.5)

        # Handle Start Attempt modal confirmation if present
        modal_confirm_btn = self.page.locator(
            ".modal-dialog input[value*='Start attempt'], .modal-dialog button:has-text('Start attempt'), #id_submitbutton"
        )
        if await modal_confirm_btn.count() > 0 and await modal_confirm_btn.first.is_visible():
            log.info("Confirming 'Start Attempt' modal...")
            await modal_confirm_btn.first.click()
            await human_delay(1.0, 1.5)

        return True

    async def parse_questions_on_page(self) -> list[ParsedQuestion]:
        """Extract all quiz questions and options on the active page."""
        questions: list[ParsedQuestion] = []
        question_nodes = self.page.locator("div.que")
        count = await question_nodes.count()

        if count == 0:
            log.warning("No questions found on the current page.")
            return []

        for idx in range(count):
            q_node = question_nodes.nth(idx)
            q_class = await q_node.get_attribute("class") or ""
            q_id = await q_node.get_attribute("id") or f"q_{idx+1}"

            # Determine question type
            q_type = "multichoice"
            if "truefalse" in q_class:
                q_type = "truefalse"
            elif "shortanswer" in q_class:
                q_type = "shortanswer"

            # Extract Question text
            q_text_el = q_node.locator("div.qtext")
            if await q_text_el.count() == 0:
                continue
            q_text = normalize_text(await q_text_el.first.inner_text())

            # Extract Options
            options: list[str] = []
            option_nodes = q_node.locator("div.answer div.r0, div.answer div.r1, div.answer label")
            opt_count = await option_nodes.count()

            for opt_idx in range(opt_count):
                opt_el = option_nodes.nth(opt_idx)
                opt_raw = await opt_el.inner_text()
                opt_cleaned = clean_option_text(opt_raw)
                if opt_cleaned:
                    options.append(opt_cleaned)

            if not options:
                # Fallback: check all input labels inside answer div
                labels = q_node.locator("div.answer label")
                l_count = await labels.count()
                for l_idx in range(l_count):
                    options.append(clean_option_text(await labels.nth(l_idx).inner_text()))

            questions.append(
                ParsedQuestion(
                    q_id=q_id,
                    slot=idx + 1,
                    q_type=q_type,
                    text=q_text,
                    options=options,
                    element_locator=q_node,
                )
            )

        return questions

    async def answer_question(self, question: ParsedQuestion, course_name: str = "", quiz_name: str = "") -> bool:
        """Resolve answer via DB or AI, and click the selected option."""
        console.rule(f"[bold blue]Question #{question.slot}[/bold blue]")
        console.print(f"[bold white]{question.text}[/bold white]")

        if not question.options:
            log.warning(f"No candidate options found for question: {question.text[:50]}")
            return False

        # Display options in console
        for o_idx, opt in enumerate(question.options):
            console.print(f"  [cyan][{o_idx}][/cyan] {opt}")

        selected_idx = 0
        selected_text = ""
        source = "AI"
        explanation = ""

        # 1. Check local SQLite DB first
        cached = self.db.get_answer(question.text)
        if cached and cached.get("selected_answer"):
            cached_ans = cached["selected_answer"]
            is_verified = cached.get("verified", False)
            for idx, opt in enumerate(question.options):
                if opt.lower() == cached_ans.lower() or cached_ans.lower() in opt.lower():
                    selected_idx = idx
                    selected_text = opt
                    source = "DB (Verified 100%)" if is_verified else "DB (Cached)"
                    explanation = cached.get("explanation", "")
                    break

        # 2. If not in DB, query AI solver
        if not selected_text:
            log.info(f"Querying AI solver ({config.AI_PROVIDER.upper()})...")
            try:
                solution = solver.solve_question(
                    question=question.text,
                    options=question.options,
                    course_context=course_name,
                )
                selected_idx = solution.selected_option_index
                selected_text = solution.selected_option_text
                explanation = solution.explanation
                source = f"AI ({config.AI_PROVIDER.upper()} - {int(solution.confidence*100)}%)"

                # Save AI answer to DB
                self.db.save_answer(
                    question_text=question.text,
                    options=question.options,
                    selected_answer=selected_text,
                    selected_index=selected_idx,
                    course_name=course_name,
                    quiz_name=quiz_name,
                    explanation=explanation,
                    verified=False,
                    confidence=solution.confidence,
                )
            except Exception as e:
                log.error(f"Failed to get AI solution: {e}. Falling back to option 0.")
                selected_idx = 0
                selected_text = question.options[0]

        console.print(f"[bold green]✓ Selected Choice ({source}):[/bold green] [bold yellow]{selected_text}[/bold yellow]")
        if explanation:
            console.print(f"  [italic dim]Reasoning: {explanation}[/italic dim]")

        # 3. Click the matching option input in Playwright
        try:
            # Option elements within the question container
            inputs = question.element_locator.locator("div.answer input[type='radio'], div.answer input[type='checkbox']")
            labels = question.element_locator.locator("div.answer label")

            # Click with human jitter delay
            await human_delay(config.HUMAN_DELAY_MIN, config.HUMAN_DELAY_MAX)

            if await inputs.count() > selected_idx:
                target_input = inputs.nth(selected_idx)
                try:
                    await target_input.scroll_into_view_if_needed(timeout=2000)
                    await target_input.click(force=True, timeout=2500)
                except Exception:
                    await target_input.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true})); }")
            elif await labels.count() > selected_idx:
                target_label = labels.nth(selected_idx)
                try:
                    await target_label.scroll_into_view_if_needed(timeout=2000)
                    await target_label.click(force=True, timeout=2500)
                except Exception:
                    await target_label.evaluate("el => el.click()")
            else:
                log.warning(f"Could not click option index {selected_idx}. Clicking first option.")
                if await inputs.count() > 0:
                    try:
                        await inputs.first.click(force=True, timeout=2500)
                    except Exception:
                        await inputs.first.evaluate("el => el.click()")

            return True
        except Exception as e:
            log.error(f"Error clicking option {selected_idx}: {e}")
            return False

    async def execute_quiz(self, quiz: LMSQuiz, course_name: str = "", allow_reattempt: bool = False) -> bool:
        """Run entire quiz lifecycle across all pages and submit."""
        started = await self.start_quiz_attempt(quiz, allow_reattempt=allow_reattempt)
        if not started:
            return True  # Skipped successfully

        page_num = 1
        while True:
            log.info(f"Processing Quiz Page #{page_num}...")
            questions = await self.parse_questions_on_page()

            if not questions:
                # Check if we are already on summary page
                if "summary.php" in self.page.url:
                    log.info("Reached summary page.")
                    break
                else:
                    log.warning("No questions found on this page. Checking navigation...")

            for q in questions:
                await self.answer_question(q, course_name=course_name, quiz_name=quiz.title)

            # Check next page or finish attempt button
            next_btn = self.page.locator("input[name='next'], input#mod_quiz-next-nav, button#mod_quiz-next-nav")
            if await next_btn.count() == 0:
                # Try generic submit or finish buttons
                next_btn = self.page.locator("input[value*='Finish attempt'], input[value*='Next page'], input[type='submit']")

            if await next_btn.count() > 0 and await next_btn.first.is_visible():
                btn_val = await next_btn.first.get_attribute("value") or await next_btn.first.inner_text()
                log.info(f"Advancing with button: '[bold yellow]{btn_val.strip()}[/bold yellow]'")
                await human_delay(1.0, 2.0)
                await next_btn.first.click()
                await self.page.wait_for_load_state("domcontentloaded")
                await human_delay(1.0, 1.5)

                if "summary.php" in self.page.url:
                    log.info("All questions answered. Reached Attempt Summary page.")
                    break
                page_num += 1
            else:
                log.info("No next button found. Attempt complete.")
                break

        # Submit attempt
        if config.AUTO_SUBMIT:
            return await self.submit_attempt(quiz, course_name=course_name)
        else:
            log.info("[bold yellow]AUTO_SUBMIT is disabled. Please review answers and submit manually in browser window.[/bold yellow]")
            return True

    async def submit_attempt(self, quiz: LMSQuiz, course_name: str = "") -> bool:
        """Click Submit all and finish, confirm popup, and parse review feedback."""
        log.info("Submitting quiz attempt...")
        
        # Click "Submit all and finish" button on summary page
        submit_btn = self.page.locator(
            "input[value*='Submit all and finish'], button:has-text('Submit all and finish'), form.quizsummaryofattempt input[type='submit']"
        )
        if await submit_btn.count() > 0:
            await human_delay(1.0, 1.5)
            await submit_btn.first.click()
            await human_delay(1.0, 1.5)

        # Confirm submission dialog modal
        confirm_btn = self.page.locator(
            ".modal-dialog input[value*='Submit all and finish'], .modal-dialog button:has-text('Submit all and finish'), .confirmation-buttons input.btn-primary"
        )
        if await confirm_btn.count() > 0 and await confirm_btn.first.is_visible():
            log.info("Confirming final submission dialog...")
            await confirm_btn.first.click()
            await self.page.wait_for_load_state("domcontentloaded")
            await human_delay(1.5, 2.5)

        # Parse review page to learn verified answers
        await self.learn_from_review(course_name=course_name, quiz_name=quiz.title)
        return True

    async def learn_from_review(self, course_name: str = "", quiz_name: str = "") -> None:
        """Extract score and update SQLite database with revealed correct answers."""
        if "review.php" not in self.page.url:
            return

        log.info("[bold green]Examining Quiz Review & Feedback...[/bold green]")
        content = await self.page.content()
        soup = BeautifulSoup(content, "lxml")

        # Extract Overall Grade
        grade_table = soup.select_one(".quizreviewsummary, .generaltable")
        if grade_table:
            for tr in grade_table.select("tr"):
                text = normalize_text(tr.get_text())
                if "Marks" in text or "Grade" in text:
                    console.print(f"[score]  {text}  [/score]")

        # Learn verified right answers for each question
        question_divs = soup.select("div.que")
        learned_count = 0

        for q_div in question_divs:
            q_text_el = q_div.select_one("div.qtext")
            if not q_text_el:
                continue
            q_text = normalize_text(q_text_el.get_text())

            # Moodle displays correct answer in div.rightanswer or div.feedback
            right_ans_el = q_div.select_one("div.rightanswer, .feedback .correct")
            if right_ans_el:
                raw_right = normalize_text(right_ans_el.get_text())
                # e.g., "The correct answer is: Article 21"
                cleaned_ans = re.sub(r"^The correct answer is:\s*", "", raw_right, flags=re.IGNORECASE)
                cleaned_ans = clean_option_text(cleaned_ans)

                # Save verified answer to DB
                self.db.save_answer(
                    question_text=q_text,
                    options=[],
                    selected_answer=cleaned_ans,
                    selected_index=0,
                    course_name=course_name,
                    quiz_name=quiz_name,
                    explanation="Verified from Moodle quiz review feedback",
                    verified=True,
                    confidence=1.0,
                )
                learned_count += 1

        if learned_count > 0:
            log.info(f"[bold green]✓ Successfully learned and verified {learned_count} question(s) in local DB![/bold green]")
