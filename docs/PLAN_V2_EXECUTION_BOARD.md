# Plan v2 Execution Board (Sprint 1/2/3)

Last updated: 2026-05-24
Source plan: docs/PLAN_V2_STRATEGIC.md

Use this as a practical delivery board. Each item is written as an owner-ready checklist with clear acceptance criteria.

## Operating Model

Sprint length:
- 2 weeks per sprint

Suggested owners:
- BE: Backend/API engineer
- FE: Frontend engineer
- QA: Test/quality engineer
- OPS: DevOps/platform engineer
- PM: Product/project owner

Status legend:
- [ ] Not started
- [~] In progress
- [x] Done

---

## Sprint 1 (P0 Foundations)

Goal:
Establish regression safety and baseline security controls.

### Track A: Reliability and Test Coverage

Owner: QA + BE

Tasks:
- [ ] Create backend test scaffold with isolated test database fixtures.
- [ ] Add tests for admin write endpoints (users/enrollment happy + failure paths).
- [ ] Add tests for audit and admin policy endpoints.
- [ ] Add tests for review/regeneration endpoints.
- [ ] Add contract checks for high-risk response shapes consumed by frontend.

Acceptance criteria:
- Test suite runs locally and in CI with repeatable results.
- Core admin and review endpoints are covered for success/failure behavior.
- Contract regressions fail CI.

### Track B: Frontend Critical Flow Tests

Owner: FE + QA

Tasks:
- [ ] Add tests for Autonomous Review findings selection and execute selected/all actions.
- [ ] Add tests for Security page role allowlist save flow.
- [ ] Add tests for audit filter and pagination interactions.

Acceptance criteria:
- Critical UI behaviors are covered and deterministic.
- Type check + tests pass in CI.

### Track C: Security Baseline Hardening

Owner: BE + OPS

Tasks:
- [ ] Define and document single-admin vs team-admin operating mode.
- [ ] Add request throttling or rate limiting on sensitive write endpoints.
- [ ] Add audit retention policy and pruning mechanism.
- [ ] Ensure blocked and failed admin operations are consistently logged.

Acceptance criteria:
- Sensitive endpoints have guardrails against abuse.
- Audit growth is controlled with a clear retention strategy.
- Security baseline checklist exists in docs.

### Sprint 1 Exit Gate

- [ ] CI enforces build + type checks + tests.
- [ ] P0 reliability and baseline security items are complete.

---

## Sprint 2 (Core Product Value)

Goal:
Deliver predictable, auditable publishing and improve runtime performance.

### Track A: Full Moodle Activity Deploy

Owner: BE + FE + PM

Tasks:
- [ ] Finalize deploy strategy decision:
  - [ ] Guided restore automation path, or
  - [ ] Direct REST activity creation path.
- [ ] Implement canonical activity mapping model from local course schema.
- [ ] Implement idempotent deploy behavior (create/update/skip semantics).
- [ ] Add dry-run deploy validation endpoint/workflow.
- [ ] Add detailed deploy report (created/updated/skipped/failed) in UI.

Acceptance criteria:
- Publish flow produces consistent activity-level outcomes.
- Dry-run explains exactly what would happen before write actions.
- Deploy report is auditable and actionable.

### Track B: Performance Optimization

Owner: FE + OPS

Tasks:
- [ ] Add route-level code splitting for major admin/studio pages.
- [ ] Add virtualization/lazy rendering for heavy lists and tables.
- [ ] Introduce shared query cache strategy for repeated fetches.
- [ ] Define and enforce basic performance budget thresholds.

Acceptance criteria:
- Initial load and route transitions improve measurably.
- Large datasets remain responsive under normal usage.

### Sprint 2 Exit Gate

- [ ] Activity-level deploy path is available with reporting.
- [ ] Performance baseline improved and documented.

---

## Sprint 3 (Scale and Release Readiness)

Goal:
Operationalize the platform and finalize v1.0 release discipline.

### Track A: Observability and Operations

Owner: OPS + BE

Tasks:
- [ ] Add structured logs with request correlation IDs.
- [ ] Add health/readiness checks for critical dependencies.
- [ ] Add scheduler/automation execution telemetry.
- [ ] Provide operational diagnostics export (or summary endpoint).

Acceptance criteria:
- Operators can diagnose failures quickly using logs and health endpoints.
- Automation behavior is visible and explainable.

### Track B: Documentation and Release Engineering

Owner: PM + QA + OPS

Tasks:
- [ ] Publish v1.0 runbook (dev/staging/production).
- [ ] Add PR checklist and release checklist.
- [ ] Add versioned migration notes guidance for DB/API changes.
- [ ] Update architecture and security docs to current admin-first reality.

Acceptance criteria:
- New contributors can onboard with minimal handholding.
- Releases are repeatable and checklist-driven.

### Sprint 3 Exit Gate

- [ ] Observability stack and runbooks are complete.
- [ ] Release process is documented and used.
- [ ] v1.0 readiness review completed.

---

## Cross-Sprint Risk Watchlist

Owner: PM (review weekly)

- [ ] Moodle API capability variance across environments.
- [ ] Regression risk from fast feature velocity.
- [ ] Security drift as admin write operations expand.
- [ ] Performance regressions as data volume grows.

Mitigation checkpoints:
- [ ] Weekly risk review and mitigation updates.
- [ ] CI failures triaged within 1 business day.
- [ ] Security and performance checks included in definition of done.

---

## Weekly Cadence Template

Owner: PM

- [ ] Monday planning: confirm sprint scope and ownership.
- [ ] Mid-week checkpoint: review blockers and adjust sequencing.
- [ ] Friday demo: show completed checklist items and metrics.
- [ ] Retro: capture what to keep/change for next sprint.

## Definition of Done (Board Level)

- [ ] Sprint 1/2/3 exit gates all passed.
- [ ] P0/P1 commitments delivered with validated outcomes.
- [ ] v1.0 readiness decision supported by evidence (tests, deploy reliability, security, ops docs).
