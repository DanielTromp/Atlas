"""Jira skill for ticket management operations.

This skill provides agents with capabilities to interact with Jira:
- Get and search issues
- Update issues and add comments
- Transition and assign tickets
- Find similar issues using text search
"""

from __future__ import annotations

import os
from typing import Any

import requests

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills.base import BaseSkill, SkillConfig

logger = get_logger(__name__)


class JiraSkill(BaseSkill):
    """Skill for Jira ticket management.

    Actions:
        - get_issue: Get issue details by key
        - search_issues: Search using JQL
        - update_issue: Update issue fields
        - add_comment: Add a comment to an issue
        - transition_issue: Change issue status
        - assign_issue: Assign issue to a user
        - get_similar_issues: Find similar issues by text

    Configuration (via environment or config):
        - ATLASSIAN_BASE_URL: Jira instance URL
        - ATLASSIAN_EMAIL: API authentication email
        - ATLASSIAN_API_TOKEN: API authentication token
    """

    name = "jira"
    category = "ticketing"
    description = "Jira ticket management operations"

    def __init__(self, config: SkillConfig | None = None):
        super().__init__(config)

        # Get configuration from environment or config
        self._base_url = self._get_config("base_url") or os.getenv("ATLASSIAN_BASE_URL", "").strip()
        self._email = self._get_config("email") or os.getenv("ATLASSIAN_EMAIL", "").strip()
        self._api_token = self._get_config("api_token") or os.getenv("ATLASSIAN_API_TOKEN", "").strip()

        self._session: requests.Session | None = None
        self._api_root: str | None = None

    def _get_config(self, key: str) -> str | None:
        """Get a configuration value."""
        if self.config and self.config.config:
            return self.config.config.get(key)
        return None

    def initialize(self) -> None:
        """Initialize the Jira client and register actions."""
        if not all([self._base_url, self._email, self._api_token]):
            logger.warning("Jira skill not configured - missing credentials")
            self.config.enabled = False
            return

        # Set up session
        self._api_root = f"{self._base_url.rstrip('/')}/rest/api/3"
        self._session = requests.Session()
        self._session.auth = (self._email, self._api_token)
        self._session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

        # Register actions
        self.register_action(
            name="get_issue",
            func=self.get_issue,
            description="Get Jira issue details by key (e.g., ESD-1234)",
            input_schema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key (e.g., ESD-1234)"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of fields to return",
                    },
                },
                "required": ["issue_key"],
            },
        )

        self.register_action(
            name="search_issues",
            func=self.search_issues,
            description="Search Jira issues using JQL query",
            input_schema={
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "JQL query string"},
                    "max_results": {"type": "integer", "description": "Maximum results to return (default 20)"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to include in results",
                    },
                },
                "required": ["jql"],
            },
        )

        self.register_action(
            name="update_issue",
            func=self.update_issue,
            description="Update fields on a Jira issue",
            is_destructive=True,
            input_schema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key"},
                    "fields": {"type": "object", "description": "Fields to update (field_name: value)"},
                },
                "required": ["issue_key", "fields"],
            },
        )

        self.register_action(
            name="add_comment",
            func=self.add_comment,
            description="Add a comment to a Jira issue",
            is_destructive=True,
            input_schema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key"},
                    "body": {"type": "string", "description": "Comment body text"},
                },
                "required": ["issue_key", "body"],
            },
        )

        self.register_action(
            name="transition_issue",
            func=self.transition_issue,
            description="Change the status of a Jira issue",
            is_destructive=True,
            requires_confirmation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key"},
                    "transition_name": {"type": "string", "description": "Target status name (e.g., 'In Progress')"},
                },
                "required": ["issue_key", "transition_name"],
            },
        )

        self.register_action(
            name="assign_issue",
            func=self.assign_issue,
            description="Assign a Jira issue to a user",
            is_destructive=True,
            input_schema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Jira issue key"},
                    "assignee": {"type": "string", "description": "Username or account ID to assign"},
                },
                "required": ["issue_key", "assignee"],
            },
        )

        self.register_action(
            name="get_similar_issues",
            func=self.get_similar_issues,
            description="Find similar issues based on text similarity",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to search for similar issues"},
                    "project": {"type": "string", "description": "Optional project key to limit search"},
                    "max_results": {"type": "integer", "description": "Maximum results (default 10)"},
                },
                "required": ["text"],
            },
        )

        self._initialized = True
        logger.info("Jira skill initialized successfully")

    def cleanup(self) -> None:
        """Clean up Jira session."""
        if self._session:
            self._session.close()
            self._session = None

    def health_check(self) -> dict[str, Any]:
        """Check Jira connectivity."""
        if not self._session:
            return {"status": "not_initialized", "skill": self.name}

        try:
            response = self._session.get(f"{self._api_root}/myself", timeout=10)
            if response.ok:
                user = response.json()
                return {
                    "status": "healthy",
                    "skill": self.name,
                    "user": user.get("displayName"),
                    "server": self._base_url,
                }
            return {"status": "error", "skill": self.name, "code": response.status_code}
        except Exception as e:
            return {"status": "error", "skill": self.name, "error": str(e)}

    # =========================================================================
    # Action implementations
    # =========================================================================

    def get_issue(self, issue_key: str, fields: list[str] | None = None) -> dict[str, Any]:
        """Get Jira issue details.

        Args:
            issue_key: Issue key like ESD-1234
            fields: Optional list of fields to return

        Returns:
            Issue data dict
        """
        if not self._session:
            raise RuntimeError("Jira skill not initialized")

        url = f"{self._api_root}/issue/{issue_key}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)

        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()

        return self._parse_issue_response(response.json())

    def search_issues(
        self,
        jql: str,
        max_results: int = 20,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search issues using JQL.

        Args:
            jql: JQL query string
            max_results: Maximum number of results
            fields: Fields to include

        Returns:
            List of issue dicts
        """
        if not self._session:
            raise RuntimeError("Jira skill not initialized")

        url = f"{self._api_root}/search"
        payload = {
            "jql": jql,
            "maxResults": min(max_results, 100),
        }
        if fields:
            payload["fields"] = fields

        response = self._session.post(url, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        return [self._parse_issue_response(issue) for issue in data.get("issues", [])]

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Update issue fields.

        Args:
            issue_key: Issue key
            fields: Fields to update

        Returns:
            Result dict with success status
        """
        if not self._session:
            raise RuntimeError("Jira skill not initialized")

        url = f"{self._api_root}/issue/{issue_key}"
        payload = {"fields": fields}

        response = self._session.put(url, json=payload, timeout=30)
        response.raise_for_status()

        logger.info(f"Updated issue {issue_key}", extra={"fields": list(fields.keys())})
        return {"success": True, "issue_key": issue_key, "updated_fields": list(fields.keys())}

    def add_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        """Add a comment to an issue.

        Args:
            issue_key: Issue key
            body: Comment body text

        Returns:
            Created comment details
        """
        if not self._session:
            raise RuntimeError("Jira skill not initialized")

        url = f"{self._api_root}/issue/{issue_key}/comment"

        # Jira Cloud uses ADF format for comments
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": body}],
                    }
                ],
            }
        }

        response = self._session.post(url, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        logger.info(f"Added comment to {issue_key}", extra={"comment_id": data.get("id")})

        return {
            "success": True,
            "issue_key": issue_key,
            "comment_id": data.get("id"),
            "created": data.get("created"),
        }

    def transition_issue(self, issue_key: str, transition_name: str) -> dict[str, Any]:
        """Transition issue to a new status.

        Args:
            issue_key: Issue key
            transition_name: Target status name

        Returns:
            Result dict
        """
        if not self._session:
            raise RuntimeError("Jira skill not initialized")

        # First, get available transitions
        url = f"{self._api_root}/issue/{issue_key}/transitions"
        response = self._session.get(url, timeout=30)
        response.raise_for_status()

        transitions = response.json().get("transitions", [])

        # Find matching transition (case-insensitive)
        target_transition = None
        for t in transitions:
            if t.get("name", "").lower() == transition_name.lower():
                target_transition = t
                break

        if not target_transition:
            available = [t.get("name") for t in transitions]
            raise ValueError(f"Transition '{transition_name}' not available. Available: {available}")

        # Execute transition
        payload = {"transition": {"id": target_transition["id"]}}
        response = self._session.post(url, json=payload, timeout=30)
        response.raise_for_status()

        logger.info(f"Transitioned {issue_key} to {transition_name}")
        return {
            "success": True,
            "issue_key": issue_key,
            "transition": transition_name,
            "transition_id": target_transition["id"],
        }

    def assign_issue(self, issue_key: str, assignee: str) -> dict[str, Any]:
        """Assign issue to a user.

        Args:
            issue_key: Issue key
            assignee: Username or account ID

        Returns:
            Result dict
        """
        if not self._session:
            raise RuntimeError("Jira skill not initialized")

        url = f"{self._api_root}/issue/{issue_key}/assignee"
        payload = {"accountId": assignee}

        response = self._session.put(url, json=payload, timeout=30)
        response.raise_for_status()

        logger.info(f"Assigned {issue_key} to {assignee}")
        return {"success": True, "issue_key": issue_key, "assignee": assignee}

    def get_similar_issues(
        self,
        text: str,
        project: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Find issues similar to the given text.

        Uses Jira's text search to find similar resolved issues.

        Args:
            text: Text to search for
            project: Optional project to limit search
            max_results: Maximum results

        Returns:
            List of similar issues
        """
        # Build JQL for text search in resolved issues
        # Escape special JQL characters in text
        escaped_text = text.replace('"', '\\"')

        jql_parts = [
            f'text ~ "{escaped_text}"',
            "status in (Resolved, Closed, Done)",
        ]

        if project:
            jql_parts.append(f"project = {project}")

        jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"

        return self.search_issues(
            jql=jql,
            max_results=max_results,
            fields=["summary", "status", "resolution", "updated", "assignee"],
        )

    def _parse_issue_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Parse Jira issue response into a cleaner format.

        Args:
            data: Raw Jira API response

        Returns:
            Cleaned issue dict
        """
        fields = data.get("fields", {})

        # Extract commonly needed fields
        result = {
            "key": data.get("key"),
            "id": data.get("id"),
            "self": data.get("self"),
            "summary": fields.get("summary"),
            "description": self._extract_text_from_adf(fields.get("description")),
            "status": fields.get("status", {}).get("name") if fields.get("status") else None,
            "priority": fields.get("priority", {}).get("name") if fields.get("priority") else None,
            "issue_type": fields.get("issuetype", {}).get("name") if fields.get("issuetype") else None,
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "resolved": fields.get("resolutiondate"),
        }

        # Assignee
        assignee = fields.get("assignee")
        if assignee:
            result["assignee"] = {
                "account_id": assignee.get("accountId"),
                "display_name": assignee.get("displayName"),
                "email": assignee.get("emailAddress"),
            }

        # Reporter
        reporter = fields.get("reporter")
        if reporter:
            result["reporter"] = {
                "account_id": reporter.get("accountId"),
                "display_name": reporter.get("displayName"),
                "email": reporter.get("emailAddress"),
            }

        # Project
        project = fields.get("project")
        if project:
            result["project"] = {
                "key": project.get("key"),
                "name": project.get("name"),
            }

        # Labels
        result["labels"] = fields.get("labels", [])

        # Comments (if present)
        comments = fields.get("comment", {}).get("comments", [])
        if comments:
            result["comments"] = [
                {
                    "id": c.get("id"),
                    "author": c.get("author", {}).get("displayName"),
                    "body": self._extract_text_from_adf(c.get("body")),
                    "created": c.get("created"),
                }
                for c in comments[-5:]  # Last 5 comments
            ]

        return result

    def _extract_text_from_adf(self, adf: dict[str, Any] | None) -> str | None:
        """Extract plain text from Atlassian Document Format.

        Args:
            adf: ADF document dict

        Returns:
            Plain text string
        """
        if not adf:
            return None

        if isinstance(adf, str):
            return adf

        text_parts = []

        def extract_content(node: dict[str, Any]) -> None:
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))
            for child in node.get("content", []):
                extract_content(child)

        extract_content(adf)
        return " ".join(text_parts) if text_parts else None
