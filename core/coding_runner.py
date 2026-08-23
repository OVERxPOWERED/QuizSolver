"""Universal Coding Assessment Runner with Test Execution and Self-Debugging Loop."""

import re
from typing import Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page
from config import config
from core.ai_solver import AICodeSolution, solver
from core.database import QuestionBankDB
from core.detector import PageContext, UniversalDetector
from core.editor_controller import EditorController
from utils.helpers import human_delay, normalize_text
from utils.logger import console, log


class CodingRunner:
    """Automates coding challenges, runs sample tests, self-debugs, and submits."""

    def __init__(self, page: Page, db: Optional[QuestionBankDB] = None):
        self.page = page
        self.db = db or QuestionBankDB()
        self.editor = EditorController(page)

    async def extract_problem_statement(self) -> dict[str, str]:
        """Extract title, description, constraints, and sample cases from page."""
        log.info("Extracting coding problem details from page...")
        content = await self.page.content()
        soup = BeautifulSoup(content, "lxml")

        # 1. Title
        title = ""
        title_el = soup.select_one(
            "h1, h2, .challenge-title, .problem-title, .title, [data-cy='question-title'], .question-title"
        )
        if title_el:
            title = normalize_text(title_el.get_text())
        if not title:
            title = await self.page.title()

        # 2. Description & Problem Body
        desc_el = soup.select_one(
            ".challenge-body, .problem-description, .question-content, [data-track-load='description_content'], .vpl_description, .problem-statement, .content"
        )
        description = normalize_text(desc_el.get_text("\n", strip=True)) if desc_el else normalize_text(soup.get_text("\n", strip=True))

        # 3. Constraints & Formats
        constraints = ""
        sample_cases = ""

        for block in soup.select(".challenge-section, .sample-test, .example, pre, code"):
            text = block.get_text("\n", strip=True)
            if "Input Format" in text or "Constraints" in text:
                constraints += "\n" + text
            elif "Sample Input" in text or "Example" in text:
                sample_cases += "\n" + text

        return {
            "title": title or "Coding Challenge",
            "description": description[:4000],  # Truncate to avoid context limit
            "constraints": constraints[:1500],
            "sample_cases": sample_cases[:2000],
        }

    async def run_and_check_tests(self) -> tuple[bool, str]:
        """Click 'Run Code' button and parse compiler/test outputs."""
        log.info("Looking for 'Run Code' or 'Compile & Test' button...")

        run_btn_selectors = [
            "button:has-text('Run Code')",
            "button:has-text('Compile & Test')",
            "button:has-text('Run')",
            "button:has-text('Test')",
            "button:has-text('Evaluate')",
            "input[value*='Run']",
            "input[value*='Evaluate']",
            "[data-cy='run-code-btn']",
        ]

        run_btn = None
        for sel in run_btn_selectors:
            loc = self.page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                run_btn = loc.first
                break

        if not run_btn:
            log.warning("No 'Run Code' button found. Attempting direct submission.")
            return True, ""

        await run_btn.click()
        log.info("Test execution triggered. Waiting for output...")

        # Wait for test results to appear
        await human_delay(3.0, 6.0)

        # Check output / console / testcase container
        content = await self.page.content()
        soup = BeautifulSoup(content, "lxml")

        output_el = soup.select_one(
            ".output-area, .console-output, .testcase-status, .test-results, .vpl_execution, [data-cy='test-results']"
        )
        output_text = normalize_text(output_el.get_text("\n", strip=True)) if output_el else ""

        # Check for success indicators
        success_signals = ["Congratulations", "Accepted", "Success", "All test cases passed", "Pass", "100%"]
        failure_signals = ["Wrong Answer", "Error", "Failed", "Compilation error", "Runtime Error", "Time Limit Exceeded"]

        is_success = any(s.lower() in output_text.lower() for s in success_signals)
        is_failure = any(f.lower() in output_text.lower() for f in failure_signals)

        if is_success and not is_failure:
            log.info("[bold green]✓ Sample tests passed successfully![/bold green]")
            return True, output_text
        else:
            log.warning(f"Tests failed or returned errors: {output_text[:200]}")
            return False, output_text

    async def submit_code(self) -> bool:
        """Click final 'Submit Code' button."""
        log.info("Submitting final code solution...")

        submit_btn_selectors = [
            "button:has-text('Submit Code')",
            "button:has-text('Submit')",
            "input[value*='Submit']",
            "[data-cy='submit-code-btn']",
        ]

        submit_btn = None
        for sel in submit_btn_selectors:
            loc = self.page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                submit_btn = loc.first
                break

        if submit_btn:
            await human_delay(1.0, 2.0)
            await submit_btn.click()
            log.info("[bold green]✓ Clicked Submit Code button![/bold green]")
            await human_delay(3.0, 5.0)
            return True

        log.warning("Submit button not found directly.")
        return False

    async def solve_challenge(self, language: str = "python", max_retries: int = 2) -> bool:
        """Execute full coding problem lifecycle: Parse -> Synthesize -> Inject -> Test -> Debug -> Submit."""
        problem = await self.extract_problem_statement()

        console.rule(f"[bold magenta]Coding Problem: {problem['title']}[/bold magenta]")
        console.print(f"[dim]{problem['description'][:300]}...[/dim]\n")

        # 1. Read existing starter template if any
        starter_code = await self.editor.get_current_code()

        # 2. Synthesize AI Code Solution
        solution: AICodeSolution = solver.solve_coding_problem(
            title=problem["title"],
            description=problem["description"],
            constraints=problem["constraints"],
            sample_cases=problem["sample_cases"],
            starter_code=starter_code,
            language=language,
        )

        console.print(f"[bold green]✓ Generated {language.upper()} Solution[/bold green] (Time: [cyan]{solution.complexity_time}[/cyan] | Space: [cyan]{solution.complexity_space}[/cyan])")
        if solution.explanation:
            console.print(f"[italic dim]Approach: {solution.explanation}[/italic dim]")

        # 3. Inject code into editor
        await self.editor.set_code(solution.code)

        # 4. Run tests and self-debug if needed
        passed, output_logs = await self.run_and_check_tests()

        retry = 0
        current_code = solution.code

        while not passed and retry < max_retries:
            retry += 1
            log.info(f"[bold yellow]Self-Debug Attempt {retry}/{max_retries}...[/bold yellow]")

            fixed_solution = solver.debug_code_solution(
                problem_description=problem["description"],
                current_code=current_code,
                error_logs=output_logs,
                language=language,
            )

            current_code = fixed_solution.code
            await self.editor.set_code(current_code)
            passed, output_logs = await self.run_and_check_tests()

        # 5. Submit solution
        if config.AUTO_SUBMIT:
            return await self.submit_code()
        else:
            log.info("[bold yellow]AUTO_SUBMIT disabled. Code injected in editor for your review.[/bold yellow]")
            return True
