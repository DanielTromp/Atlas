"""Admin management endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from infrastructure_atlas.application.dto.admin import (
    admin_global_key_to_dto,
    admin_global_keys_to_dto,
    admin_role_to_dto,
    admin_roles_to_dto,
    admin_user_to_dto,
    admin_users_to_dto,
)
from infrastructure_atlas.application.role_defaults import ROLE_CAPABILITIES
from infrastructure_atlas.application.services.admin import AdminService
from infrastructure_atlas.interfaces.api.dependencies import AdminUserDep, get_admin_service
from infrastructure_atlas.interfaces.api.schemas import (
    AdminCreateUser,
    AdminRoleUpdate,
    AdminSetPassword,
    AdminUpdateUser,
    APIKeyPayload,
)

router = APIRouter(prefix="/admin", tags=["admin"])

AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]
AdminCreateUserBody = Annotated[AdminCreateUser, Body(...)]
AdminUpdateUserBody = Annotated[AdminUpdateUser, Body(...)]
AdminSetPasswordBody = Annotated[AdminSetPassword, Body(...)]
AdminRoleUpdateBody = Annotated[AdminRoleUpdate, Body(...)]
APIKeyPayloadBody = Annotated[APIKeyPayload, Body(...)]


@router.get("/users")
def list_users(
    admin: AdminUserDep,
    service: AdminServiceDep,
    include_inactive: bool = False,
):
    entities = service.list_users(include_inactive=include_inactive)
    return [dto.dict_clean() for dto in admin_users_to_dto(entities)]


@router.post("/users")
def create_user(
    admin: AdminUserDep,
    payload: AdminCreateUserBody,
    service: AdminServiceDep,
):
    username = payload.username.strip().lower()
    password = payload.password.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    try:
        service.ensure_username_available(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        entity = service.create_user(
            username=username,
            password=password,
            display_name=payload.display_name or None,
            email=payload.email or None,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return admin_user_to_dto(entity).dict_clean()


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    admin: AdminUserDep,
    payload: AdminUpdateUserBody,
    service: AdminServiceDep,
):
    target = service.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.role and target.id == admin.id and payload.role != admin.role:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    if payload.is_active is False and target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate yourself")

    if payload.display_name is not None:
        target.display_name = payload.display_name or None
    if payload.email is not None:
        email = payload.email or None
        if email and "@" not in email:
            raise HTTPException(status_code=400, detail="Invalid email address")
        target.email = email
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active

    try:
        updated = service.save_user(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return admin_user_to_dto(updated).dict_clean()


@router.post("/users/{user_id}/password")
def set_user_password(
    user_id: str,
    admin: AdminUserDep,
    payload: AdminSetPasswordBody,
    service: AdminServiceDep,
):
    target = service.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    new_password = payload.new_password.strip()
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    service.set_password(target, new_password)
    return {"status": "ok"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    admin: AdminUserDep,
    service: AdminServiceDep,
):
    target = service.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete yourself")
    service.delete_user(target)
    return {"status": "deleted"}


@router.get("/global-api-keys")
def list_global_api_keys(
    admin: AdminUserDep,
    service: AdminServiceDep,
):
    entities = service.list_global_api_keys()
    return [dto.dict_clean() for dto in admin_global_keys_to_dto(entities)]


@router.put("/global-api-keys/{provider}")
def upsert_global_api_key(
    provider: str,
    admin: AdminUserDep,
    payload: APIKeyPayloadBody,
    service: AdminServiceDep,
):
    provider_norm = (provider or "").strip().lower()
    if not provider_norm:
        raise HTTPException(status_code=400, detail="Provider is required")
    secret = payload.secret.strip()
    if not secret:
        raise HTTPException(status_code=400, detail="Secret is required")
    entity = service.upsert_global_api_key(provider_norm, secret, payload.label or None)
    return admin_global_key_to_dto(entity).dict_clean()


@router.delete("/global-api-keys/{provider}")
def delete_global_api_key(
    provider: str,
    admin: AdminUserDep,
    service: AdminServiceDep,
):
    provider_norm = (provider or "").strip().lower()
    if not service.delete_global_api_key(provider_norm):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "deleted"}


@router.get("/roles")
def list_roles(
    admin: AdminUserDep,
    service: AdminServiceDep,
):
    entities = service.list_role_permissions()
    roles = [dto.dict_clean() for dto in admin_roles_to_dto(entities)]
    capabilities = [dict(cap) for cap in ROLE_CAPABILITIES]
    return {"roles": roles, "capabilities": capabilities}


@router.patch("/roles/{role}")
def update_role(
    role: str,
    admin: AdminUserDep,
    payload: AdminRoleUpdateBody,
    service: AdminServiceDep,
):
    try:
        entity = service.update_role_permission(
            role=role,
            label=payload.label,
            description=payload.description,
            permissions=payload.permissions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return admin_role_to_dto(entity).dict_clean()


# ============================================================================
# Module Management Endpoints
# ============================================================================


@router.get("/modules")
def list_modules(admin: AdminUserDep):
    """List all registered modules with their metadata and enabled status."""
    from infrastructure_atlas.infrastructure.modules import get_module_registry

    registry = get_module_registry()
    modules = []

    for metadata in registry.list_modules():
        try:
            is_enabled = registry.is_enabled(metadata.name)
            health = registry.health_check(metadata.name) if is_enabled else None

            modules.append({
                "name": metadata.name,
                "display_name": metadata.display_name,
                "description": metadata.description,
                "version": metadata.version,
                "category": metadata.category,
                "dependencies": list(metadata.dependencies),
                "required_env_vars": list(metadata.required_env_vars),
                "optional_env_vars": list(metadata.optional_env_vars),
                "enabled": is_enabled,
                "health": {
                    "status": health.status.value,
                    "message": health.message,
                    "details": health.details,
                } if health else None,
            })
        except Exception as e:
            modules.append({
                "name": metadata.name,
                "display_name": metadata.display_name,
                "description": metadata.description,
                "enabled": False,
                "error": str(e),
            })

    return {"modules": modules}


@router.get("/modules/{module_name}")
def get_module(module_name: str, admin: AdminUserDep):
    """Get detailed information about a specific module."""
    from infrastructure_atlas.infrastructure.modules import (
        ModuleNotFoundError,
        get_module_registry,
    )

    registry = get_module_registry()

    try:
        module = registry.get_module(module_name)
        metadata = module.metadata
        is_enabled = registry.is_enabled(module_name)
        health = registry.health_check(module_name) if is_enabled else None

        # Find dependent modules
        dependent_modules = []
        for m in registry.list_modules():
            if module_name in m.dependencies and registry.is_enabled(m.name):
                dependent_modules.append(m.name)

        return {
            "name": metadata.name,
            "display_name": metadata.display_name,
            "description": metadata.description,
            "version": metadata.version,
            "category": metadata.category,
            "dependencies": list(metadata.dependencies),
            "dependent_modules": dependent_modules,
            "required_env_vars": list(metadata.required_env_vars),
            "optional_env_vars": list(metadata.optional_env_vars),
            "enabled": is_enabled,
            "health": {
                "status": health.status.value,
                "message": health.message,
                "details": health.details,
            } if health else None,
        }
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/modules/{module_name}/enable")
def enable_module(module_name: str, admin: AdminUserDep):
    """Enable a module."""
    from infrastructure_atlas.infrastructure.modules import (
        ModuleDependencyError,
        ModuleNotFoundError,
        get_module_registry,
    )

    registry = get_module_registry()

    try:
        registry.enable(module_name, persist=True)
        return {"status": "enabled", "module": module_name}
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModuleDependencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to enable module: {exc}") from exc


@router.post("/modules/{module_name}/disable")
def disable_module(module_name: str, admin: AdminUserDep, force: bool = False):
    """Disable a module.

    Args:
        module_name: Name of the module to disable.
        force: If True, disable even if other modules depend on it.
    """
    from infrastructure_atlas.infrastructure.modules import (
        ModuleDependencyError,
        ModuleNotFoundError,
        get_module_registry,
    )

    registry = get_module_registry()

    try:
        registry.disable(module_name, persist=True, force=force)
        return {"status": "disabled", "module": module_name}
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModuleDependencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to disable module: {exc}") from exc


@router.get("/modules/health/all")
def health_check_all_modules(admin: AdminUserDep):
    """Check the health of all enabled modules."""
    from infrastructure_atlas.infrastructure.modules import get_module_registry

    registry = get_module_registry()
    health_results = registry.health_check_all()

    return {
        "results": {
            name: {
                "status": status.status.value,
                "message": status.message,
                "details": status.details,
            }
            for name, status in health_results.items()
        }
    }


# ============================================================================
# Playground Usage Statistics (Admin)
# ============================================================================


@router.get("/playground/usage/stats")
def get_overall_usage_stats(
    admin: AdminUserDep,
    days: int = 30,
):
    """Get overall playground usage statistics for all users."""
    from infrastructure_atlas.agents.usage import create_usage_service

    usage_service = create_usage_service()
    return usage_service.get_overall_stats(days=days)


@router.get("/playground/usage/users")
def get_all_users_usage(
    admin: AdminUserDep,
    days: int = 30,
):
    """Get usage statistics broken down by user."""
    from infrastructure_atlas.agents.usage import create_usage_service

    usage_service = create_usage_service()
    return usage_service.get_all_users_stats(days=days)


@router.get("/playground/usage/recent")
def get_all_recent_usage(
    admin: AdminUserDep,
    limit: int = 50,
):
    """Get recent usage records for all users."""
    from infrastructure_atlas.agents.usage import create_usage_service

    usage_service = create_usage_service()
    return usage_service.get_recent_usage(user_id=None, limit=limit)
