"""Skills registry for the Atlas Agents Platform.

The SkillsRegistry is a singleton that manages all available skills.
It handles skill registration, configuration, and provides a unified
interface for agents to access skill capabilities.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

import yaml

from infrastructure_atlas.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.tools import StructuredTool

    from .base import BaseSkill, SkillConfig

logger = get_logger(__name__)

# Module-level singleton instance
_registry_instance: SkillsRegistry | None = None
_registry_lock = RLock()


def get_skills_registry(auto_init: bool = True) -> SkillsRegistry:
    """Get the global SkillsRegistry singleton.

    Args:
        auto_init: If True, auto-discover and initialize skills on first access

    Returns:
        The global SkillsRegistry instance
    """
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = SkillsRegistry()
            if auto_init:
                # Auto-discover skills from the skills package
                _registry_instance.auto_discover_skills("infrastructure_atlas.skills")
                # Initialize all discovered skills (registers their actions)
                _registry_instance.initialize_all()
                logger.info("Skills registry auto-initialized")
        return _registry_instance


class SkillsRegistry:
    """Central registry for skill management.

    The registry:
    - Loads skill configurations from YAML
    - Manages skill instances
    - Provides lookup by name
    - Supports enable/disable

    Example usage:
        registry = get_skills_registry()
        registry.load_config("config/skills.yaml")

        jira = registry.get("jira")
        if jira:
            result = jira.execute("get_issue", {"issue_key": "ESD-123"})
    """

    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}
        self._config: dict[str, Any] = {}
        self._lock = RLock()
        self._initialized = False

    def load_config(self, config_path: str | Path | None = None) -> None:
        """Load skill configurations from YAML file.

        Args:
            config_path: Path to skills.yaml config file.
                         If None, looks in standard locations.
        """
        with self._lock:
            if config_path is None:
                # Look in standard locations
                possible_paths = [
                    Path("config/skills.yaml"),
                    Path.home() / ".atlas" / "skills.yaml",
                    Path(os.environ.get("ATLAS_CONFIG_DIR", "config")) / "skills.yaml",
                ]
                for path in possible_paths:
                    if path.exists():
                        config_path = path
                        break

            if config_path and Path(config_path).exists():
                with open(config_path) as f:
                    self._config = yaml.safe_load(f) or {}
                logger.info(f"Loaded skills config from {config_path}")
            else:
                logger.warning("No skills config found, using defaults")
                self._config = {}

    def register(self, skill: BaseSkill) -> None:
        """Register a skill instance.

        Args:
            skill: Skill instance to register
        """
        with self._lock:
            if skill.name in self._skills:
                logger.warning(f"Skill '{skill.name}' already registered, replacing")

            self._skills[skill.name] = skill

            logger.info(
                f"Registered skill: {skill.name}",
                extra={
                    "skill": skill.name,
                    "category": skill.category,
                    "actions": len(skill.get_actions()),
                },
            )

    def get(self, name: str) -> BaseSkill | None:
        """Get a skill by name.

        Args:
            name: Skill name

        Returns:
            Skill instance or None if not found
        """
        with self._lock:
            return self._skills.get(name)

    def list_skills(self) -> list[dict[str, Any]]:
        """List all registered skills.

        Returns:
            List of skill information dicts
        """
        with self._lock:
            return [
                {
                    "name": skill.name,
                    "category": skill.category,
                    "description": skill.description,
                    "enabled": skill.is_enabled,
                    "actions": [
                        {
                            "name": action.name,
                            "description": action.description,
                            "is_destructive": action.is_destructive,
                        }
                        for action in skill.get_actions()
                    ],
                }
                for skill in self._skills.values()
            ]

    def get_all_tools(self) -> list[StructuredTool]:
        """Get all actions from all enabled skills as LangChain tools.

        Returns:
            List of StructuredTool instances from all enabled skills
        """
        tools = []
        with self._lock:
            for skill in self._skills.values():
                if skill.is_enabled:
                    tools.extend(skill.get_langchain_tools())
        return tools

    def get_tools_by_names(self, names: list[str]) -> list[StructuredTool]:
        """Get tools from specific skills.

        Args:
            names: List of skill names

        Returns:
            List of StructuredTool instances from specified skills
        """
        tools = []
        with self._lock:
            for name in names:
                skill = self._skills.get(name)
                if skill and skill.is_enabled:
                    tools.extend(skill.get_langchain_tools())
        return tools

    def initialize_all(self) -> dict[str, str]:
        """Initialize all registered skills.

        Returns:
            Dict mapping skill name to initialization status
        """
        results = {}
        with self._lock:
            for name, skill in self._skills.items():
                try:
                    skill.initialize()
                    results[name] = "ok"
                    logger.info(f"Initialized skill: {name}")
                except Exception as e:
                    results[name] = f"error: {e!s}"
                    logger.error(f"Failed to initialize skill: {name}: {e!s}")

            self._initialized = True

        return results

    def cleanup_all(self) -> None:
        """Clean up all registered skills."""
        with self._lock:
            for name, skill in self._skills.items():
                try:
                    skill.cleanup()
                    logger.debug(f"Cleaned up skill: {name}")
                except Exception as e:
                    logger.error(f"Error cleaning up skill {name}: {e!s}")

            self._initialized = False

    def health_check_all(self) -> dict[str, dict[str, Any]]:
        """Run health checks on all skills.

        Returns:
            Dict mapping skill name to health check result
        """
        results = {}
        with self._lock:
            for name, skill in self._skills.items():
                try:
                    results[name] = skill.health_check()
                except Exception as e:
                    results[name] = {"status": "error", "error": str(e)}
        return results

    def load_skill_from_module(self, module_path: str, class_name: str | None = None) -> BaseSkill | None:
        """Dynamically load a skill from a Python module.

        Args:
            module_path: Full module path (e.g., "infrastructure_atlas.skills.jira.skill")
            class_name: Optional class name to load. If None, looks for skill class.

        Returns:
            Loaded skill instance or None if failed
        """
        try:
            module = importlib.import_module(module_path)

            # Find the skill class
            skill_class = None
            if class_name:
                skill_class = getattr(module, class_name, None)
            else:
                # Look for a class that inherits from BaseSkill
                from .base import BaseSkill

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseSkill)
                        and attr is not BaseSkill
                    ):
                        skill_class = attr
                        break

            if skill_class is None:
                logger.error(f"No skill class found in {module_path}")
                return None

            # Get config for this skill if available
            skill_name = getattr(skill_class, "name", module_path.split(".")[-2])
            skill_config = self._get_skill_config(skill_name)

            # Instantiate and return
            skill = skill_class(skill_config) if skill_config else skill_class()
            return skill

        except Exception as e:
            logger.error(f"Failed to load skill from {module_path}: {e!s}")
            return None

    def _get_skill_config(self, skill_name: str) -> SkillConfig | None:
        """Get configuration for a skill from loaded config.

        Args:
            skill_name: Name of the skill

        Returns:
            SkillConfig or None if not configured
        """
        from .base import SkillConfig

        skills_config = self._config.get("skills", {})
        if skill_name not in skills_config:
            return None

        config_data = skills_config[skill_name]
        return SkillConfig(
            name=skill_name,
            category=config_data.get("category", "general"),
            enabled=config_data.get("enabled", True),
            config=config_data,
        )

    def auto_discover_skills(self, package_path: str = "infrastructure_atlas.skills") -> int:
        """Auto-discover and register skills from a package.

        Looks for skill classes in submodules of the given package.

        Args:
            package_path: Package path to scan for skills

        Returns:
            Number of skills discovered and registered
        """
        count = 0
        try:
            package = importlib.import_module(package_path)
            package_dir = Path(package.__file__).parent

            for item in package_dir.iterdir():
                if item.is_dir() and (item / "__init__.py").exists():
                    module_path = f"{package_path}.{item.name}.skill"
                    skill = self.load_skill_from_module(module_path)
                    if skill:
                        self.register(skill)
                        count += 1

        except Exception as e:
            logger.error(f"Error during skill auto-discovery: {e!s}")

        logger.info(f"Auto-discovered {count} skills")
        return count
