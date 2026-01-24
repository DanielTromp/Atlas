"""Engineer Agent for investigating and solving technical issues.

The EngineerAgent is responsible for:
- Gathering system information from multiple sources
- Analyzing problems and identifying root causes
- Creating investigation plans
- Preparing solutions and customer responses
"""

from __future__ import annotations

from typing import Any

from infrastructure_atlas.agents.workflow_agent import AgentConfig, BaseAgent
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


class EngineerAgent(BaseAgent):
    """Agent specialized in technical investigation and problem-solving.

    This agent:
    1. Gathers system information from NetBox, Zabbix, vCenter
    2. Analyzes problems and correlates information
    3. Creates investigation plans for complex issues
    4. Prepares solutions and customer responses
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        skills_registry: SkillsRegistry | None = None,
    ):
        if config is None:
            config = AgentConfig(
                name="Engineer Agent",
                role="senior infrastructure engineer",
                prompt_file="engineer.md",
                model="claude-sonnet-4-5-20250929",
                temperature=0.5,
                tools=["jira", "netbox", "zabbix", "vcenter", "confluence", "export"],
            )
        super().__init__(config, skills_registry)

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Process a ticket for investigation.

        Args:
            state: Workflow state containing ticket and triage data

        Returns:
            Updated state with investigation results
        """
        ticket = state.get("ticket", {})
        category = state.get("category")
        complexity = state.get("complexity")

        if not ticket:
            logger.warning("Engineer: No ticket data provided")
            return {"errors": [{"phase": "investigate", "message": "No ticket data"}]}

        # Build investigation context
        context = self._build_investigation_context(ticket, state)

        # Step 1: Gather system information
        system_info = self._gather_system_info(ticket, category)

        # Step 2: Analyze the problem
        analysis = self._analyze_problem(context, system_info, complexity)

        # Step 3: Create investigation plan (for complex issues)
        investigation_plan = None
        if complexity == "complex":
            investigation_plan = self._create_investigation_plan(context, analysis)

        # Step 4: Prepare solution/response
        prepared_response = self._prepare_response(ticket, analysis)

        # Step 5: Determine proposed actions
        proposed_actions = self._determine_actions(analysis, category)

        logger.info(
            f"Investigation complete for {ticket.get('key')}",
            extra={
                "related_systems": len(system_info.get("systems", [])),
                "actions_proposed": len(proposed_actions),
            },
        )

        return {
            "investigation": analysis,
            "related_systems": system_info.get("systems", []),
            "investigation_plan": investigation_plan,
            "prepared_response": prepared_response,
            "proposed_actions": proposed_actions,
        }

    def _build_investigation_context(
        self,
        ticket: dict[str, Any],
        state: dict[str, Any],
    ) -> str:
        """Build comprehensive context for investigation."""
        parts = [
            "=== Ticket Information ===",
            f"Key: {ticket.get('key')}",
            f"Summary: {ticket.get('summary')}",
            f"Type: {ticket.get('issue_type')}",
            f"Priority: {ticket.get('priority')}",
            f"Status: {ticket.get('status')}",
        ]

        if ticket.get("description"):
            parts.append(f"Description: {ticket.get('description')[:2000]}")

        # Add triage information
        parts.append("\n=== Triage Results ===")
        parts.append(f"Category: {state.get('category', 'Unknown')}")
        parts.append(f"Complexity: {state.get('complexity', 'Unknown')}")

        if state.get("similar_tickets"):
            parts.append("\n=== Similar Tickets ===")
            for similar in state.get("similar_tickets", [])[:3]:
                parts.append(f"- {similar.get('key')}: {similar.get('summary')}")

        return "\n".join(parts)

    def _gather_system_info(
        self,
        ticket: dict[str, Any],
        category: str | None,
    ) -> dict[str, Any]:
        """Gather relevant system information based on ticket content."""
        systems = []
        alerts = []
        metrics = []

        # Extract potential hostnames/systems from ticket
        potential_hosts = self._extract_hosts_from_ticket(ticket)

        if not self.skills_registry:
            return {"systems": systems, "alerts": alerts, "metrics": metrics}

        # Gather from Zabbix if monitoring-related
        if category in ("Monitoring/Alert", "Infrastructure/Server"):
            zabbix = self.skills_registry.get("zabbix")
            if zabbix:
                for host in potential_hosts:
                    try:
                        host_info = zabbix.execute("get_host", {"hostname": host})
                        if host_info:
                            systems.append({"source": "zabbix", "host": host, "info": host_info})

                        problems = zabbix.execute("get_host_problems", {"hostname": host})
                        if problems:
                            alerts.extend(problems)
                    except Exception as e:
                        logger.debug(f"Zabbix lookup failed for {host}: {e!s}")

        # Gather from NetBox for infrastructure context
        netbox = self.skills_registry.get("netbox")
        if netbox:
            for host in potential_hosts:
                try:
                    device = netbox.execute("search_device", {"name": host})
                    if device:
                        systems.append({"source": "netbox", "host": host, "info": device})
                except Exception as e:
                    logger.debug(f"NetBox lookup failed for {host}: {e!s}")

        return {
            "systems": systems,
            "alerts": alerts,
            "metrics": metrics,
        }

    def _analyze_problem(
        self,
        context: str,
        system_info: dict[str, Any],
        complexity: str | None,
    ) -> dict[str, Any]:
        """Analyze the problem using gathered information."""
        # Build analysis context with system info
        full_context = context

        if system_info.get("systems"):
            full_context += "\n\n=== Related Systems ===\n"
            for sys in system_info.get("systems", []):
                full_context += f"- {sys.get('source')}: {sys.get('host')}\n"

        if system_info.get("alerts"):
            full_context += "\n\n=== Active Alerts ===\n"
            for alert in system_info.get("alerts", [])[:5]:
                full_context += f"- {alert}\n"

        question = """Analyze this issue and provide:
1. Most likely root cause(s)
2. Affected systems and potential blast radius
3. Recommended immediate actions
4. Any escalation considerations"""

        response = self.think(context=full_context, question=question)

        return {
            "summary": response,
            "likely_causes": self._extract_causes(response),
            "affected_systems": [s.get("host") for s in system_info.get("systems", [])],
            "alerts_found": len(system_info.get("alerts", [])),
        }

    def _create_investigation_plan(
        self,
        context: str,
        analysis: dict[str, Any],
    ) -> str:
        """Create a detailed investigation plan for complex issues."""
        question = """Create a step-by-step investigation plan including:
1. Data to collect
2. Tests to run
3. Verification steps
4. Escalation criteria
5. Rollback procedures if applicable"""

        plan_context = f"{context}\n\nAnalysis: {analysis.get('summary')}"
        return self.think(context=plan_context, question=question)

    def _prepare_response(
        self,
        ticket: dict[str, Any],
        analysis: dict[str, Any],
    ) -> str:
        """Prepare a professional customer response."""
        context = f"""Ticket: {ticket.get('key')}
Summary: {ticket.get('summary')}
Analysis: {analysis.get('summary')}"""

        question = """Draft a professional customer response that:
1. Acknowledges the issue
2. Explains what was found (in non-technical terms)
3. States the resolution or next steps
4. Sets appropriate expectations"""

        return self.think(context=context, question=question)

    def _determine_actions(
        self,
        analysis: dict[str, Any],
        category: str | None,
    ) -> list[dict[str, Any]]:
        """Determine actions to propose based on analysis."""
        actions = []

        # Always propose adding analysis as a comment
        actions.append({
            "skill": "jira",
            "action": "add_comment",
            "description": "Add investigation findings as internal comment",
            "params": {"body": analysis.get("summary", "")},
            "is_destructive": True,
        })

        return actions

    def _extract_hosts_from_ticket(self, ticket: dict[str, Any]) -> list[str]:
        """Extract potential hostnames from ticket content."""
        import re

        hosts = set()
        text = f"{ticket.get('summary', '')} {ticket.get('description', '')}"

        # Common hostname patterns
        patterns = [
            r"\b([a-zA-Z][a-zA-Z0-9-]*\.[a-zA-Z]{2,})\b",  # FQDN
            r"\b(srv[a-zA-Z0-9-]+)\b",  # srv* servers
            r"\b(web[a-zA-Z0-9-]+)\b",  # web* servers
            r"\b(db[a-zA-Z0-9-]+)\b",  # db* servers
            r"\b(app[a-zA-Z0-9-]+)\b",  # app* servers
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            hosts.update(matches)

        return list(hosts)[:10]  # Limit to 10 hosts

    def _extract_causes(self, analysis: str) -> list[str]:
        """Extract likely causes from analysis text."""
        # Simplified extraction - would use structured output in production
        causes = []

        lines = analysis.split("\n")
        for line in lines:
            if any(kw in line.lower() for kw in ["cause", "reason", "likely", "probably"]):
                causes.append(line.strip())

        return causes[:3]  # Top 3 causes
