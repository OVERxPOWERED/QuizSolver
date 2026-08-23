# ⚡ QuizSolver: Universal AI Quiz & Coding Assessment Automator

An intelligent, modular, universal AI automation platform capable of autonomously solving:
1. **Academic Quizzes & Online Tests:** Moodle, Google Forms, Microsoft Forms, Canvas, Blackboard, and custom web portals.
2. **Coding Assessments & Competitive Contests:** HackerRank, LeetCode, Moodle VPL / CodeRunner, HackerEarth, GeeksforGeeks, Mettl, etc.
3. **Advanced Question Formats:** Multiple Choice, Multi-select Checkboxes, True/False, Short Answer, Fill in the Blanks, and Live Code Synthesis with Self-Correction.

---

## 🌟 Universal Capabilities

- **💻 Multi-Platform Coding Engine:**
  - Automatically extracts problem descriptions, constraints, input/output formats, and sample test cases.
  - Generates optimal code in **Python, C++, Java, C, JavaScript, or SQL**.
  - Directly injects solutions into web code editors: **Monaco Editor (VS Code Web)**, **CodeMirror (v5 & v6)**, **ACE Editor**, and custom textareas.
  - **Self-Correction & Test Execution:** Clicks "Run Code", captures compiler errors / failed test cases, and iteratively self-debugs until all test cases pass before final submission.
- **📝 Universal Quiz & Form Solver:**
  - Semantic DOM extraction across Moodle, Google Forms, Canvas, Blackboard, and generic test sites.
  - Handles single choice, multi-select checkboxes, true/false, text inputs, and dropdowns.
- **🧠 Universal AI Reasoning Engine:**
  - Supports **Google Gemini** (Gemini 3.5 Flash / Lite, Gemini 3.6 Flash, Gemini 3.7 Flash) and **NVIDIA NIM** (Llama 3.3 70B) with automatic model fallback and zero downtime.
- **💾 Local SQLite QA & Code Bank:**
  - Saves all solved questions, test cases, and verified answers locally for instant recall.
- **⚡ Super Fast Headless Mode:**
  - Run with `--fast` and `--headless` to complete 10-question quizzes or code challenges in seconds without artificial delays.

---

## 🛠️ Quick Start

### 1. Configure Credentials (`.env`)
```ini
# Google Gemini Configuration (Primary)
AI_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite

# (Optional) NVIDIA NIM Key (Alternative / Fallback)
NVIDIA_API_KEY=your_nvidia_api_key

# (Optional) LMS Credentials (If using for Acropolis / Moodle)
LMS_USERNAME=your_enrollment_number
LMS_PASSWORD=your_password
```

---

## 🎮 Usage Examples

### 1. Solve Any Direct URL (Coding Challenge or Quiz)
```bash
.venv/bin/python main.py --url "https://www.hackerrank.com/challenges/two-sum/problem" --lang python
```

### 2. Solve Google Forms / Canvas / Web Quiz URL
```bash
.venv/bin/python main.py --url "https://docs.google.com/forms/d/e/.../viewform"
```

### 3. Run Acropolis LMS Course Quizzes
```bash
# Interactive Course Selector
.venv/bin/python main.py

# Solve all assigned courses in background
.venv/bin/python main.py --all --headless --fast
```

### 4. Code in C++, Java, or JavaScript
```bash
.venv/bin/python main.py --url "<problem_url>" --lang cpp
.venv/bin/python main.py --url "<problem_url>" --lang java
```

---

## 🧪 Testing
```bash
PYTHONPATH=. .venv/bin/pytest tests/ -v
```
