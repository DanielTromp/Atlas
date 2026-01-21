"""Bot platform management CLI commands."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import typer
from rich import print
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from infrastructure_atlas.application.context import ServiceContext
from infrastructure_atlas.bots.adapters.telegram import TelegramAdapter
from infrastructure_atlas.bots.linking import UserLinkingService
from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.db.models import (
    BotConversation,
    BotMessage,
    BotPlatformAccount,
    BotWebhookConfig,
    User,
)
from infrastructure_atlas.infrastructure.modules.registry import get_module_registry

app = typer.Typer(help="Bot platform management", context_settings={"help_option_names": ["-h", "--help"]})
console = Console()


def _service_context() -> ServiceContext:
    """Create a service context with database session factory."""
    return ServiceContext(session_factory=get_sessionmaker())


def _require_bots_enabled() -> None:
    """Check if bots module is enabled."""
    registry = get_module_registry()
    if not registry.is_enabled("bots"):
        print("[red]Bots module is not enabled[/red]")
        print("[dim]Enable it with: ATLAS_MODULE_BOTS_ENABLED=1[/dim]")
        raise typer.Exit(code=1)


def _get_storage_backend() -> str:
    """Get the configured storage backend."""
    return os.getenv("ATLAS_STORAGE_BACKEND", "sqlite").lower()


def _save_webhook_config(
    platform: str,
    bot_token_secret: str,
    webhook_secret: str | None = None,
) -> None:
    """Save webhook configuration to the database (MongoDB or SQLite)."""
    backend = _get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

        db = get_mongodb_client().atlas
        collection = db["bot_webhook_configs"]

        doc = {
            "platform": platform,
            "enabled": True,
            "bot_token_secret": bot_token_secret,
            "webhook_secret": webhook_secret,
            "updated_at": datetime.now(UTC),
        }

        collection.update_one(
            {"platform": platform},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(UTC)}},
            upsert=True,
        )
    else:
        # SQLite via SQLAlchemy
        ctx = _service_context()
        with ctx.session_scope() as session:
            config = session.query(BotWebhookConfig).filter_by(platform=platform).first()

            if config:
                config.bot_token_secret = bot_token_secret
                config.webhook_secret = webhook_secret
                config.enabled = True
            else:
                config = BotWebhookConfig(
                    platform=platform,
                    enabled=True,
                    bot_token_secret=bot_token_secret,
                    webhook_secret=webhook_secret,
                )
                session.add(config)

            session.commit()


def _get_user_by_username(username: str) -> Any | None:
    """Get a user by username (MongoDB or SQLite)."""
    backend = _get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

        db = get_mongodb_client().atlas
        collection = db["users"]
        doc = collection.find_one({"username": username.lower()})
        if doc:
            # Return a simple object with id and username
            class UserObj:
                def __init__(self, d: dict):
                    self.id = d.get("_id")
                    self.username = d.get("username")
            return UserObj(doc)
        return None
    else:
        ctx = _service_context()
        with ctx.session_scope() as session:
            return session.query(User).filter_by(username=username.lower()).first()


def _generate_link_code(user_id: str, platform: str) -> str:
    """Generate a verification code for linking (MongoDB or SQLite)."""
    backend = _get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.bots.service_factory import MongoDBBotSession, MongoDBUserLinkingService

        session = MongoDBBotSession()
        linking = MongoDBUserLinkingService(session)
        return linking.generate_verification_code(user_id, platform)
    else:
        ctx = _service_context()
        with ctx.session_scope() as session:
            linking = UserLinkingService(session)
            return linking.generate_verification_code(user_id, platform)


def _unlink_user_platform(user_id: str, platform: str) -> bool:
    """Unlink a user from a platform (MongoDB or SQLite)."""
    backend = _get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.bots.service_factory import MongoDBBotSession, MongoDBUserLinkingService

        session = MongoDBBotSession()
        linking = MongoDBUserLinkingService(session)
        return linking.unlink_user_platform(user_id, platform)
    else:
        ctx = _service_context()
        with ctx.session_scope() as session:
            linking = UserLinkingService(session)
            return linking.unlink_user_platform(user_id, platform)


@app.callback()
def callback():
    """Bot platform management commands.

    Manage Telegram, Slack, and Teams bot integrations.
    """
    pass


def _get_platform_stats(platform: str) -> tuple[int, int]:
    """Get statistics for a platform (MongoDB or SQLite).

    Returns:
        Tuple of (linked_count, message_count_24h)
    """
    backend = _get_storage_backend()
    now = datetime.now(UTC)
    day_ago = now - timedelta(days=1)

    if backend == "mongodb":
        from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

        db = get_mongodb_client().atlas

        # Count linked (verified) accounts
        linked_count = db["bot_platform_accounts"].count_documents({
            "platform": platform,
            "verified": True,
        })

        # Count messages in last 24h - need to join through conversations
        # First get conversation IDs for this platform
        conv_ids = [
            c["_id"] for c in db["bot_conversations"].find(
                {"platform": platform},
                {"_id": 1}
            )
        ]

        message_count = 0
        if conv_ids:
            message_count = db["bot_messages"].count_documents({
                "conversation_id": {"$in": conv_ids},
                "created_at": {"$gte": day_ago},
            })

        return linked_count, message_count
    else:
        ctx = _service_context()
        with ctx.session_scope() as session:
            linked_count = session.execute(
                select(func.count(BotPlatformAccount.id)).where(
                    BotPlatformAccount.platform == platform,
                    BotPlatformAccount.verified == True,  # noqa: E712
                )
            ).scalar() or 0

            message_count = session.execute(
                select(func.count(BotMessage.id))
                .join(BotConversation)
                .where(
                    BotConversation.platform == platform,
                    BotMessage.created_at >= day_ago,
                )
            ).scalar() or 0

            return linked_count, message_count


@app.command("status")
def status():
    """Show status of all bot platforms."""
    _require_bots_enabled()

    table = Table(title="Bot Platform Status")
    table.add_column("Platform", style="cyan")
    table.add_column("Configured", style="green")
    table.add_column("Bot Name", style="magenta")
    table.add_column("Linked Users", style="yellow")
    table.add_column("Messages (24h)", style="blue")

    for platform in ["telegram", "slack", "teams"]:
        configured = False
        bot_name = "-"

        # Check configuration
        if platform == "telegram":
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if token:
                configured = True
                try:
                    adapter = TelegramAdapter(bot_token=token)
                    info = asyncio.run(adapter.get_bot_info())
                    bot_name = f"@{info.get('username', 'unknown')}"
                except Exception as e:
                    bot_name = f"[red]Error: {e}[/red]"
        elif platform == "slack":
            slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
            slack_app_token = os.getenv("SLACK_APP_TOKEN")
            if slack_bot_token and slack_app_token:
                configured = True
                try:
                    from infrastructure_atlas.bots.adapters.slack import SlackAdapter

                    adapter = SlackAdapter(bot_token=slack_bot_token)
                    info = asyncio.run(adapter.get_bot_info())
                    bot_name = f"@{info.get('username', 'unknown')} ({info.get('team', '')})"
                except ImportError:
                    bot_name = "[yellow]slack-bolt not installed[/yellow]"
                except Exception as e:
                    bot_name = f"[red]Error: {e}[/red]"
            elif slack_bot_token:
                configured = False
                bot_name = "[yellow]Missing SLACK_APP_TOKEN[/yellow]"
        elif platform == "teams":
            configured = bool(os.getenv("TEAMS_APP_ID") and os.getenv("TEAMS_APP_PASSWORD"))
            if configured:
                bot_name = "[dim]Configured[/dim]"

        # Get statistics (MongoDB or SQLite)
        linked_count, message_count = _get_platform_stats(platform)

        table.add_row(
            platform.capitalize(),
            "[green]Yes[/green]" if configured else "[red]No[/red]",
            bot_name,
            str(linked_count),
            str(message_count),
        )

    console.print(table)


@app.command("setup-telegram")
def setup_telegram(
    bot_token: str = typer.Option(..., "--token", help="Telegram Bot Token from @BotFather"),
    webhook_url: str = typer.Option(None, "--webhook-url", help="Webhook URL (https required)"),
    webhook_secret: str = typer.Option(None, "--webhook-secret", help="Secret for webhook verification"),
):
    """Configure Telegram bot and optionally set webhook.

    You can get a bot token from @BotFather on Telegram.
    """
    _require_bots_enabled()

    # Test the token
    adapter = TelegramAdapter(bot_token=bot_token)
    try:
        info = asyncio.run(adapter.get_bot_info())
        print(f"[green]Bot verified:[/green] @{info.get('username')} ({info.get('first_name')})")
    except Exception as e:
        print(f"[red]Failed to verify bot token:[/red] {e}")
        raise typer.Exit(code=1)

    # Store in database (MongoDB or SQLite)
    _save_webhook_config(
        platform="telegram",
        bot_token_secret="TELEGRAM_BOT_TOKEN",
        webhook_secret=webhook_secret,
    )

    print("[green]Telegram bot configuration saved[/green]")

    # Set webhook if URL provided
    if webhook_url:
        try:
            success = asyncio.run(
                adapter.set_webhook(
                    webhook_url=webhook_url,
                    secret_token=webhook_secret,
                )
            )
            if success:
                print(f"[green]Webhook set to:[/green] {webhook_url}")
            else:
                print("[red]Failed to set webhook[/red]")
        except Exception as e:
            print(f"[red]Failed to set webhook:[/red] {e}")

    # Show instructions
    print()
    print("[bold]Next steps:[/bold]")
    print("1. Set TELEGRAM_BOT_TOKEN environment variable")
    if not webhook_url:
        print("2. Configure webhook URL: atlas bots setup-telegram --token ... --webhook-url https://your-domain.com/webhooks/bots/telegram/secret")
    print()
    print("[dim]Users can link their accounts with /link <code> in Telegram[/dim]")


@app.command("link-user")
def link_user(
    username: str = typer.Argument(..., help="Atlas username to generate code for"),
    platform: str = typer.Argument(..., help="Platform (telegram, slack, teams)"),
):
    """Generate a verification code for a user to link their account.

    The user should send /link <code> in their platform chat to complete the linking.
    """
    _require_bots_enabled()

    if platform not in ["telegram", "slack", "teams"]:
        print(f"[red]Invalid platform: {platform}[/red]")
        print("[dim]Valid platforms: telegram, slack, teams[/dim]")
        raise typer.Exit(code=1)

    # Find user (MongoDB or SQLite)
    user = _get_user_by_username(username)
    if not user:
        print(f"[red]User not found: {username}[/red]")
        raise typer.Exit(code=1)

    # Generate code (MongoDB or SQLite)
    code = _generate_link_code(str(user.id), platform)

    print(f"[green]Verification code generated for {username}[/green]")
    print()
    print(f"[bold]Code:[/bold] {code}")
    print("[dim]Valid for 10 minutes[/dim]")
    print()
    # Slack uses ! prefix since / is reserved for native slash commands
    cmd_prefix = "!" if platform == "slack" else "/"
    print(f"Tell the user to send this command in their {platform.capitalize()} chat:")
    print(f"  {cmd_prefix}link {code}")


@app.command("unlink-user")
def unlink_user(
    username: str = typer.Argument(..., help="Atlas username"),
    platform: str = typer.Argument(..., help="Platform (telegram, slack, teams)"),
):
    """Unlink a user's platform account."""
    _require_bots_enabled()

    if platform not in ["telegram", "slack", "teams"]:
        print(f"[red]Invalid platform: {platform}[/red]")
        raise typer.Exit(code=1)

    # Find user (MongoDB or SQLite)
    user = _get_user_by_username(username)
    if not user:
        print(f"[red]User not found: {username}[/red]")
        raise typer.Exit(code=1)

    # Unlink (MongoDB or SQLite)
    if _unlink_user_platform(str(user.id), platform):
        print(f"[green]Unlinked {username} from {platform.capitalize()}[/green]")
    else:
        print(f"[yellow]No {platform.capitalize()} account linked for {username}[/yellow]")


@app.command("list-accounts")
def list_accounts(
    platform: str = typer.Option(None, "--platform", help="Filter by platform"),
):
    """List all linked platform accounts."""
    _require_bots_enabled()

    table = Table(title="Linked Platform Accounts")
    table.add_column("Username", style="cyan")
    table.add_column("Platform", style="magenta")
    table.add_column("Platform User", style="green")
    table.add_column("Verified", style="yellow")
    table.add_column("Linked At")

    backend = _get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

        db = get_mongodb_client().atlas

        query = {}
        if platform:
            query["platform"] = platform

        accounts = list(db["bot_platform_accounts"].find(query).sort("created_at", -1))

        if not accounts:
            print("[yellow]No linked accounts found[/yellow]")
            return

        # Get user mapping for usernames
        user_ids = [a.get("user_id") for a in accounts if a.get("user_id")]
        users = {str(u["_id"]): u for u in db["users"].find({"_id": {"$in": user_ids}})}

        for account in accounts:
            user_id = account.get("user_id")
            user = users.get(str(user_id)) if user_id else None
            username = user.get("username") if user else "[red]Unknown[/red]"
            created = account.get("created_at")
            created_str = created.strftime("%Y-%m-%d %H:%M") if created else "-"

            table.add_row(
                username,
                account.get("platform", "").capitalize(),
                account.get("platform_username") or account.get("platform_user_id", ""),
                "[green]Yes[/green]" if account.get("verified") else "[red]No[/red]",
                created_str,
            )
    else:
        ctx = _service_context()
        with ctx.session_scope() as session:
            query = select(BotPlatformAccount).order_by(BotPlatformAccount.created_at.desc())

            if platform:
                query = query.where(BotPlatformAccount.platform == platform)

            accounts = list(session.execute(query).scalars().all())

            if not accounts:
                print("[yellow]No linked accounts found[/yellow]")
                return

            for account in accounts:
                table.add_row(
                    account.user.username if account.user else "[red]Unknown[/red]",
                    account.platform.capitalize(),
                    account.platform_username or account.platform_user_id,
                    "[green]Yes[/green]" if account.verified else "[red]No[/red]",
                    account.created_at.strftime("%Y-%m-%d %H:%M"),
                )

    console.print(table)


@app.command("usage")
def usage(
    days: int = typer.Option(30, "--days", help="Number of days to show"),
    platform: str = typer.Option(None, "--platform", help="Filter by platform"),
):
    """Show bot usage statistics."""
    _require_bots_enabled()

    now = datetime.now(UTC)
    start_date = now - timedelta(days=days)
    backend = _get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.infrastructure.mongodb.client import get_mongodb_client

        db = get_mongodb_client().atlas

        # Get conversation IDs for platform filter
        conv_filter = {}
        if platform:
            conv_filter["platform"] = platform
        conv_ids = [c["_id"] for c in db["bot_conversations"].find(conv_filter, {"_id": 1})]

        # Build message filter
        msg_filter: dict[str, Any] = {"created_at": {"$gte": start_date}}
        if conv_ids:
            msg_filter["conversation_id"] = {"$in": conv_ids}
        elif platform:
            # No conversations for this platform
            conv_ids = []

        # Stats
        total_messages = db["bot_messages"].count_documents(msg_filter) if conv_ids or not platform else 0
        total_conversations = len(set(
            m["conversation_id"] for m in db["bot_messages"].find(msg_filter, {"conversation_id": 1})
        )) if conv_ids or not platform else 0

        # Aggregation for tokens and cost
        pipeline = [
            {"$match": msg_filter},
            {"$group": {
                "_id": None,
                "total_input": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                "total_output": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                "total_cost": {"$sum": {"$ifNull": ["$cost_usd", 0]}},
            }}
        ]
        agg_result = list(db["bot_messages"].aggregate(pipeline))
        total_input = agg_result[0]["total_input"] if agg_result else 0
        total_output = agg_result[0]["total_output"] if agg_result else 0
        total_cost = agg_result[0]["total_cost"] if agg_result else 0.0

        # Messages by platform (get all conversations, then count)
        all_convs = {c["_id"]: c["platform"] for c in db["bot_conversations"].find({}, {"_id": 1, "platform": 1})}
        platform_msg_filter = {"created_at": {"$gte": start_date}}
        platform_counts_dict: dict[str, int] = {}
        for msg in db["bot_messages"].find(platform_msg_filter, {"conversation_id": 1}):
            p = all_convs.get(msg.get("conversation_id"), "unknown")
            platform_counts_dict[p] = platform_counts_dict.get(p, 0) + 1
        platform_counts = list(platform_counts_dict.items())

        # Messages by agent
        agent_pipeline = [
            {"$match": {"created_at": {"$gte": start_date}, "agent_id": {"$ne": None}}},
            {"$group": {"_id": "$agent_id", "count": {"$sum": 1}}}
        ]
        agent_counts = [(r["_id"], r["count"]) for r in db["bot_messages"].aggregate(agent_pipeline)]
    else:
        ctx = _service_context()
        with ctx.session_scope() as session:
            # Build filters
            message_filter = [BotMessage.created_at >= start_date]
            if platform:
                message_filter.append(BotConversation.platform == platform)

            # Total messages
            total_messages = session.execute(
                select(func.count(BotMessage.id))
                .join(BotConversation)
                .where(*message_filter)
            ).scalar() or 0

            # Total conversations
            total_conversations = session.execute(
                select(func.count(func.distinct(BotConversation.id)))
                .join(BotMessage)
                .where(*message_filter)
            ).scalar() or 0

            # Token usage
            total_input = session.execute(
                select(func.sum(BotMessage.input_tokens))
                .join(BotConversation)
                .where(*message_filter)
            ).scalar() or 0

            total_output = session.execute(
                select(func.sum(BotMessage.output_tokens))
                .join(BotConversation)
                .where(*message_filter)
            ).scalar() or 0

            total_cost = session.execute(
                select(func.sum(BotMessage.cost_usd))
                .join(BotConversation)
                .where(*message_filter)
            ).scalar() or 0.0

            # Messages by platform
            platform_counts = session.execute(
                select(BotConversation.platform, func.count(BotMessage.id))
                .join(BotConversation)
                .where(BotMessage.created_at >= start_date)
                .group_by(BotConversation.platform)
            ).all()

            # Messages by agent
            agent_counts = session.execute(
                select(BotMessage.agent_id, func.count(BotMessage.id))
                .join(BotConversation)
                .where(BotMessage.created_at >= start_date, BotMessage.agent_id.isnot(None))
                .group_by(BotMessage.agent_id)
            ).all()

    # Display
    print(f"\n[bold]Bot Usage Statistics ({days} days)[/bold]\n")

    stats_table = Table(show_header=False, box=None)
    stats_table.add_column("Metric", style="dim")
    stats_table.add_column("Value", style="cyan")

    stats_table.add_row("Total Messages", str(total_messages))
    stats_table.add_row("Total Conversations", str(total_conversations))
    stats_table.add_row("Input Tokens", f"{total_input:,}")
    stats_table.add_row("Output Tokens", f"{total_output:,}")
    stats_table.add_row("Total Cost", f"${float(total_cost):.4f}")

    console.print(stats_table)

    if platform_counts:
        print("\n[bold]Messages by Platform:[/bold]")
        for p, count in platform_counts:
            print(f"  {p.capitalize()}: {count}")

    if agent_counts:
        print("\n[bold]Messages by Agent:[/bold]")
        for agent, count in agent_counts:
            print(f"  {agent or 'unknown'}: {count}")


@app.command("test-telegram")
def test_telegram(
    chat_id: str = typer.Argument(..., help="Chat ID to send test message to"),
):
    """Send a test message to a Telegram chat.

    You can find the chat ID by sending /start to your bot and checking the logs.
    """
    _require_bots_enabled()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[red]TELEGRAM_BOT_TOKEN not set[/red]")
        raise typer.Exit(code=1)

    adapter = TelegramAdapter(bot_token=token)

    try:
        message_id = asyncio.run(
            adapter.send_message(
                chat_id=chat_id,
                content="*Test message from Atlas*\n\nIf you see this, the bot is working correctly\\!",
            )
        )
        print(f"[green]Test message sent successfully[/green] (message_id: {message_id})")
    except Exception as e:
        print(f"[red]Failed to send test message:[/red] {e}")
        raise typer.Exit(code=1)


@app.command("webhook-info")
def webhook_info():
    """Show current Telegram webhook configuration."""
    _require_bots_enabled()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[red]TELEGRAM_BOT_TOKEN not set[/red]")
        raise typer.Exit(code=1)

    adapter = TelegramAdapter(bot_token=token)

    try:
        info = asyncio.run(adapter.get_webhook_info())

        print("\n[bold]Telegram Webhook Configuration[/bold]\n")

        table = Table(show_header=False, box=None)
        table.add_column("Setting", style="dim")
        table.add_column("Value", style="cyan")

        table.add_row("URL", info.get("url") or "[yellow]Not set[/yellow]")
        table.add_row("Has Custom Certificate", str(info.get("has_custom_certificate", False)))
        table.add_row("Pending Updates", str(info.get("pending_update_count", 0)))
        table.add_row("Max Connections", str(info.get("max_connections", 40)))

        if info.get("last_error_date"):
            from datetime import datetime

            error_time = datetime.fromtimestamp(info["last_error_date"])
            table.add_row("Last Error", f"{error_time}: {info.get('last_error_message', 'Unknown')}")

        if info.get("allowed_updates"):
            table.add_row("Allowed Updates", ", ".join(info["allowed_updates"]))

        console.print(table)

    except Exception as e:
        print(f"[red]Failed to get webhook info:[/red] {e}")
        raise typer.Exit(code=1)


@app.command("run-telegram")
def run_telegram():
    """Run the Telegram bot in polling mode (no public URL required).

    This starts a long-running process that polls Telegram for updates.
    Use Ctrl+C to stop.

    This is the recommended mode for internal/private deployments where
    you don't have a public HTTPS endpoint for webhooks.
    """
    _require_bots_enabled()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[red]TELEGRAM_BOT_TOKEN not set[/red]")
        print("[dim]Add TELEGRAM_BOT_TOKEN=your_token to your .env file[/dim]")
        raise typer.Exit(code=1)

    print("[bold]Starting Telegram bot in polling mode...[/bold]")
    print("[dim]Press Ctrl+C to stop[/dim]\n")

    try:
        from infrastructure_atlas.bots.adapters.telegram_polling import run_polling_bot

        asyncio.run(run_polling_bot(bot_token=token))
    except KeyboardInterrupt:
        print("\n[yellow]Bot stopped[/yellow]")
    except Exception as e:
        print(f"[red]Bot error:[/red] {e}")
        raise typer.Exit(code=1)


# ============================================================================
# Slack Commands
# ============================================================================


@app.command("setup-slack")
def setup_slack(
    bot_token: str = typer.Option(None, "--bot-token", help="Slack Bot Token (xoxb-...)"),
    app_token: str = typer.Option(None, "--app-token", help="Slack App Token for Socket Mode (xapp-...)"),
):
    """Configure Slack bot for Socket Mode (no public endpoints needed).

    Socket Mode connects via WebSocket - perfect for internal deployments.

    \b
    To set up:
    1. Go to https://api.slack.com/apps and create a new app
    2. Enable Socket Mode in the app settings
    3. Generate an App-Level Token with 'connections:write' scope
    4. Add Bot Token Scopes:
       - app_mentions:read, chat:write, im:history, im:read, im:write, users:read
    5. Subscribe to events: message.im, app_mention
    6. Install the app to your workspace
    """
    _require_bots_enabled()

    # Get tokens from args or env
    bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN")
    app_token = app_token or os.getenv("SLACK_APP_TOKEN")

    if not bot_token:
        print("[red]Bot token required[/red]")
        print("[dim]Use --bot-token or set SLACK_BOT_TOKEN env var[/dim]")
        raise typer.Exit(code=1)

    if not app_token:
        print("[red]App token required for Socket Mode[/red]")
        print("[dim]Use --app-token or set SLACK_APP_TOKEN env var[/dim]")
        print("[dim]Generate one at: https://api.slack.com/apps > Your App > Basic Information > App-Level Tokens[/dim]")
        raise typer.Exit(code=1)

    # Test the tokens
    try:
        from infrastructure_atlas.bots.adapters.slack import SlackAdapter

        adapter = SlackAdapter(bot_token=bot_token, app_token=app_token)
        info = asyncio.run(adapter.get_bot_info())
        print(f"[green]Bot verified:[/green] @{info.get('username')} (team: {info.get('team')})")
    except ImportError:
        print("[red]slack-bolt package not installed[/red]")
        print("[dim]Run: uv add slack-bolt slack-sdk[/dim]")
        raise typer.Exit(code=1)
    except Exception as e:
        print(f"[red]Failed to verify bot tokens:[/red] {e}")
        raise typer.Exit(code=1)

    # Store in database (MongoDB or SQLite)
    _save_webhook_config(
        platform="slack",
        bot_token_secret="SLACK_BOT_TOKEN",
        webhook_secret="SLACK_APP_TOKEN",
    )

    print("[green]Slack bot configuration saved[/green]")
    print()
    print("[bold]Next steps:[/bold]")
    print("1. Add these environment variables to your .env file:")
    print(f"   SLACK_BOT_TOKEN={bot_token[:20]}...")
    print(f"   SLACK_APP_TOKEN={app_token[:20]}...")
    print("2. Run the bot: [cyan]atlas bots run-slack[/cyan]")
    print()
    print("[dim]Users can link their accounts with /link <code> in Slack DMs[/dim]")


@app.command("run-slack")
def run_slack():
    """Run the Slack bot in Socket Mode (no public URL required).

    This starts a persistent WebSocket connection to Slack.
    Use Ctrl+C to stop.

    Socket Mode is ideal for:
    - Internal deployments behind firewalls
    - Development and testing
    - Environments without public HTTPS endpoints

    \b
    Required environment variables:
    - SLACK_BOT_TOKEN: Bot User OAuth Token (xoxb-...)
    - SLACK_APP_TOKEN: App-Level Token for Socket Mode (xapp-...)
    """
    _require_bots_enabled()

    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")

    if not bot_token:
        print("[red]SLACK_BOT_TOKEN not set[/red]")
        print("[dim]Add SLACK_BOT_TOKEN=xoxb-... to your .env file[/dim]")
        raise typer.Exit(code=1)

    if not app_token:
        print("[red]SLACK_APP_TOKEN not set[/red]")
        print("[dim]Add SLACK_APP_TOKEN=xapp-... to your .env file[/dim]")
        print("[dim]This is required for Socket Mode (no webhooks needed)[/dim]")
        raise typer.Exit(code=1)

    print("[bold]Starting Slack bot in Socket Mode...[/bold]")
    print("[dim]Press Ctrl+C to stop[/dim]\n")

    try:
        from infrastructure_atlas.bots.adapters.slack_socket import run_socket_mode_bot

        asyncio.run(run_socket_mode_bot(bot_token=bot_token, app_token=app_token))
    except ImportError as e:
        print(f"[red]Missing dependency:[/red] {e}")
        print("[dim]Run: uv add slack-bolt slack-sdk[/dim]")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        print("\n[yellow]Bot stopped[/yellow]")
    except Exception as e:
        print(f"[red]Bot error:[/red] {e}")
        raise typer.Exit(code=1)


@app.command("test-slack")
def test_slack(
    channel_id: str = typer.Argument(..., help="Channel or DM ID to send test message to"),
):
    """Send a test message to a Slack channel or DM.

    The channel ID looks like C01234567 (channels) or D01234567 (DMs).
    You can find it by right-clicking a channel > View channel details > Copy ID.
    """
    _require_bots_enabled()

    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        print("[red]SLACK_BOT_TOKEN not set[/red]")
        raise typer.Exit(code=1)

    try:
        from infrastructure_atlas.bots.adapters.slack import SlackAdapter

        adapter = SlackAdapter(bot_token=token)
        message_id = asyncio.run(
            adapter.send_message(
                chat_id=channel_id,
                content="*Test message from Atlas* :robot_face:\n\nIf you see this, the bot is working correctly!",
            )
        )
        print(f"[green]Test message sent successfully[/green] (ts: {message_id})")
    except ImportError:
        print("[red]slack-bolt package not installed[/red]")
        print("[dim]Run: uv add slack-bolt slack-sdk[/dim]")
        raise typer.Exit(code=1)
    except Exception as e:
        print(f"[red]Failed to send test message:[/red] {e}")
        raise typer.Exit(code=1)
