"""Skycart: a small Python client for Blackbaud's Raiser's Edge NXT SKY API.

    import skycart

    skycart.login()                                   # once, opens your browser
    skycart.get("/constituent/v1/constituents/280")   # any endpoint, as JSON
    skycart.get_prospect_status("280")                # named helpers
    skycart.to_dataframe(skycart.get_all("/constituent/v1/constituents", limit=100))

See README.md for setup.
"""

from .auth import login, run_login_flow
from .client import SkyAPIError, get, get_all, post, request, to_dataframe
from .endpoints import (
    get_constituent,
    get_fundraiser_assignments,
    get_prospect_status,
    get_prospect_statuses,
    query,
    search_constituents,
)

__version__ = "0.1.0"

__all__ = [
    # logging in
    "login",
    "run_login_flow",
    # general-purpose calls
    "get",
    "post",
    "get_all",
    "request",
    "to_dataframe",
    "SkyAPIError",
    # named endpoint helpers
    "get_constituent",
    "search_constituents",
    "get_prospect_status",
    "get_prospect_statuses",
    "get_fundraiser_assignments",
    "query",
]
