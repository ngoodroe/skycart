"""Offline tests for skycart.client -- no internet or Blackbaud account needed.

Instead of calling the real SKY API, each test swaps out `requests.request`
for a fake that hands back responses we wrote by hand. pytest's `monkeypatch`
does the swapping and puts everything back after each test.

Run with:  pytest
"""

import json

import pytest
import requests

import skycart
from skycart import auth, client


def make_response(status_code: int, body=None, headers=None) -> requests.Response:
    """Build a real requests.Response object without making a network call."""
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode() if body is not None else b""
    response.headers.update(headers or {})
    response.url = "https://api.sky.blackbaud.com/test"
    return response


class FakeSkyAPI:
    """Stands in for requests.request. Give it a list of responses; it hands
    them out one per call and remembers which URLs were called."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers=None, **kwargs):
        self.calls.append({"method": method, "url": url, "headers": headers, **kwargs})
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """Every test gets a pretend token and subscription key, so nothing tries
    to read a real .env or token file."""
    monkeypatch.setenv("BB_SUBSCRIPTION_KEY", "test-subscription-key")
    monkeypatch.setattr(auth, "get_valid_access_token", lambda: "test-access-token")
    monkeypatch.setattr(client.time, "sleep", lambda seconds: None)  # don't actually wait


def test_get_returns_json_and_sends_auth_headers(monkeypatch):
    fake = FakeSkyAPI([make_response(200, {"id": "280", "name": "Jane Holloway"})])
    monkeypatch.setattr(client.requests, "request", fake)

    result = skycart.get("/constituent/v1/constituents/280")

    assert result == {"id": "280", "name": "Jane Holloway"}
    assert fake.calls[0]["url"] == "https://api.sky.blackbaud.com/constituent/v1/constituents/280"
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer test-access-token"
    assert fake.calls[0]["headers"]["Bb-Api-Subscription-Key"] == "test-subscription-key"


def test_get_raises_sky_api_error_on_failure(monkeypatch):
    fake = FakeSkyAPI([make_response(404, [{"message": "Constituent not found"}])])
    monkeypatch.setattr(client.requests, "request", fake)

    with pytest.raises(skycart.SkyAPIError) as error:
        skycart.get("/constituent/v1/constituents/does-not-exist")

    assert error.value.status_code == 404
    assert "Constituent not found" in str(error.value)


def test_get_all_follows_next_link(monkeypatch):
    fake = FakeSkyAPI(
        [
            make_response(200, {"count": 3, "value": [{"id": "1"}, {"id": "2"}],
                                "next_link": "https://api.sky.blackbaud.com/page2"}),
            make_response(200, {"count": 3, "value": [{"id": "3"}]}),
        ]
    )
    monkeypatch.setattr(client.requests, "request", fake)

    records = skycart.get_all("/constituent/v1/constituents", params={"limit": 2})

    assert [r["id"] for r in records] == ["1", "2", "3"]
    assert fake.calls[1]["url"] == "https://api.sky.blackbaud.com/page2"
    assert fake.calls[1]["params"] is None  # next_link already has the query string


def test_get_all_stops_at_limit(monkeypatch):
    fake = FakeSkyAPI(
        [make_response(200, {"value": [{"id": "1"}, {"id": "2"}], "next_link": "https://x/page2"})]
    )
    monkeypatch.setattr(client.requests, "request", fake)

    records = skycart.get_all("/constituent/v1/constituents", limit=1)

    assert records == [{"id": "1"}]
    assert len(fake.calls) == 1  # never fetched page 2


def test_waits_and_retries_when_rate_limited(monkeypatch):
    fake = FakeSkyAPI(
        [
            make_response(429, headers={"Retry-After": "2"}),
            make_response(200, {"ok": True}),
        ]
    )
    monkeypatch.setattr(client.requests, "request", fake)

    assert skycart.get("/anything") == {"ok": True}
    assert len(fake.calls) == 2


def test_refreshes_token_and_retries_once_on_401(monkeypatch):
    fake = FakeSkyAPI([make_response(401), make_response(200, {"ok": True})])
    monkeypatch.setattr(client.requests, "request", fake)

    refreshed = []
    monkeypatch.setattr(auth, "load_tokens", lambda: {"refresh_token": "old-refresh"})
    monkeypatch.setattr(auth, "refresh_access_token", lambda token: refreshed.append(token) or {"expires_in": 3600})
    monkeypatch.setattr(auth, "save_tokens", lambda tokens: None)

    assert skycart.get("/anything") == {"ok": True}
    assert refreshed == ["old-refresh"]


def test_prospect_statuses_skips_constituents_with_no_status(monkeypatch):
    fake = FakeSkyAPI(
        [
            make_response(200, {"constituent_id": "1", "status": "Cultivation", "days_elapsed": 42}),
            make_response(404, [{"message": "Not found"}]),
        ]
    )
    monkeypatch.setattr(client.requests, "request", fake)

    rows = skycart.get_prospect_statuses(["1", "2"])

    assert rows[0]["days_elapsed"] == 42
    assert rows[1] == {"constituent_id": "2", "status": None}


def test_to_dataframe_flattens_nested_fields():
    df = skycart.to_dataframe([{"id": "1", "address": {"city": "Boston"}}])
    assert list(df.columns) == ["id", "address.city"]
    assert df.loc[0, "address.city"] == "Boston"


def test_missing_credentials_give_a_helpful_message(monkeypatch):
    monkeypatch.delenv("BB_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="BB_CLIENT_ID"):
        skycart.config.client_id()
