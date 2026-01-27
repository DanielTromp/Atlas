"""API endpoints for Foreman configuration and inventory."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from infrastructure_atlas.application.dto.foreman import foreman_config_to_dto, foreman_configs_to_dto
from infrastructure_atlas.application.services import create_foreman_service
from infrastructure_atlas.application.services.foreman import ForemanServiceProtocol
from infrastructure_atlas.infrastructure.external import ForemanAuthError, ForemanClientError
from infrastructure_atlas.infrastructure.security.secret_store import SecretStoreUnavailable
from infrastructure_atlas.interfaces.api.dependencies import AdminUserDep, CurrentUserDep
from infrastructure_atlas.interfaces.api.schemas import ForemanConfigCreate, ForemanConfigUpdate

router = APIRouter(prefix="/foreman", tags=["foreman"])


def get_foreman_service() -> ForemanServiceProtocol:
    """Return the Foreman service using the configured backend."""
    return create_foreman_service()


ForemanServiceDep = Annotated[ForemanServiceProtocol, Depends(get_foreman_service)]
CreateBody = Annotated[ForemanConfigCreate, Body(...)]
UpdateBody = Annotated[ForemanConfigUpdate, Body(...)]


@router.get("/configs")
def list_configs(admin: AdminUserDep, service: ForemanServiceDep):
    """List all Foreman configurations."""
    configs = service.list_configs()
    return [dto.dict_clean() for dto in foreman_configs_to_dto(configs)]


@router.post("/configs")
def create_config(admin: AdminUserDep, payload: CreateBody, service: ForemanServiceDep):
    """Create a new Foreman configuration."""
    try:
        entity = service.create_config(
            name=payload.name,
            base_url=payload.base_url,
            username=payload.username,
            token=payload.token,
            verify_ssl=payload.verify_ssl,
        )
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return foreman_config_to_dto(entity).dict_clean()


@router.put("/configs/{config_id}")
def update_config(admin: AdminUserDep, config_id: str, payload: UpdateBody, service: ForemanServiceDep):
    """Update an existing Foreman configuration."""
    try:
        entity = service.update_config(
            config_id,
            name=payload.name,
            base_url=payload.base_url,
            username=payload.username,
            token=payload.token,
            verify_ssl=payload.verify_ssl,
        )
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if message.lower().endswith("not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return foreman_config_to_dto(entity).dict_clean()


@router.delete("/configs/{config_id}")
def delete_config(admin: AdminUserDep, config_id: str, service: ForemanServiceDep):
    """Delete a Foreman configuration."""
    try:
        removed = service.delete_config(config_id)
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Foreman configuration not found")
    return {"status": "deleted"}


def _meta_to_payload(meta: dict[str, object]) -> dict[str, object]:
    """Convert metadata to API payload format."""
    generated_at = meta.get("generated_at")
    if isinstance(generated_at, datetime):
        generated_at_str = generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    else:
        generated_at_str = None
    return {
        "generated_at": generated_at_str,
        "host_count": meta.get("host_count"),
        "source": meta.get("source"),
    }


@router.get("/instances")
def list_instances(user: CurrentUserDep, service: ForemanServiceDep):
    """List all Foreman instances for the web UI."""
    entries = service.list_configs_with_status()
    response: list[dict[str, object]] = []
    for config, meta in entries:
        meta_payload = _meta_to_payload(meta or {}) if meta else {"generated_at": None, "host_count": None, "source": None}
        response.append(
            {
                "id": config.id,
                "name": config.name,
                "base_url": config.base_url,
                "username": config.username,
                "verify_ssl": config.verify_ssl,
                "has_credentials": bool(config.token_secret),
                "last_refresh": meta_payload.get("generated_at"),
                "host_count": meta_payload.get("host_count"),
            }
        )
    return response


@router.get("/configs/{config_id}/test")
def test_connection(admin: AdminUserDep, config_id: str, service: ForemanServiceDep):
    """Test connectivity to a Foreman instance."""
    try:
        result = service.test_connection(config_id)
        return result
    except ValueError as exc:
        message = str(exc)
        if message.lower().endswith("not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/hosts")
def list_hosts(
    user: CurrentUserDep,
    request: Request,
    service: ForemanServiceDep,
    config_id: str | None = None,
    search: str | None = None,
    refresh: bool = Query(False, description="Force refresh from Foreman API"),
):
    """List hosts from Foreman (uses cache for web UI, direct API for CLI)."""
    permissions = getattr(request.state, "permissions", frozenset())
    if "foreman.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="Foreman access requires additional permissions")

    # Get config
    if config_id:
        config = service.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="Foreman configuration not found")
    else:
        configs = service.list_configs()
        if not configs:
            raise HTTPException(status_code=404, detail="No Foreman configurations found")
        config = configs[0]

    try:
        # Use cache for web UI, direct API calls for CLI
        # Check if this is a web UI request (has referer or accepts JSON)
        is_web_ui = request.headers.get("referer") or request.headers.get("accept", "").startswith("application/json")
        
        if is_web_ui and not refresh:
            # Use cache for web UI
            _, hosts, meta = service.get_inventory(config.id, refresh=False)
            # Apply search filter if provided
            if search:
                search_lower = search.lower()
                hosts = [
                    h for h in hosts
                    if search_lower in str(h.get("name", "")).lower()
                    or search_lower in str(h.get("operatingsystem_name", "")).lower()
                    or search_lower in str(h.get("environment_name", "")).lower()
                ]
            return {
                "results": hosts,
                "total": len(hosts),
                "config_id": config.id,
                "meta": _meta_to_payload(meta or {}),
            }
        else:
            # Direct API call (CLI or refresh)
            client = service.get_client(config.id)
            with client:
                hosts = client.list_hosts(search=search, force_refresh=refresh)
            return {"results": hosts, "total": len(hosts), "config_id": config.id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ForemanAuthError, ForemanClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Foreman API error: {exc}") from exc
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{config_id}/refresh")
def refresh_hosts(
    config_id: str,
    request: Request,
    user: CurrentUserDep,
    service: ForemanServiceDep,
):
    """Refresh Foreman hosts cache."""
    permissions = getattr(request.state, "permissions", frozenset())
    if "foreman.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="Foreman access requires additional permissions")

    try:
        config, hosts, meta = service.refresh_inventory(config_id)
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if message.lower().endswith("not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    except ForemanAuthError as exc:
        raise HTTPException(status_code=401, detail=f"Failed to authenticate with Foreman: {exc}") from exc
    except ForemanClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "config_id": config.id,
        "hosts": hosts,
        "meta": _meta_to_payload(meta or {}),
    }


@router.get("/hosts/{host_id}")
def get_host_detail(
    host_id: str,
    request: Request,
    user: CurrentUserDep,
    service: ForemanServiceDep,
    config_id: str | None = None,
):
    """Get detailed host information including Puppet configuration."""
    permissions = getattr(request.state, "permissions", frozenset())
    if "foreman.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="Foreman access requires additional permissions")

    # Get config
    if config_id:
        config = service.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="Foreman configuration not found")
    else:
        configs = service.list_configs()
        if not configs:
            raise HTTPException(status_code=404, detail="No Foreman configurations found")
        config = configs[0]

    try:
        client = service.get_client(config.id)
        with client:
            host_detail = client.get_host_detail(host_id)
            if not host_detail:
                raise HTTPException(status_code=404, detail=f"Host {host_id} not found")
            return host_detail
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ForemanAuthError, ForemanClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Foreman API error: {exc}") from exc


@router.get("/hosts/{host_id}/puppet-classes")
def get_host_puppet_classes(
    host_id: str,
    request: Request,
    user: CurrentUserDep,
    service: ForemanServiceDep,
    config_id: str | None = None,
):
    """Get Puppet classes assigned to a host."""
    permissions = getattr(request.state, "permissions", frozenset())
    if "foreman.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="Foreman access requires additional permissions")

    # Get config
    if config_id:
        config = service.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="Foreman configuration not found")
    else:
        configs = service.list_configs()
        if not configs:
            raise HTTPException(status_code=404, detail="No Foreman configurations found")
        config = configs[0]

    try:
        client = service.get_client(config.id)
        with client:
            classes = client.get_host_puppet_classes(host_id)
            return {"results": classes, "total": len(classes)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ForemanAuthError, ForemanClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Foreman API error: {exc}") from exc


@router.get("/hosts/{host_id}/puppet-parameters")
def get_host_puppet_parameters(
    host_id: str,
    request: Request,
    user: CurrentUserDep,
    service: ForemanServiceDep,
    config_id: str | None = None,
):
    """Get Puppet parameters (user configs) for a host."""
    permissions = getattr(request.state, "permissions", frozenset())
    if "foreman.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="Foreman access requires additional permissions")

    # Get config
    if config_id:
        config = service.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="Foreman configuration not found")
    else:
        configs = service.list_configs()
        if not configs:
            raise HTTPException(status_code=404, detail="No Foreman configurations found")
        config = configs[0]

    try:
        client = service.get_client(config.id)
        with client:
            parameters = client.get_host_puppet_parameters(host_id)
            return {"results": parameters, "total": len(parameters)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ForemanAuthError, ForemanClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Foreman API error: {exc}") from exc


@router.get("/hosts/{host_id}/puppet-facts")
def get_host_puppet_facts(
    host_id: str,
    request: Request,
    user: CurrentUserDep,
    service: ForemanServiceDep,
    config_id: str | None = None,
    search: str | None = None,
):
    """Get Puppet facts for a host."""
    permissions = getattr(request.state, "permissions", frozenset())
    if "foreman.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="Foreman access requires additional permissions")

    # Get config
    if config_id:
        config = service.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="Foreman configuration not found")
    else:
        configs = service.list_configs()
        if not configs:
            raise HTTPException(status_code=404, detail="No Foreman configurations found")
        config = configs[0]

    try:
        client = service.get_client(config.id)
        with client:
            facts = client.get_host_puppet_facts(host_id)

            # Filter by search if provided
            if search:
                search_lower = search.lower()
                facts = {k: v for k, v in facts.items() if search_lower in k.lower()}

            return {"results": facts, "total": len(facts)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ForemanAuthError, ForemanClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Foreman API error: {exc}") from exc


@router.get("/hosts/{host_id}/puppet-status")
def get_host_puppet_status(
    host_id: str,
    request: Request,
    user: CurrentUserDep,
    service: ForemanServiceDep,
    config_id: str | None = None,
):
    """Get Puppet status and proxy information for a host."""
    permissions = getattr(request.state, "permissions", frozenset())
    if "foreman.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="Foreman access requires additional permissions")

    # Get config
    if config_id:
        config = service.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="Foreman configuration not found")
    else:
        configs = service.list_configs()
        if not configs:
            raise HTTPException(status_code=404, detail="No Foreman configurations found")
        config = configs[0]

    try:
        client = service.get_client(config.id)
        with client:
            status = client.get_host_puppet_status(host_id)
            if not status:
                raise HTTPException(status_code=404, detail=f"Host {host_id} not found")
            return status
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ForemanAuthError, ForemanClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Foreman API error: {exc}") from exc
