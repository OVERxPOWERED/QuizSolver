"""Main entry point for Acropolis LMS Quiz Automation."""

import argparse
import asyncio
import sys
from rich.panel import Panel
from rich.table import Table
from config import config
from core.browser import BrowserManager
from core.database import QuestionBankDB
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

    info_table.add_row("🌐 LMS URL", f"{config.base_url} ({config.LMS_NETWORK.upper()})")
    info_table.add_row("👤 Student ID", config.LMS_USERNAME or "[dim yellow]Not configured (Set in .env)[/dim yellow]")
    info_table.add_row("🧠 AI Engine", ai_status)
    info_table.add_row("🖥️  Mode", "Headless (Silent Background)" if config.HEADLESS else "Headful (Live Interactive Window)")
    info_table.add_row("📦 Local QA Bank", f"{db_count} learned questions in SQLite")

    console.print(
        Panel(
            info_table,
            title="[bold yellow]⚡ Acropolis LMS AI Quiz Automation ⚡[/bold yellow]",
            subtitle="[italic dim]Automated Quiz Solver & Knowledge Learner[/italic dim]",
            border_style="bright_blue",
        )
    )


async def run_automation(args: argparse.Namespace):
    """Main async pipeline."""
    db = QuestionBankDB()
    print_banner(db)

    # Validate credentials
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

    # Validate AI key
    if config.AI_PROVIDER == "gemini" and not config.GEMINI_API_KEY:
        if not config.NVIDIA_API_KEY:
            console.print(
                Panel(
                    "[bold red]Neither GEMINI_API_KEY nor NVIDIA_API_KEY is configured in .env![/bold red]\n"
                    "Get a free Gemini key at: [link=https://aistudio.google.com/app/apikey]https://aistudio.google.com/app/apikey[/link]\n"
                    "Or NVIDIA key at: [link=https://build.nvidia.com]https://build.nvidia.com[/link]",
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
        lms_client = LMSClient(page)
        quiz_runner = QuizRunner(page, db=db)

        # 1. Login
        logged_in = await lms_client.login()
        if not logged_in:
            log.error("Aborting automation due to login failure.")
            return

        # 2. Discover target courses
        courses = await lms_client.get_enrolled_courses()
        if not courses:
            log.error("No target courses found. Please ensure you are enrolled.")
            return

        # Select course(s) to process
        selected_courses = []
        if args.all:
            selected_courses = courses
        elif args.course:
            # Match by index or name
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
            # Interactive selection
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

        # 3. Process each selected course
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

        # 4. Display Final Summary Table
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
    parser = argparse.ArgumentParser(description="Acropolis LMS AI-Powered Quiz Automator")
    parser.add_argument("--all", action="store_true", help="Attempt all assigned target courses sequentially")
    parser.add_argument("--course", type=str, help="Specific course name or index to attempt")
    parser.add_argument("--headless", action="store_true", default=None, help="Run browser in background")
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

    try:
        asyncio.run(run_automation(args))
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Operation cancelled by user.[/bold yellow]")


if __name__ == "__main__":
    main()
