"""Bounded, robots-aware evidence collection for a declared audit sample.

  python3 collect.py discover https://example.com/ OUTPUT_DIR
      Read robots.txt and sitemaps (expanding indexes) and list candidate pages,
      with the robots decision for common search, training and user-triggered
      crawler tokens. No page other than robots.txt and sitemaps is fetched.

  python3 collect.py fetch OUTPUT_DIR URL [URL ...]    (or --urls-file FILE)
      Capture each chosen sample URL once. Writes validated evidence records for
      run.json, the raw response bodies and a collection log.

Limits follow the audit method: at most 50 pages, 30 seconds and 5 MiB per
response, 5 redirects and at least one second between requests to a host
(longer when robots.txt asks for a crawl delay). Robots rules follow RFC 9309
and are applied to this collector's own token, GEO-Audit; other tokens are only
reported. This is a polite single-threaded collector for a local audit: it does
not run JavaScript, bypass bot challenges or log in, and its private-address
check cannot prevent DNS rebinding. Outputs never replace existing files.
"""
import argparse
from datetime import datetime, timezone
from functools import lru_cache
import gzip
import hashlib
import http.client
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import string
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
import urllib.request
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import validate_registry  # noqa: E402
from safe_io import check_new, write_new  # noqa: E402
from version import TOOLKIT_VERSION  # noqa: E402

MAX_PAGES = 50
TIMEOUT = 30
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
MIN_DELAY = 1.0
MAX_CRAWL_DELAY = 30.0
ROBOTS_LIMIT = 500 * 1024
SITEMAP_TEXT_LIMIT = 50 * 1024 * 1024
SITEMAP_EMBED_LIMIT = 200_000
MAX_SITEMAPS = 50
MAX_SITEMAP_URLS = 50_000

TOKEN = "GEO-Audit"
USER_AGENT = f"{TOKEN}/{TOOLKIT_VERSION} (+local website readiness review)"
METHOD = f"collect.py {TOOLKIT_VERSION}: HTTP GET without JavaScript"
# Reported, never impersonated. Check each provider's documentation for what its token controls.
REPORT_AGENTS = ("Googlebot", "Google-Extended", "Bingbot", "OAI-SearchBot", "GPTBot", "ChatGPT-User",
                 "PerplexityBot", "Perplexity-User", "ClaudeBot", "Claude-SearchBot", "Claude-User",
                 "Applebot", "Applebot-Extended", "CCBot")
REDIRECTS = {301, 302, 303, 307, 308}
UNRESERVED = set(string.ascii_letters + string.digits + "-._~")
TEXT_TYPES = ("text/", "application/xhtml+xml", "application/xml", "application/json", "application/ld+json")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# robots.txt (RFC 9309)
# ---------------------------------------------------------------------------

def parse_robots(text):
    """Return (groups, sitemaps). Each group has lower-case agent tokens, rules and a crawl delay."""
    groups, sitemaps, current = [], [], None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "sitemap":
            if value:
                sitemaps.append(value)
        elif key == "user-agent":
            # A user-agent line after any rule starts a new group.
            if current is None or current["closed"]:
                current = {"agents": [], "rules": [], "crawl_delay": None, "closed": False}
                groups.append(current)
            token = value.split("/", 1)[0].strip().lower()
            if token:
                current["agents"].append(token)
        elif current is not None and key in {"allow", "disallow"}:
            current["closed"] = True
            if value:  # An empty Disallow allows everything and adds no rule.
                current["rules"].append((key == "allow", value, normalise(value)))
        elif current is not None and key == "crawl-delay":
            current["closed"] = True
            try:
                current["crawl_delay"] = float(value)
            except ValueError:
                pass
    for group in groups:
        del group["closed"]
    return groups, sitemaps


def normalise(value):
    """Percent-encode non-ASCII and decode escaped unreserved characters, as RFC 9309 requires."""
    encoded = quote(value, safe="!#$%&'()*+,/:;=?@[]~-._")
    return re.sub(r"%([0-9A-Fa-f]{2})",
                  lambda m: chr(int(m[1], 16)) if chr(int(m[1], 16)) in UNRESERVED else "%" + m[1].upper(),
                  encoded)


@lru_cache(maxsize=4096)
def compile_pattern(pattern):
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    return re.compile("".join(".*" if char == "*" else re.escape(char) for char in body) + ("$" if anchored else ""))


def pattern_matches(pattern, path):
    return compile_pattern(pattern).match(path) is not None


def request_path(url):
    parts = urlsplit(url)
    return normalise((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))


class Robots:
    """Robots rules for one origin. State: parsed, unavailable (allow all) or unreachable (disallow all)."""

    def __init__(self, url, state, text="", http_status=None, detail=""):
        self.url, self.state, self.http_status, self.detail = url, state, http_status, detail
        self.groups, self.sitemaps = parse_robots(text) if state == "parsed" else ([], [])

    def groups_for(self, token):
        token = token.lower()
        matched = [group for group in self.groups if token in group["agents"]]
        return matched or [group for group in self.groups if "*" in group["agents"]]

    def crawl_delay(self, token):
        delays = [group["crawl_delay"] for group in self.groups_for(token) if group["crawl_delay"] is not None]
        return min(max(delays), MAX_CRAWL_DELAY) if delays else 0.0

    def decision(self, token, url):
        return self.decide(self.groups_for(token), token, url)

    def decide(self, groups, token, url):
        if self.state == "unavailable":
            return {"allowed": True, "rule": None, "reason": f"robots.txt unavailable ({self.detail}): no restrictions"}
        if self.state == "unreachable":
            return {"allowed": False, "rule": None, "reason": f"robots.txt unreachable ({self.detail}): complete disallow"}
        path = request_path(url)
        if path == "/robots.txt":
            return {"allowed": True, "rule": None, "reason": "robots.txt itself is always allowed"}
        best = None
        for group in groups:
            for allow, original, pattern in group["rules"]:
                if pattern_matches(pattern, path):
                    # The longest match wins; on a tie the allow rule wins.
                    key = (len(pattern), allow)
                    if best is None or key > best[0]:
                        best = (key, allow, original)
        scope = f"group for {token}" if groups and token.lower() in groups[0]["agents"] else (
            "group for *" if groups else "no matching group")
        if best is None:
            return {"allowed": True, "rule": None, "reason": f"no matching rule ({scope})"}
        rule = ("Allow: " if best[1] else "Disallow: ") + best[2]
        return {"allowed": best[1], "rule": rule, "reason": f"longest matching rule in the {scope}"}

    def summary(self):
        return {"url": self.url, "state": self.state, "http_status": self.http_status, "detail": self.detail,
                "sitemaps": self.sitemaps,
                "groups": [{"agents": g["agents"], "crawl_delay": g["crawl_delay"],
                            "rules": [("Allow: " if allow else "Disallow: ") + original
                                      for allow, original, _ in g["rules"]]} for g in self.groups]}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are followed by the collector so each hop is checked and recorded."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Response:
    def __init__(self, url, status=None, reason="", headers=(), body=b"", error=None):
        self.url, self.status, self.reason, self.headers, self.body, self.error = url, status, reason, headers, body, error
        self.collected_at = now()

    def header(self, name):
        name = name.lower()
        return next((value for key, value in self.headers if key.lower() == name), None)

    @property
    def location(self):
        value = self.header("location")
        return urljoin(self.url, value) if self.status in REDIRECTS and value else None


def address_problem(host):
    """Refuse loopback, private, link-local and other non-public destinations."""
    try:
        addresses = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return None  # Not resolvable here; a configured proxy may still resolve it.
        addresses = [ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos]
    for address in addresses:
        if not address.is_global:
            return f"{host} resolves to the non-public address {address}"
    return None


class Client:
    def __init__(self, *, delay=MIN_DELAY, timeout=TIMEOUT, max_bytes=MAX_BYTES, allow_private=False,
                 proxies=None, clock=time.monotonic, sleep=time.sleep):
        handlers = [NoRedirect()]
        if proxies is not None:
            handlers.append(urllib.request.ProxyHandler(proxies))
        self.opener = urllib.request.build_opener(*handlers)
        self.delay, self.timeout, self.max_bytes = delay, timeout, max_bytes
        self.allow_private, self.clock, self.sleep = allow_private, clock, sleep
        self.last, self.host_delay, self.robots_cache = {}, {}, {}

    def refusal(self, url):
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return f"not an HTTP(S) URL: {url}"
        if not self.allow_private:
            return address_problem(parts.hostname)
        return None

    def get(self, url):
        host = urlsplit(url).netloc.lower()
        wait = self.host_delay.get(host, self.delay) - (self.clock() - self.last.get(host, float("-inf")))
        if wait > 0:
            self.sleep(wait)
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept-Encoding": "identity",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5"})
        started = self.clock()
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except HTTPError as error:  # 3xx (redirects are not followed here), 4xx and 5xx
                response = error
            with response:
                headers = list(response.headers.items())
                length = response.headers.get("Content-Length", "")
                if length.isdigit() and int(length) > self.max_bytes:
                    raise ValueError(f"declared size {int(length):,} bytes exceeds the {self.max_bytes:,}-byte limit")
                body = self.read(response, started)
            return Response(url, response.status, response.reason or "", headers, body)
        except (URLError, OSError, http.client.HTTPException, ValueError) as error:
            reason = getattr(error, "reason", error)
            return Response(url, error=f"{type(error).__name__}: {reason}")
        finally:
            self.last[host] = self.clock()

    def read(self, response, started):
        chunks, size = [], 0
        while True:
            if self.clock() - started > self.timeout:
                raise TimeoutError(f"response exceeded {self.timeout} seconds")
            chunk = response.read(65536)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > self.max_bytes:
                raise ValueError(f"response exceeds the {self.max_bytes:,}-byte limit")
            chunks.append(chunk)

    def robots(self, url):
        """Fetch and cache robots.txt for the URL's origin; returns (Robots, chain of responses)."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc.lower()}"
        if origin in self.robots_cache:
            return self.robots_cache[origin]
        target, chain = origin + "/robots.txt", []
        robots = None
        for _ in range(MAX_REDIRECTS + 1):
            problem = self.refusal(target)
            if problem:
                robots = Robots(origin + "/robots.txt", "unreachable", detail=problem)
                break
            response = self.get(target)
            chain.append(response)
            if response.error:
                robots = Robots(target, "unreachable", detail=response.error)
            elif response.location:
                target = response.location
                continue
            elif 200 <= response.status < 300:
                text = response.body[:ROBOTS_LIMIT].decode("utf-8", errors="replace")
                robots = Robots(target, "parsed", text, response.status, f"HTTP {response.status}")
            elif 300 <= response.status < 500 and response.status != 429:
                # A 4xx (or a redirect without a target) means no robots.txt applies.
                robots = Robots(target, "unavailable", http_status=response.status, detail=f"HTTP {response.status}")
            else:
                robots = Robots(target, "unreachable", http_status=response.status, detail=f"HTTP {response.status}")
            break
        if robots is None:
            robots = Robots(target, "unavailable", detail=f"more than {MAX_REDIRECTS} redirects")
        crawl_delay = robots.crawl_delay(TOKEN)
        if crawl_delay > self.delay:
            self.host_delay[parts.netloc.lower()] = crawl_delay
        self.robots_cache[origin] = (robots, chain)
        return robots, chain


# ---------------------------------------------------------------------------
# Captures and evidence records
# ---------------------------------------------------------------------------

def decode(response):
    """Decode a text body; returns (text or None, charset, note)."""
    content_type = (response.header("content-type") or "").lower()
    if content_type and not content_type.startswith(TEXT_TYPES) and "+xml" not in content_type \
            and "+json" not in content_type:
        return None, None, None
    body = response.body
    declared = re.search(r"charset=[\"']?([A-Za-z0-9_.:-]+)", content_type)
    sniffed = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_.:-]+)", body[:4096], re.IGNORECASE)
    if body.startswith(b"\xef\xbb\xbf"):
        charset = "utf-8-sig"
    elif declared:
        charset = declared[1]
    elif sniffed:
        charset = sniffed[1].decode("ascii")
    else:
        charset = "utf-8"
    try:
        return body.decode(charset), charset, None
    except LookupError:
        return body.decode("utf-8", errors="replace"), "utf-8", f"Unknown charset {charset}; decoded as UTF-8"
    except UnicodeDecodeError:
        return (body.decode(charset, errors="replace"), charset,
                f"Some bytes were invalid {charset} and were replaced with U+FFFD")


def visible_text(html):
    html = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1\s*>", " ", html)
    return " ".join(re.sub(r"(?s)<[^>]+>", " ", html).split())


CHALLENGE_TITLE = re.compile(r"\b(client challenge|just a moment|attention required|access denied|security check|"
                             r"checking your browser|are you a robot|bot verification|human verification|"
                             r"ddos protection)\b")
# Interstitial wording and vendor signatures (Cloudflare, Fastly, Akamai, Imperva, DataDome, PerimeterX).
CHALLENGE_MARKERS = ("enable javascript to proceed", "enable javascript and cookies to continue",
                     "verify you are human", "cf-chl", "challenge-platform", "/cdn-cgi/challenge", "/_fs-ch-",
                     "_incapsula_resource", "captcha-delivery.com", "px-captcha")


def flags(response, text):
    """Heuristic prompts for human review, never conclusions."""
    found = []
    robots_header = (response.header("x-robots-tag") or "").lower()
    directives = {part.strip() for part in re.split(r"[,:]", robots_header)}
    if directives & {"noindex", "none"}:
        found.append("noindex_header")
    if text is None:
        return found
    head = text[:200_000]
    for tag in re.findall(r"(?is)<meta\b[^>]*>", head):
        if re.search(r"name=[\"']?(robots|googlebot)\b", tag, re.I) and re.search(r"noindex|\bnone\b", tag, re.I):
            found.append("noindex_meta")
            break
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", head)
    title = " ".join(title[1].split()).lower() if title else ""
    lower = head.lower()
    # Bot challenges are often served with HTTP 200, and also as 403, 429 or 503.
    if CHALLENGE_TITLE.search(title) or any(marker in lower for marker in CHALLENGE_MARKERS):
        found.append("possible_challenge")
    if response.status == 200:
        if re.search(r"\b(404|not found|page not found|does not exist)\b", title):
            found.append("possible_soft_404")
        if len(visible_text(head)) < 200:
            found.append("thin_response")
    return found


def header_line(key, value):
    """Cookie values can be session tokens; keep the name and security attributes only."""
    if key.lower() == "set-cookie":
        name, _, rest = value.partition("=")
        attributes = rest.split(";", 1)[1].strip() if ";" in rest else ""
        value = f"{name.strip()}=[value redacted by collect.py]" + (f"; {attributes}" if attributes else "")
    return f"{key}: {value}"


def describe(requested, chain, final_text, notes, binary):
    """Readable capture: request, every redirect hop, the final response headers and body."""
    final = chain[-1]
    lines = [f"Request: GET {requested}", f"User-Agent: {USER_AGENT}"]
    lines += [f"Redirect: {hop.status} {hop.url} -> {hop.location}" for hop in chain[:-1]]
    lines += [f"Response: {final.status} {final.reason}".rstrip(), f"Final URL: {final.url}"]
    lines += [header_line(key, value) for key, value in final.headers]
    lines += [f"Note: {note}" for note in notes]
    lines.append("")
    lines.append(final_text if final_text is not None else binary)
    return "\n".join(lines)


def record(identifier, source, collected_at, content, status):
    return {"id": identifier, "source": source, "collected_at": collected_at, "method": METHOD,
            "content": content, "status": status, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}


def host_twins(url):
    host = (urlsplit(url).hostname or "").lower()
    bare = host[4:] if host.startswith("www.") else host
    return {bare, "www." + bare}


def follow(client, url, scope, allowed=None):
    """Request url and follow redirects within scope. Returns (chain, notes, error)."""
    chain, notes, current = [], [], url
    for hop in range(MAX_REDIRECTS + 1):
        response = client.get(current)
        if response.error:
            return chain, notes, response.error
        chain.append(response)
        target = response.location
        if target is None:
            break
        if hop == MAX_REDIRECTS:
            notes.append(f"Redirect limit of {MAX_REDIRECTS} reached; {target} was not fetched")
        elif (urlsplit(target).hostname or "").lower() not in scope:
            notes.append(f"Redirect target outside the collection scope was not fetched: {target}")
        elif client.refusal(target):
            notes.append(f"Redirect target was not fetched: {client.refusal(target)}")
        elif allowed and not allowed(target):
            notes.append(f"Redirect target is disallowed by robots.txt for {TOKEN} and was not fetched: {target}")
        else:
            current = target
            continue
        break
    return chain, notes, None


def robots_record(client, url):
    robots, chain = client.robots(url)
    origin = urlsplit(robots.url)
    slug = re.sub(r"[^a-z0-9]+", "-", origin.netloc.lower()).strip("-")
    identifier = f"robots-{slug}" if origin.scheme == "https" else f"robots-{origin.scheme}-{slug}"
    if chain and not chain[-1].error:
        text, _, note = decode(chain[-1])
        if text is not None:
            text = text[:ROBOTS_LIMIT]
        content = describe(chain[0].url, chain, text, [f"Robots state: {robots.state} ({robots.detail})"]
                           + ([note] if note else []), "[Binary robots.txt body omitted]")
        return robots, record(identifier, chain[0].url, chain[-1].collected_at, content, "success")
    detail = chain[-1].error if chain else robots.detail
    content = f"Request: GET {robots.url}\nNot captured: {detail}\nRobots state: {robots.state}"
    return robots, record(identifier, robots.url, now(), content, "failed" if chain else "unavailable")


def capture_page(client, identifier, url, raw_dir):
    """Capture one sample URL. Returns (evidence record, log entry)."""
    robots, _ = client.robots(url)
    log = {"id": identifier, "url": url, "robots_for_collector": robots.decision(TOKEN, url)}
    refusal = client.refusal(url)
    if refusal or not log["robots_for_collector"]["allowed"]:
        reason = refusal or f"disallowed by robots.txt for {TOKEN} ({log['robots_for_collector']['rule'] or robots.state})"
        log.update(status="unavailable", notes=[reason])
        return record(identifier, url, now(), f"Request: GET {url}\nNot fetched: {reason}", "unavailable"), log
    def allowed(target):
        return robots_for(client, target).decision(TOKEN, target)["allowed"]
    chain, notes, error = follow(client, url, host_twins(url), allowed)
    if error:
        hops = "".join(f"\nRedirect: {hop.status} {hop.url} -> {hop.location}" for hop in chain)
        log.update(status="failed", notes=[error], redirects=[hop.url for hop in chain])
        return record(identifier, url, now(), f"Request: GET {url}{hops}\nCollection failed: {error}", "failed"), log
    final = chain[-1]
    text, charset, note = decode(final)
    if note:
        notes.append(note)
    digest = hashlib.sha256(final.body).hexdigest()
    raw_path = raw_dir / f"{digest}.bin"
    if not raw_path.exists():
        write_new(raw_path, final.body)
    binary = f"[Binary body omitted: {final.header('content-type') or 'unknown type'}, {len(final.body):,} bytes, " \
             f"SHA-256 {digest}]"
    content = describe(url, chain, text, notes, binary)
    log.update(status="success", http_status=final.status, final_url=final.url,
               redirects=[{"status": hop.status, "from": hop.url, "to": hop.location} for hop in chain[:-1]],
               content_type=final.header("content-type"), charset=charset, bytes=len(final.body),
               body_sha256=digest, raw_path=str(raw_path.relative_to(raw_dir.parent)), flags=flags(final, text),
               notes=notes)
    return record(identifier, url, final.collected_at, content, "success"), log


# ---------------------------------------------------------------------------
# Sitemaps
# ---------------------------------------------------------------------------

def sitemap_text(response):
    body = response.body
    if body.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(SITEMAP_TEXT_LIMIT + 1)
        if len(body) > SITEMAP_TEXT_LIMIT:
            raise ValueError("decompressed sitemap exceeds 50 MiB")
    return body.decode("utf-8", errors="replace")


def parse_sitemap(text):
    """Return ('index'|'urlset'|'text', entries). XML with a DTD is refused, never expanded."""
    stripped = text.lstrip("﻿ \t\r\n")
    if not stripped.startswith("<"):
        return "text", [{"loc": line.strip()} for line in text.splitlines() if line.strip().startswith("http")]
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise ValueError("sitemap declares a DTD or entities; refused for safety")
    root = ElementTree.fromstring(text)
    local = root.tag.rsplit("}", 1)[-1]
    if local not in {"sitemapindex", "urlset"}:
        raise ValueError(f"unexpected sitemap root element {local}")
    entries = []
    for item in root:
        values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in item}
        if values.get("loc"):
            entries.append({"loc": values["loc"], **({"lastmod": values["lastmod"]} if values.get("lastmod") else {})})
    return ("index" if local == "sitemapindex" else "urlset"), entries


def discover(client, origin, *, agents=REPORT_AGENTS, max_sitemaps=MAX_SITEMAPS, max_urls=MAX_SITEMAP_URLS):
    """Robots, sitemaps and candidate pages for one origin. Returns (summary, evidence records)."""
    robots, robots_evidence = robots_record(client, origin)
    evidence, notes = [robots_evidence], []
    scope = host_twins(origin)
    queue = list(dict.fromkeys(robots.sitemaps))
    if not queue:
        queue = [urljoin(origin, "/sitemap.xml")]
        notes.append("robots.txt declares no sitemap; tried the conventional /sitemap.xml")
    seen, sitemaps, candidates, out_of_scope, truncated = set(), [], {}, 0, False
    while queue and len(seen) < max_sitemaps and not truncated:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        entry = {"url": url}
        sitemaps.append(entry)
        refusal = client.refusal(url) or (None if robots_for(client, url).decision(TOKEN, url)["allowed"]
                                          else f"disallowed by robots.txt for {TOKEN}")
        if refusal:
            entry["error"] = refusal
            continue
        identifier = f"sitemap-{len(sitemaps):02d}"
        chain, follow_notes, error = follow(client, url, host_twins(url) | scope)
        if error:
            entry["error"] = error
            evidence.append(record(identifier, url, now(), f"Request: GET {url}\nCollection failed: {error}", "failed"))
            continue
        if chain[-1].location or chain[-1].status != 200:
            entry["error"] = follow_notes[0] if follow_notes else f"HTTP {chain[-1].status}"
            evidence.append(record(identifier, url, chain[-1].collected_at,
                                   describe(url, chain, None, follow_notes, "[Body not used]"), "success"))
            continue
        try:
            text = sitemap_text(chain[-1])
            kind, entries = parse_sitemap(text)
        except (ValueError, OSError, ElementTree.ParseError) as error:
            entry["error"] = f"{type(error).__name__}: {error}"
            text, kind, entries = None, None, []
        entry.update(kind=kind, entries=len(entries))
        body = text if text is not None and len(text) <= SITEMAP_EMBED_LIMIT else (
            f"[Sitemap body not embedded: {len(text or ''):,} characters. Entries listed: {len(entries):,}. "
            f"Raw response SHA-256 {hashlib.sha256(chain[-1].body).hexdigest()}.]")
        evidence.append(record(identifier, url, chain[-1].collected_at,
                               describe(url, chain, body, follow_notes, "[Binary body]"), "success"))
        if kind == "index":
            queue += [item["loc"] for item in entries if item["loc"] not in seen]
            continue
        for item in entries:
            if len(candidates) >= max_urls:
                truncated = True
                break
            loc = item["loc"]
            if (urlsplit(loc).hostname or "").lower() not in scope:
                out_of_scope += 1
            elif loc not in candidates:
                candidates[loc] = item
    if truncated:
        notes.append(f"Stopped at {max_urls:,} candidate URLs; later sitemap entries were not listed")
    elif queue:
        truncated = True
        notes.append(f"Stopped after {max_sitemaps} sitemaps; {len(queue)} more were not fetched")
    report, blocked_by_rules = {}, {}
    for agent in agents:
        groups = robots.groups_for(agent)
        # Agents that fall back to the same groups share one pass over the candidates.
        key = tuple(id(group) for group in groups)
        if key not in blocked_by_rules:
            blocked_by_rules[key] = [url for url in candidates if not robots.decide(groups, agent, url)["allowed"]]
        blocked = blocked_by_rules[key]
        report[agent] = {"homepage": robots.decision(agent, urljoin(origin, "/")),
                         "disallowed_candidates": len(blocked), "examples": blocked[:5]}
    summary = {"origin": origin, "collected_at": now(), "collector": USER_AGENT, "robots": robots.summary(),
               "agents": report, "sitemaps": sitemaps, "candidates": list(candidates.values()),
               "candidate_count": len(candidates), "out_of_scope": out_of_scope, "truncated": truncated,
               "notes": notes}
    return summary, evidence


def robots_for(client, url):
    return client.robots(url)[0]


def fetch(client, urls, raw_dir, *, agents=REPORT_AGENTS, id_prefix="page"):
    """Capture each URL once. Returns (evidence records, log)."""
    problems = check_urls(urls)
    if problems:
        raise ValueError("; ".join(problems))
    evidence, entries, robots_ids = [], [], set()
    for index, url in enumerate(urls, 1):
        robots, robots_evidence = robots_record(client, url)
        if robots_evidence["id"] not in robots_ids:
            robots_ids.add(robots_evidence["id"])
            evidence.append(robots_evidence)
        page, entry = capture_page(client, f"{id_prefix}-{index:02d}", url, raw_dir)
        entry["robots_reported"] = {agent: robots.decision(agent, url) for agent in agents}
        evidence.append(page)
        entries.append(entry)
    validate_registry(evidence)
    counts = {status: sum(entry["status"] == status for entry in entries) for status in ("success", "failed", "unavailable")}
    log = {"collector": USER_AGENT, "completed_at": now(), "limits": {
        "max_pages": MAX_PAGES, "timeout_seconds": client.timeout, "max_bytes": client.max_bytes,
        "max_redirects": MAX_REDIRECTS, "min_delay_seconds": client.delay, "host_delays": client.host_delay},
        "counts": counts, "pages": entries}
    return evidence, log


def check_urls(urls):
    problems = []
    if not urls:
        problems.append("supply at least one URL")
    if len(urls) > MAX_PAGES:
        problems.append(f"at most {MAX_PAGES} pages can be captured for one run")
    if len(set(urls)) != len(urls):
        problems.append("each URL must appear once")
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            problems.append(f"not an HTTP(S) URL: {url}")
        elif "#" in url:
            problems.append(f"remove the fragment, which never reaches the server: {url}")
    return problems


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def delay_value(text):
    value = float(text)
    if value < MIN_DELAY:
        raise argparse.ArgumentTypeError(f"delay must be at least {MIN_DELAY} seconds")
    return value


def dump(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser("discover", help="Read robots.txt and sitemaps; list candidate pages")
    find.add_argument("origin")
    find.add_argument("output", type=Path)
    find.add_argument("--max-sitemaps", type=int, default=MAX_SITEMAPS)
    find.add_argument("--max-urls", type=int, default=MAX_SITEMAP_URLS)
    get = commands.add_parser("fetch", help="Capture the chosen sample pages as evidence records")
    get.add_argument("output", type=Path)
    get.add_argument("urls", nargs="*")
    get.add_argument("--urls-file", type=Path, help="One URL per line; blank lines and # comments are ignored")
    get.add_argument("--id-prefix", default="page")
    for command in (find, get):
        command.add_argument("--agent", action="append", help="Crawler token to report (repeatable)")
        command.add_argument("--delay", type=delay_value, default=MIN_DELAY, help="Seconds between requests to a host")
        command.add_argument("--allow-private", action="store_true",
                             help="Permit loopback/private addresses, for example a local staging site")
    args = parser.parse_args()
    agents = tuple(args.agent) if args.agent else REPORT_AGENTS
    client = Client(delay=args.delay, allow_private=args.allow_private)
    try:
        if args.command == "discover":
            if check_urls([args.origin]):
                parser.error("; ".join(check_urls([args.origin])))
            args.output.mkdir(parents=True, exist_ok=True)
            targets = [args.output / "discovery.json", args.output / "discovery-evidence.json"]
            for target in targets:
                check_new(target)
            summary, evidence = discover(client, args.origin, agents=agents,
                                         max_sitemaps=args.max_sitemaps, max_urls=args.max_urls)
            validate_registry(evidence)
            write_new(targets[0], dump(summary))
            write_new(targets[1], dump(evidence))
            print(json.dumps({"discovery": str(targets[0]), "evidence": str(targets[1]),
                              "robots": summary["robots"]["state"], "sitemaps": len(summary["sitemaps"]),
                              "candidates": summary["candidate_count"], "truncated": summary["truncated"]}, indent=2))
        else:
            urls = list(args.urls)
            if args.urls_file:
                urls += [line.strip() for line in args.urls_file.read_text(encoding="utf-8").splitlines()
                         if line.strip() and not line.lstrip().startswith("#")]
            if check_urls(urls):
                parser.error("; ".join(check_urls(urls)))
            args.output.mkdir(parents=True, exist_ok=True)
            targets = [args.output / "fetch-evidence.json", args.output / "fetch-log.json"]
            for target in targets:
                check_new(target)
            raw_dir = args.output / "raw"
            raw_dir.mkdir(exist_ok=True)
            evidence, log = fetch(client, urls, raw_dir, agents=agents, id_prefix=args.id_prefix)
            write_new(targets[0], dump(evidence))
            write_new(targets[1], dump(log))
            print(json.dumps({"evidence": str(targets[0]), "log": str(targets[1]), **log["counts"]}, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Collection failed: {exc}\n")


if __name__ == "__main__":
    main()
