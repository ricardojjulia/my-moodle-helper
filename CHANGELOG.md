# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- Admin-first routing slices now shipped with real pages:
  - `/admin/overview` (site health + quick actions)
  - `/admin/analytics` (site/course performance workspace)
  - `/admin/automation` (scheduled review operations)
  - `/admin/users` (directory + lifecycle operations)
  - `/admin/enrollment` (roster + role operations)
- New Moodle admin endpoints for user and enrollment operations:
  - `GET /api/moodle/users`
  - `POST /api/moodle/users`
  - `POST /api/moodle/users/{user_id}/suspend`
  - `DELETE /api/moodle/users/{user_id}`
  - `GET /api/moodle/courses/{course_id}/enrollment`
  - `POST /api/moodle/courses/{course_id}/enrollments`
  - `DELETE /api/moodle/courses/{course_id}/enrollments/{user_id}`
  - `POST /api/moodle/courses/{course_id}/roles/assign`
  - `POST /api/moodle/courses/{course_id}/roles/unassign`
- Security diagnostics and auditability:
  - `GET /api/moodle/write-capabilities` for wsfunction readiness checks
  - `GET /api/settings/audit-logs` for recent admin write events
  - New `admin_audit_logs` SQLite table with backend write-event recording hooks

### Changed

- Settings → Security now includes capability diagnostics and recent admin write audit history.
- Enrollment and Users pages moved from read-only placeholders to guarded action workflows.

## [0.3.0] — 2026-05-08

### Added

- **Autonomous Review** — bulk LLM audit of library courses against configurable expert agents
  - **Course Reviewer agent** — checks theology, structure, assessments, and course quality
  - **Student Critic agent** — stress-tests content from a student perspective (depth, relevance, "So What?" factor)
  - Two-agent setup: each agent has an enable/disable toggle and an editable prompt with a reset-to-default button
  - Category filter in the "Courses to Review" panel for scoped audits
  - Real-time step tracking: every `course × agent` pair shown as a progress row (pending → running → done/error)
- **Apply feedback & regenerate** — step-driven course rewrite from review findings
  - Frontend drives each step: fork → per-module regeneration → quiz & syllabus finalize
  - Colored step list (violet = running, green = done) updates live inside the course header
  - Imported courses supported: existing lecture content injected as context so the LLM improves rather than regenerates from scratch
  - Model fallback for imported courses uses `last_model` from Settings
- New backend endpoints: `POST /{sn}/review`, `POST /{sn}/regenerate-from-review`, `POST /{sn}/versions/{vid}/finalize-review`

### Changed

- **Course Studio** redesigned into four numbered cards: Language Model, Course Identity, Assessment, Course Prompt
- **Generation progress** replaced Mantine `<Stepper>` with a live step-row tracker matching the Autonomous Review style
- **Library stats dashboard**: replaced Backup Coverage with Version Distribution (V1 / V2 / V3+); replaced Avg Duration and Avg Users with Avg Versions/Course and Last Activity
- **Library search**: full-text search + category filter bar added above the two-panel split

---

## [0.2.0] — 2026-05-02

### Added

- **Course library two-panel layout** — left: instance groups with stats; right: course detail with version viewer
- **Instance organisation** — courses grouped by Moodle instance (Local vs. named Moodle site)
- **Activity detail modal** — click any activity row in the Course Viewer to view full HTML content on demand
- **Collapsible instance groups** — collapse/expand instance sections in the Library left panel
- **Bulk delete** — select multiple courses and delete in one action
- **Batch import from Moodle** — import multiple live courses into the library at once
- **Moodle instance management** in Settings — save, activate, and delete named Moodle connections
- **Deploy from Review panel** — fork or deploy directly from Course Studio → Review Step 3
- **Provider-aware model picker** — auto-detects LLM provider from URL; cloud providers show a simple Autocomplete, local providers show evaluate + ranked model cards
- **Per-module regeneration** with custom instructions and model override
- **Homework pill toggles** — module homework toggles styled as clickable pills in Course Studio

### Changed

- Settings: Moodle URL and token moved into the Instances panel; supports multiple simultaneous connections
- Model evaluation now caches results; "Re-evaluate" button clears and reruns the benchmark

---

## [0.1.0] — 2026-04-28

### Added

- `create_course.py` — core pipeline: course structure → module content → syllabus → quiz → homework → Moodle 5.x `.mbz`
- FastAPI backend (`app/backend/`) with SQLite library for courses and versions
- React + Mantine v7 frontend with New Course wizard, Course Library, Settings, and Moodle Sync tabs
- LLM model evaluation: scores every available local model on a theology test prompt; caches results
- Homework support: per-module Assignment or Forum activities with LLM-generated prompts
- Moodle webservice integration: create courses, update section summaries, add forum discussions
- `docker-compose.yml` — local Moodle 5.x + MariaDB stack for testing

### Fixed

- `gradebook.xml` no longer includes `itemtype=mod` grade items — Moodle's restore pipeline only accepts `course`, `category`, and `manual` types at the course level

---

[0.3.0]: https://github.com/ricardojjulia/moodle-course-creator/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ricardojjulia/moodle-course-creator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ricardojjulia/moodle-course-creator/releases/tag/v0.1.0
