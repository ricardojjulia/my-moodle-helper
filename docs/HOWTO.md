# How to Install and Use Moodle Course Creator

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Running the Application](#3-running-the-application)
4. [First-time Setup (Settings)](#4-first-time-setup-settings)
5. [Generating a Course from Scratch](#5-generating-a-course-from-scratch)
6. [Building and Importing the .mbz](#6-building-and-importing-the-mbz)
7. [Course Library](#7-course-library)
8. [Autonomous Quality Review](#8-autonomous-quality-review)
9. [Moodle Integration](#9-moodle-integration)
10. [Student Analytics](#10-student-analytics)
11. [Curriculum Map](#11-curriculum-map)
12. [Scheduled Reviews](#12-scheduled-reviews)
13. [Bible Reference Validator](#13-bible-reference-validator)
14. [Quiz Bank Editor](#14-quiz-bank-editor)
15. [Course Progress Report](#15-course-progress-report)
16. [LLM Provider Setup](#16-llm-provider-setup)
17. [Local Moodle with Docker](#17-local-moodle-with-docker)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. Prerequisites

| Requirement | Minimum | Recommended | Notes |
| ----------- | ------- | ----------- | ----- |
| Python | 3.11 | 3.12+ | `python3 --version` to check |
| Node.js | 20 LTS | 22 LTS | includes npm |
| LLM server | — | — | See [Section 16](#16-llm-provider-setup) |
| Moodle | 5.0 | 5.2 | For import/sync — optional |
| Git | any | — | For cloning the repo |
| SQLite | built-in | — | Part of Python's standard library — **no installation required** |

The application runs entirely on your local machine. No public internet access is required unless you use a cloud LLM provider (OpenAI, OpenRouter, Anthropic).

> **`apscheduler` is optional.** It is listed in `requirements.txt` and installed by `pip install -r requirements.txt`. If you skip it or it fails to install, the app starts normally — scheduled reviews simply run on-demand only (no background daemon).

---

## 2. Installation

### Clone the repository

```bash
git clone https://github.com/your-org/moodle-course-creator.git
cd moodle-course-creator
```

### Python environment

Using a virtual environment is strongly recommended to avoid dependency conflicts:

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# OR
.venv\Scripts\activate             # Windows
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Frontend

```bash
cd app/frontend
npm install
cd ../..
```

> **Note:** In development mode you run Vite separately (see [Section 3](#3-running-the-application)). For production, run `npm run build` once to compile into `app/frontend/dist/`.

---

## 3. Running the Application

### Development mode (recommended during setup)

Run the backend and frontend as two separate processes so both support hot reload:

```bash
# Terminal 1 — backend (API on port 4100)
source .venv/bin/activate
uvicorn app.backend.main:app --reload --port 4100

# Terminal 2 — frontend dev server (UI on port 4101)
cd app/frontend
npm run dev
```

Open **<http://localhost:4101>** in your browser. API calls are proxied to `:4100` automatically.

### Production mode

Compile the frontend once, then run a single process:

```bash
cd app/frontend && npm run build && cd ../..
source .venv/bin/activate
uvicorn app.backend.main:app --host 0.0.0.0 --port 4100
```

Open **<http://localhost:4100>**. FastAPI serves the compiled frontend from `app/frontend/dist/`.

### Convenience script

A `start.sh` script in the project root starts both processes in development mode:

```bash
bash start.sh
```

### Data storage

The app creates `app/library.db` (SQLite) on first run. This file stores all courses, versions, reviews, settings, and Moodle connections. Back it up regularly — it is excluded from git by `.gitignore`.

**SQLite limits to be aware of:**

| Limit | Value | Notes |
| ----- | ----- | ----- |
| Concurrent writers | 1 at a time | WAL mode is enabled for read concurrency; avoid running multiple backend workers |
| Practical library size | ~5,000 courses | Beyond that, query latency increases; consider migrating to PostgreSQL |
| Per-value (BLOB) size | 1 GB (default) | Each course version JSON is typically 50–500 KB — well within limits |
| Database file size | disk-bound | Theoretical SQLite ceiling is 281 TB |
| Migration path | swap `database.py` | Only the connection logic changes; all SQL is standard and portable |

---

## 4. First-time Setup (Settings)

Open the **Settings** tab to configure your LLM and Moodle connections.

### LLM Configuration

Select a provider preset at the top, or enter a custom URL:

| Provider | URL to enter |
| -------- | ------------ |
| LM Studio (local) | `http://localhost:1234/v1` |
| Ollama (local) | `http://localhost:11434/v1` |
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Anthropic | `https://api.anthropic.com/v1` |
| Custom / self-hosted | your server's base URL |

For cloud providers, also enter your **API Key**. For local servers, leave the key blank.

The app auto-detects which provider you are using from the URL and adjusts the model picker accordingly — local providers get the evaluate-and-rank workflow; cloud providers get a simple model ID input.

### Moodle Instances

Click **Add Instance** and fill in:

- **Name** — a label for this connection (e.g. `Production`, `Local Docker`)
- **URL** — your Moodle site root (e.g. `https://your-moodle.example.com`)
- **Token** — a Moodle webservice token with the required permissions (see [Section 9](#9-moodle-integration))

Click **Save**. The instance appears in the list. Click **Activate** to make it the active connection used throughout the app.

You can save multiple instances and switch between them at any time.

---

## 5. Generating a Course from Scratch

Navigate to the **Course Studio** tab.

### Step 1 — Language Model

**Local LLM:**

1. Click **Evaluate Models** — the app sends a test prompt to every model available on your LLM server and scores them on accuracy, speed, and JSON validity.
2. The top 3 models are displayed as cards with score rings. Click any card to select it.
3. Expand "Show all N models" to see the full ranked list.

**Cloud LLM:**

The evaluate workflow is skipped. A model ID autocomplete appears with suggestions for your provider. Type or select a model ID (e.g. `gpt-4o`, `claude-sonnet-4-6`).

### Step 2 — Course Identity

| Field | Description | Example |
| ----- | ----------- | ------- |
| Short name | Unique course code used as the filename | `TH308-2026` |
| Full name | Human-readable course title | `TH 308 — Christian Ethics` |
| Professor | Instructor name, appears in the syllabus | `Prof. Jane Smith` |
| Category | Moodle course category | `2025–2026 Spring Term` |
| Start date | Course start (sets the Moodle timeline) | `2026-01-15` |
| End date | Course end | `2026-03-15` |

### Step 3 — Assessment

- **Quiz questions** — total number of questions in the final quiz bank (30–50 recommended; reviewers flag anything below 30)
- **Homework modules** — click any of the five module pills to add a homework activity to that module:
  - **Assignment** — an LLM-written written assignment prompt
  - **Forum** — an LLM-written discussion forum prompt

### Step 4 — Course Prompt

Write a plain-text description of the course. The richer and more specific the prompt, the better the generated content.

**Good prompt:**

```text
Christian Ethics course for third-year evangelical theology students.
Topics: biblical foundations of ethics, virtue and Christian character,
contemporary ethical dilemmas (bioethics, sexual ethics, social justice)
from a Reformed perspective. Practical focus for pastoral ministry.
Language: English.
```

**Weak prompt:**

```text
Ethics course for theology students.
```

### Generation

Click **Generate Course**. The step tracker shows each phase in real time:

1. **Course structure** — module titles, objectives, key topics
2. **Module content** — lectures, glossary terms, discussion questions (5 modules)
3. **Syllabus** — prontuario and learning outcomes
4. **Quiz** — question bank
5. **Homework** — assignment and forum prompts (if enabled)

Total time: **5–20 minutes** depending on model speed and prompt complexity. Do not close the browser tab while generation is running.

When finished, the course appears automatically in the Library.

---

## 6. Building and Importing the .mbz

### Build

1. Go to the **Library** tab.
2. Click a course in the left panel, then select a version.
3. Click **Build .mbz** — the server compiles all content into a Moodle backup archive.
4. Click **Download** to save the `.mbz` file to your computer.

### Import into Moodle

1. Log in to your Moodle site as administrator.
2. Go to **Site administration → Courses → Restore course**.
3. Upload the `.mbz` file.
4. Follow the restore wizard — select a destination category and confirm course settings.
5. Click **Perform restore**.

The course will appear in the selected category with all sections, activities, quiz questions, and the syllabus page fully populated.

### Import a .mbz into your Library

You can also go the other direction — import an existing `.mbz` file (e.g. from a backup) into your local library:

- **Upload**: In the Library header, click the upload icon and select a `.mbz` file from your computer.
- **From URL**: Paste a download URL (e.g. from Moodle's backup area) into the import dialog.

The file is parsed and saved as a new version in your library, ready for editing and regeneration.

---

## 7. Course Library

### Browsing

The Library is a two-panel layout:

- **Left panel** — courses grouped by Moodle instance. Each instance header shows a stats dashboard (total courses, categories, version distribution V1/V2/V3+, last activity date). Use the search bar and category filter to narrow the list.
- **Right panel** — appears when you click a course: metadata, version list, and the full Course Viewer.

### Course Viewer

Click any version to open the Course Viewer. Tabs let you browse:

- Module structure (objectives, key topics)
- Lecture content for each module
- Glossary terms
- Discussion questions
- Quiz questions
- Syllabus

### Inline Editing

Every text field in the Course Viewer is editable:

1. Click the pencil/edit icon next to any field.
2. Edit the content in the text area that appears.
3. Click **Save** — the change is written directly to the version (no new version is created).

This is ideal for small fixes without triggering a full regeneration.

### Per-module Regeneration

To rewrite a single module without touching the rest:

1. In the Course Viewer, click the wand icon next to the module name.
2. Optionally add custom instructions (e.g. "Include more practical examples").
3. Choose a model if you want to override the default.
4. The module content is replaced in-place.

### Forking

Fork a version to create a safe copy before making significant changes:

- Click the **Fork** button in the version list or the top of the Course Viewer.
- A new version (incremented number) is created with identical content.

### Deploy History

After deploying a version to Moodle, a badge appears on the version showing the deployment timestamp, section and forum counts, and a direct link to the live course.

---

## 8. Autonomous Quality Review

The Autonomous Review feature audits courses in bulk using two configurable LLM agents.

### Setup

1. Navigate to the **Autonomous Review** tab.
2. **Select a category** in the "Courses to Review" card, then pick individual courses (or use All/None).
3. **Choose agents** — both are enabled by default:
   - **Course Reviewer** — checks theology, structure, syllabus completeness, quiz count, and assignment load
   - **Student Critic** — stress-tests depth, modern relevance, and the "So What?" factor
4. Toggle the switch on each agent card to enable or disable it. Click **Edit prompt** to customise the agent's instructions.
5. **Select a model** in the Model card.

### Running a Review

Click **Begin Autonomous Review**. A step list appears showing every `course × agent` combination. Rows turn green as each review completes, violet while running, and red on error.

### Reading Results

Each result card shows:

- **Overall verdict** — Passed / Needs Revision / Incomplete
- **Score** — 0–100
- **Summary** — 2–3 sentence overall assessment
- **Audit detail** — expandable section-by-section breakdown with per-item status (Passed / Needs Revision / Missing) and a one-sentence note

### Applying Feedback

Click **Apply feedback & regenerate** on any course to run the full improvement pipeline:

1. **Fork** — creates a new version from the current latest
2. **Module regeneration** — each module is rewritten with all failing items from both agents injected as improvement instructions
3. **Quiz & Syllabus** — regenerated if flagged or below the 30-question minimum

The step list inside the course card tracks each phase in real time.

---

## 9. Moodle Integration

### Generating a Moodle Token

1. Log in to Moodle as an administrator.
2. Go to **Site administration → Server → Web services → Manage tokens**.
3. Click **Create token**, select a user with admin or manager rights, and choose the **Moodle mobile web service** (or create a custom service with the functions listed below).
4. Copy the token and paste it into Settings → Moodle Instances.

### Required Webservice Functions

| Function | Used for |
| -------- | -------- |
| `core_webservice_get_site_info` | Ping / site stats |
| `core_course_get_courses` | Browse courses |
| `core_course_get_contents` | Read section content |
| `core_course_create_courses` | Deploy new courses |
| `core_course_update_courses` | Update course metadata |
| `core_course_edit_section` | Push section summaries |
| `core_enrol_get_enrolled_users` | Student analytics |
| `core_user_get_users` | Site user stats |
| `core_course_get_categories` | Category list |
| `gradereport_user_get_grade_items` | Grade book + analytics |
| `mod_forum_add_discussion` | Seed forum discussions |
| `mod_quiz_get_quizzes_by_courses` | Quiz analytics |
| `mod_quiz_get_user_attempts` | Per-quiz pass rates |

### Deploying a Course to Moodle

From the Library, with a version open:

1. Click **Deploy to Moodle**.
2. Select a **Moodle category** from the dropdown.
3. Optionally set start and end dates.
4. Click **Deploy** — section summaries and forum discussion questions are pushed to Moodle via the REST API.
5. A link to the live course appears on success, and a deploy badge is recorded on the version.

### Browsing the Instance Course Catalog

The **Instance Course Catalog** tab connects to the active Moodle instance:

- Browse all courses grouped by category
- Click any course to inspect its section/activity structure
- View grade books with the full student roster
- Click **Select Missing** to auto-select all courses not yet in your local library
- Click **Import to Library** to snapshot a single course, or use batch import for multiple

---

## 10. Student Analytics

The Analytics panel is available in the **Instance Course Catalog** tab for any selected course.

1. Select a course in the left panel.
2. Click the **Analytics** tab in the right panel (alongside Structure and Grades).

The panel shows:

| Section | What it shows |
| ------- | ------------- |
| **Enrollment** | Total enrolled, active in the last 30 days, never accessed, suspended |
| **Grade Distribution** | A/B/C/D/F bars with counts and percentages |
| **Pass Rate** | Percentage of students with a total grade ≥ 60%, and the class average |
| **Quiz Performance** | Table of all quizzes: attempt count, average grade, pass rate |
| **Weak Areas** | Alert listing any quiz with pass rate below 70% |

> **Note:** Enrollment and quiz data require the corresponding Moodle webservice functions to be enabled (see [Section 9](#9-moodle-integration)).

---

## 11. Curriculum Map

The **Curriculum Map** tab gives a bird's-eye view of theological domain coverage across your entire course library.

### Reading the Matrix

- **Rows** — one row per library course
- **Columns** — eight theological domains: Old Testament, New Testament, Systematic Theology, Church History, Pastoral Ministry, Biblical Languages, Ethics, and Missions & Evangelism
- **Cell badge** — keyword-match score; green = strong coverage (5+ hits), blue = moderate, gray = weak
- **Domain totals** — a summary bar at the bottom shows aggregate keyword hits across all courses
- **Coverage ring** — the ring at the top shows what percentage of all domains are addressed by at least one course

### Filtering

If you have courses from multiple Moodle instances, use the **instance selector** (top right) to filter the matrix to one instance at a time.

### How Scores are Calculated

The app scans module titles, key topics, objectives, discussion questions, and the course prompt for domain-specific keywords in both English and Spanish. A score of 1 means at least one keyword was found; higher scores indicate denser coverage.

---

## 12. Scheduled Reviews

Scheduled reviews let you configure courses to be automatically re-reviewed on a recurring schedule, so quality regressions are caught without manual intervention.

### Creating a Schedule

1. Go to the **Settings** tab.
2. Scroll to the **Scheduled Reviews** section.
3. Click **Add Schedule**.
4. Fill in:
   - **Course** — select from your library
   - **Agent** — Theological Reviewer or Student Critic
   - **Frequency** — Daily, Weekly, or Monthly
   - **Model ID** — the LLM model to use for the review
5. Click **Save Schedule**.

The schedule is created and the first run is scheduled for one frequency-period from now.

### Running Overdue Reviews

When reviews are past their scheduled time, an orange **N overdue** badge appears next to the section title.

Click **Run N overdue** to trigger all past-due reviews immediately. The LLM runs each review in sequence. When complete, a notification shows how many ran and whether any errors occurred.

All results are saved to each course's review history and appear in the [Course Progress Report](#15-course-progress-report).

### Managing Schedules

Each schedule card shows:

- Course shortname, agent, and frequency
- **Next run** date/time
- **Last run** date/time (after at least one review has run)
- A **delete** button (trash icon) to remove the schedule

---

## 13. Bible Reference Validator

The Bible Reference Validator scans all text content in a course version for Scripture citations and validates them.

### Running a Scan

1. Open the **Library** tab and select a course and version.
2. In the Course Viewer, scroll to the **Bible References** accordion (below the Quiz Bank).
3. Click **Scan** (or **Re-scan** to refresh).

### What is Scanned

| Field | Location |
| ----- | -------- |
| Module lecture HTML | Each of the 5 modules |
| Forum discussion questions | Each module |
| Glossary definitions | All terms |
| Syllabus intro and body | `intro_html` and `content_html` |
| Course summary | Top-level description |

### Status Labels

| Status | Meaning |
| ------ | ------- |
| **Valid** | Book name and chapter are confirmed |
| **Unknown book** | The abbreviated or full book name was not recognized |
| **Chapter out of range** | The cited chapter number exceeds the book's actual chapter count |
| **Verse likely OK** | Book and chapter validated; verse not independently checked |

### Supported Languages

Book names are recognized in both **English** and **Spanish**, including common abbreviations (e.g. `Gen`, `Gn`, `Génesis`, `1 Co`, `1 Cor`, `1 Corinthians`).

---

## 14. Quiz Bank Editor

The Quiz Bank is accessible inside the Course Viewer under the **Quiz** accordion.

### Editing Questions

- Click any question card to expand it and see the full text, options, correct answer index, and explanation.
- Click the edit button to modify any field.
- Click **Save** to write the change directly to the version.

### Reordering Questions

Use the **↑** and **↓** arrow buttons on the right side of each question card to move it up or down in the list.

### Import / Export

- **Export** — downloads the current quiz bank as a JSON file (`quiz_questions.json`). This is useful for backing up questions, sharing them with colleagues, or editing them offline.
- **Import** — uploads a previously exported JSON file and appends the questions from it to the current bank. Malformed entries are silently skipped.

### JSON Format

```json
[
  {
    "question": "What is the primary meaning of logos in John 1:1?",
    "options": ["Wisdom", "Word / Reason", "Law", "Spirit"],
    "correct_index": 1,
    "explanation": "Logos in Greek philosophy and in John's prologue denotes the divine Word or Reason through which God creates and reveals himself."
  }
]
```

---

## 15. Course Progress Report

The Progress Report gives a longitudinal view of how a course's quality has evolved across all review runs.

### Opening the Report

1. In the **Library** tab, click a course.
2. Click the **chart bar** icon (top right of the course header). The tooltip reads "Progress Report (N reviews)".

### What the Report Shows

#### Score Timeline

A table with agents as rows and review dates as columns. Each cell shows:

- The review score (colored badge)
- A trend arrow: ↑ improved, ↓ regressed, → unchanged vs. the previous run by the same agent
- The version number that was reviewed

#### Improvement / Regression Summary

For any agent with two or more reviews, a diff section lists:

- **Improved items** (green ↑) — checks that went from "Needs Revision" or "Missing" to "Passed"
- **Regressed items** (red ↓) — checks that went from "Passed" to "Needs Revision" or "Missing"

#### Full History

An expandable accordion showing every stored review, newest first, with the full section-by-section checklist and per-item notes.

---

## 16. LLM Provider Setup

### LM Studio (recommended for local use)

1. Download [LM Studio](https://lmstudio.ai).
2. In the Discover tab, download a model (7B–13B parameter models work well; 13B+ gives better results for complex theological content).
3. Go to **Local Server** and click **Start Server**.
4. In Settings, enter URL: `http://localhost:1234/v1` (no API key needed).
5. Click **Evaluate Models** in Course Studio to rank all available models automatically.

**Recommended models for theological content:**

- `mistral-7b-instruct` — fast, good JSON compliance
- `llama-3.1-8b-instruct` — well-rounded general quality
- `qwen2.5-14b-instruct` — higher quality, slower

### Ollama

```bash
# Install Ollama, pull a model, start the server
ollama pull llama3.1
ollama serve       # starts on http://localhost:11434
```

In Settings, enter URL: `http://localhost:11434/v1`

### OpenAI

Enter URL `https://api.openai.com/v1` and your OpenAI API key. Recommended models: `gpt-4o` (best quality) or `gpt-4o-mini` (faster, lower cost).

### OpenRouter

Enter URL `https://openrouter.ai/api/v1` and your OpenRouter API key. OpenRouter gives access to Claude, GPT-4o, Gemini, Llama, and 100+ models through a single API — including a free tier.

### Anthropic

Enter URL `https://api.anthropic.com/v1` and your Anthropic API key. Recommended: `claude-sonnet-4-6` (strong reasoning, reliable JSON output).

---

## 17. Local Moodle with Docker

The repo includes a `docker-compose.yml` that starts a full Moodle 5.x + MariaDB stack for local testing.

### Start

```bash
docker compose up -d
```

Moodle will be available at **<http://localhost:4103>** once the containers are healthy (typically 2–3 minutes on first start).

### First-time Moodle setup

1. Open <http://localhost:4103> and complete the installation wizard.
2. Database credentials (already configured in `docker-compose.yml`):
   - Host: `db`, User: `moodle`, Password: `moodle`, Database: `moodle`
3. Create an admin account when prompted.
4. After setup, generate a webservice token (see [Section 9](#9-moodle-integration)) and add it in Settings.

### Stop

```bash
docker compose down          # stops containers, keeps data
docker compose down -v       # stops and deletes all data (clean slate)
```

---

## 18. Troubleshooting

### "No models found" in Course Studio

- Verify your LLM server is running and the URL in Settings is correct.
- For LM Studio, confirm the server is started (green indicator in the Local Server tab).
- Click **Evaluate Models** — if the request times out, increase LM Studio's request timeout.

### Generation fails with a JSON error

The LLM returned malformed JSON. Try:

- Switching to a model with a higher evaluation score (better JSON compliance).
- Lowering the temperature — well-rated models at 0.2–0.4 produce more reliable JSON.
- Simplifying or shortening the course prompt.

### Moodle token "access denied"

- Confirm the token has all required webservice functions enabled (see [Section 9](#9-moodle-integration)).
- Ensure the token user has the **manager** or **administrator** role.
- Check that the REST protocol is enabled: **Site administration → Plugins → Web services → Manage protocols → REST**.

### Analytics shows no data

- Enrollment data requires `core_enrol_get_enrolled_users` to be enabled for the token.
- Quiz data requires `mod_quiz_get_quizzes_by_courses` and `mod_quiz_get_user_attempts`.
- Ensure the token user has the role to view all student grades.

### .mbz import fails in Moodle

- The `.mbz` file is a ZIP archive. Open it with any ZIP tool and verify `moodle_backup.xml` is present at the root.
- Ensure you are restoring to a Moodle 5.x site; older versions may reject the backup format.

### Frontend shows a blank page

- In production mode: check that `app/frontend/dist/` exists — run `cd app/frontend && npm run build` if missing.
- In development mode: confirm both the backend (`:4100`) and the Vite dev server (`:4101`) are running.

### Database errors on startup

The SQLite database is created automatically at `app/library.db`. If it becomes corrupted, stop the server, delete `app/library.db`, and restart — the schema is recreated automatically. Generated `.mbz` files in `app/builds/` are unaffected.

### Scheduled reviews not running

- Reviews run only when you click **Run N overdue** in Settings — there is no background daemon.
- Confirm the LLM URL and model ID are configured correctly in Settings.
- Check that the course referenced by the schedule still exists in the library.
