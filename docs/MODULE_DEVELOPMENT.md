# Module Development Guide

This guide explains how to create, update, and manage modules in Infrastructure Atlas.

## Table of Contents

1. [Module Architecture](#module-architecture)
2. [Creating a New Module](#creating-a-new-module)
3. [Module Lifecycle](#module-lifecycle)
4. [Updating an Existing Module](#updating-an-existing-module)
5. [Deleting a Module](#deleting-a-module)
6. [Versioning & Release Notes](#versioning--release-notes)
7. [Testing Modules](#testing-modules)
8. [Best Practices](#best-practices)

## Module Architecture

Infrastructure Atlas uses a modular architecture where features can be independently enabled/disabled based on environment variables or database configuration.

### Module Components

Each module consists of:

1. **Module Definition** (`infrastructure/modules/{name}.py`) - Module metadata and configuration
2. **CLI Commands** (`interfaces/cli/{name}.py`) - Command-line interface (optional)
3. **API Routes** (`interfaces/api/routes/{name}.py`) - REST API endpoints (optional)
4. **External Client** (`infrastructure/external/{name}_client.py`) - External API client (if applicable)
5. **Application Services** (`application/services/{name}.py`) - Business logic layer (optional)

### Module Enablement

Modules can be enabled/disabled via:

1. **Database Config** (highest priority) - Persisted in `module_config` table
2. **Per-Module Environment Variable** - `ATLAS_MODULE_{NAME}_ENABLED=1|0`
3. **Global Module List** - `ATLAS_MODULES_ENABLED=netbox,vcenter,zabbix`
4. **Default** - All modules enabled by default

## Creating a New Module

### Step 1: Define the Module

Create `src/infrastructure_atlas/infrastructure/modules/{name}.py`:

```python
"""Example module for demonstration purposes."""

from __future__ import annotations

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.modules.base import BaseModule, ModuleHealthStatus, ModuleMetadata, ModuleHealth

logger = get_logger(__name__)


class ExampleModule(BaseModule):
    """Example module demonstrating best practices."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="example",
            display_name="Example Integration",
            description="Integration with Example Service for infrastructure management",
            version="1.0.0",
            author="Your Name",
            category="integration",

            # Dependencies
            dependencies=frozenset(),  # e.g., frozenset(["netbox"]) if depends on NetBox

            # Environment variables
            required_env_vars=frozenset([
                "EXAMPLE_URL",
                "EXAMPLE_API_KEY",
            ]),
            optional_env_vars=frozenset([
                "EXAMPLE_TIMEOUT",
                "EXAMPLE_VERIFY_SSL",
            ]),

            # Documentation
            changelog_url="https://github.com/yourorg/atlas/blob/main/CHANGELOG.md#example-module",
            documentation_url="https://docs.example.com/atlas-integration",
            release_notes="Initial release with core functionality",
        )

    def validate_config(self) -> tuple[bool, str | None]:
        """Validate module configuration beyond environment variables."""
        # Call parent to check required env vars
        is_valid, error_msg = super().validate_config()
        if not is_valid:
            return is_valid, error_msg

        # Add custom validation
        import os
        url = os.getenv("EXAMPLE_URL", "")
        if url and not url.startswith(("http://", "https://")):
            return False, "EXAMPLE_URL must start with http:// or https://"

        return True, None

    def on_enable(self) -> None:
        """Called when module is enabled."""
        super().on_enable()
        logger.info("Example module enabled - initializing resources")
        # Initialize clients, register handlers, etc.

    def on_disable(self) -> None:
        """Called when module is disabled."""
        logger.info("Example module disabled - cleaning up resources")
        # Clean up resources, close connections, etc.
        super().on_disable()

    def health_check(self) -> ModuleHealthStatus:
        """Check module health by testing API connectivity."""
        if not self._enabled:
            return ModuleHealthStatus(
                status=ModuleHealth.UNKNOWN,
                message="Module is not enabled"
            )

        # Validate configuration
        is_valid, error_msg = self.validate_config()
        if not is_valid:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Configuration invalid: {error_msg}"
            )

        # Test connectivity (example)
        try:
            import os
            import requests

            url = os.getenv("EXAMPLE_URL")
            api_key = os.getenv("EXAMPLE_API_KEY")

            response = requests.get(
                f"{url}/health",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5
            )

            if response.status_code == 200:
                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message="Example API is reachable",
                    details={"response_time_ms": int(response.elapsed.total_seconds() * 1000)}
                )
            else:
                return ModuleHealthStatus(
                    status=ModuleHealth.DEGRADED,
                    message=f"Example API returned status {response.status_code}"
                )
        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Cannot reach Example API: {e}"
            )
```

### Step 2: Register the Module

Update `src/infrastructure_atlas/infrastructure/modules/loader.py`:

```python
from .example import ExampleModule

def initialize_modules() -> None:
    """Initialize and register all modules."""
    registry = get_module_registry()

    # ... existing modules ...

    # Register example module
    registry.register(ExampleModule())
```

### Step 3: Create CLI Commands (Optional)

Create `src/infrastructure_atlas/interfaces/cli/example.py`:

```python
"""Example CLI commands."""

from __future__ import annotations

import typer
from rich import print as _print

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.modules import get_module_registry

logger = get_logger(__name__)

app = typer.Typer(help="Example service operations", context_settings={"help_option_names": ["-h", "--help"]})


@app.callback(invoke_without_command=True)
def check_module_enabled(ctx: typer.Context):
    """Ensure Example module is enabled before running commands."""
    if ctx.invoked_subcommand:
        registry = get_module_registry()
        try:
            registry.require_enabled("example")
        except Exception as e:
            _print(f"[red]Example module is disabled:[/red] {e}")
            raise typer.Exit(code=1)


@app.command("test")
def example_test():
    """Test Example API connectivity."""
    registry = get_module_registry()
    health = registry.health_check("example")

    if health.status.value == "healthy":
        _print(f"[green]✓[/green] Example API is healthy: {health.message}")
    else:
        _print(f"[red]✗[/red] Example API check failed: {health.message}")
        raise typer.Exit(code=1)


@app.command("sync")
def example_sync():
    """Synchronize data from Example service."""
    _print("[cyan]Synchronizing data from Example...[/cyan]")
    # Implementation here
    _print("[green]✓ Sync complete[/green]")
```

Register in `src/infrastructure_atlas/cli.py`:

```python
from .interfaces.cli import example as example_cli

def _register_cli_commands() -> None:
    # ...existing code...

    if registry.is_enabled("example"):
        app.add_typer(example_cli.app, name="example")
        logger.debug("Enabled Example CLI commands")
    else:
        logger.debug("Example module disabled, skipping CLI commands")
```

### Step 4: Create API Routes (Optional)

Create `src/infrastructure_atlas/interfaces/api/routes/example.py`:

```python
"""Example API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from infrastructure_atlas.api.app import require_permission
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.modules import get_module_registry

logger = get_logger(__name__)

router = APIRouter(prefix="/example", tags=["example"])


def require_example_enabled():
    """Dependency to ensure Example module is enabled."""
    registry = get_module_registry()
    try:
        registry.require_enabled("example")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Example module is disabled: {e}")


@router.get("/health")
def example_health(request: Request):
    """Check Example module health."""
    require_permission(request, "example.view")
    require_example_enabled()

    registry = get_module_registry()
    health = registry.health_check("example")

    return {
        "status": health.status.value,
        "message": health.message,
        "details": health.details or {}
    }


@router.get("/data")
def example_data(request: Request):
    """Get data from Example service."""
    require_permission(request, "example.view")
    require_example_enabled()

    # Implementation here
    return {"items": []}
```

Register in `src/infrastructure_atlas/interfaces/api/__init__.py`:

```python
from .routes import example

def bootstrap_api() -> APIRouter:
    # ...existing code...

    if registry.is_enabled("example"):
        router.include_router(example.router)
        logger.info("Enabled Example API routes")
    else:
        logger.info("Example module is disabled, skipping routes")
```

### Step 5: Add Environment Configuration

Update `.env.example`:

```bash
# Example Module
EXAMPLE_URL=https://example.com/api
EXAMPLE_API_KEY=your_api_key_here
EXAMPLE_TIMEOUT=30
EXAMPLE_VERIFY_SSL=true

# Enable/disable Example module (default: enabled)
# ATLAS_MODULE_EXAMPLE_ENABLED=1
```

### Step 6: Update Routes Export

Add to `src/infrastructure_atlas/interfaces/api/routes/__init__.py`:

```python
from . import example

__all__ = [..., "example"]
```

## Module Lifecycle

### Lifecycle Hooks

1. **`on_enable()`** - Called when module is enabled
   - Initialize resources (DB connections, API clients)
   - Register event handlers
   - Start background tasks
   - Should be idempotent

2. **`on_disable()`** - Called when module is disabled
   - Close connections
   - Unregister handlers
   - Stop background tasks
   - Should be idempotent

3. **`validate_config()`** - Validate module configuration
   - Check environment variables
   - Validate URLs, credentials
   - Test API connectivity (optional)

4. **`health_check()`** - Check module health
   - Return current operational status
   - Include diagnostic details
   - Should complete quickly (<5 seconds)

### Module States

- **HEALTHY** - Module is operational and all systems are functioning
- **DEGRADED** - Module is operational but with reduced functionality
- **UNHEALTHY** - Module has critical failures
- **UNKNOWN** - Module is disabled or health cannot be determined

## Updating an Existing Module

### Version Update Process

1. **Update version in metadata**:
   ```python
   version="1.1.0",  # Semantic versioning: MAJOR.MINOR.PATCH
   ```

2. **Add release notes**:
   ```python
   release_notes="Added support for custom fields, fixed timeout handling",
   ```

3. **Update changelog URL** (if using):
   ```python
   changelog_url="https://github.com/yourorg/atlas/blob/main/CHANGELOG.md#v110",
   ```

4. **Update code**:
   - Add new features
   - Fix bugs
   - Update dependencies

5. **Test thoroughly**:
   - Run unit tests
   - Test enable/disable
   - Test health checks
   - Test API endpoints

6. **Update documentation**:
   - Update docstrings
   - Update `.env.example` if new env vars added
   - Update CLAUDE.md if architecture changed

### Migration Handling

If your update requires data migration:

```python
def on_enable(self) -> None:
    """Enable hook with migration support."""
    super().on_enable()

    # Check if migration is needed
    current_version = self._get_stored_version()
    if current_version != self.metadata.version:
        self._run_migration(current_version, self.metadata.version)
        self._store_version(self.metadata.version)
```

## Deleting a Module

### Step 1: Deprecate First

Before deleting, deprecate the module for at least one major version:

```python
@property
def metadata(self) -> ModuleMetadata:
    return ModuleMetadata(
        name="old_module",
        display_name="Old Module (DEPRECATED)",
        description="This module is deprecated and will be removed in v2.0",
        version="0.9.0",
        release_notes="DEPRECATED: Use new_module instead",
        # ...
    )
```

### Step 2: Disable by Default

Update loader to not register the module by default:

```python
# Only register if explicitly enabled
if os.getenv("ATLAS_MODULE_OLD_MODULE_ENABLED") == "1":
    registry.register(OldModule())
```

### Step 3: Remove After Deprecation Period

1. Remove module files:
   ```bash
   rm src/infrastructure_atlas/infrastructure/modules/old_module.py
   rm src/infrastructure_atlas/interfaces/cli/old_module.py
   rm src/infrastructure_atlas/interfaces/api/routes/old_module.py
   rm src/infrastructure_atlas/infrastructure/external/old_module_client.py
   ```

2. Remove from loader:
   ```python
   # Delete: registry.register(OldModule())
   ```

3. Remove from CLI registration:
   ```python
   # Delete: app.add_typer(old_module_cli.app, name="old_module")
   ```

4. Remove from API registration:
   ```python
   # Delete: router.include_router(old_module.router)
   ```

5. Update documentation to remove references

## Versioning & Release Notes

### Semantic Versioning

Follow [SemVer](https://semver.org/):

- **MAJOR** (1.0.0) - Breaking changes, incompatible API changes
- **MINOR** (0.1.0) - New features, backward-compatible
- **PATCH** (0.0.1) - Bug fixes, backward-compatible

### Release Notes Guidelines

Keep release notes concise and user-focused:

```python
release_notes=(
    "v1.2.0: Added webhook support, improved error handling. "
    "v1.1.0: Added bulk import. "
    "v1.0.0: Initial release"
)
```

### Changelog Structure

Maintain `CHANGELOG.md` at repository root:

```markdown
# Changelog

## [1.2.0] - 2025-01-21

### Example Module
- Added webhook support for real-time updates
- Improved error handling with retry logic
- Fixed timeout issue with large datasets

### NetBox Module
- Updated to support NetBox 4.0 API
- Added custom field synchronization

## [1.1.0] - 2025-01-15

### Example Module
- Added bulk import functionality
- Performance improvements for large datasets
```

## Testing Modules

### Unit Tests

Create `tests/infrastructure/modules/test_example.py`:

```python
"""Tests for Example module."""

import os
from unittest.mock import Mock, patch

import pytest

from infrastructure_atlas.infrastructure.modules.example import ExampleModule
from infrastructure_atlas.infrastructure.modules.base import ModuleHealth


def test_example_metadata():
    """Test module metadata."""
    module = ExampleModule()
    meta = module.metadata

    assert meta.name == "example"
    assert meta.version.startswith("1.")
    assert "EXAMPLE_URL" in meta.required_env_vars
    assert "EXAMPLE_API_KEY" in meta.required_env_vars


def test_example_validate_config_missing_env():
    """Test validation fails when required env vars missing."""
    module = ExampleModule()

    with patch.dict(os.environ, {}, clear=True):
        is_valid, error_msg = module.validate_config()
        assert not is_valid
        assert "EXAMPLE_URL" in error_msg


def test_example_validate_config_invalid_url():
    """Test validation fails for invalid URL."""
    module = ExampleModule()

    with patch.dict(os.environ, {
        "EXAMPLE_URL": "not-a-url",
        "EXAMPLE_API_KEY": "test"
    }):
        is_valid, error_msg = module.validate_config()
        assert not is_valid
        assert "http" in error_msg


def test_example_health_check_disabled():
    """Test health check when module is disabled."""
    module = ExampleModule()
    health = module.health_check()

    assert health.status == ModuleHealth.UNKNOWN
    assert "not enabled" in health.message


@patch('requests.get')
def test_example_health_check_healthy(mock_get):
    """Test health check when API is reachable."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.elapsed.total_seconds.return_value = 0.05
    mock_get.return_value = mock_response

    module = ExampleModule()
    module.on_enable()

    with patch.dict(os.environ, {
        "EXAMPLE_URL": "https://example.com",
        "EXAMPLE_API_KEY": "test"
    }):
        health = module.health_check()

        assert health.status == ModuleHealth.HEALTHY
        assert health.details["response_time_ms"] == 50
```

### Integration Tests

```python
"""Integration tests for Example module."""

import pytest

from infrastructure_atlas.infrastructure.modules import get_module_registry


@pytest.mark.integration
def test_example_enable_disable():
    """Test module enable/disable cycle."""
    registry = get_module_registry()

    # Module should be registered
    module = registry.get_module("example")
    assert module is not None

    # Test enable
    registry.enable("example", persist=False)
    assert registry.is_enabled("example")

    # Test disable
    registry.disable("example", persist=False)
    assert not registry.is_enabled("example")
```

### Manual Testing

Test module scenarios:

```bash
# Test with module disabled
ATLAS_MODULE_EXAMPLE_ENABLED=0 uv run atlas example test
# Should error: "Example module is disabled"

# Test with module enabled
ATLAS_MODULE_EXAMPLE_ENABLED=1 uv run atlas example test
# Should succeed if credentials configured

# Test health endpoint
curl http://localhost:8000/example/health \
  -H "Authorization: Bearer $ATLAS_API_TOKEN"
```

## Best Practices

### 1. Module Independence
- Modules should be self-contained
- Minimize dependencies on other modules
- Use dependency injection for shared services

### 2. Configuration
- All configuration via environment variables
- Provide sensible defaults
- Validate configuration on startup
- Use descriptive error messages

### 3. Error Handling
- Use specific exception types
- Log errors with context
- Provide actionable error messages
- Fail gracefully when disabled

### 4. Performance
- Health checks should complete quickly (<5s)
- Use caching for expensive operations
- Implement rate limiting for external APIs
- Monitor resource usage

### 5. Security
- Never log credentials
- Use secret store for sensitive data
- Validate all external input
- Implement proper authentication/authorization

### 6. Logging
- Log module lifecycle events (enable/disable)
- Log configuration validation failures
- Use appropriate log levels
- Include contextual information

### 7. Documentation
- Document all environment variables in `.env.example`
- Keep docstrings up to date
- Update CLAUDE.md for architecture changes
- Maintain CHANGELOG.md

### 8. Testing
- Write unit tests for all public methods
- Test enable/disable cycles
- Test health checks
- Test with module disabled
- Integration tests for critical paths

### 9. Backward Compatibility
- Follow semantic versioning strictly
- Deprecate before removing features
- Provide migration paths
- Document breaking changes

### 10. Monitoring
- Implement comprehensive health checks
- Return meaningful diagnostic details
- Monitor external API availability
- Track usage metrics

## Example Module Checklist

When creating a new module, ensure:

- [ ] Module class extends `BaseModule`
- [ ] Metadata includes all required fields
- [ ] Version follows semantic versioning
- [ ] Release notes are clear and concise
- [ ] Environment variables documented in `.env.example`
- [ ] `validate_config()` checks required variables
- [ ] `on_enable()` and `on_disable()` are idempotent
- [ ] `health_check()` completes quickly
- [ ] Module registered in `loader.py`
- [ ] CLI commands (if any) have module guard
- [ ] API routes (if any) check module enabled
- [ ] CLI/API registered conditionally in cli.py/api/__init__.py
- [ ] Unit tests cover core functionality
- [ ] Integration tests verify enable/disable
- [ ] Documentation updated in CLAUDE.md
- [ ] Manual testing performed

## Reference Examples

See these existing modules for reference:

- **NetBox** (`infrastructure/modules/netbox.py`) - Full-featured integration
- **vCenter** (`infrastructure/modules/vcenter.py`) - External API client
- **Zabbix** (`infrastructure/modules/zabbix.py`) - Health monitoring
- **Jira** (`infrastructure/modules/jira.py`) - Simple configuration

## Getting Help

- Review existing module implementations
- Check CLAUDE.md for architectural guidance
- Run `uv run atlas --help` to see registered commands
- Use `uv run pytest tests/infrastructure/modules/` to run module tests
- Check logs in `logs/` directory for diagnostic information
