# Skycart

**A small Python client for Blackbaud's SKY API, built for Jupyter notebooks.**

Raiser's Edge NXT holds a lot of data that its built-in queries and exports
can't reach. Prospect status is a good example: RE will tell you someone is in
*Cultivation*, but not that they've been sitting there for 224 days. The SKY API
has that data. The hard part is getting connected: OAuth2 logins, expiring
tokens, subscription keys, paging, rate limits.

Skycart handles all of that, so a notebook cell can just ask for data:

```python
import skycart

skycart.login()                          # once -- opens your browser

skycart.get_prospect_status("280")
# {'constituent_id': '280', 'status': 'Cultivation',
#  'start': '2026-03-02T00:00:00', 'days_elapsed': 224, 'comments': None}
```

It's deliberately small (four short files) and commented so you can read
exactly what it does with your credentials before you run it.

---

## 1. Install

Python 3.10 or newer.

```bash
pip install "skycart[pandas] @ git+https://github.com/ngoodroe/skycart.git"
```

The `[pandas]` part is optional. It adds pandas so you can turn results into
DataFrames with `skycart.to_dataframe()`. Leave it off for plain scripts:

```bash
pip install git+https://github.com/ngoodroe/skycart.git
```

## 2. Get Blackbaud credentials

Skycart needs three values from a Blackbaud SKY API app, which you (or your
organization's Blackbaud admin) create at the
[SKY API developer dashboard](https://developer.blackbaud.com/skyapi/apps):

1. Create an app (or use an existing one).
2. Register a **redirect URI** of `http://localhost:8765/callback`. This must
   match exactly, including the port. See `BB_REDIRECT_URI` below if you need
   a different port.
3. From that app, note down:
   - **Client ID**
   - **Client secret**
   - **Subscription key**. This is separate from the client ID and secret.
     It's tied to your Blackbaud developer account, not the individual app.
     Find it under *My subscriptions*.

Your app also has to be connected to your organization's environment before it
can read real data. In RE NXT, an admin does this under *Control panel →
Applications*.

## 3. Configure

Create a file named `.env` in the folder you'll run your notebook from (or any
folder above it):

```
BB_CLIENT_ID=your-client-id
BB_CLIENT_SECRET=your-client-secret
BB_SUBSCRIPTION_KEY=your-subscription-key
BB_REDIRECT_URI=http://localhost:8765/callback
```

There's a copy of this in [`.env.example`](.env.example). `BB_REDIRECT_URI` is
optional if you're using the default port.

**Never commit `.env` to git.** Add it to your `.gitignore`.

## 4. Log in (one time)

```python
import skycart
skycart.login()
```

Or from a terminal: `python -m skycart`

This opens your browser to Blackbaud's approval screen. Approve it and
Blackbaud redirects back to a tiny web server Skycart runs for a moment on your
machine. You'll see:

```
Success! Tokens saved to /Users/you/.skycart/tokens.json
```

From then on Skycart refreshes your access automatically, so you only log in
again if that saved login eventually expires (Skycart will tell you when).

**Running in Docker, on a remote Jupyter server, or in Colab?** Your browser
can't reach Skycart's little web server there, so use
`skycart.login(paste=True)` (or `python -m skycart --paste`). After approving,
your browser lands on a localhost page that won't load. That's expected. Copy
the whole URL from the address bar and paste it into the prompt.

**Keep `~/.skycart/tokens.json` private.** Anyone with that file can act as you
against the SKY API. It lives in your home folder, outside your projects, so it
can't get committed by accident. Set `SKYCART_TOKEN_CACHE` to store it
somewhere else.

## 5. Use it

### Any endpoint

Find what you want in the
[SKY API reference](https://developer.blackbaud.com/skyapi/products/renxt) and
pass its path:

```python
skycart.get("/constituent/v1/constituents/280")
skycart.get("/constituent/v1/constituents/280/relationships")
skycart.post("/some/endpoint", json={"field": "value"})
```

`get()` and `post()` return plain Python data (dicts and lists). If Blackbaud
answers with an error, you get a `skycart.SkyAPIError` that includes
Blackbaud's own message and a `.status_code`.

### Lists, with paging handled

SKY list endpoints come back one page at a time. `get_all()` follows the pages
and gives you one list. `limit` stops early, so you don't accidentally pull
your whole database while exploring:

```python
constituents = skycart.get_all("/constituent/v1/constituents", limit=200)
```

### Straight into pandas

```python
df = skycart.to_dataframe(constituents)
```

Nested fields are flattened into columns. For example, `address.city`.

### Named helpers

| Function | What it gets you |
| --- | --- |
| `skycart.get_constituent(id)` | One constituent record |
| `skycart.search_constituents(text)` | Search by name, email, or lookup ID |
| `skycart.get_prospect_status(id)` | Current prospect status and **days in status** |
| `skycart.get_prospect_statuses(ids)` | The same for a whole list (one call each) |
| `skycart.get_fundraiser_assignments(id)` | A gift officer's assigned portfolio |
| `skycart.query(id)` | *Coming soon:* run a saved RE query |

Putting them together, here's a portfolio sorted by who's been stuck the
longest:

```python
assignments = skycart.get_fundraiser_assignments("123")
ids = [a["constituent_id"] for a in assignments]

statuses = skycart.to_dataframe(skycart.get_prospect_statuses(ids))
statuses.sort_values("days_elapsed", ascending=False)
```

There's a runnable version in
[`examples/quickstart.ipynb`](examples/quickstart.ipynb).

### Rate limits

Blackbaud limits how fast you can call the API. If you go over, Skycart waits
the amount of time Blackbaud asks for and tries again, so a loop over a few
hundred constituents just runs a little slower instead of crashing. Keep an
eye on your daily quota for big loops.

## 6. Add your own endpoint helpers

Every named helper in [`skycart/endpoints.py`](skycart/endpoints.py) is a few
lines long. Copy one, change the path, and you're done:

```python
def get_gift(gift_id: str) -> dict:
    """One gift record."""
    return client.get(f"/gift/v1/gifts/{gift_id}")
```

Add it to the imports in `skycart/__init__.py` so `skycart.get_gift(...)` works.
You never need to think about tokens or headers. `client.get` handles them.

## How it's put together

```
skycart/
  config.py     reads .env, knows Blackbaud's URLs and where the login is saved
  auth.py       the OAuth2 login, saving tokens, refreshing them when they expire
  client.py     get / post / get_all / to_dataframe, plus retries for 401 and 429
  endpoints.py  small named helpers for specific endpoints
```

## Working on Skycart itself

```bash
git clone https://github.com/ngoodroe/skycart.git
cd skycart
pip install -e ".[dev]"   # -e: your edits take effect without reinstalling
pytest                    # offline tests, no Blackbaud account needed
```

## Real-world example

[Job Checker](https://github.com/ngoodroe/bbdevdays-2026-job-checker), my
BBDevDays 2026 project, reads constituent employment data from the SKY API and
checks it against the public web using small AI models that run entirely on
your own computer.

---

Built by [Nathan Goodroe](https://www.linkedin.com/in/nathan-goodroe/), a
nonprofit data person who got tired of not being able to get the data out. If
you're working on something in Raiser's Edge and want help, or want to build
something together, [get in touch](https://minecartdata.com/#contact).

Skycart isn't affiliated with or endorsed by Blackbaud. Raiser's Edge NXT and
SKY API are Blackbaud trademarks. MIT licensed.
