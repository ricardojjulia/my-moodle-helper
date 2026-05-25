# Plan v2: Strategic Remaining Work

Last updated: 2026-05-24

This plan intentionally excludes work that is already complete in the current codebase.
It focuses on the highest-leverage items left to reach a stable v1.0 release posture.

## Scope Baseline

Already complete and out of scope for this plan:
- Admin-first control center routes and live operations pages
- User and enrollment write workflows with auditing and policy guardrails
- Autonomous Review with targeted findings execution
- Bible reference validation
- Quiz bank import/export/reorder
- Moodle deploy history and forum seeding

## Strategic Priorities

| Priority | Initiative | Why it matters | Effort | Impact |
|---|---|---|---|---|
| P0 | Quality and test coverage | Reduce regressions in a fast-moving codebase | Medium | Very High |
| P0 | Full activity-level Moodle deploy path | Deliver true “publish-ready” courses without manual restore gaps | High | Very High |
| P1 | Security hardening for multi-user/internal production | Protect tokens, credentials, and admin operations | Medium | High |
| P1 | Performance and bundle optimization | Improve UX responsiveness and maintainability | Medium | High |
| P2 | Operability and observability | Faster diagnosis and safer operations | Medium | Medium |
| P2 | Documentation and release engineering | Predictable onboarding and release quality | Low | Medium |

## Workstreams

### 1) Reliability and Test Coverage (P0)

Objective:
Create confidence gates for backend logic and critical frontend/admin workflows.

Deliverables:
- Backend pytest suite for core routers and database helpers
- Contract tests for critical API response shapes used by frontend
- Frontend component tests for Autonomous Review remediation controls and admin security flows
- Minimal end-to-end smoke tests for generate -> review -> deploy -> audit path

Suggested milestones:
1. Add backend test scaffolding and fixture DB setup.
2. Cover high-risk endpoints first:
   - /api/moodle user/enrollment write endpoints
   - /api/settings audit and admin policy endpoints
   - /api/courses review/regeneration endpoints
3. Add frontend tests for:
   - findings selection and execute selected/all behavior
   - role allowlist and audit filter pagination interactions
4. Add CI check to run tests + type checks + build.

Exit criteria:
- Failing tests block merge.
- Critical paths have automated coverage and stable contracts.

---

### 2) Full Moodle Activity Deploy (P0)

Objective:
Move beyond summary/forum seeding to robust activity-level publishing.

Deliverables:
- Strategy decision and implementation for one of:
  - Guided .mbz restore API workflow, or
  - Direct REST creation for Pages/Assignments/Quizzes/Forums with mapping
- Idempotent deploy behavior with clear diff/redeploy semantics
- Better deploy report in UI: what was created, updated, skipped, failed

Suggested milestones:
1. Define canonical activity mapping model from local course schema.
2. Implement deploy adapter with per-activity status collection.
3. Add dry-run mode (validation without applying changes).
4. Expose detailed deploy timeline/history in Library and admin analytics.

Exit criteria:
- A course can be published with consistent structure and key activities with no manual patching.
- Deploy output is auditable and actionable.

---

### 3) Security Hardening (P1)

Objective:
Raise security posture for internal production operation.

Deliverables:
- Secrets handling improvements (token/key storage policy and masking hardening)
- Optional RBAC-style operator profiles for sensitive actions
- Rate-limit or guardrail for high-risk endpoints
- Enhanced audit integrity:
  - include blocked and failed attempts consistently
  - export filters and retention controls

Suggested milestones:
1. Define security profile modes (single-admin vs team-admin).
2. Add middleware-level request throttling for write-heavy endpoints.
3. Add retention policy and pruning task for audit log table.
4. Add hardening checklist in settings/docs.

Exit criteria:
- Security controls documented and enforced for the most sensitive operations.

---

### 4) Frontend and Runtime Performance (P1)

Objective:
Reduce load cost and improve interaction speed in larger datasets.

Deliverables:
- Route-level code splitting for admin and studio pages
- Progressive/lazy rendering for large tables and long lists
- Query caching strategy for repeated API calls (especially settings/audit/reviews)
- Performance budget and warning thresholds

Suggested milestones:
1. Split large route bundles in the app shell.
2. Add list virtualization where data grows large.
3. Introduce shared data-fetch patterns with cache invalidation.
4. Measure before/after bundle size and page interaction latency.

Exit criteria:
- Initial load and major page transitions are materially faster.

---

### 5) Observability and Operations (P2)

Objective:
Improve troubleshooting and operational clarity for long-running usage.

Deliverables:
- Structured backend logs with request correlation IDs
- Health endpoints and startup checks for dependencies
- Scheduler and automation execution telemetry
- Error dashboards or exported diagnostics summaries

Exit criteria:
- Operators can quickly identify root causes without ad-hoc debugging.

---

### 6) Documentation and Release Engineering (P2)

Objective:
Make the project easy to run, verify, and release reliably.

Deliverables:
- v1.0 runbook (dev, staging, production)
- PR checklist and release checklist
- Versioned migration notes for database and API changes
- Updated architecture and security docs aligned with current admin-first design

Exit criteria:
- New contributors and operators can bootstrap and ship safely with minimal tribal knowledge.

## Sequencing (Recommended)

Phase A (Immediate):
1. Reliability and test coverage
2. Security hardening baseline

Phase B (Core product value):
1. Full Moodle activity deploy path
2. Performance optimization

Phase C (Scale and release):
1. Observability and operations
2. Documentation and release engineering

## 30/60/90-Day Outcome Targets

30 days:
- CI quality gates running (tests/build/type checks)
- Critical endpoint regression coverage in place
- Security hardening baseline implemented

60 days:
- Activity-level deploy path available (or restore automation path finalized)
- Deploy reporting and audit improvements complete
- Major frontend bundle/perf wins delivered

90 days:
- Operational telemetry and diagnostics stabilized
- Release process documented and repeatable
- Candidate v1.0 readiness review complete

## Risks and Mitigations

Risk: Moodle API variability across instances.
Mitigation: Capability checks, deploy dry-run mode, graceful fallback strategies.

Risk: Regression from rapid feature velocity.
Mitigation: Contract tests, CI gates, release checklist enforcement.

Risk: Security drift as write operations grow.
Mitigation: Centralized policy enforcement and periodic audit reviews.

## Definition of Done for Plan v2

Plan v2 is complete when:
- Quality gates prevent regressions on critical flows.
- Publishing workflow is predictable and auditable end-to-end.
- Security and operational controls are in place for sustained internal production use.
- Documentation enables repeatable onboarding and release execution.
