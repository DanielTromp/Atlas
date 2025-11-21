"""Authentication routes - login, logout, and user profile."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from infrastructure_atlas.application.dto import user_to_dto
from infrastructure_atlas.application.security import verify_password
from infrastructure_atlas.application.services import DefaultUserService
from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.db.models import User
from infrastructure_atlas.infrastructure.db import mappers
from infrastructure_atlas.interfaces.api.dependencies import CurrentUserDep, get_user_service

router = APIRouter()
SessionLocal = get_sessionmaker()

UserServiceDep = Annotated[DefaultUserService, Depends(get_user_service)]

# Session constants
SESSION_USER_KEY = "user_id"


# Helper functions


def get_user_by_username(db: Session, username: str) -> User | None:
    """Get user by username (case-insensitive)."""
    uname = (username or "").strip().lower()
    if not uname:
        return None
    stmt = select(User).where(User.username == uname)
    return db.execute(stmt).scalar_one_or_none()


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Authenticate user with username and password."""
    user = get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if verify_password(password, user.password_hash):
        return user
    return None


def _has_ui_session(request: Request) -> bool:
    """Check if request has a valid UI session."""
    try:
        return bool(request.session.get(SESSION_USER_KEY))
    except Exception:
        return False


def _login_html(next_url: str, error: str | None = None) -> HTMLResponse:
    """Generate login HTML page."""
    err_html = f'<div class="error">{error}</div>' if error else ""
    logo_svg = ""
    logo_path = Path(__file__).parent.parent.parent / "api" / "static" / "logo.svg"
    if logo_path.exists():
        try:
            raw_logo = logo_path.read_text(encoding="utf-8")
            start = raw_logo.find("<svg")
            if start != -1:
                logo_svg = raw_logo[start:]
            else:
                logo_svg = raw_logo
        except OSError:
            logo_svg = ""
    logo_html = logo_svg or '<span class="brand-logo__fallback" aria-hidden="true"></span>'
    return HTMLResponse(
        f"""
        <!doctype html>
        <html><head>
        <meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <title>Login — Infrastructure Atlas</title>
        <style>
        * {{ box-sizing: border-box; }}

        /* Theme CSS Variables */
        :root {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #fbfdff 0%, #f6f8fb 100%);
          --panel: #ffffff;
          --text: #0f172a;
          --muted: #64748b;
          --accent: #7c3aed;
          --grid-border: #e5e7eb;
          --input-bg: #ffffff;
          --input-border: #e5e7eb;
          --input-placeholder: rgba(100, 116, 139, 0.8);
          --focus-ring: rgba(59, 130, 246, 0.18);
          --panel-shadow: 0 8px 28px rgba(2, 6, 23, 0.08);
          --btn-gradient: linear-gradient(180deg, #ffffff, #f8fafc);
          --btn-text: #0f172a;
          --btn-hover-shadow: 0 12px 26px rgba(2, 6, 23, 0.12);
        }}

        body.theme-nebula-light {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #f1efff 0%, #d8ceff 100%);
          --panel: #ffffff;
          --text: #1a1337;
          --muted: #65589a;
          --accent: #7917f8;
          --grid-border: #beb3f1;
          --input-bg: #ffffff;
          --input-border: #b8adf1;
          --input-placeholder: rgba(90, 77, 131, 0.72);
          --focus-ring: rgba(121, 23, 248, 0.28);
          --panel-shadow: 0 10px 27px rgba(69, 28, 148, 0.14);
          --btn-gradient: linear-gradient(180deg, #ffffff, #e6defc);
          --btn-text: #1a1337;
          --btn-hover-shadow: 0 14px 30px rgba(80, 32, 165, 0.2);
        }}

        body.theme-nebula-dark {{
          color-scheme: dark;
          --bg-gradient: radial-gradient(120% 160% at 50% 10%, rgba(156, 75, 255, 0.25) 0%, rgba(53, 20, 112, 0.6) 35%, #09011f 68%, #050014 100%);
          --panel: rgba(24, 10, 58, 0.92);
          --text: #f5f3ff;
          --muted: #b2a8d9;
          --accent: #a855f7;
          --grid-border: rgba(155, 100, 255, 0.3);
          --input-bg: rgba(31, 15, 66, 0.92);
          --input-border: rgba(170, 111, 255, 0.55);
          --input-placeholder: rgba(212, 198, 255, 0.6);
          --focus-ring: rgba(168, 85, 247, 0.45);
          --panel-shadow: 0 22px 48px rgba(26, 8, 58, 0.65);
          --btn-gradient: linear-gradient(180deg, rgba(138, 78, 255, 0.96), rgba(98, 49, 209, 0.92));
          --btn-text: #f8f5ff;
          --btn-hover-shadow: 0 18px 46px rgba(98, 58, 178, 0.5);
        }}

        body.theme-forest-light {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #f0fdf4 0%, #bbf7d0 100%);
          --panel: #ffffff;
          --text: #052e16;
          --muted: #166534;
          --accent: #16a34a;
          --grid-border: #86efac;
          --input-bg: #ffffff;
          --input-border: #86efac;
          --input-placeholder: rgba(21, 128, 61, 0.72);
          --focus-ring: rgba(22, 163, 74, 0.28);
          --panel-shadow: 0 10px 27px rgba(4, 120, 87, 0.14);
          --btn-gradient: linear-gradient(180deg, #ffffff, #dcfce7);
          --btn-text: #052e16;
          --btn-hover-shadow: 0 14px 30px rgba(4, 120, 87, 0.2);
        }}

        body.theme-forest-dark {{
          color-scheme: dark;
          --bg-gradient: radial-gradient(140% 180% at 50% 0%, rgba(34, 197, 94, 0.15) 0%, rgba(21, 128, 61, 0.25) 30%, #0a2818 65%, #051912 100%);
          --panel: rgba(20, 83, 45, 0.85);
          --text: #e7faf0;
          --muted: #86efac;
          --accent: #22c55e;
          --grid-border: rgba(34, 197, 94, 0.25);
          --input-bg: rgba(21, 128, 61, 0.85);
          --input-border: rgba(34, 197, 94, 0.4);
          --input-placeholder: rgba(167, 243, 208, 0.55);
          --focus-ring: rgba(34, 197, 94, 0.4);
          --panel-shadow: 0 18px 42px rgba(8, 69, 35, 0.55);
          --btn-gradient: linear-gradient(180deg, rgba(34, 197, 94, 0.95), rgba(21, 128, 61, 0.9));
          --btn-text: #ffffff;
          --btn-hover-shadow: 0 14px 35px rgba(34, 197, 94, 0.45);
        }}

        body.theme-jade-light {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #ecfeff 0%, #a5f3fc 100%);
          --panel: #ffffff;
          --text: #083344;
          --muted: #0e7490;
          --accent: #06b6d4;
          --grid-border: #67e8f9;
          --input-bg: #ffffff;
          --input-border: #67e8f9;
          --input-placeholder: rgba(14, 116, 144, 0.72);
          --focus-ring: rgba(6, 182, 212, 0.28);
          --panel-shadow: 0 10px 27px rgba(8, 145, 178, 0.14);
          --btn-gradient: linear-gradient(180deg, #ffffff, #cffafe);
          --btn-text: #083344;
          --btn-hover-shadow: 0 14px 30px rgba(8, 145, 178, 0.2);
        }}

        body.theme-jade-dark {{
          color-scheme: dark;
          --bg-gradient: radial-gradient(140% 180% at 50% 0%, rgba(6, 182, 212, 0.2) 0%, rgba(14, 116, 144, 0.3) 30%, #042f2e 65%, #022020 100%);
          --panel: rgba(14, 116, 144, 0.88);
          --text: #e0f2fe;
          --muted: #67e8f9;
          --accent: #06b6d4;
          --grid-border: rgba(6, 182, 212, 0.28);
          --input-bg: rgba(8, 145, 178, 0.85);
          --input-border: rgba(6, 182, 212, 0.42);
          --input-placeholder: rgba(165, 243, 252, 0.55);
          --focus-ring: rgba(6, 182, 212, 0.42);
          --panel-shadow: 0 18px 42px rgba(8, 51, 68, 0.6);
          --btn-gradient: linear-gradient(180deg, rgba(6, 182, 212, 0.96), rgba(8, 145, 178, 0.92));
          --btn-text: #ffffff;
          --btn-hover-shadow: 0 14px 35px rgba(6, 182, 212, 0.45);
        }}

        body.theme-coral-light {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%);
          --panel: #ffffff;
          --text: #431407;
          --muted: #9a3412;
          --accent: #f97316;
          --grid-border: #fdba74;
          --input-bg: #ffffff;
          --input-border: #fdba74;
          --input-placeholder: rgba(154, 52, 18, 0.72);
          --focus-ring: rgba(249, 115, 22, 0.28);
          --panel-shadow: 0 10px 27px rgba(234, 88, 12, 0.14);
          --btn-gradient: linear-gradient(180deg, #ffffff, #fed7aa);
          --btn-text: #431407;
          --btn-hover-shadow: 0 14px 30px rgba(234, 88, 12, 0.2);
        }}

        body.theme-coral-dark {{
          color-scheme: dark;
          --bg-gradient: radial-gradient(140% 180% at 50% 0%, rgba(249, 115, 22, 0.18) 0%, rgba(194, 65, 12, 0.25) 30%, #1c1917 65%, #0c0a09 100%);
          --panel: rgba(41, 37, 36, 0.9);
          --text: #fef3c7;
          --muted: #fdba74;
          --accent: #f97316;
          --grid-border: rgba(249, 115, 22, 0.3);
          --input-bg: rgba(68, 64, 60, 0.92);
          --input-border: rgba(249, 115, 22, 0.45);
          --input-placeholder: rgba(254, 215, 170, 0.55);
          --focus-ring: rgba(249, 115, 22, 0.4);
          --panel-shadow: 0 18px 42px rgba(41, 37, 36, 0.65);
          --btn-gradient: linear-gradient(180deg, rgba(249, 115, 22, 0.96), rgba(234, 88, 12, 0.92));
          --btn-text: #ffffff;
          --btn-hover-shadow: 0 14px 35px rgba(249, 115, 22, 0.48);
        }}

        body.theme-midnight-light {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #eff6ff 0%, #bfdbfe 100%);
          --panel: #ffffff;
          --text: #0f172a;
          --muted: #1e40af;
          --accent: #3b82f6;
          --grid-border: #93c5fd;
          --input-bg: #ffffff;
          --input-border: #93c5fd;
          --input-placeholder: rgba(30, 64, 175, 0.72);
          --focus-ring: rgba(59, 130, 246, 0.28);
          --panel-shadow: 0 10px 27px rgba(30, 64, 175, 0.14);
          --btn-gradient: linear-gradient(180deg, #ffffff, #dbeafe);
          --btn-text: #0f172a;
          --btn-hover-shadow: 0 14px 30px rgba(30, 64, 175, 0.2);
        }}

        body.theme-midnight-dark {{
          color-scheme: dark;
          --bg-gradient: radial-gradient(140% 180% at 50% 0%, rgba(59, 130, 246, 0.18) 0%, rgba(30, 64, 175, 0.28) 30%, #0f172a 65%, #020617 100%);
          --panel: rgba(30, 41, 59, 0.9);
          --text: #f1f5f9;
          --muted: #94a3b8;
          --accent: #3b82f6;
          --grid-border: rgba(59, 130, 246, 0.28);
          --input-bg: rgba(51, 65, 85, 0.9);
          --input-border: rgba(59, 130, 246, 0.42);
          --input-placeholder: rgba(203, 213, 225, 0.55);
          --focus-ring: rgba(59, 130, 246, 0.4);
          --panel-shadow: 0 18px 42px rgba(15, 23, 42, 0.65);
          --btn-gradient: linear-gradient(180deg, rgba(59, 130, 246, 0.96), rgba(37, 99, 235, 0.92));
          --btn-text: #ffffff;
          --btn-hover-shadow: 0 14px 35px rgba(59, 130, 246, 0.45);
        }}

        body.theme-silver-light {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #ffffff 0%, #f5f5f5 100%);
          --panel: #ffffff;
          --text: #0f172a;
          --muted: #64748b;
          --accent: #64748b;
          --grid-border: #e2e8f0;
          --input-bg: #ffffff;
          --input-border: #cbd5e1;
          --input-placeholder: rgba(100, 116, 139, 0.65);
          --focus-ring: rgba(100, 116, 139, 0.2);
          --panel-shadow: 0 8px 28px rgba(15, 23, 42, 0.06);
          --btn-gradient: linear-gradient(180deg, #ffffff, #f8fafc);
          --btn-text: #0f172a;
          --btn-hover-shadow: 0 12px 28px rgba(100, 116, 139, 0.15);
        }}

        body.theme-silver-dark {{
          color-scheme: dark;
          --bg-gradient: radial-gradient(140% 180% at 50% 0%, rgba(148, 163, 184, 0.12) 0%, rgba(71, 85, 105, 0.18) 25%, #0f0f0f 60%, #000000 100%);
          --panel: rgba(23, 23, 23, 0.92);
          --text: #e2e8f0;
          --muted: #94a3b8;
          --accent: #94a3b8;
          --grid-border: rgba(148, 163, 184, 0.22);
          --input-bg: rgba(30, 30, 30, 0.92);
          --input-border: rgba(148, 163, 184, 0.35);
          --input-placeholder: rgba(148, 163, 184, 0.5);
          --focus-ring: rgba(148, 163, 184, 0.35);
          --panel-shadow: 0 20px 48px rgba(0, 0, 0, 0.75), 0 0 0 1px rgba(148, 163, 184, 0.08);
          --btn-gradient: linear-gradient(180deg, rgba(148, 163, 184, 0.22), rgba(100, 116, 139, 0.18));
          --btn-text: #f8fafc;
          --btn-hover-shadow: 0 16px 40px rgba(148, 163, 184, 0.25);
        }}

        body.theme-default {{
          color-scheme: light;
          --bg-gradient: linear-gradient(180deg, #fbfdff 0%, #f6f8fb 100%);
          --panel: #ffffff;
          --text: #0f172a;
          --muted: #64748b;
          --accent: #7c3aed;
          --grid-border: #e5e7eb;
          --input-bg: #ffffff;
          --input-border: #e5e7eb;
          --input-placeholder: rgba(100, 116, 139, 0.8);
          --focus-ring: rgba(59, 130, 246, 0.18);
          --panel-shadow: 0 8px 28px rgba(2, 6, 23, 0.08);
          --btn-gradient: linear-gradient(180deg, #ffffff, #f8fafc);
          --btn-text: #0f172a;
          --btn-hover-shadow: 0 12px 26px rgba(2, 6, 23, 0.12);
        }}

        body {{
          font-family: -apple-system, system-ui, Segoe UI, Roboto, Ubuntu, Cantarell, 'Helvetica Neue', Arial, 'Noto Sans', 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
          background: var(--bg-gradient);
          color: var(--text);
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 100vh;
          margin: 0;
          padding: 24px;
        }}
        .box {{
          background: var(--panel);
          padding: 32px 30px;
          border-radius: 16px;
          width: min(400px, 100%);
          border: 1px solid var(--grid-border);
          box-shadow: var(--panel-shadow);
          backdrop-filter: blur(12px);
          display: flex;
          flex-direction: column;
          gap: 18px;
        }}
        .brand {{ display: flex; align-items: center; gap: 12px; }}
        .brand-logo {{ display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; }}
        .brand-logo svg {{ width: 100%; height: auto; display: block; }}
        .brand-logo__fallback {{ display: block; width: 34px; height: 34px; }}
        .brand h1 {{ font-size: 20px; margin: 0; letter-spacing: 0.28px; font-weight: 680; }}
        label {{ display: block; }}
        input[type=text], input[type=password] {{
          width: 100%;
          padding: 12px 14px;
          border-radius: 10px;
          border: 1px solid var(--input-border);
          background: var(--input-bg);
          color: var(--text);
          font-size: 14px;
          transition: border-color 160ms ease, box-shadow 160ms ease;
        }}
        input[type=text]::placeholder, input[type=password]::placeholder {{
          color: var(--input-placeholder);
        }}
        input[type=text]:focus, input[type=password]:focus {{
          outline: none;
          border-color: var(--accent);
          box-shadow: 0 0 0 3px var(--focus-ring);
        }}
        button {{
          display: block;
          width: 100%;
          padding: 12px 14px;
          border-radius: 10px;
          border: 1px solid var(--accent);
          background: var(--btn-gradient);
          color: var(--btn-text);
          margin-top: 4px;
          cursor: pointer;
          font-weight: 600;
          transition: transform 120ms ease, box-shadow 160ms ease;
        }}
        button:hover {{
          transform: translateY(-1px);
          box-shadow: var(--btn-hover-shadow);
        }}
        button:active {{ transform: translateY(0); }}
        .tagline {{ margin: 0; color: var(--muted); font-size: 13px; }}
        .hint {{ color: var(--muted); font-size: 12px; text-align: center; margin-top: 8px; }}
        .error {{
          background: rgba(127, 29, 29, 0.85);
          color: #fecaca;
          padding: 10px 12px;
          border-radius: 10px;
          border: 1px solid rgba(248, 113, 113, 0.65);
          margin: 4px 0;
        }}

        /* Logo inversion for dark themes */
        body.theme-nebula-dark .brand-logo,
        body.theme-forest-dark .brand-logo,
        body.theme-jade-dark .brand-logo,
        body.theme-coral-dark .brand-logo,
        body.theme-midnight-dark .brand-logo,
        body.theme-silver-dark .brand-logo {{
          filter: brightness(0) invert(1);
        }}

        /* Logo normal for light themes */
        body.theme-default .brand-logo,
        body.theme-nebula-light .brand-logo,
        body.theme-forest-light .brand-logo,
        body.theme-jade-light .brand-logo,
        body.theme-coral-light .brand-logo,
        body.theme-midnight-light .brand-logo,
        body.theme-silver-light .brand-logo {{
          filter: none;
        }}
        </style>
        <script>
          (function() {{
            try {{
              var defaultTheme = 'silver-dark';
              fetch('/config/ui')
                .then(function(res) {{ return res.json(); }})
                .then(function(data) {{
                  if (data && data.theme_default) {{
                    var theme = data.theme_default;
                    if (theme === 'nebula') {{
                      theme = 'nebula-dark';
                    }}
                    document.body.className = 'theme-' + theme;
                  }} else {{
                    document.body.className = 'theme-' + defaultTheme;
                  }}
                }})
                .catch(function() {{
                  document.body.className = 'theme-' + defaultTheme;
                }});
            }} catch (err) {{
              document.body.className = 'theme-silver-dark';
            }}
          }})();
        </script>
        </head><body class=\"theme-silver-dark\">
        <form class=\"box\" method=\"post\" action=\"/auth/login\">
          <div class=\"brand\">
            <div class=\"brand-logo\">{logo_html}</div>
            <h1>Infrastructure Atlas</h1>
          </div>
          <p class=\"tagline\">Sign in to manage Infrastructure Atlas exports and tools.</p>
          {err_html}
          <input type=\"hidden\" name=\"next\" value=\"{next_url}\" />
          <label>
            <input type=\"text\" name=\"username\" placeholder=\"Username\" autofocus required />
          </label>
          <label>
            <input type=\"password\" name=\"password\" placeholder=\"Password\" required />
          </label>
          <button type=\"submit\">Sign in</button>
          <div class=\"hint\">UI access enables API calls from this browser.</div>
        </form>
        </body></html>
        """
    )


# API Routes


@router.get("/auth/me")
def auth_me(
    current_user: CurrentUserDep,
    user_service: UserServiceDep,
):
    """Return the authenticated user's profile."""
    entity = user_service.get_current_user(current_user.id)
    if entity is None:
        entity = mappers.user_to_entity(current_user)
    dto = user_to_dto(entity)
    return dto.dict_clean()


@router.get("/auth/login")
def auth_login_form(request: Request, next_url: str | None = None):
    """Display login form."""
    n = next_url or "/app/"
    # If already logged in, redirect to target
    if _has_ui_session(request):
        return RedirectResponse(url=n)
    return _login_html(n)


@router.post("/auth/login")
async def auth_login(request: Request):
    """Process login form submission."""
    content_type = request.headers.get("content-type", "").lower()
    is_json = "application/json" in content_type

    if is_json:
        payload = await request.json()
    else:
        payload = await request.form()

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    next_url = str(payload.get("next") or "/app/")
    if not next_url.startswith("/"):
        next_url = "/app/"

    with SessionLocal() as db:
        user = authenticate_user(db, username, password)
        if user:
            request.session.clear()
            request.session[SESSION_USER_KEY] = user.id
            request.session["username"] = user.username
            if is_json:
                return {"status": "ok", "next": next_url}
            return RedirectResponse(url=next_url, status_code=303)

    if is_json:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _login_html(next_url, error="Invalid username or password")


@router.get("/auth/logout")
def auth_logout(request: Request):
    """Log out and redirect to login page."""
    try:
        request.session.clear()
    except Exception:
        pass
    return RedirectResponse(url="/auth/login")


__all__ = ["router"]
