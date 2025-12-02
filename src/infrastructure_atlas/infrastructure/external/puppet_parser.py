"""Parser for Puppet manifests to extract user and group definitions.

This parser extracts user and group information from Puppet .pp files
following the VoiceWorks/Enreach user management structure:
- site/user/manifests/virtual_users/*.pp - User definitions
- site/user/manifests/virtual_groups/*.pp - Group definitions with members
- site/user/manifests/groups/*_full.pp - Sudo access definitions
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PuppetUser:
    """Parsed Puppet user definition."""

    username: str
    uid: int | None = None
    key_type: str | None = None
    key_name: str | None = None  # Usually email address
    has_password: bool = False
    has_ssh_key: bool = False
    source_file: str | None = None
    enabled: bool = True  # False if commented out in virtual.pp
    # Password details
    password_hash: str | None = None  # Full hash for analysis
    password_algorithm: str | None = None  # md5, sha256, sha512, locked, none
    account_locked: bool = False  # True if password is '!' or '*'
    # SSH key details
    ssh_key: str | None = None  # The actual public key content
    ssh_key_bits: int | None = None  # Key size in bits (derived from key)


@dataclass(slots=True)
class PuppetGroup:
    """Parsed Puppet group definition."""

    name: str
    gid: int | None = None
    members: list[str] = field(default_factory=list)
    not_members: list[str] = field(default_factory=list)
    source_file: str | None = None


@dataclass(slots=True)
class PuppetUserAccess:
    """Represents a user's access to a group with their permission level."""

    username: str
    group_name: str
    has_sudo: bool = False
    access_type: str = "user"  # "user" or "full"


@dataclass(slots=True)
class PuppetInventory:
    """Complete inventory of Puppet user management data."""

    users: dict[str, PuppetUser] = field(default_factory=dict)
    groups: dict[str, PuppetGroup] = field(default_factory=dict)
    user_access: list[PuppetUserAccess] = field(default_factory=list)
    sudo_users: set[str] = field(default_factory=set)
    removed_users: set[str] = field(default_factory=set)


class PuppetParser:
    """Parser for Puppet user management manifests."""

    # Regex patterns for parsing .pp files
    _USER_BLOCK_PATTERN = re.compile(
        r"@user::vwuser\s*\{\s*['\"]([^'\"]+)['\"]\s*:",
        re.IGNORECASE | re.MULTILINE,
    )
    _UID_PATTERN = re.compile(r"uid\s*=>\s*(\d+)", re.IGNORECASE)
    _PASSWORD_PATTERN = re.compile(r"password\s*=>\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
    _KEY_TYPE_PATTERN = re.compile(r"key_type\s*=>\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
    _KEY_PATTERN = re.compile(r"(?<!key_type\s|key_name\s)key\s*=>\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
    _KEY_NAME_PATTERN = re.compile(r"key_name\s*=>\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)

    _GROUP_BLOCK_PATTERN = re.compile(
        r"@user::vwgroup\s*\{\s*['\"]([^'\"]+)['\"]\s*:",
        re.IGNORECASE | re.MULTILINE,
    )
    _GID_PATTERN = re.compile(r"gid\s*=>\s*(\d+)", re.IGNORECASE)
    _MEMBERS_PATTERN = re.compile(
        r"\$members\s*=\s*\[\s*([^\]]*)\]",
        re.IGNORECASE | re.DOTALL,
    )
    _NOTMEMBERS_PATTERN = re.compile(
        r"\$notmembers\s*=\s*\[\s*([^\]]*)\]",
        re.IGNORECASE | re.DOTALL,
    )

    _CLASS_DECLARATION_PATTERN = re.compile(
        r"class\s*\{\s*['\"]user::virtual_users::([^'\"]+)['\"]\s*:\s*\}",
        re.IGNORECASE,
    )
    _COMMENTED_CLASS_PATTERN = re.compile(
        r"#\s*class\s*\{\s*['\"]user::virtual_users::([^'\"]+)['\"]\s*:\s*\}",
        re.IGNORECASE,
    )

    _REMOVE_USER_PATTERN = re.compile(
        r"user\s*\{\s*['\"]([^'\"]+)['\"]\s*:\s*ensure\s*=>\s*['\"]?absent['\"]?",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, repo_path: Path) -> None:
        """Initialize parser with repository path.

        Args:
            repo_path: Path to the cloned Puppet repository.
        """
        self.repo_path = Path(repo_path)

    def parse_inventory(self) -> PuppetInventory:
        """Parse the complete Puppet user management inventory.

        Returns:
            PuppetInventory with all parsed data.
        """
        inventory = PuppetInventory()

        # Parse user definitions
        self._parse_virtual_users(inventory)

        # Parse group definitions
        self._parse_virtual_groups(inventory)

        # Check which users are enabled in virtual.pp
        self._parse_virtual_pp(inventory)

        # Parse remove.pp to find removed users
        self._parse_remove_pp(inventory)

        # Parse sudo access from groups/*_full.pp
        self._parse_sudo_access(inventory)

        # Build user access relationships
        self._build_user_access(inventory)

        return inventory

    def _parse_virtual_users(self, inventory: PuppetInventory) -> None:
        """Parse user definitions from virtual_users/*.pp files."""
        users_dir = self.repo_path / "site" / "user" / "manifests" / "virtual_users"
        if not users_dir.exists():
            logger.warning("Virtual users directory not found: %s", users_dir)
            return

        for pp_file in users_dir.glob("*.pp"):
            try:
                content = pp_file.read_text(encoding="utf-8", errors="replace")
                user = self._parse_user_file(content, pp_file.name)
                if user:
                    inventory.users[user.username] = user
            except Exception as exc:
                logger.warning("Failed to parse user file %s: %s", pp_file, exc)

    def _parse_user_file(self, content: str, filename: str) -> PuppetUser | None:
        """Parse a single user definition file."""
        match = self._USER_BLOCK_PATTERN.search(content)
        if not match:
            return None

        username = match.group(1)
        user = PuppetUser(username=username, source_file=filename)

        # Extract UID
        uid_match = self._UID_PATTERN.search(content)
        if uid_match:
            try:
                user.uid = int(uid_match.group(1))
            except ValueError:
                pass

        # Extract password and analyze hash
        password_match = self._PASSWORD_PATTERN.search(content)
        if password_match:
            password_value = password_match.group(1).strip()
            if password_value:
                user.password_hash = password_value
                user.has_password = True

                # Determine password algorithm from hash prefix
                if password_value in ("!", "*", "!!", ""):
                    user.account_locked = True
                    user.password_algorithm = "locked"
                    user.has_password = False
                elif password_value.startswith("$6$"):
                    user.password_algorithm = "sha512"  # Strong
                elif password_value.startswith("$5$"):
                    user.password_algorithm = "sha256"  # Good
                elif password_value.startswith("$1$"):
                    user.password_algorithm = "md5"  # Weak/legacy
                elif password_value.startswith("$2a$") or password_value.startswith("$2b$"):
                    user.password_algorithm = "bcrypt"  # Strong
                elif password_value.startswith("$y$"):
                    user.password_algorithm = "yescrypt"  # Modern/strong
                else:
                    user.password_algorithm = "unknown"

        # Extract key type
        key_type_match = self._KEY_TYPE_PATTERN.search(content)
        if key_type_match:
            key_type = key_type_match.group(1)
            user.key_type = key_type if key_type else None

        # Extract SSH key content
        key_match = self._KEY_PATTERN.search(content)
        if key_match:
            key_content = key_match.group(1).strip()
            if key_content:
                user.ssh_key = key_content
                user.has_ssh_key = True
                # Estimate key size from base64 length (rough approximation)
                user.ssh_key_bits = self._estimate_key_bits(user.key_type, key_content)

        # Extract key name (email)
        key_name_match = self._KEY_NAME_PATTERN.search(content)
        if key_name_match:
            user.key_name = key_name_match.group(1) or None

        return user

    def _estimate_key_bits(self, key_type: str | None, key_content: str) -> int | None:
        """Estimate SSH key size from type and base64 content length."""
        if not key_content:
            return None

        # Decode base64 length to approximate key size
        import base64

        try:
            decoded_len = len(base64.b64decode(key_content))
        except Exception:
            return None

        key_type_lower = (key_type or "").lower()

        if "ed25519" in key_type_lower:
            return 256  # Ed25519 is always 256 bits
        elif "ecdsa" in key_type_lower:
            # ECDSA key size varies: nistp256=256, nistp384=384, nistp521=521
            if "nistp256" in key_type_lower or decoded_len < 150:
                return 256
            elif "nistp384" in key_type_lower or decoded_len < 200:
                return 384
            else:
                return 521
        elif "rsa" in key_type_lower or not key_type_lower:
            # RSA key size estimation from decoded length
            # RSA keys: ~140 bytes for 1024, ~270 for 2048, ~550 for 4096
            if decoded_len < 200:
                return 1024
            elif decoded_len < 400:
                return 2048
            elif decoded_len < 700:
                return 4096
            else:
                return 8192

        return None

    def _parse_virtual_groups(self, inventory: PuppetInventory) -> None:
        """Parse group definitions from virtual_groups/*.pp files."""
        groups_dir = self.repo_path / "site" / "user" / "manifests" / "virtual_groups"
        if not groups_dir.exists():
            logger.warning("Virtual groups directory not found: %s", groups_dir)
            return

        for pp_file in groups_dir.glob("*.pp"):
            try:
                content = pp_file.read_text(encoding="utf-8", errors="replace")
                group = self._parse_group_file(content, pp_file.name)
                if group:
                    inventory.groups[group.name] = group
            except Exception as exc:
                logger.warning("Failed to parse group file %s: %s", pp_file, exc)

    def _parse_group_file(self, content: str, filename: str) -> PuppetGroup | None:
        """Parse a single group definition file."""
        # Extract group name from @user::vwgroup block or from filename
        match = self._GROUP_BLOCK_PATTERN.search(content)
        group_name = match.group(1) if match else filename.replace(".pp", "")

        group = PuppetGroup(name=group_name, source_file=filename)

        # Extract GID
        gid_match = self._GID_PATTERN.search(content)
        if gid_match:
            try:
                group.gid = int(gid_match.group(1))
            except ValueError:
                pass

        # Extract members
        members_match = self._MEMBERS_PATTERN.search(content)
        if members_match:
            members_str = members_match.group(1)
            group.members = self._parse_array_values(members_str)

        # Extract notmembers
        notmembers_match = self._NOTMEMBERS_PATTERN.search(content)
        if notmembers_match:
            notmembers_str = notmembers_match.group(1)
            group.not_members = self._parse_array_values(notmembers_str)

        return group

    def _parse_array_values(self, array_str: str) -> list[str]:
        """Parse array values from Puppet array syntax."""
        # Match quoted strings
        values = re.findall(r"['\"]([^'\"]+)['\"]", array_str)
        return [v.strip() for v in values if v.strip()]

    def _parse_virtual_pp(self, inventory: PuppetInventory) -> None:
        """Parse virtual.pp to determine which users are enabled."""
        virtual_pp = self.repo_path / "site" / "user" / "manifests" / "virtual.pp"
        if not virtual_pp.exists():
            logger.warning("virtual.pp not found: %s", virtual_pp)
            return

        try:
            content = virtual_pp.read_text(encoding="utf-8", errors="replace")

            # Find commented out users
            for match in self._COMMENTED_CLASS_PATTERN.finditer(content):
                username = match.group(1)
                if username in inventory.users:
                    inventory.users[username].enabled = False

            # Find enabled users
            for match in self._CLASS_DECLARATION_PATTERN.finditer(content):
                username = match.group(1)
                if username in inventory.users:
                    inventory.users[username].enabled = True

        except Exception as exc:
            logger.warning("Failed to parse virtual.pp: %s", exc)

    def _parse_remove_pp(self, inventory: PuppetInventory) -> None:
        """Parse remove.pp to find users marked for removal."""
        remove_pp = self.repo_path / "site" / "user" / "manifests" / "remove.pp"
        if not remove_pp.exists():
            return

        try:
            content = remove_pp.read_text(encoding="utf-8", errors="replace")
            for match in self._REMOVE_USER_PATTERN.finditer(content):
                username = match.group(1)
                inventory.removed_users.add(username)
                # Mark as disabled if exists
                if username in inventory.users:
                    inventory.users[username].enabled = False
        except Exception as exc:
            logger.warning("Failed to parse remove.pp: %s", exc)

    def _parse_sudo_access(self, inventory: PuppetInventory) -> None:
        """Parse groups/*_full.pp files to determine sudo access."""
        groups_dir = self.repo_path / "site" / "user" / "manifests" / "groups"
        if not groups_dir.exists():
            return

        # Parse *_full.pp files for sudo access
        for pp_file in groups_dir.glob("*_full.pp"):
            try:
                content = pp_file.read_text(encoding="utf-8", errors="replace")
                # Check if this grants sudo access (has sudoers file reference)
                if "/etc/sudoers.d/" in content:
                    # Extract users who get this access
                    # Can be individual user files (username_full.pp) or group-based

                    # Check if it's for a specific user
                    user_realize = re.search(
                        r"User::Vwuser\[\s*['\"]([^'\"]+)['\"]\s*\]",
                        content,
                        re.IGNORECASE,
                    )
                    if user_realize:
                        username = user_realize.group(1)
                        inventory.sudo_users.add(username)

                    # Check if it references a group's members
                    group_members_ref = re.search(
                        r"\$user::virtual_groups::([^:]+)::members",
                        content,
                        re.IGNORECASE,
                    )
                    if group_members_ref:
                        group_name = group_members_ref.group(1)
                        if group_name in inventory.groups:
                            for member in inventory.groups[group_name].members:
                                inventory.sudo_users.add(member)

            except Exception as exc:
                logger.warning("Failed to parse sudo file %s: %s", pp_file, exc)

        # Also check sudoers files directly
        sudoers_dir = self.repo_path / "site" / "user" / "files" / "groups"
        if sudoers_dir.exists():
            for sudoers_file in sudoers_dir.glob("*_full"):
                try:
                    content = sudoers_file.read_text(encoding="utf-8", errors="replace")
                    # Parse sudoers format: username ALL=(ALL) ALL or %groupname ALL=(ALL) ALL
                    user_match = re.search(r"^(\w+)\s+ALL=", content, re.MULTILINE)
                    if user_match and not user_match.group(1).startswith("%"):
                        inventory.sudo_users.add(user_match.group(1))
                except Exception as exc:
                    logger.warning("Failed to parse sudoers file %s: %s", sudoers_file, exc)

    def _build_user_access(self, inventory: PuppetInventory) -> None:
        """Build user access relationships from groups."""
        for group_name, group in inventory.groups.items():
            for member in group.members:
                # Skip if user is in notmembers
                if member in group.not_members:
                    continue

                has_sudo = member in inventory.sudo_users
                access_type = "full" if has_sudo else "user"

                access = PuppetUserAccess(
                    username=member,
                    group_name=group_name,
                    has_sudo=has_sudo,
                    access_type=access_type,
                )
                inventory.user_access.append(access)


__all__ = [
    "PuppetGroup",
    "PuppetInventory",
    "PuppetParser",
    "PuppetUser",
    "PuppetUserAccess",
]

