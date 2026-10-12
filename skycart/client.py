"""Generic authenticated HTTP calls to the SKY API.

There are two layers here:

- request() is the low-level call. It handles the boring, repeated part:
  attaching a valid access token and the subscription key, refreshing and
  retrying once if the token turns out to be stale, and waiting politely if
  Blackbaud says we're going too fast. It returns a raw `requests.Response`.

- get(), post(), and get_all() sit on top of it and hand you parsed JSON
  (plain Python dicts and lists), raising a SkyAPIError with Blackbaud's own
  error message if something goes wrong. These are what you'll use day to day.

The named endpoint helpers in endpoints.py are built on get()/get_all() --
no auth code needed there at all.
"""

import time

import requests

from . import auth, config

# If Blackbaud answers 429 ("too many requests"), how many times we wait and
# try again before giving up.
MAX_RATE_LIMIT_RETRIES = 5


class SkyAPIError(Exception):
    """Raised when the SKY API answers with an error status (4xx or 5xx).

    The full `requests.Response` is kept on `.response` in case you want to
    dig into it, and `.status_code` is there as a shortcut -- e.g. to treat a
    404 ("no such record") differently from other errors.
    """

    def __init__(self, response: requests.Response):
        self.response = response
        self.status_code = response.status_code
        method = response.request.method if response.request is not None else ""
        message = (
            f"SKY API returned {response.status_code} for {method} {response.url}\n"
            f"{response.text[:1000]}"
        )
        super().__init__(message)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {auth.get_valid_access_token()}",
        "Bb-Api-Subscription-Key": config.subscription_key(),
    }


def _full_url(path: str) -> str:
    """Accept either a path like "/constituent/v1/constituents/280" or a full
    URL. Paging links (next_link) come back from Blackbaud as full URLs."""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{config.SKY_API_BASE_URL}{path}"


def _seconds_to_wait(response: requests.Response) -> float:
    """Blackbaud's 429 responses include a Retry-After header saying how many
    seconds to wait. Fall back to 1 second if it's missing or odd."""
    try:
        return max(float(response.headers.get("Retry-After", 1)), 0.5)
    except ValueError:
        return 1.0


def _send(method: str, url: str, **kwargs) -> requests.Response:
    """Send one request, waiting and retrying if we hit the rate limit."""
    extra_headers = kwargs.pop("headers", {})

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        headers = {**_headers(), **extra_headers}
        response = requests.request(method, url, headers=headers, **kwargs)

        if response.status_code != 429 or attempt == MAX_RATE_LIMIT_RETRIES:
            return response

        time.sleep(_seconds_to_wait(response))

    return response


def request(method: str, path: str, **kwargs) -> requests.Response:
    """Make an authenticated request to the SKY API and return the raw response.

    `path` is relative to the SKY API base URL, e.g. "/constituent/v1/constituents/280",
    or a full URL. Any extra keyword arguments (params, json, etc.) are passed
    straight through to requests.request().

    If the server says the token is bad (401), we force a refresh and retry
    exactly once -- this covers the case where a token expired between our
    expiry check and the request actually reaching Blackbaud.
    """
    url = _full_url(path)
    response = _send(method, url, **kwargs)

    if response.status_code == 401:
        tokens = auth.load_tokens()
        if tokens is not None:
            tokens = auth.refresh_access_token(tokens["refresh_token"])
            auth.save_tokens(tokens)
        response = _send(method, url, **kwargs)

    return response


def _json_or_raise(response: requests.Response):
    """Turn a response into parsed JSON, or raise SkyAPIError if it failed.
    Some successful calls (like a PATCH or DELETE) have no body -- those
    return None."""
    if not response.ok:
        raise SkyAPIError(response)
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def get(path: str, params: dict | None = None, **kwargs):
    """GET a SKY API endpoint and return the parsed JSON.

        skycart.get("/constituent/v1/constituents/280")
        skycart.get("/constituent/v1/constituents", params={"limit": 10})
    """
    return _json_or_raise(request("GET", path, params=params, **kwargs))


def post(path: str, json: dict | None = None, **kwargs):
    """POST to a SKY API endpoint (with an optional JSON body) and return the
    parsed JSON response."""
    return _json_or_raise(request("POST", path, json=json, **kwargs))


def get_all(path: str, params: dict | None = None, limit: int | None = None) -> list:
    """GET a list endpoint and return ALL the records, following Blackbaud's
    paging for you.

    SKY list endpoints answer with a page shaped like:

        {"count": 1234, "value": [...records...], "next_link": "https://..."}

    We collect every page's "value" into one list, and keep following
    next_link until there isn't one. Pass `limit` to stop early (handy while
    exploring, so you don't accidentally pull 50,000 constituents).

    Endpoints that aren't paged just come back as a single page, which works
    the same way.
    """
    records = []
    url = path

    while url:
        page = get(url, params=params)
        records.extend(page.get("value", []))

        if limit is not None and len(records) >= limit:
            return records[:limit]

        url = page.get("next_link")
        # next_link already has the query string (limit, offset, filters)
        # baked in, so we don't send params again on later pages.
        params = None

    return records


def to_dataframe(data):
    """Turn SKY API JSON into a pandas DataFrame, flattening nested fields
    (e.g. a constituent's "address": {"city": ...} becomes an "address.city"
    column).

    Accepts a list of records (what get_all() returns), a single record, or a
    raw page with a "value" list in it.

    pandas is optional for Skycart, so it's only imported here. Install it with
    `pip install pandas` if you don't already have it.
    """
    try:
        import pandas as pd
    except ImportError as error:
        raise ImportError(
            "skycart.to_dataframe() needs pandas. Install it with `pip install pandas`."
        ) from error

    if isinstance(data, dict):
        data = data.get("value", [data])

    return pd.json_normalize(data)
