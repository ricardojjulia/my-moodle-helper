# Moodle Course Creator

> AI-powered course authoring studio — generate complete, classroom-ready Moodle 5.x course backups (`.mbz`) from a single text prompt using any OpenAI-compatible LLM.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20%2B-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Moodle](https://img.shields.io/badge/Moodle-5.x-F98012?logo=moodle&logoColor=white)](https://moodle.org/)

---

## What is this?

**Moodle Course Creator** is a full-stack web application that turns a plain-text description of a course into a complete, importable Moodle backup file (`.mbz`) — including module lectures, a glossary, discussion questions, a syllabus, a 30–50 question quiz bank, and optional homework activities.

Designed for theological colleges, seminaries, and any institution that needs to produce structured, standards-compliant Moodle courses at scale. The entire generation pipeline runs against a locally-hosted LLM (LM Studio, Ollama) or any cloud provider with an OpenAI-compatible API (OpenAI, OpenRouter, Anthropic). No Moodle CLI access or special hosting is required.

---

## Features

### AI Course Generation

- **Full pipeline in one click** — course structure → modules → syllabus → quiz bank → optional homework
- **Configurable module count** — choose 3–12 modules per course
- **Multi-language generation** — Spanish, English, Portuguese, French, German
- **Any LLM, any provider** — LM Studio, Ollama, OpenAI, OpenRouter, Anthropic — provider auto-detected from URL
- **Model evaluation** — benchmarks every locally-available model on a test prompt, scores and ranks them by accuracy, speed, and JSON validity
- **Homework configurator** — per-module toggle to add Assignment or Forum activities with LLM-written prompts
- **First-run wizard** — guided setup on first launch if no LLM URL is configured

### Course Library

- **Version history** — every generation saved as a numbered snapshot; fork, compare, or roll back at any time
- **In-browser Course Viewer** — browse module content, glossary, quiz questions, discussion prompts, syllabus
- **Inline editing** — edit any lecture, forum question, glossary entry, or syllabus field directly in the browser
- **Per-module regeneration** — rewrite a single module with custom instructions without touching the rest
- **Fork** — duplicate any version as a safe starting point before making changes
- **Build & download** — compile any version to a valid `.mbz` on demand
- **Import from `.mbz`** — upload or import-from-URL any Moodle backup file into your library
- **HTML export** — export any version to a print-ready HTML page
- **Word export** — download any version as a formatted `.docx` file

### Quality Assurance

- **Autonomous Review** — bulk LLM audit of entire course categories against two configurable expert agents
  - **Course Reviewer** — academic auditor checking theology, structure, quiz count, and syllabus completeness
  - **Student Critic** — stress-tests content for depth, modern relevance, and the "So What?" factor
- **Apply feedback & regenerate** — one click rewrites every module, quiz, and syllabus using the reviewers' findings
- **Review history & Progress Report** — every review is stored; a per-course progress report shows score trends over time and which items improved or regressed across agents
- **Bible Reference Validator** — scans all text fields for Scripture citations, validates book names (English + Spanish), checks chapter ranges, and flags invalid or missing references
- **Quiz Bank editor** — reorder questions with ↑/↓ arrows, import/export the bank as JSON, add/edit/delete individual questions

### Moodle Integration

- **Multi-instance support** — save and switch between multiple Moodle sites (development, staging, production)
- **Live deploy** — push a library version directly to Moodle as a new course, with section summaries and forum discussions seeded automatically
- **Deploy history** — each deployment is recorded with timestamp, section/forum counts, and a direct link to the live course
- **Instance Course Catalog** — browse live courses, expand section contents and activities, view grade books
- **Batch import** — select multiple live Moodle courses and import them all into your library in one operation
- **REST API proxy** — update course metadata, section summaries, and forum discussions without leaving the app
- **Student Analytics** — per-course enrollment stats, grade distribution (A/B/C/D/F), pass rate, and per-quiz performance; weak-area detection

### Curriculum Map

- **AI-scored domain coverage** — each course is evaluated by the best available LLM and scored 0–100 against eight theological domains: Old Testament, New Testament, Systematic Theology, Church History, Pastoral Ministry, Biblical Languages, Ethics, Missions & Evangelism
- **Bilingual evaluation** — the AI recognises equivalent terms in both English and Spanish
- **Bulk evaluation** — select any combination of courses (or "Select pending") and evaluate them all in one run, with a live progress bar and per-row score updates as each finishes
- **Persistent scores** — evaluations are stored in SQLite; re-evaluation is on demand from the Library or Curriculum Map
- **Auto-eval on import** — any course added via generation, `.mbz` upload, or URL import is automatically queued for background evaluation
- **Coverage ring** — summary ring shows what percentage of the eight domains are addressed across the library, with per-domain average scores

### Scheduled Reviews

- **Auto-review scheduler** — configure courses for automatic periodic re-review (daily / weekly / monthly)
- **Background scheduler** — APScheduler checks for overdue reviews every 15 minutes while the server is running
- **Overdue indicator** — Settings tab shows how many scheduled reviews are past-due
- **Run on demand** — trigger all overdue reviews with one click; results appear in each course's review history

### Security

- **Bearer token authentication** — optional API-level protection; all endpoints require a valid `Authorization: Bearer <token>` header when enabled
- **Token management** — generate a secure random token or set a custom one in Settings; disable auth by clearing the token
- **Login modal** — the frontend prompts for the token on first load if auth is enabled; the token is stored in `sessionStorage`
- **Transparent pass-through** — auth is completely optional; if no token is configured, all requests proceed without a header check
- **Write capability diagnostics** — Security panel validates whether required Moodle webservice functions are available for user/enrollment write workflows
- **Admin audit trail** — user/enrollment write operations are recorded in SQLite and surfaced in Settings for operational traceability

### Site Analytics & Settings

- **Instance dashboard** — site-wide stats (courses, categories, active users, auth methods, library coverage)
- **LLM evaluation cache** — model benchmark results are cached and can be refreshed on demand
- **Multi-provider presets** — select local, OpenAI, OpenRouter, or Anthropic with one click

---

## Tech Stack

| Layer | Technology | Version |
| ----- | ---------- | ------- |
| Frontend framework | React | 18 |
| UI component library | Mantine | 7 |
| Icon set | Tabler Icons React | 3 |
| Build tool | Vite | 6 |
| Language (frontend) | TypeScript | 5.6 |
| API framework | FastAPI | 0.115 |
| Language (backend) | Python | 3.11+ |
| Database | SQLite (built-in) | no install; single-writer; scales to ~5,000 courses |
| LLM client | OpenAI-compatible REST | any |
| Course output format | Moodle `.mbz` (ZIP) | Moodle 5.x |
| Local Moodle (optional) | Docker + Bitnami Moodle | 5.x |

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Browser  (React + Mantine)                           │
│                                                                              │
│  Library  │  Course Studio  │  Moodle Catalog  │  Curriculum Map            │
│           │                 │                  │                            │
│  Autonomous Review          │  Settings         │                            │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │  HTTP /api/…
┌──────────────────────────────────▼──────────────────────────────────────────┐
│                            FastAPI  (Python 3.11+)                           │
│                                                                              │
│  /api/courses  ·  /api/llm  ·  /api/moodle  ·  /api/settings                │
│                                                                              │
│                          SQLite  library.db                                  │
│  courses · versions · reviews · schedules · deploys · curriculum_evals · settings  │
└────────┬──────────────────────────────────────────────┬─────────────────────┘
         │                                              │
         ▼                                              ▼
  create_course.py                              Moodle REST API
  ┌─────────────────────┐                    (webservice/rest.php)
  │  LLM pipeline       │
  │  ─────────────────  │
  │  1. Structure       │
  │  2. Content × 5     │
  │  3. Syllabus        │
  │  4. Quiz            │
  │  5. Homework        │
  │  ─────────────────  │
  │  .mbz builder       │
  └────────┬────────────┘
           │
           ▼
   OpenAI-compatible
      LLM server
  (LM Studio / Ollama /
   OpenAI / OpenRouter /
   Anthropic)
```

---

## Quick Start

Full step-by-step instructions are in [docs/HOWTO.md](docs/HOWTO.md).

### Prerequisites

| Requirement | Minimum | Notes |
| ----------- | ------- | ----- |
| Python | 3.11 | 3.12+ recommended |
| Node.js | 20 LTS | includes npm |
| LLM server | — | LM Studio ≥ 0.3, Ollama, or a cloud API key |
| Moodle | 5.x | for `.mbz` import or live sync (optional) |
| SQLite | built-in | part of Python's standard library — no separate install; `app/library.db` is created automatically on first run |

> **`apscheduler` is optional.** If it is not installed the app starts normally; scheduled reviews run on-demand only (no background daemon).

### Install

```bash
git clone https://github.com/your-org/moodle-course-creator.git
cd moodle-course-creator

# Python environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd app/frontend
npm install
cd ../..
```

### Run

```bash
# Development — hot reload on both ends
source .venv/bin/activate
uvicorn app.backend.main:app --reload --port 4100 &   # API on :4100
cd app/frontend && npm run dev                         # UI  on :4101
# open http://localhost:4101

# Production — frontend served by FastAPI
cd app/frontend && npm run build && cd ../..
uvicorn app.backend.main:app --host 0.0.0.0 --port 4100
# open http://localhost:4100
```

### Optional: local Moodle via Docker

```bash
docker compose up -d
# Moodle 5.x available at http://localhost:4103
```

---

## Project Structure

```text
.
├── create_course.py          # Core LLM pipeline + .mbz builder
├── requirements.txt          # Python dependencies
├── docker-compose.yml        # Local Moodle 5.x + MariaDB
├── start.sh                  # Convenience startup script
├── LICENSE
├── CHANGELOG.md
│
├── app/
│   ├── backend/
│   │   ├── main.py           # FastAPI app + static file serving
│   │   ├── database.py       # SQLite schema and all DB helpers
│   │   └── routers/
│   │       ├── courses.py    # Library CRUD, generate, build, review,
│   │       │                 # regenerate, curriculum, schedules
│   │       ├── llm.py        # Model list, evaluation cache
│   │       ├── moodle.py     # Moodle REST proxy, deploy, analytics
│   │       └── settings.py   # App settings, Moodle instance management
│   │
│   ├── frontend/
│   │   ├── index.html
│   │   ├── vite.config.ts
│   │   └── src/
│   │       ├── App.tsx                       # Tab routing
│   │       ├── api/client.ts                 # Fully typed API client
│   │       ├── components/
│   │       │   ├── CourseViewer.tsx          # Course content browser + editor
│   │       │   └── VersionDiff.tsx           # Side-by-side version diff
│   │       └── pages/
│   │           ├── NewCourse.tsx             # Course Studio
│   │           ├── Library.tsx               # Course library + progress report
│   │           ├── AutonomousReview.tsx      # Bulk AI review
│   │           ├── MoodleCourses.tsx         # Live Moodle browser + analytics
│   │           ├── Curriculum.tsx            # Theological domain coverage map
│   │           └── Settings.tsx              # App config + scheduled reviews
│   │
│   └── builds/               # Generated .mbz files (git-ignored)
│
└── docs/
    ├── HOWTO.md              # Full installation and usage guide
    └── MVP_ASSESSMENT.md     # Feature audit and readiness assessment
```

---

## API Reference

Interactive docs at `http://localhost:4100/docs` when running.

| Group | Endpoint | Description |
| ----- | -------- | ----------- |
| **Library** | `GET /api/courses` | List all courses |
| | `POST /api/courses/generate` | Run full LLM generation pipeline |
| | `GET /api/courses/{sn}/versions` | List versions for a course |
| | `POST /api/courses/{sn}/versions/{vid}/build` | Compile version to `.mbz` |
| | `GET /api/courses/{sn}/versions/{vid}/download` | Download `.mbz` file |
| | `POST /api/courses/{sn}/versions/{vid}/fork` | Duplicate a version |
| | `PATCH /api/courses/{sn}/versions/{vid}/field` | Inline field edit |
| | `POST /api/courses/{sn}/versions/{vid}/modules/{n}/regenerate` | Regenerate one module |
| | `GET /api/courses/{sn}/versions/{vid}/export-html` | Print-ready HTML export |
| | `GET /api/courses/{sn}/versions/{vid}/export-docx` | Word (.docx) export |
| | `GET /api/courses/{sn}/versions/{vid}/bible-refs` | Validate Bible references |
| | `PUT /api/courses/{sn}/versions/{vid}/quiz` | Save quiz question bank |
| **Review** | `POST /api/courses/{sn}/review` | Single-course LLM audit |
| | `GET /api/courses/{sn}/reviews` | List all stored reviews |
| | `POST /api/courses/{sn}/regenerate-from-review` | Full rewrite from review findings |
| | `POST /api/courses/{sn}/versions/{vid}/finalize-review` | Regenerate quiz + syllabus |
| | `GET /api/courses/reviews/recent` | Recent reviews across all courses |
| **Schedules** | `GET /api/courses/schedules` | List scheduled reviews |
| | `POST /api/courses/schedules` | Create a new schedule |
| | `DELETE /api/courses/schedules/{id}` | Delete a schedule |
| | `POST /api/courses/schedules/run-overdue` | Run all past-due scheduled reviews |
| **Curriculum** | `GET /api/courses/curriculum` | AI-scored theological domain coverage map |
| | `POST /api/courses/{sn}/curriculum-eval` | Run AI evaluation for one course |
| **LLM** | `GET /api/llm/models` | List available models |
| | `GET /api/llm/evaluation` | Get cached evaluation results |
| | `POST /api/llm/evaluate` | Run model evaluation benchmark |
| **Moodle** | `GET /api/moodle/courses` | List live Moodle courses |
| | `GET /api/moodle/courses/{id}/contents` | Course section structure |
| | `GET /api/moodle/courses/{id}/grades` | Grade book |
| | `GET /api/moodle/courses/{id}/analytics` | Enrollment + grade + quiz analytics |
| | `POST /api/moodle/deploy` | Deploy library version to Moodle |
| | `GET /api/moodle/deploys` | Deploy history for a version |
| | `GET /api/moodle/stats` | Site-wide statistics |
| **Settings** | `GET /api/settings` | Get current settings |
| | `PUT /api/settings` | Update LLM / general settings |
| | `GET /api/settings/instances` | List saved Moodle instances |
| | `POST /api/settings/instances` | Add or update a Moodle instance |
| | `POST /api/settings/instances/{name}/activate` | Set active Moodle instance |
| **Auth** | `GET /api/auth/status` | Whether token auth is enabled |
| | `POST /api/auth/token` | Set a custom auth token |
| | `POST /api/auth/token/generate` | Generate a secure random token |
| | `DELETE /api/auth/token` | Disable authentication |
| | `GET /api/auth/verify` | Verify caller's token is valid |

---

## Contributing

Pull requests are welcome. The `main` branch is protected — all changes must go through a PR.

```bash
git checkout -b feat/your-feature
# make changes and commit
git push origin feat/your-feature
# open a Pull Request
```

Please keep PRs focused and include a clear description of what changes and why. For significant new features, open an issue first to discuss the approach.

---

## License

[MIT](LICENSE) © 2026 Ricardo Julia
