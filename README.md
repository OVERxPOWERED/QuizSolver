# ⚡ LMS AI Quiz Automator

An intelligent, robust automation tool for automatically solving assigned academic quizzes on **Acropolis Moodle LMS** using **Playwright** and **AI (Google Gemini / NVIDIA NIM)**.

---

## 🚀 Features

- **🌐 Dual Network Support:** Works from home (`47.29.0.163`) and college campus LAN (`172.16.8.203`).
- **🧠 Universal AI Reasoning:** Supports **Google Gemini** (Gemini 2.5 / 2.0 / 1.5 Flash) and **NVIDIA NIM** (Llama 3.3 70B, DeepSeek R1) with automatic fallback.
- **📚 Domain-Tuned Accuracy:** Specialized prompts for:
  1. *Outcome Based Education Awareness Programme* (OBE, Bloom's Taxonomy, POs/COs, NBA/NAAC)
  2. *Indian Constitution* (Articles, Schedules, Fundamental Rights, Judiciary)
  3. *Indian Knowledge System* (IKS, Vedic Sciences, Ayurveda, Ancient Mathematics)
- **💾 Local SQLite QA Bank:** Remembers all answered and verified questions. Re-attempts and identical questions across students are answered with instant 100% accuracy.
- **👀 Live Interactive vs Headless Mode:** Watch the browser solve questions live in real-time or run silently in the background.
- **🛡️ Human-Like Jitter & Safety:** Emulates human reading and clicking delays (1–2.5s) to avoid bot detection and rate limits.

---

## 🛠️ Quick Start

### 1. Setup Environment
```bash
# Activate virtual environment
source .venv/bin/activate
```

### 2. Configure Credentials (`.env`)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env`:
```ini
# LMS Credentials
LMS_NETWORK=internet
LMS_USERNAME=your_enrollment_number_here  # Example: 0827cs113112
LMS_PASSWORD=Student@123                 # Your LMS password

# AI Provider (Choose Gemini or NVIDIA)
AI_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here

# (Optional) NVIDIA NIM API Key
NVIDIA_API_KEY=your_nvidia_api_key_here
```

> **Where to get API Keys:**
> - Google Gemini API Key (Free): [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
> - NVIDIA NIM API Key (Free credits): [https://build.nvidia.com](https://build.nvidia.com)

---

## 🎮 Usage

### 1. Interactive Course Selector (Recommended)
```bash
.venv/bin/python main.py
```

### 2. Attempt All Courses Sequentially
```bash
.venv/bin/python main.py --all
```

### 3. Attempt a Specific Course
```bash
.venv/bin/python main.py --course "Indian Constitution"
```

### 4. Run Headless (Background Execution)
```bash
.venv/bin/python main.py --all --headless
```

### 5. Run from College Campus LAN
```bash
.venv/bin/python main.py --network campus
```

---

## 🧪 Testing & Verification
```bash
PYTHONPATH=. .venv/bin/pytest -v
```
