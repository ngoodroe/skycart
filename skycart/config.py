"""Configuration for Skycart: loads secrets from .env and defines constants for
talking to Blackbaud's SKY API.

Finding your .env file
----------------------
We call `load_dotenv(find_dotenv(usecwd=True))`. The `usecwd=True` part matters:
it tells python-dotenv to start looking in the folder you're *running from*
(your notebook's folder, or wherever you ran `python`) and walk UP through
parent folders until it finds a .env file.

Without it, python-dotenv starts looking from the folder this config.py file
lives in. That's fine when skycart/ sits inside your project, but once Skycart
is pip-installed it lives deep inside your Python install (site-packages), and
your project's .env would never be found.

Reading credentials lazily
--------------------------
The credentials below are small functions, not plain variables. That way
`import skycart` always works -- even before you've set up a .env -- and you
only get the "missing environment variable" error when a call actually needs
the credential. Much friendlier in a notebook.
"""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))


def require_env(name: str) -> str:
    """Read a required environment variable, or raise a helpful error.

    Using this instead of os.environ[name] directly means that a missing
    variable gives you a clear message pointing at .env.example, instead of a
    bare KeyError with no context.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to a file named .env (in your project folder) and "
            "fill in your Blackbaud SKY API credentials from the developer dashboard: "
            "https://developer.blackbaud.com/skyapi/apps"
        )
    return value


# Blackbaud app credentials -- from the SKY API developer dashboard.
def client_id() -> str:
    return require_env("BB_CLIENT_ID")


def client_secret() -> str:
    return require_env("BB_CLIENT_SECRET")


def subscription_key() -> str:
    return require_env("BB_SUBSCRIPTION_KEY")


def redirect_uri() -> str:
    """Must exactly match the redirect URI registered for your app in the SKY
    API developer dashboard."""
    return os.environ.get("BB_REDIRECT_URI") or "http://localhost:8765/callback"


def token_cache_path() -> Path:
    """Where we cache the access/refresh tokens between runs, so you don't have
    to re-approve in the browser every time.

    Defaults to ~/.skycart/tokens.json -- in your home folder, outside any
    project, so it can never be committed to git by accident. Override with
    SKYCART_TOKEN_CACHE if you want it stored somewhere else.
    """
    custom = os.environ.get("SKYCART_TOKEN_CACHE")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".skycart" / "tokens.json"


# Blackbaud's OAuth2 endpoints (fixed, not configurable).
AUTHORIZATION_URL = "https://oauth2.sky.blackbaud.com/authorization"
TOKEN_URL = "https://oauth2.sky.blackbaud.com/token"

# Base URL for actual SKY API resource calls (constituents, gifts, queries, etc).
SKY_API_BASE_URL = "https://api.sky.blackbaud.com"
