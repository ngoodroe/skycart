"""Named helpers for specific SKY API endpoints.

Each one is a small function that calls client.get() / client.get_all() with
the right path. They're useful on their own, but they're also meant as
templates: when you find an endpoint you want in Blackbaud's API reference
(https://developer.blackbaud.com/skyapi/products/renxt), copy one of these,
change the path, and add it to __init__.py.
"""

from . import client
from .client import SkyAPIError


def get_constituent(constituent_id: str) -> dict:
    """One constituent record: name, address, email, lookup ID, and so on."""
    return client.get(f"/constituent/v1/constituents/{constituent_id}")


def search_constituents(search_text: str, limit: int | None = None) -> list:
    """Search constituents by name, email, or lookup ID -- the same kind of
    search as the box at the top of Raiser's Edge NXT."""
    return client.get_all(
        "/constituent/v1/constituents/search",
        params={"search_text": search_text},
        limit=limit,
    )


def get_prospect_status(constituent_id: str) -> dict:
    """A constituent's current prospect status, including how long they've
    been in it. Blackbaud sends back:

        {
          "constituent_id": "280",
          "status": "Cultivation",
          "start": "2026-03-02T00:00:00",
          "days_elapsed": 224,          # days in the current status
          "comments": "..."
        }

    days_elapsed is something RE queries can't easily give you -- this is one of
    the main reasons Skycart exists.
    """
    return client.get(f"/constituent/v1/constituents/{constituent_id}/prospectstatus")


def get_prospect_statuses(constituent_ids: list) -> list:
    """Prospect status for a whole list of constituents (say, one gift officer's
    portfolio). Blackbaud has no bulk version of this endpoint, so this is one
    API call per constituent.

    Constituents with no prospect status get a row with status None instead of
    stopping the whole loop. Pass the result to skycart.to_dataframe().
    """
    results = []
    for constituent_id in constituent_ids:
        try:
            results.append(get_prospect_status(constituent_id))
        except SkyAPIError as error:
            if error.status_code != 404:
                raise
            results.append({"constituent_id": str(constituent_id), "status": None})
    return results


def get_fundraiser_assignments(fundraiser_id: str) -> list:
    """Everyone assigned to a fundraiser (gift officer) -- their portfolio.
    The fundraiser ID is that fundraiser's own constituent system record ID."""
    return client.get_all(f"/fundraising/v1/fundraisers/{fundraiser_id}/assignments")


def query(query_id: str) -> list:
    """TODO (future session): run a saved Raiser's Edge NXT query and return
    its results.

    The plan, from Blackbaud's Query API docs:
      1. POST to start the query running as a background job -> get a job ID
      2. GET the job's status every few seconds until it says "Completed"
      3. Download the results file from the link the finished job gives us

    Deliberately left to build together -- the details vary by query type and
    are easiest to get right while testing against a real database.
    """
    raise NotImplementedError("query() isn't built yet -- coming in a future version.")
