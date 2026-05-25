# Changelog

All notable changes to My Moodle Helper are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Admin-first operational pages for overview, analytics, automation, users, and enrollment workflows.
- Moodle admin endpoints for user lifecycle, enrollment, and role assignment actions.
- Security diagnostics for Moodle write capability readiness.
- Admin audit log storage, filtering, export, retention policy, and pruning controls.
- Contract-style API tests for high-risk response shapes.
- Security tests for throttling, audit retention, and prune behavior.
- Defensive curriculum score parsing for malformed or legacy persisted data.
- Root-level npm wrapper commands so frontend workflows can run from the repository root.
- Dedicated architecture documentation with Mermaid diagrams.

### Changed

- Product naming updated across the app surface to My Moodle Helper.
- Autonomous Review now supports focused execution of selected findings as well as run-all remediation.
- Curriculum Map, scheduled reviews, and security workflows now have stronger operational resilience.
- Automation scheduling now starts empty, supports manual schedule creation only, and includes a clear-all action for resetting scheduled reviews.
- README rewritten as a cleaner public-facing project landing page.
- Repository links updated to the new GitHub slug `ricardojjulia/my-moodle-helper`.

### Fixed

- Curriculum endpoint no longer fails on malformed stored `scores_json` values.
- Module regeneration no longer hard-fails when `json_repair` is unavailable at runtime.
- Backend now avoids dormant scheduled-review behavior for reviewable courses that lacked a saved schedule.
- Existing scheduled-review queues can now be reset without deleting courses, versions, or review history.

## [0.3.0] - 2026-05-08

### Added

- Autonomous Review for bulk LLM auditing of library courses against configurable expert agents.
- Course Reviewer agent for theology, structure, assessments, and academic quality checks.
- Student Critic agent for depth, clarity, modern relevance, and learner-impact review.
- Apply-feedback-and-regenerate workflow across modules, quiz, and syllabus.
- Review endpoints for single-course review, regenerate-from-review, and finalize-review flows.

### Changed

- Course Studio redesigned into clearer configuration sections.
- Generation progress updated to a live step tracker.
- Library dashboard updated with more useful version and activity metrics.
- Library search expanded with full-text search and category filtering.

## [0.2.0] - 2026-05-02

### Added

- Two-panel course library layout with grouped Moodle instances.
- Activity detail modal in the Course Viewer.
- Bulk delete and batch import workflows.
- Named Moodle instance management in Settings.
- Deploy-from-review workflow.
- Provider-aware model picker and per-module regeneration controls.
- Homework toggles per module in Course Studio.

### Changed

- Settings moved Moodle URL and token handling into multi-instance management.
- Model evaluation results are now cached and refreshable.

## [0.1.0] - 2026-04-28

### Added

- Core `create_course.py` pipeline for structure, module content, syllabus, quiz, homework, and Moodle `.mbz` generation.
- FastAPI backend with SQLite-backed library management.
- React frontend with New Course, Library, Settings, and Moodle Sync foundations.
- LLM model evaluation and ranking for local environments.
- Moodle webservice integration for course creation and content updates.
- Local Moodle Docker stack for testing.

### Fixed

- `gradebook.xml` generation now avoids unsupported course-level `itemtype=mod` values in Moodle restore flows.

[0.3.0]: https://github.com/ricardojjulia/my-moodle-helper/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ricardojjulia/my-moodle-helper/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ricardojjulia/my-moodle-helper/releases/tag/v0.1.0
