# Architecture

This document gives a high-level technical view of My Moodle Helper: repository structure, runtime architecture, and the main operational workflows.

## System Architecture

```mermaid
flowchart LR
    User[Operator or Academic User]
    UI[React Frontend]
    API[FastAPI Backend]
    DB[(SQLite database)]
    LLM[OpenAI-compatible LLM provider]
    Moodle[Moodle REST API]

    User --> UI
    UI --> API
    API --> DB
    API --> LLM
    API --> Moodle
```

## Application Components

```mermaid
flowchart TD
    FRONTEND[Frontend app]
    FRONTEND --> STUDIO[Course Studio]
    FRONTEND --> LIBRARY[Library]
    FRONTEND --> REVIEW[Autonomous Review]
    FRONTEND --> CURRICULUM[Curriculum Map]
    FRONTEND --> ADMIN[Admin Workflows]
    FRONTEND --> SETTINGS[Settings and Security]

    BACKEND[Backend app]
    BACKEND --> COURSES[courses router]
    BACKEND --> MOODLE[moodle router]
    BACKEND --> SETTINGSAPI[settings router]
    BACKEND --> LLMAPI[llm router]
    BACKEND --> CANVAS[canvas router]

    COURSES --> DB[(SQLite)]
    MOODLE --> DB
    SETTINGSAPI --> DB
    LLMAPI --> DB
```

## Repository Structure

```mermaid
flowchart TD
    ROOT[Repository]
    ROOT --> APP[app]
    ROOT --> DOCS[docs]
    ROOT --> TESTS[tests]
    ROOT --> PIPELINE[create_course.py]
    ROOT --> CI[.github/workflows]

    APP --> BACKEND[backend]
    APP --> FRONTEND[frontend]
    APP --> BUILDS[builds]

    BACKEND --> MAIN[main.py]
    BACKEND --> DATABASE[database.py]
    BACKEND --> ROUTERS[routers]

    FRONTEND --> SRC[src]
    SRC --> PAGES[pages]
    SRC --> COMPONENTS[components]
    SRC --> API[api]
    SRC --> I18N[i18n]
```

## Course Generation Workflow

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant B as Backend
    participant C as create_course.py
    participant L as LLM
    participant D as SQLite

    U->>F: Submit course metadata and prompt
    F->>B: POST /api/courses/generate
    B->>C: Start generation pipeline
    C->>L: Generate structure
    C->>L: Generate module content
    C->>L: Generate syllabus
    C->>L: Generate quiz and homework
    C->>D: Save course + version
    B-->>F: Return saved version
```

## Review And Remediation Workflow

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant B as Backend
    participant L as LLM
    participant D as SQLite

    U->>F: Run review
    F->>B: POST /api/courses/{sn}/review
    B->>L: Audit course content
    L-->>B: Structured review JSON
    B->>D: Save review result
    B-->>F: Return findings

    U->>F: Apply selected findings
    F->>B: POST regenerate/finalize endpoints
    B->>L: Regenerate targeted content
    B->>D: Save improved version
    B-->>F: Return updated version
```

## Scheduled Review Workflow

```mermaid
flowchart TD
    A[Course version saved] --> B[Default review schedule seeded]
    B --> C[Scheduler checks overdue reviews every 15 minutes]
    C --> D{Overdue schedule exists?}
    D -- No --> E[Wait for next scheduler tick]
    D -- Yes --> F[Build review prompt from course version]
    F --> G[Call LLM]
    G --> H[Parse and persist review result]
    H --> I[Advance next_run_at]
```

## Moodle Deployment Workflow

```mermaid
flowchart TD
    A[Selected library version] --> B[Review and finalize content]
    B --> C[Build deployment payload]
    C --> D[Create course in Moodle]
    D --> E[Push section summaries and activities]
    E --> F[Seed forums and metadata]
    F --> G[Record deploy event]
```

## Data Model Overview

```mermaid
erDiagram
    COURSES ||--o{ COURSE_VERSIONS : has
    COURSES ||--o{ REVIEWS : accumulates
    COURSES ||--o{ REVIEW_SCHEDULES : schedules
    COURSES ||--o{ CURRICULUM_EVALUATIONS : scored_by
    COURSE_VERSIONS ||--o{ MOODLE_DEPLOYS : deployed_as
    SETTINGS ||--|| SETTINGS : stores_key_values
    ADMIN_AUDIT_LOGS {
        int id
        string area
        string action
        string actor
        string target_type
        string status
    }
```

## Operational Notes

- The backend is the control plane: every authoring, review, curriculum, deployment, and admin workflow passes through FastAPI.
- SQLite is intentionally used as the single operational store to keep setup simple for local and small-team deployments.
- Scheduled reviews only execute while the backend process is running.
- Security-sensitive Moodle admin writes are audited and rate-limited.
- LLM providers are interchangeable as long as they expose an OpenAI-compatible interface.
