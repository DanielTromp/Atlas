<!--
Sync Impact Report
==================
Version change: Initial → 1.0.0
Type: MAJOR (Initial constitution establishment)

Modified principles: N/A (Initial creation)
Added sections:
  - All 7 core principles (CLI-First, Service-Oriented, Test-First, Integration Testing, Observability, Security & Credentials, Simplicity & YAGNI)
  - Development Workflow section
  - Quality Gates section
  - Governance section

Removed sections: N/A (Initial creation)

Templates requiring updates:
  ✅ plan-template.md - Constitution Check section aligns with new principles
  ✅ spec-template.md - Requirements sections compatible with principles
  ✅ tasks-template.md - Test-first workflow and task structure align with TDD principle
  ⚠ Consider adding security checklist items for credential handling

Follow-up TODOs: None
-->

# Infrastructure Atlas Constitution

## Core Principles

### I. CLI-First Architecture

Every feature MUST expose functionality via CLI before other interfaces. This ensures:
- Text-based input/output protocol: stdin/arguments → stdout, errors → stderr
- Support for both JSON and human-readable output formats (via `--json` flag)
- Scriptability and automation as first-class concerns
- Web UI and API endpoints are convenience layers built on top of CLI commands

**Rationale**: CLI-first design enforces clear contracts, enables automation, ensures testability, and provides a consistent interface across all features regardless of how they're consumed.

### II. Service-Oriented Implementation

Features MUST be implemented as services with clear boundaries:
- Services are self-contained with well-defined interfaces
- Each service handles a single domain (e.g., NetBox export, Commvault backups, vCenter inventory)
- Services MUST be independently testable without external dependencies
- CLI commands, API endpoints, and background jobs all consume the same service layer

**Rationale**: Service-oriented architecture prevents code duplication, enables parallel development, facilitates testing, and ensures consistency across different interfaces (CLI, API, scheduled jobs).

### III. Test-First Development (NON-NEGOTIABLE)

Test-Driven Development is MANDATORY for all features:
1. Tests MUST be written FIRST and MUST FAIL before implementation begins
2. Follow Red-Green-Refactor cycle strictly:
   - **Red**: Write failing tests that define expected behavior
   - **Green**: Implement minimum code to make tests pass
   - **Refactor**: Improve code while keeping tests green
3. User approval of tests required before implementation begins
4. No code merged without corresponding tests

**Rationale**: TDD ensures requirements are clear before coding begins, provides regression protection, serves as living documentation, and prevents over-engineering by focusing on actual requirements.

### IV. Integration Testing for Contracts

Integration tests are REQUIRED for these scenarios:
- New service contract creation (test the full service interface)
- Changes to existing service contracts (verify backward compatibility or document breaking changes)
- Inter-service communication (e.g., export service → Confluence service)
- External API integration (NetBox, Commvault, vCenter, Atlassian, Zabbix)
- Shared schemas and data models (ensure consistency across services)
- End-to-end CLI workflows that span multiple services

**Rationale**: Integration tests verify that components work together correctly, catch contract violations early, and ensure external integrations remain stable across updates.

### V. Observability First

Every feature MUST support debugging and monitoring:
- Structured logging REQUIRED for all operations (use Python's logging framework)
- Support for configurable log levels (via `--log-level` or environment variables)
- Text I/O ensures debuggability (no binary formats without text alternatives)
- Cache hit/miss instrumentation for all caching layers
- Performance metrics for long-running operations (e.g., API fetches, exports)
- Error context MUST include actionable information for troubleshooting

**Rationale**: Operations-focused software like Infrastructure Atlas requires deep observability for troubleshooting production issues, understanding performance bottlenecks, and maintaining system reliability.

### VI. Security & Credentials Management

Credentials and secrets MUST be handled securely:
- Credentials stored in `.env` file (not committed to repository)
- Encrypted secret store (via `ATLAS_SECRET_KEY` Fernet encryption) for sensitive values
- Support for database-backed credential storage with encryption at rest
- API authentication via Bearer tokens (`ATLAS_API_TOKEN`)
- Web UI authentication via session cookies with secure configuration
- TLS/HTTPS support for API endpoints (certificate and key configuration)
- NEVER log credentials, tokens, or sensitive data
- Environment variable validation on startup to catch missing credentials early

**Rationale**: Infrastructure management tools handle highly sensitive credentials (API tokens, passwords, encryption keys). Robust credential management prevents security breaches and ensures compliance with security best practices.

### VII. Simplicity & YAGNI

Start simple and add complexity only when proven necessary:
- Implement the simplest solution that satisfies requirements
- YAGNI (You Aren't Gonna Need It) principle strictly enforced
- Complexity MUST be justified and documented (see Complexity Tracking in plan.md)
- Prefer configuration over code where appropriate
- Avoid premature optimization - measure before optimizing
- Keep dependencies minimal (only add when clear value exists)

**Rationale**: Infrastructure management is inherently complex. Simple, focused solutions are easier to maintain, debug, and extend. Unnecessary complexity increases cognitive load and introduces bugs.

## Development Workflow

### Feature Development Process

1. **Specification Phase**: Create feature spec (`/speckit.specify`) with user stories, requirements, and success criteria
2. **Planning Phase**: Generate implementation plan (`/speckit.plan`) with architecture, research, and design artifacts
3. **Task Generation**: Create actionable task list (`/speckit.tasks`) organized by user story priority
4. **Constitution Check**: Verify compliance with all principles before implementation
5. **Test-First Implementation**: Follow `/speckit.implement` workflow with TDD discipline
6. **Analysis**: Run `/speckit.analyze` for cross-artifact consistency validation

### Code Review Requirements

- All PRs MUST verify compliance with constitution principles
- Tests MUST pass before merge (CI/CD enforcement)
- Breaking changes MUST be documented and versioned
- Security-sensitive changes require explicit credential handling review
- Performance-critical paths require benchmarking data

## Quality Gates

### Before Implementation Begins

- [ ] Feature specification approved with clear user stories
- [ ] Constitution Check passed (all principle violations justified)
- [ ] Tests written and failing (Red phase)
- [ ] User approval obtained for test suite

### Before Code Review

- [ ] All tests passing (Green phase)
- [ ] Code refactored for clarity (Refactor phase)
- [ ] Integration tests added for service contracts
- [ ] Structured logging implemented for new operations
- [ ] Credentials handled securely (no hardcoded secrets)
- [ ] Documentation updated (if public API/CLI changes)

### Before Merge

- [ ] Constitution compliance verified
- [ ] No new complexity without justification
- [ ] Performance impact assessed (for critical paths)
- [ ] Security review completed (for auth/credential changes)

## Governance

### Constitutional Authority

This constitution supersedes all other practices and documents. When conflicts arise, constitution principles take precedence.

### Amendment Process

Amendments require:
1. Documentation of the proposed change with rationale
2. Version bump following semantic versioning:
   - MAJOR: Backward-incompatible governance changes, principle removals/redefinitions
   - MINOR: New principles added or materially expanded guidance
   - PATCH: Clarifications, wording improvements, non-semantic refinements
3. Review of dependent templates and documentation for consistency
4. Migration plan for existing code (if applicable)
5. Update of the Sync Impact Report

### Compliance Review

- All PRs and code reviews MUST verify compliance with constitution principles
- Complexity violations MUST be documented in Complexity Tracking table (plan.md)
- Constitution Check is a mandatory gate before Phase 0 research begins
- Re-check constitution compliance after Phase 1 design completes

### Development Guidance

This constitution provides governance rules. For runtime development guidance and workflow orchestration, refer to slash commands in `.specify/templates/commands/` and workflow templates in `.specify/templates/`.

**Version**: 1.0.0 | **Ratified**: 2025-11-05 | **Last Amended**: 2025-11-05
