"""Moodle LMS Client for authentication, course discovery, and quiz navigation."""

import re
from typing import Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page
from config import config
from utils.helpers import human_delay, normalize_text
from utils.logger import console, log


class LMSCourse:
    def __init__(self, title: str, url: str, course_id: Optional[str] = None):
        self.title = title
        self.url = url
        self.course_id = course_id

    def __repr__(self):
        return f"<LMSCourse: '{self.title}' ({self.url})>"


class LMSQuiz:
    def __init__(self, title: str, url: str, quiz_id: Optional[str] = None, status: str = "Pending"):
        self.title = title
        self.url = url
        self.quiz_id = quiz_id
        self.status = status

    def __repr__(self):
        return f"<LMSQuiz: '{self.title}' ({self.url}) - {self.status}>"


class LMSClient:
    """Handles high-level Moodle navigation and state."""

    def __init__(self, page: Page):
        self.page = page

    async def is_authenticated(self) -> bool:
        """Check if current session is authenticated as a logged-in user."""
        # Check for logout link or user avatar/name (present ONLY when logged in)
        logout_count = await self.page.locator("a[href*='logout.php'], a[href*='login/logout.php']").count()
        if logout_count > 0:
            return True
        user_name_count = await self.page.locator(".usertext, .userbutton .avatars, span.userbutton").count()
        if user_name_count > 0:
            return True
        not_logged_in_count = await self.page.locator("body.notloggedin, .loginform input#username").count()
        return not_logged_in_count == 0

    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Authenticate to Acropolis Moodle LMS."""
        user = (username or config.LMS_USERNAME).strip().lower()
        pwd = password or config.LMS_PASSWORD

        if not user:
            raise ValueError("LMS Username (Enrollment Number) cannot be empty. Please set LMS_USERNAME in .env")

        login_url = config.login_url
        log.info(f"Navigating to LMS Login: [link={login_url}]{login_url}[/link]")

        await self.page.goto(login_url, wait_until="domcontentloaded")
        await human_delay(0.5, 1.0)

        # Check if already authenticated
        if await self.is_authenticated():
            log.info("[bold green]Already logged in to LMS session.[/bold green]")
            return True

        # Ensure login form elements are present
        username_input = self.page.locator("input#username, input[name='username']")
        password_input = self.page.locator("input#password, input[name='password']")

        if await username_input.count() == 0:
            log.warning("Username field not found directly. Checking page state...")
            if await self.is_authenticated():
                return True

        log.info(f"Submitting credentials for student: [bold cyan]{user}[/bold cyan]")
        await username_input.first.fill(user)
        await human_delay(0.3, 0.6)
        await password_input.first.fill(pwd)
        await human_delay(0.3, 0.6)

        # Click submit button
        submit_btn = self.page.locator("button#loginbtn, input#loginbtn, #login button[type='submit'], input[type='submit']")
        await submit_btn.first.click()

        # Wait for navigation
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

        await human_delay(1.0, 2.0)

        # Check for invalid login error alert
        error_el = self.page.locator(".alert-danger, .loginerrors, #loginerrormsg, .notifyproblem")
        if await error_el.count() > 0:
            err_msg = normalize_text(await error_el.first.inner_text())
            log.error(f"[bold red]❌ LMS Login Failed: '{err_msg}'[/bold red]")
            log.error("[yellow]Please check your LMS_USERNAME and LMS_PASSWORD in the .env file.[/yellow]")
            return False

        if "change_password.php" in self.page.url:
            log.warning("⚠️ LMS requires a mandatory password change! Please change your password on the LMS first.")
            return False

        # Verify login success
        if await self.is_authenticated():
            log.info("[bold green]✓ Successfully logged into LMS![/bold green]")
            return True

        log.error(f"[bold red]❌ Login verification failed. Still on unauthenticated page: {self.page.url}[/bold red]")
        return False

    async def get_enrolled_courses(self) -> list[LMSCourse]:
        """Fetch all courses accessible by the user, matching target courses."""
        log.info("Searching for enrolled target courses...")
        courses: list[LMSCourse] = []

        # 1. Try "My Courses" page first
        my_courses_url = config.my_courses_url
        try:
            await self.page.goto(my_courses_url, wait_until="domcontentloaded")
            await human_delay(1.0, 1.5)
        except Exception:
            pass

        content = await self.page.content()
        soup = BeautifulSoup(content, "lxml")

        # Select course cards/links across various Moodle themes
        course_links = soup.select(
            "a[href*='/course/view.php?id='], .dashboard-card a, .coursebox .coursename a, .card-title a, .coursename a"
        )

        seen_urls = set()
        for link in course_links:
            href = link.get("href", "")
            title = normalize_text(link.get_text())
            if not href or href in seen_urls or not title:
                continue

            id_match = re.search(r"id=(\d+)", href)
            course_id = id_match.group(1) if id_match else None

            if "view.php?id=" in href and not any(x in href for x in ["/mod/", "/user/", "/grade/"]):
                seen_urls.add(href)
                courses.append(LMSCourse(title=title, url=href, course_id=course_id))

        # Check Site Home or Frontpage if empty
        if not courses:
            log.info("Checking Frontpage courses...")
            try:
                await self.page.goto(config.base_url, wait_until="domcontentloaded")
                await human_delay(1.0, 1.5)
                soup = BeautifulSoup(await self.page.content(), "lxml")
                for link in soup.select("a[href*='/course/view.php?id=']"):
                    href = link.get("href", "")
                    title = normalize_text(link.get_text())
                    if href and href not in seen_urls and title and not any(x in href for x in ["/mod/", "/user/"]):
                        seen_urls.add(href)
                        courses.append(LMSCourse(title=title, url=href))
            except Exception as e:
                log.warning(f"Could not scan frontpage: {e}")

        # Filter and prioritize target courses
        target_matches: list[LMSCourse] = []
        for course in courses:
            norm_title = course.title.lower()
            for target in config.TARGET_COURSES:
                if target.lower() in norm_title or any(word.lower() in norm_title for word in target.split() if len(word) > 4):
                    if course not in target_matches:
                        target_matches.append(course)
                        break

        if target_matches:
            log.info(f"Discovered [bold green]{len(target_matches)}[/bold green] target course(s):")
            for c in target_matches:
                log.info(f" - [bold cyan]{c.title}[/bold cyan] ({c.url})")
            return target_matches

        return courses

    async def get_course_quizzes(self, course: LMSCourse) -> list[LMSQuiz]:
        """Navigate to a course page and list all quiz activities with completion status."""
        log.info(f"Scanning quizzes in course: [bold cyan]{course.title}[/bold cyan]...")
        await self.page.goto(course.url, wait_until="domcontentloaded")
        await human_delay(1.0, 1.5)

        # Expand any collapsed course sections if present in Moodle 4.x
        expand_buttons = self.page.locator(".collapseexpand, button[data-action='expand-all'], .course-section-header.collapsed")
        if await expand_buttons.count() > 0:
            try:
                await expand_buttons.first.click()
                await human_delay(0.5, 1.0)
            except Exception:
                pass

        soup = BeautifulSoup(await self.page.content(), "lxml")
        quizzes: list[LMSQuiz] = []
        seen_urls = set()

        # Check activity item containers first to capture completion status
        activity_items = soup.select(".activity-item, li.activity, .activity")
        for item in activity_items:
            quiz_link = item.select_one("a[href*='/mod/quiz/view.php']")
            if not quiz_link:
                continue
            href = quiz_link.get("href", "")
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            title = normalize_text(quiz_link.get_text())
            title = re.sub(r"^Quiz\s*", "", title, flags=re.IGNORECASE).strip()
            title = re.sub(r"\s*(Done|To do)$", "", title, flags=re.IGNORECASE).strip()

            item_text = normalize_text(item.get_text())
            status = "Done" if "Done" in item_text and "To do" not in item_text else "Pending"

            id_match = re.search(r"id=(\d+)", href)
            quiz_id = id_match.group(1) if id_match else None
            quizzes.append(LMSQuiz(title=title or f"Quiz {len(quizzes)+1}", url=href, quiz_id=quiz_id, status=status))

        # Fallback for any standalone quiz links
        for a in soup.select("a[href*='/mod/quiz/view.php']"):
            href = a.get("href", "")
            if href and href not in seen_urls:
                seen_urls.add(href)
                title = normalize_text(a.get_text())
                title = re.sub(r"^Quiz\s*", "", title, flags=re.IGNORECASE).strip()
                id_match = re.search(r"id=(\d+)", href)
                quizzes.append(LMSQuiz(title=title or f"Quiz {len(quizzes)+1}", url=href, quiz_id=id_match.group(1) if id_match else None))

        log.info(f"Found [bold cyan]{len(quizzes)}[/bold cyan] quiz(zes) in '{course.title}'.")
        for q in quizzes:
            status_color = "green" if q.status == "Done" else "yellow"
            log.info(f"  - {q.title}: [{status_color}]{q.status}[/{status_color}]")

        return quizzes
