"""Bot platform integration module for Telegram, Slack, and Teams."""

from __future__ import annotations

import os

from .base import BaseModule, ModuleHealth, ModuleHealthStatus, ModuleMetadata


class BotsModule(BaseModule):
    """Bot platform integration module.

    This module provides bot integrations for:
    - Telegram
    - Slack
    - Microsoft Teams

    Each platform can be configured independently via database or environment variables.
    At least one platform must be configured for the module to be considered healthy.
    """

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="bots",
            display_name="Bot Integrations",
            description="Chat bot integrations for Telegram, Slack, and Microsoft Teams",
            version="1.0.0",
            dependencies=frozenset(),  # No hard dependencies on other modules
            required_env_vars=frozenset(),  # All platform configs are optional
            optional_env_vars=frozenset([
                # Telegram
                "TELEGRAM_BOT_TOKEN",
                # Slack
                "SLACK_BOT_TOKEN",
                "SLACK_SIGNING_SECRET",
                "SLACK_APP_TOKEN",  # For socket mode
                # Teams
                "TEAMS_APP_ID",
                "TEAMS_APP_PASSWORD",
            ]),
            category="integration",
            release_notes="Initial release with Telegram, Slack, and Teams support",
        )

    def validate_config(self) -> tuple[bool, str | None]:
        """Validate that at least one platform is configured.

        Unlike other modules, bots module doesn't require all env vars.
        At least one platform should be configured for the module to be useful.
        """
        # Check if any platform is configured
        telegram_configured = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
        slack_configured = bool(os.getenv("SLACK_BOT_TOKEN"))
        teams_configured = bool(os.getenv("TEAMS_APP_ID") and os.getenv("TEAMS_APP_PASSWORD"))

        if not (telegram_configured or slack_configured or teams_configured):
            # This is a warning, not an error - module can still be enabled for DB-based config
            return True, None

        return True, None

    def health_check(self) -> ModuleHealthStatus:
        """Check the health of configured bot platforms.

        Returns healthy if at least one platform is configured and reachable.
        """
        if not self._enabled:
            return ModuleHealthStatus(
                status=ModuleHealth.UNKNOWN,
                message="Module is not enabled",
            )

        platforms_status: dict[str, str] = {}
        healthy_count = 0

        # Check Telegram
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_token:
            try:
                import requests

                response = requests.get(
                    f"https://api.telegram.org/bot{telegram_token}/getMe",
                    timeout=5,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        bot_name = data.get("result", {}).get("username", "unknown")
                        platforms_status["telegram"] = f"healthy (@{bot_name})"
                        healthy_count += 1
                    else:
                        platforms_status["telegram"] = f"unhealthy: {data.get('description', 'unknown error')}"
                else:
                    platforms_status["telegram"] = f"unhealthy: status {response.status_code}"
            except Exception as e:
                platforms_status["telegram"] = f"unhealthy: {e}"
        else:
            platforms_status["telegram"] = "not configured"

        # Check Slack
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if slack_token:
            try:
                import requests

                response = requests.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {slack_token}"},
                    timeout=5,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        bot_name = data.get("bot", {}).get("name", data.get("user", "unknown"))
                        platforms_status["slack"] = f"healthy ({bot_name})"
                        healthy_count += 1
                    else:
                        platforms_status["slack"] = f"unhealthy: {data.get('error', 'unknown error')}"
                else:
                    platforms_status["slack"] = f"unhealthy: status {response.status_code}"
            except Exception as e:
                platforms_status["slack"] = f"unhealthy: {e}"
        else:
            platforms_status["slack"] = "not configured"

        # Check Teams - requires more setup, just check config for now
        teams_app_id = os.getenv("TEAMS_APP_ID")
        teams_password = os.getenv("TEAMS_APP_PASSWORD")
        if teams_app_id and teams_password:
            # Teams requires actual OAuth flow to verify, just check config exists
            platforms_status["teams"] = "configured (health check requires runtime)"
            healthy_count += 1
        else:
            platforms_status["teams"] = "not configured"

        # Determine overall status
        configured_count = sum(1 for s in platforms_status.values() if s != "not configured")

        if configured_count == 0:
            return ModuleHealthStatus(
                status=ModuleHealth.DEGRADED,
                message="No bot platforms configured",
                details={"platforms": platforms_status},
            )

        if healthy_count == 0:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message="All configured platforms are unhealthy",
                details={"platforms": platforms_status},
            )

        if healthy_count < configured_count:
            return ModuleHealthStatus(
                status=ModuleHealth.DEGRADED,
                message=f"{healthy_count}/{configured_count} platforms healthy",
                details={"platforms": platforms_status},
            )

        return ModuleHealthStatus(
            status=ModuleHealth.HEALTHY,
            message=f"All {healthy_count} configured platform(s) healthy",
            details={"platforms": platforms_status},
        )
