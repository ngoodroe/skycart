"""OAuth2 Authorization Code flow for Blackbaud's SKY API.

This is a one-time (well, one-time-per-refresh-token-lifetime) interactive flow:
a person opens a browser, logs into Blackbaud, and approves this app's access.
Blackbaud then redirects back to BB_REDIRECT_URI with a short-lived code, which
we trade for an access token (good for ~60 minutes) and a refresh token (good
for much longer, used to get new access tokens without asking the user again).

Do that one-time login from a notebook cell:

    import skycart
    skycart.login()

or from a terminal:

    python -m skycart

There are two ways to catch Blackbaud's redirect:

1. The default: Skycart starts a tiny temporary web server on your machine at
   BB_REDIRECT_URI and catches the redirect itself. Nothing to copy or paste.
2. `skycart.login(paste=True)`: no web server. After approving, your browser
   lands on a localhost page that won't load -- that's expected. You copy that
   whole URL from the address bar and paste it back in. Use this when Skycart
   is running somewhere your browser can't reach directly, like inside a
   Docker container, a remote Jupyter server, or Google Colab.
"""

import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from . import config

# How long the local callback server waits for you to approve in the browser
# before giving up, so a notebook cell never hangs forever.
LOGIN_TIMEOUT_SECONDS = 300


def parse_callback_url(url: str) -> dict:
    """Pull the useful bits out of the URL Blackbaud redirects back to.

    Blackbaud calls back with either ?code=...&state=... (approved) or
    ?error=...&error_description=... (denied). Used by both login styles.
    """
    query = parse_qs(urlparse(url).query)
    return {
        "code": query.get("code", [None])[0],
        "state": query.get("state", [None])[0],
        "error": query.get("error", [None])[0],
    }


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches the redirect Blackbaud sends after the user approves (or denies)
    access, and stashes the result on the server object so wait_for_callback()
    can read it.

    Browsers sometimes make extra requests (like /favicon.ico), so anything
    that isn't our redirect path gets a 404 and is otherwise ignored.
    """

    def do_GET(self):
        expected_path = urlparse(config.redirect_uri()).path or "/"
        if urlparse(self.path).path != expected_path:
            self.send_response(404)
            self.end_headers()
            return

        self.server.callback_result = parse_callback_url(self.path)

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>Skycart</h1>"
            b"<p>You can close this tab and go back to your notebook or terminal.</p>"
            b"</body></html>"
        )

    def log_message(self, format, *args):
        # Silence BaseHTTPRequestHandler's default request logging to stderr.
        pass


def build_authorization_url(state: str) -> str:
    """Build the URL to send the user to in their browser to approve access.

    `state` is a random value we generate and check on the way back, so we can
    tell a real Blackbaud redirect apart from someone else hitting our local
    callback server (a basic CSRF protection).
    """
    params = {
        "client_id": config.client_id(),
        "response_type": "code",
        "redirect_uri": config.redirect_uri(),
        "state": state,
    }
    return f"{config.AUTHORIZATION_URL}?{urlencode(params)}"


def check_callback(result: dict | None, expected_state: str) -> str:
    """Make sure the redirect is a real approval for *this* login attempt, and
    return the authorization code from it."""
    if result is None or result.get("error"):
        error = result.get("error") if result else "no response received"
        raise RuntimeError(f"Blackbaud authorization failed: {error}")

    if result.get("state") != expected_state:
        raise RuntimeError("State mismatch on OAuth callback -- possible CSRF, aborting.")

    if not result.get("code"):
        raise RuntimeError("Blackbaud's redirect didn't include an authorization code.")

    return result["code"]


def wait_for_callback(expected_state: str) -> str:
    """Start a temporary local web server and wait for Blackbaud's redirect,
    then return the authorization code from it.

    HTTPServer.handle_request() (singular -- not serve_forever) handles one
    request and returns. We call it in a loop until the real redirect arrives
    (skipping stray requests like /favicon.ico) or we run out of time.
    """
    redirect = urlparse(config.redirect_uri())
    port = redirect.port or 80

    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.callback_result = None
    server.timeout = 5  # seconds handle_request() waits before returning empty-handed

    deadline = time.time() + LOGIN_TIMEOUT_SECONDS
    try:
        while server.callback_result is None and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if server.callback_result is None:
        raise RuntimeError(
            f"Timed out after {LOGIN_TIMEOUT_SECONDS // 60} minutes waiting for Blackbaud "
            "to redirect back. Run skycart.login() again when you're ready to approve."
        )

    return check_callback(server.callback_result, expected_state)


def ask_for_pasted_callback(expected_state: str) -> str:
    """The no-web-server version of wait_for_callback(): the user copies the
    URL they landed on and pastes it here."""
    print("After approving, your browser will land on a localhost page that")
    print("doesn't load. That's expected. Copy the ENTIRE URL from the address bar.\n")
    pasted = input("Paste the full redirect URL here: ").strip()
    return check_callback(parse_callback_url(pasted), expected_state)


def _post_to_token_url(data: dict) -> dict:
    """Both the code exchange and the refresh are a POST to the same token URL,
    authenticated with your app's client ID and secret."""
    response = requests.post(
        config.TOKEN_URL,
        data=data,
        auth=(config.client_id(), config.client_secret()),
    )
    response.raise_for_status()
    return response.json()


def exchange_code_for_token(code: str) -> dict:
    """Trade a freshly-issued authorization code for an access + refresh token."""
    return _post_to_token_url(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri(),
        }
    )


def refresh_access_token(refresh_token: str) -> dict:
    """Trade a refresh token for a new access token (and usually a new refresh
    token too -- Blackbaud rotates them).

    Refresh tokens do eventually expire (or get revoked). When that happens
    Blackbaud answers with a 400/401, and the only fix is to log in again --
    so we say exactly that instead of showing a raw HTTP error.
    """
    try:
        new_tokens = _post_to_token_url(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code in (400, 401):
            raise RuntimeError(
                "Your saved Skycart login has expired or was revoked. "
                "Run skycart.login() to log in again."
            ) from error
        raise

    # If Blackbaud didn't send a new refresh token, keep using the old one.
    new_tokens.setdefault("refresh_token", refresh_token)
    return new_tokens


def load_tokens() -> dict | None:
    """Read the cached tokens from disk, or None if we've never logged in."""
    path = config.token_cache_path()
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_tokens(tokens: dict) -> None:
    """Save tokens to disk, converting Blackbaud's relative expires_in (seconds
    from now) into an absolute expires_at timestamp, so anything reading the
    cache later doesn't need to know when the token was originally issued.

    The file is made readable by your user account only (chmod 600), since
    anyone holding it can act as you against the SKY API.
    """
    to_save = dict(tokens)
    to_save["expires_at"] = time.time() + tokens["expires_in"]

    path = config.token_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_save, indent=2))
    path.chmod(0o600)


def get_valid_access_token() -> str:
    """Return an access token good for at least the next minute, refreshing it
    first if needed. This is the one function the rest of Skycart calls --
    callers never need to think about expiry themselves.
    """
    tokens = load_tokens()
    if tokens is None:
        raise RuntimeError(
            "No saved Skycart login found. Run skycart.login() once (or "
            "`python -m skycart` in a terminal) to log in and authorize this app."
        )

    if time.time() >= tokens["expires_at"] - 60:
        tokens = refresh_access_token(tokens["refresh_token"])
        save_tokens(tokens)

    return tokens["access_token"]


def login(paste: bool = False) -> None:
    """Do the full one-time interactive login: open a browser, wait for the
    user to approve, and save the resulting tokens.

    Pass paste=True if Skycart is running somewhere your browser can't reach
    (Docker, a remote Jupyter server, Colab) -- see the top of this file.
    """
    state = secrets.token_urlsafe(16)
    url = build_authorization_url(state)

    print("Opening your browser to approve Skycart's access to the Blackbaud SKY API...")
    print(f"If it doesn't open automatically, visit this URL:\n{url}\n")
    webbrowser.open(url)

    if paste:
        code = ask_for_pasted_callback(state)
    else:
        code = wait_for_callback(state)

    tokens = exchange_code_for_token(code)
    save_tokens(tokens)

    print(f"Success! Tokens saved to {config.token_cache_path()}")


# The original name, kept so older code that calls it still works.
run_login_flow = login


if __name__ == "__main__":
    login()
