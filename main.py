"""Universal AI Assessment & Coding Solver CLI Entry Point."""

import argparse
import asyncio
import sys
from rich.panel import Panel
from rich.table import Table
from config import config
from core.browser import BrowserManager
from core.coding_runner import CodingRunner
from core.database import QuestionBankDB
from core.detector import UniversalDetector
from core.lms_client import LMSClient
from core.quiz_runner import QuizRunner
from utils.logger import console, log


def print_banner(db: QuestionBankDB):
    """Display rich status header."""
    db_count = db.count_questions()
    ai_status = (
        f"[bold green]Gemini ({config.GEMINI_MODEL})[/bold green]"
        if config.AI_PROVIDER == "gemini"
        else f"[bold green]NVIDIA NIM ({config.NVIDIA_MODEL})[/bold green]"
    )

    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Key", style="bold cyan")
    info_table.add_column("Value", style="bold white")

    info_table.add_row("🌐 LMS / Target", config.TARGET_URL or f"{config.base_url} ({config.LMS_NETWORK.upper()})")
    info_table.add_row("👤 Student ID", config.LMS_USERNAME or "[dim yellow]Not configured[/dim yellow]")
    info_table.add_row("🧠 AI Engine", ai_status)
    info_table.add_row("💻 Coding Lang", f"[bold magenta]{config.CODING_LANGUAGE.upper()}[/bold magenta]")
    info_table.add_row("🖥️  Mode", "Headless (Silent Background)" if config.HEADLESS else "Headful (Live Interactive Window)")
    info_table.add_row("📦 QA Bank", f"{db_count} learned questions in SQLite")

    console.print(
        Panel(
            info_table,
            title="[bold yellow]⚡ Universal AI Quiz & Coding Assessment Solver ⚡[/bold yellow]",
            subtitle="[italic dim]Autonomous Solver for Quizzes, Forms & Coding Challenges[/italic dim]",
            border_style="bright_blue",
        )
    )


async def run_automation(args: argparse.Namespace):
    """Main async pipeline."""
    db = QuestionBankDB()
    print_banner(db)

    # Validate AI key
    if config.AI_PROVIDER == "gemini" and not config.GEMINI_API_KEY:
        if not config.NVIDIA_API_KEY:
            console.print(
                Panel(
                    "[bold red]Neither GEMINI_API_KEY nor NVIDIA_API_KEY is configured in .env![/bold red]",
                    title="API Key Missing",
                    border_style="red",
                )
            )
            sys.exit(1)

    # Initialize Browser
    headless_mode = args.headless if args.headless is not None else config.HEADLESS
    browser_mgr = BrowserManager(headless=headless_mode)
    page = await browser_mgr.start()

    try:
        # ==========================================
        # 1. Direct Target URL Mode (Coding or Form)
        # ==========================================
        target_url = args.url or config.TARGET_URL
        if target_url:
            log.info(f"Opening Target Assessment URL: [link={target_url}]{target_url}[/link]")
            await page.goto(target_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            page_ctx = await UniversalDetector.analyze_page(page)

            # Determine execution path
            mode = args.mode if args.mode != "auto" else page_ctx.mode

            if mode in ("coding", "mixed") or page_ctx.editor_type != "unknown":
                coding_runner = CodingRunner(page, db=db)
                await coding_runner.solve_challenge(language=args.lang)
            else:
                quiz_runner = QuizRunner(page, db=db)
                # Parse and answer generic page questions
                from core.question_parser import UniversalQuestionParser
                questions = await UniversalQuestionParser.parse_questions_from_page(page)
                log.info(f"Found {len(questions)} question(s) on target page.")
                for q in questions:
                    parsed_q = type("ParsedQ", (), {
                        "slot": q.slot,
                        "text": q.text,
                        "options": q.options,
                        "element_locator": q.element_locator
                    })()
                    await quiz_runner.answer_question(parsed_q, course_name="Direct Assessment")

            console.print("\n[bold green]✓ Assessment execution completed successfully![/bold green]\n")
            return

        # ==========================================
        # 2. LMS Course Assessment Mode
        # ==========================================
        if not config.LMS_USERNAME:
            console.print(
                Panel(
                    "[bold red]LMS_USERNAME is not set in your .env file![/bold red]\n"
                    "Please edit the [bold cyan].env[/bold cyan] file with your student enrollment number and password.",
                    title="Configuration Error",
                    border_style="red",
                )
            )
            sys.exit(1)

        lms_client = LMSClient(page)
        quiz_runner = QuizRunner(page, db=db)

        # Login
        logged_in = await lms_client.login()
        if not logged_in:
            log.error("Aborting automation due to login failure.")
            return

        # Discover courses
        courses = await lms_client.get_enrolled_courses()
        if not courses:
            log.error("No target courses found.")
            return

        selected_courses = []
        if args.all:
            selected_courses = courses
        elif args.course:
            if args.course.isdigit():
                idx = int(args.course) - 1
                if 0 <= idx < len(courses):
                    selected_courses = [courses[idx]]
            else:
                selected_courses = [c for c in courses if args.course.lower() in c.title.lower()]
            if not selected_courses:
                log.error(f"Course matching '{args.course}' not found.")
                return
        else:
            console.print("\n[bold cyan]Available Target Courses:[/bold cyan]")
            for idx, c in enumerate(courses, 1):
                console.print(f"  [bold yellow][{idx}][/bold yellow] {c.title}")
            console.print(f"  [bold yellow][A][/bold yellow] Attempt All Courses Sequentially")

            choice = input("\nEnter choice [1-N or A] (default: A): ").strip()
            if choice.upper() == "A" or not choice:
                selected_courses = courses
            elif choice.isdigit() and 1 <= int(choice) <= len(courses):
                selected_courses = [courses[int(choice) - 1]]
            else:
                log.error("Invalid choice.")
                return

        # Process selected courses
        summary_results = []
        for course in selected_courses:
            console.rule(f"[bold magenta]Course: {course.title}[/bold magenta]")
            quizzes = await lms_client.get_course_quizzes(course)

            if not quizzes:
                log.warning(f"No quizzes found in '{course.title}'. Skipping.")
                continue

            for q_idx, quiz in enumerate(quizzes, 1):
                console.rule(f"[bold cyan]Quiz {q_idx}/{len(quizzes)}: {quiz.title}[/bold cyan]")
                success = await quiz_runner.execute_quiz(
                    quiz, course_name=course.title, allow_reattempt=getattr(args, "reattempt", False)
                )
                status_str = "[bold green]Completed[/bold green]" if success else "[bold yellow]Skipped/Locked[/bold yellow]"
                summary_results.append((course.title, quiz.title, status_str))

        # Summary Table
        console.print("\n")
        table = Table(title="🎯 [bold green]Automation Execution Summary[/bold green]", border_style="green")
        table.add_column("Course", style="cyan")
        table.add_column("Quiz", style="white")
        table.add_column("Status", style="bold")

        for c_title, q_title, status in summary_results:
            table.add_row(c_title, q_title, status)

        console.print(table)
        console.print(f"\n[bold green]✓ All tasks finished. Total questions in database: {db.count_questions()}[/bold green]\n")

    finally:
        await browser_mgr.close()


def main():
    parser = argparse.ArgumentParser(description="Universal AI Quiz & Coding Assessment Automator")
    parser.add_argument("--url", type=str, help="Direct URL to any quiz, form, or coding problem")
    parser.add_argument("--mode", choices=["auto", "quiz", "coding"], default="auto", help="Assessment mode")
    parser.add_argument("--lang", type=str, default="python", help="Target language for coding (python, cpp, java, c, javascript, sql)")
    parser.add_argument("--all", action="store_true", help="Attempt all assigned target courses sequentially")
    parser.add_argument("--course", type=str, help="Specific course name or index to attempt")
    parser.add_argument("--headless", action="store_true", default=None, help="Run browser in background")
    parser.add_argument("--headful", action="store_false", dest="headless", help="Run browser in visible window")
    parser.add_argument("--reattempt", action="store_true", help="Force re-attempting already completed/passed quizzes")
    parser.add_argument("--fast", action="store_true", help="Fast mode: eliminates artificial delays (super fast solving)")
    parser.add_argument("--network", choices=["internet", "campus"], help="Override network mode")

    args = parser.parse_args()

    if args.network:
        config.LMS_NETWORK = args.network
    if args.fast:
        config.HUMAN_DELAY_MIN = 0.1
        config.HUMAN_DELAY_MAX = 0.3
        config.SLOW_MO_MS = 0
    if args.lang:
        config.CODING_LANGUAGE = args.lang

    try:
        asyncio.run(run_automation(args))
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Operation cancelled by user.[/bold yellow]")


if __name__ == "__main__":
    main()
