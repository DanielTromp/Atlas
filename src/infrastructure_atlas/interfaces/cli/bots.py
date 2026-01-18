"""Bot platform management CLI commands."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

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


@app.callback()
def callback():
    """Bot platform management commands.

    Manage Telegram, Slack, and Teams bot integrations.
    """
    pass


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

    ctx = _service_context()
    with ctx.session_scope() as session:
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
                configured = bool(os.getenv("SLACK_BOT_TOKEN"))
                if configured:
                    bot_name = "[dim]Configured[/dim]"
            elif platform == "teams":
                configured = bool(os.getenv("TEAMS_APP_ID") and os.getenv("TEAMS_APP_PASSWORD"))
                if configured:
                    bot_name = "[dim]Configured[/dim]"

            # Get statistics
            now = datetime.now(UTC)
            day_ago = now - timedelta(days=1)

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

    # Store in database
    ctx = _service_context()
    with ctx.session_scope() as session:
        config = session.query(BotWebhookConfig).filter_by(platform="telegram").first()

        if config:
            config.bot_token_secret = "TELEGRAM_BOT_TOKEN"  # Env var reference
            config.webhook_secret = webhook_secret
            config.enabled = True
        else:
            config = BotWebhookConfig(
                platform="telegram",
                enabled=True,
                bot_token_secret="TELEGRAM_BOT_TOKEN",
                webhook_secret=webhook_secret,
            )
            session.add(config)

        session.commit()

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

    ctx = _service_context()
    with ctx.session_scope() as session:
        # Find user
        user = session.query(User).filter_by(username=username.lower()).first()
        if not user:
            print(f"[red]User not found: {username}[/red]")
            raise typer.Exit(code=1)

        # Generate code
        linking = UserLinkingService(session)
        code = linking.generate_verification_code(user.id, platform)

    print(f"[green]Verification code generated for {username}[/green]")
    print()
    print(f"[bold]Code:[/bold] {code}")
    print("[dim]Valid for 10 minutes[/dim]")
    print()
    print(f"Tell the user to send this command in their {platform.capitalize()} chat:")
    print(f"  /link {code}")


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

    ctx = _service_context()
    with ctx.session_scope() as session:
        # Find user
        user = session.query(User).filter_by(username=username.lower()).first()
        if not user:
            print(f"[red]User not found: {username}[/red]")
            raise typer.Exit(code=1)

        # Unlink
        linking = UserLinkingService(session)
        if linking.unlink_user_platform(user.id, platform):
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

    ctx = _service_context()
    with ctx.session_scope() as session:
        now = datetime.now(UTC)
        start_date = now - timedelta(days=days)

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
