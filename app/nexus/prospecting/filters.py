"""Domain blocklists for prospecting guardrails.

Single source of truth for domains that are never a real company target,
regardless of vertical:

  BLOCKED_EXACT_DOMAINS  — frozenset, matched against parsed hostname (used by ddg.py)
  BLOCKED_HINT_PREFIXES  — tuple of substrings, matched against full URL blob (used by service.py)

Per-vertical blocklists (e.g. real-estate/accounting directory portals) live in
sales_verticals.discovery_config['blocked_hint_prefixes'] — see SalesVerticalsRepository.

To block a new domain: add it to BLOCKED_EXACT_DOMAINS (and BLOCKED_HINT_PREFIXES if it
needs partial/subdomain matching). Never touch ddg.py or service.py directly for this.
"""

from __future__ import annotations

# ── 1. Exact-domain blocklist ─────────────────────────────────────────────────
# Matched via `hostname in BLOCKED_EXACT_DOMAINS` or `root_domain in BLOCKED_EXACT_DOMAINS`.
# Use this for domains where any subdomain/path is also off-limits.

BLOCKED_EXACT_DOMAINS: frozenset[str] = frozenset({
    # Social networks
    "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "tiktok.com",
    # Maps & review aggregators
    "google.com", "google.es", "maps.google.com",
    "tripadvisor.com", "tripadvisor.es",
    "yelp.com", "yelp.es",
    "thefork.com", "thefork.es", "eltenedor.es",
    # Generic B2B directories & business info portals
    "paginasamarillas.es", "paginasblancas.es", "infobel.com",
    "axesor.es", "einforma.com", "infocif.es", "empresite.es",
    "expansion.com", "eleconomista.es", "cincodias.elpais.com",
    "boe.es", "noticias.juridicas.com",
    "infoisinfo.com", "infoisinfo.es",
    "europages.es", "europages.com",
    "kompass.com", "kompass.es",
    "hotfrog.es", "hotfrog.com",
    # Knowledge / encyclopaedia
    "wikipedia.org", "wikimedia.org",
    # Real estate portals (generic — also covered in inmobiliaria's discovery_config.blocked_hint_prefixes)
    "idealista.com", "fotocasa.es", "pisos.com", "habitaclia.com",
    "yaencontre.com", "indomio.es", "globaliza.com", "trovimap.com",
    "kyero.com", "nestoria.com", "thinkspain.com", "milanuncios.com",
})

# ── 2. Substring hint blocklist ───────────────────────────────────────────────
# Matched via `hint in url_blob` where url_blob is a lowercased concat of url+title+name.
# Use this when you need to catch subdomains, ccTLDs, or paths (e.g. "tripadvisor." catches
# tripadvisor.com, tripadvisor.es, tripadvisor.co.uk, etc.).

BLOCKED_HINT_PREFIXES: tuple[str, ...] = (
    "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "google.com", "google.es",
    "tripadvisor.", "thefork.", "yelp.",
    "paginasamarillas",
    "infoisinfo.", "europages.", "kompass.", "hotfrog.",
    "wikipedia.org", "wikimedia.org",
)
