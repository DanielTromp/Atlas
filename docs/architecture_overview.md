# Architecture Overview

This document tracks the long-term refactor of the Enreach tools project. The
codebase now follows a layered structure:

- **Domain (`src/enreach_tools/domain/`)** — business entities, value objects, and
  domain-specific rules expressed as lightweight dataclasses. These types are
  transport-agnostic and free from persistence concerns.
- **Application (`src/enreach_tools/application/`)** — orchestration of use cases
  via services that coordinate domain entities, repositories, and adapters. DTO
  helpers live here to translate between domain models and transport schemas.
- **Infrastructure (`src/enreach_tools/infrastructure/`)** — concrete
  implementations for external systems (databases, HTTP APIs, caching, logging,
  job queues). Configuration scaffolding lives alongside these adapters.
- **Interfaces (`src/enreach_tools/interfaces/`)** — delivery mechanisms such as
  FastAPI routers, Typer CLI commands, and background workers.

The existing monolithic FastAPI application and CLI commands will migrate into
this structure incrementally.
- Profile management endpoints now live in `interfaces/api/routes/profile.py`, leveraging the shared profile service and DTO helpers for consistent responses.
- Admin management endpoints (user provisioning and global keys) moved to `interfaces/api/routes/admin.py`, backed by `AdminService` and dedicated DTOs.
 The initial scaffolding does not change runtime
behaviour; future PRs will relocate logic and wire services through the new
interfaces.

## Coding Conventions

- Python 3.11, 4-space indentation, maximum line length 120 characters.
- Domain/dataclass types use `slots=True` to reduce memory footprint and clarify
  intent.
- DTOs inherit from `DomainModel` (`pydantic.BaseModel`) with `from_attributes`
  enabled for smooth conversion from ORM/domain instances.
- Logging is initialised via `enreach_tools.infrastructure.setup_logging()` to
  centralise structured logging decisions.
- Application services receive a `ServiceContext`, which will later be backed by
  dependency injection when the FastAPI app is decomposed.

## Transition Guidelines

1. New features should first express domain entities and DTOs, then introduce
   application services. Only after those pieces are in place should interface
   layers be updated.
2. When migrating existing modules, replace ad-hoc dict responses with DTOs and
   persist through repository interfaces instead of importing SQLAlchemy models
   directly.
3. Keep migrations forward-only; each schema change should provide backfill
   notes and instrumentation updates in the corresponding PR checklist.

Refer to `docs/refactor_plan.md` for the detailed milestone plan and PR
breakdown.

## Repository Adapters

- Domain repository protocols live in `src/enreach_tools/domain/repositories.py`.
- SQLAlchemy-backed implementations are introduced under
  `src/enreach_tools/infrastructure/db/repositories.py`, translating ORM models
  into domain entities via pure conversion helpers.
- Future refactors can swap these implementations (e.g., for telemetry or
  caching) without impacting the application layer.

## Application Services

- Service protocols live in `src/enreach_tools/application/services/__init__.py` and
  define the behaviour expected by the interface layer.
- Default implementations (`users.py`, `chat.py`) consume repositories and return
  domain entities, keeping transport concerns decoupled.
- Factory helpers (`create_user_service`, `create_chat_history_service`) enable
  dependency injection from FastAPI/Typer modules while supporting custom
  repository providers in tests.
- DTO helpers in `src/enreach_tools/application/dto/` convert entities to
  response-ready Pydantic models, standardising API output formatting.

## API Interfaces

- Feature routers live under `src/enreach_tools/interfaces/api/routes/`; the
  initial extraction moves `/auth/me` into the `auth` router and relies on
  application services for data access.
- Common FastAPI dependencies reside in `src/enreach_tools/interfaces/api/dependencies.py`,
  providing service factories and user/session guards.
- The legacy monolithic `api/app.py` now includes the bootstrap router so we can
  migrate additional endpoints incrementally without changing behaviour.
- CLI user administration commands call into `create_admin_service` to ensure CLI/API parity using shared DTOs.
- Suggestion endpoints now return DTO-backed responses with explicit meta blocks and total counts.
- External adapters (`infrastructure/external/`) now provide NetBox, Confluence, and backup clients backed by a shared TTL cache utility.
