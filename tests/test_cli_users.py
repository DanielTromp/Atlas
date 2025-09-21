import json
import os
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from enreach_tools.cli import app
from enreach_tools.db.setup import init_database

runner = CliRunner()


def _with_temp_db():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = Path(tmpdir.name) / "cli.sqlite3"
    env = os.environ.copy()
    env_value = f"sqlite:///{db_path}"
    env["ENREACH_DB_URL"] = env_value
    os.environ["ENREACH_DB_URL"] = env_value
    init_database()
    return tmpdir, env


def _extract_json(output: str):
    lines = output.strip().splitlines()
    start = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            start = idx
            break
    if start is not None:
        json_str = "\n".join(line.strip() for line in lines[start:])
        return json.loads(json_str)
    raise AssertionError("No JSON payload found in output\n" + output)


def test_cli_user_create_set_password_and_list():
    tmpdir, env = _with_temp_db()
    try:
        result = runner.invoke(
            app,
            [
                "users",
                "create",
                "alice",
                "--password",
                "secretpass",
                "--display-name",
                "Alice",
                "--email",
                "alice@example.com",
                "--role",
                "member",
            ],
            env=env,
        )
        assert result.exit_code == 0
        assert "Created user" in result.stdout

        result = runner.invoke(
            app,
            [
                "users",
                "set-password",
                "alice",
                "--password",
                "newsecret",
            ],
            env=env,
        )
        assert result.exit_code == 0
        assert "Password updated" in result.stdout

        result = runner.invoke(app, ["users", "list", "--json"], env=env)
        assert result.exit_code == 0
        payload = _extract_json(result.stdout)
        usernames = {item["username"] for item in payload}
        assert "alice" in usernames
    finally:
        tmpdir.cleanup()
        os.environ.pop("ENREACH_DB_URL", None)
