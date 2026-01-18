"""User linking service for connecting external platform accounts to Atlas users.

Provides secure verification flow:
1. User requests a verification code via CLI or web UI
2. Code is valid for 10 minutes
3. User sends /link <code> in their platform chat
4. Platform account is linked and verified
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from infrastructure_atlas.db.models import BotPlatformAccount, User


class UserLinkingService:
    """Manages linking external platform accounts to Atlas users."""

    # Verification code settings
    CODE_LENGTH = 6
    CODE_EXPIRY_MINUTES = 10

    def __init__(self, db: Session):
        self.db = db

    def generate_verification_code(
        self,
        user_id: str,
        platform: str,
        platform_user_id: str | None = None,
        platform_username: str | None = None,
    ) -> str:
        """Generate a verification code for linking a platform account.

        Args:
            user_id: Atlas user ID
            platform: Platform name (telegram, slack, teams)
            platform_user_id: Optional platform user ID (if known ahead of time)
            platform_username: Optional display name from platform

        Returns:
            6-digit verification code

        If an unverified account already exists for this user/platform, it will be updated.
        """
        # Check for existing unverified account
        existing = self.db.execute(
            select(BotPlatformAccount).where(
                BotPlatformAccount.user_id == user_id,
                BotPlatformAccount.platform == platform,
                BotPlatformAccount.verified == False,  # noqa: E712
            )
        ).scalar_one_or_none()

        # Generate new code
        code = "".join(secrets.choice("0123456789") for _ in range(self.CODE_LENGTH))
        expires = datetime.now(UTC) + timedelta(minutes=self.CODE_EXPIRY_MINUTES)

        if existing:
            # Update existing unverified account
            existing.verification_code = code
            existing.verification_expires = expires
            if platform_user_id:
                existing.platform_user_id = platform_user_id
            if platform_username:
                existing.platform_username = platform_username
        else:
            # Create new unverified account
            # Use a placeholder for platform_user_id if not provided
            account = BotPlatformAccount(
                user_id=user_id,
                platform=platform,
                platform_user_id=platform_user_id or f"pending:{user_id}",
                platform_username=platform_username,
                verified=False,
                verification_code=code,
                verification_expires=expires,
            )
            self.db.add(account)

        self.db.commit()
        return code

    def verify_code(
        self,
        platform: str,
        platform_user_id: str,
        code: str,
        platform_username: str | None = None,
    ) -> BotPlatformAccount | None:
        """Verify a code and link the platform account.

        Args:
            platform: Platform name (telegram, slack, teams)
            platform_user_id: Platform-specific user ID
            code: Verification code from user
            platform_username: Optional display name to update

        Returns:
            The linked BotPlatformAccount if successful, None otherwise
        """
        now = datetime.now(UTC)

        # Find account with matching code (not expired)
        account = self.db.execute(
            select(BotPlatformAccount).where(
                BotPlatformAccount.platform == platform,
                BotPlatformAccount.verification_code == code,
                BotPlatformAccount.verified == False,  # noqa: E712
            )
        ).scalar_one_or_none()

        if not account:
            return None

        # Check expiry (handle naive datetime from database)
        if account.verification_expires:
            expires = account.verification_expires
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires < now:
                return None

        # Check if this platform user is already linked to an account
        existing = self.db.execute(
            select(BotPlatformAccount).where(
                BotPlatformAccount.platform == platform,
                BotPlatformAccount.platform_user_id == platform_user_id,
                BotPlatformAccount.verified == True,  # noqa: E712
            )
        ).scalar_one_or_none()

        if existing:
            if existing.user_id == account.user_id:
                # Already linked to the same user - just delete the pending request
                self.db.delete(account)
                self.db.commit()
                return existing
            else:
                # Linked to a different user - unlink the old one first
                self.db.delete(existing)

        # Update account with verified info
        account.platform_user_id = platform_user_id
        if platform_username:
            account.platform_username = platform_username
        account.verified = True
        account.verification_code = None
        account.verification_expires = None

        self.db.commit()
        return account

    def get_linked_account(self, platform: str, platform_user_id: str) -> BotPlatformAccount | None:
        """Get a linked account if it exists and is verified.

        Args:
            platform: Platform name
            platform_user_id: Platform-specific user ID

        Returns:
            BotPlatformAccount if found and verified, None otherwise
        """
        return self.db.execute(
            select(BotPlatformAccount)
            .options(joinedload(BotPlatformAccount.user))  # Eager load user
            .where(
                BotPlatformAccount.platform == platform,
                BotPlatformAccount.platform_user_id == platform_user_id,
                BotPlatformAccount.verified == True,  # noqa: E712
            )
        ).scalar_one_or_none()

    def get_user_accounts(self, user_id: str, platform: str | None = None) -> list[BotPlatformAccount]:
        """Get all linked accounts for a user.

        Args:
            user_id: Atlas user ID
            platform: Optional platform filter

        Returns:
            List of BotPlatformAccount objects
        """
        query = select(BotPlatformAccount).where(BotPlatformAccount.user_id == user_id)
        if platform:
            query = query.where(BotPlatformAccount.platform == platform)
        return list(self.db.execute(query).scalars().all())

    def unlink_account(self, account_id: int) -> bool:
        """Unlink a platform account.

        Args:
            account_id: BotPlatformAccount ID

        Returns:
            True if account was deleted, False if not found
        """
        account = self.db.get(BotPlatformAccount, account_id)
        if not account:
            return False

        self.db.delete(account)
        self.db.commit()
        return True

    def unlink_user_platform(self, user_id: str, platform: str) -> bool:
        """Unlink all accounts for a user on a specific platform.

        Args:
            user_id: Atlas user ID
            platform: Platform name

        Returns:
            True if any accounts were deleted
        """
        accounts = self.db.execute(
            select(BotPlatformAccount).where(
                BotPlatformAccount.user_id == user_id,
                BotPlatformAccount.platform == platform,
            )
        ).scalars().all()

        if not accounts:
            return False

        for account in accounts:
            self.db.delete(account)

        self.db.commit()
        return True

    def get_user_by_platform(self, platform: str, platform_user_id: str) -> User | None:
        """Get Atlas user from their platform account.

        Args:
            platform: Platform name
            platform_user_id: Platform-specific user ID

        Returns:
            User if found and account is verified, None otherwise
        """
        account = self.get_linked_account(platform, platform_user_id)
        if not account:
            return None

        return self.db.get(User, account.user_id)

    def cleanup_expired_codes(self) -> int:
        """Remove expired verification codes.

        Returns:
            Number of accounts with expired codes that were cleaned up
        """
        now = datetime.now(UTC)

        expired = self.db.execute(
            select(BotPlatformAccount).where(
                BotPlatformAccount.verified == False,  # noqa: E712
                BotPlatformAccount.verification_expires < now,
            )
        ).scalars().all()

        count = 0
        for account in expired:
            # Delete accounts that were never verified (pending placeholder)
            if account.platform_user_id.startswith("pending:"):
                self.db.delete(account)
            else:
                # Clear code but keep account for potential re-verification
                account.verification_code = None
                account.verification_expires = None
            count += 1

        if count:
            self.db.commit()
        return count
