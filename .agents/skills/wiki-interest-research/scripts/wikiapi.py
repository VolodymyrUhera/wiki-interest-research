"""Wikimedia API access (MediaWiki, Wikidata, Pageviews) with an on-disk JSON cache."""
import hashlib
import http.client
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def _default_cache_dir():
    """The skill's own .cache/, or the user cache dir when the skill is installed read-only."""
    local = SKILL_DIR / ".cache"
    try:
        local.mkdir(exist_ok=True)
        if os.access(local, os.W_OK):
            return local
    except OSError:
        pass
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "wiki-interest-research"


CACHE_DIR = Path(os.environ.get("WIKI_CACHE_DIR") or _default_cache_dir())
# Wikimedia asks for a descriptive User-Agent; set WIKI_UA to add your contact info.
UA = os.environ.get("WIKI_UA", "wiki-interest-research-skill/1.0 (Agent Skill; https://agentskills.io)") + (
    f" Python-urllib/{sys.version_info.major}.{sys.version_info.minor}")
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WEEK = 7 * 24 * 3600


_MISS = object()


def _read_cache(path):
    """Cached data, or _MISS if absent, expired, corrupt or in an old format."""
    try:
        entry = json.loads(path.read_text())
    except (OSError, ValueError):
        return _MISS
    if not isinstance(entry, dict) or "expires" not in entry:
        return _MISS
    if entry["expires"] is not None and time.time() >= entry["expires"]:
        return _MISS
    return entry["data"]


# Transient failures worth retrying. urllib does not wrap read timeouts or dropped connections in URLError.
_RETRYABLE = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException)


def get_json(url, ttl=None, valid=None):
    """GET a JSON URL through the cache. HTTP 404 is returned (and cached) as None.

    ttl is fixed when the response is stored (None = forever), so data cached while still incomplete keeps its short
    lifetime even after the period it covers becomes final. Responses failing `valid` (e.g. API error payloads)
    are returned but never cached, and such entries already in the cache are refetched.
    """
    path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    cached = _read_cache(path)
    if cached is not _MISS and (valid is None or valid(cached)):
        return cached
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            break
        except ValueError:  # 200 with an HTML/empty body (proxy or outage page)
            if attempt == 4:
                raise RuntimeError(f"non-JSON response from {url.split('?')[0]}") from None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = None
                break
            if e.code != 429 and e.code < 500 or attempt == 4:
                raise
            wait = e.headers.get("Retry-After", "") if e.headers else ""
            if wait.isdigit():
                time.sleep(min(int(wait), 60))
                continue
        except _RETRYABLE:
            if attempt == 4:
                raise
        time.sleep(2 ** attempt)
    if valid is None or valid(data):
        _write_cache(path, {"expires": None if ttl is None else time.time() + ttl, "data": data})
    return data


def _write_cache(path, entry):
    """Best effort: a cache that cannot be written only costs speed, never the result."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Temp file + rename, so an interrupted or concurrent write never leaves a truncated entry.
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(entry, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _mediawiki(lang, **params):
    params.update(format="json", formatversion="2")
    data = get_json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params), ttl=WEEK,
                    valid=lambda d: "error" not in (d or {}))
    if "error" in (data or {}):
        raise RuntimeError(f"{lang}.wikipedia API: {data['error'].get('info', data['error'])}")
    return data


def is_qid(topic):
    return topic[:1] in "Qq" and topic[1:].isdigit()


def canonical(lang, title):
    """Follow redirects/normalization. Returns (canonical_title, wikidata_qid) or (None, None) if missing."""
    if not title.strip() or "|" in title:
        return None, None
    q = _mediawiki(lang, action="query", titles=title, redirects=1, prop="pageprops", ppprop="wikibase_item")["query"]
    if not q.get("pages"):  # interwiki prefix like "fr:Paris"
        return None, None
    page = q["pages"][0]
    if page.get("missing") or page.get("invalid"):
        return None, None
    return page["title"], page.get("pageprops", {}).get("wikibase_item")


def resolve(topic, source_lang, langs):
    """Map a topic (article title in source_lang, or a Wikidata QID like Q1666254) to article titles per language."""
    if is_qid(topic):
        qid = topic.upper()
    else:
        title, qid = canonical(source_lang, topic)
        if title is None:
            return {"topic": topic, "error": f"no article '{topic}' on {source_lang}.wikipedia; try the search command"}
        if not qid:
            return {"topic": topic, "qid": None,
                    "titles": {lang: title if lang == source_lang else None for lang in langs}}
    ent = get_json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": qid, "props": "sitelinks|labels", "languages": "en", "format": "json"}),
        ttl=WEEK)
    entity = (ent or {}).get("entities", {}).get(qid, {})
    if "missing" in entity or not entity:
        return {"topic": topic, "error": f"Wikidata item {qid} not found"}
    links = entity.get("sitelinks", {})
    sites = wikipedia_sites()
    label = entity.get("labels", {}).get("en", {}).get("value", topic)
    titles = {lang: links.get(site_id(lang, sites), {}).get("title") for lang in langs}
    # A sitelink can point at a redirect (de: "Generative künstliche Intelligenz" -> "Generatives KI-Modell");
    # measuring the redirect page would count only its own few views, so follow it to the article.
    titles = {lang: (canonical(lang, t)[0] or t) if t else None for lang, t in titles.items()}
    return {"topic": topic, "label": label, "qid": qid, "titles": titles}


def wikipedia_sites():
    """{'uk': 'ukwiki', 'be-tarask': 'be_x_oldwiki', ...} for every open Wikipedia edition (Wikimedia sitematrix)."""
    data = get_json("https://meta.wikimedia.org/w/api.php?action=sitematrix&smtype=language&smsiteprop=url|dbname"
                    "&format=json&formatversion=2", ttl=WEEK, valid=lambda d: bool(d and "sitematrix" in d))
    sites = {}
    for key, lang in data["sitematrix"].items():
        for site in lang.get("site", []) if key != "count" else []:
            host = site["url"].split("//")[1]
            if host.endswith(".wikipedia.org") and not site.get("closed"):
                sites[host.split(".")[0]] = site["dbname"]
    return sites


# Fallback when the sitematrix is unavailable: Wikidata ids that are not "<code with - as _>wiki".
_SITE_ID_EXCEPTIONS = {"be-tarask": "be_x_oldwiki"}


def site_id(lang, sites=None):
    """Wikidata sitelink key for a Wikipedia language code, e.g. zh-yue -> zh_yuewiki."""
    return (sites or {}).get(lang) or _SITE_ID_EXCEPTIONS.get(lang, lang.replace("-", "_") + "wiki")


def search(query, lang, limit=5):
    """Full-text search in one language edition; returns [{title, words}] best-first."""
    res = _mediawiki(lang, action="query", list="search", srsearch=query, srlimit=limit, srprop="wordcount")
    return [{"title": r["title"], "words": r.get("wordcount", 0)} for r in res["query"]["search"]]


def redirects(lang, title):
    """Titles (namespace 0) that redirect to the article. Their views are counted separately by Wikimedia."""
    out, cont = [], {}
    while True:
        res = _mediawiki(lang, action="query", titles=title, prop="redirects", rdnamespace=0, rdlimit="max", **cont)
        out += [r["title"] for r in res["query"]["pages"][0].get("redirects", [])]
        if "continue" not in res:
            return out
        cont = {"rdcontinue": res["continue"]["rdcontinue"]}


def _ttl_for(end):
    # Pageviews for dates older than a few days are final; newer ones may still be loading.
    return None if end < date.today() - timedelta(days=5) else 3600


def article_daily(lang, title, start, end):
    """{'YYYY-MM-DD': views} for user traffic (all platforms). Days with no data are absent."""
    t = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"{PAGEVIEWS}/per-article/{lang}.wikipedia/all-access/user/{t}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00"
    data = get_json(url, ttl=_ttl_for(end)) or {"items": []}
    return {f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-{i['timestamp'][6:8]}": i["views"] for i in data["items"]}


def project_monthly(lang, start, end):
    """{'YYYY-MM': views} of all user traffic to the whole language edition (used for normalization)."""
    url = f"{PAGEVIEWS}/aggregate/{lang}.wikipedia/all-access/user/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00"
    data = get_json(url, ttl=_ttl_for(end)) or {"items": []}
    return {f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}": i["views"] for i in data["items"]}
