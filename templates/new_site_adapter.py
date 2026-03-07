"""Template for creating a new site adapter — copy and fill in the blanks.

Steps:
    1. Copy this file to ``apt_scrape/sites/your_site.py``.
    2. Fill in ``CONFIG`` with the site's URL structure and CSS selectors.
    3. Register in ``apt_scrape/sites/__init__.py``::

           from .your_site import YourSiteAdapter
           ADAPTERS.append(YourSiteAdapter())

    4. Optionally override ``parse_search`` / ``parse_detail`` if the default
       config-driven logic does not work for the site's HTML structure.

Finding selectors:
    Run the CLI dump command to capture rendered HTML::

        python -m apt_scrape.cli dump \\
            --url "https://yoursite.com/search?..." \\
            -o dump.html

    Open ``dump.html`` in a browser, inspect listing cards, and note 2–3
    CSS selectors per field as fallbacks.
"""

from apt_scrape.sites.base import (
    DetailSelectors,
    SearchSelectors,
    SelectorGroup,
    SiteAdapter,
    SiteConfig,
)

CONFIG = SiteConfig(
    # ---- Identity -------------------------------------------------------
    site_id="yoursite",       # short slug used as --source value
    display_name="YourSite.it",
    base_url="https://www.yoursite.it",
    domain_pattern=r"yoursite\.it",  # regex matched against listing URLs

    # ---- Search URL structure -------------------------------------------
    # Placeholders available: {operation}, {property_type}, {city}
    search_path_template="/{operation}-{property_type}/{city}/",

    # Map normalized filter names to this site's query parameter names.
    # Only include parameters the site actually supports.
    query_param_map={
        "min_price": "prezzoMinimo",
        "max_price": "prezzoMassimo",
        "min_sqm": "superficieMinima",
        "max_sqm": "superficieMassima",
        "min_rooms": "localiMinimo",
        "max_rooms": "localiMassimo",
        "published_within": "giorniPubblicazione",
    },

    page_param="pag",  # e.g. ?pag=2

    # CSS selector Camoufox waits for before parsing begins.
    search_wait_selector="li.listing-item",
    detail_wait_selector="h1",

    # ---- Property type / operation slug mapping -------------------------
    property_type_map={
        "case": "case",
        "appartamenti": "appartamenti",
        "ville": "ville",
        # Add more as needed.
    },
    operation_map={
        "affitto": "affitto",
        "vendita": "vendita",
    },

    # ---- Search page selectors ------------------------------------------
    # Each SelectorGroup is a list of CSS selectors tried in order.
    # First match wins — add 2–3 fallbacks per field.
    search_selectors=SearchSelectors(
        listing_card=SelectorGroup([
            "li.listing-item",
            "div[class*='listing']",
            "article[class*='result']",
        ]),
        title=SelectorGroup([
            "a[class*='title']",
            "h2 a",
            "a[href*='/annunci/']",
        ]),
        price=SelectorGroup([
            "[class*='price']",
            "span[class*='prezzo']",
        ]),
        features=SelectorGroup([
            "li[class*='feature']",
            "span[class*='info']",
        ]),
        address=SelectorGroup([
            "[class*='address']",
            "[class*='location']",
        ]),
        thumbnail=SelectorGroup([
            "img[data-src]",
            "img",
        ]),
        description=SelectorGroup([
            "[class*='description']",
            "p[class*='excerpt']",
        ]),
    ),

    # ---- Detail page selectors ------------------------------------------
    detail_selectors=DetailSelectors(
        title=SelectorGroup(["h1"]),
        price=SelectorGroup(["[class*='price']"]),
        description=SelectorGroup(["[class*='description']"]),
        features_keys=SelectorGroup(["dl dt", "[class*='feature'] [class*='label']"]),
        features_values=SelectorGroup(["dl dd", "[class*='feature'] [class*='value']"]),
        address=SelectorGroup(["[class*='address']"]),
        photos=SelectorGroup(["[class*='gallery'] img", "img[data-src]"]),
        energy_class=SelectorGroup(["[class*='energy']"]),
        agency=SelectorGroup(["[class*='agency']"]),
        costs_keys=SelectorGroup(["[class*='cost'] dt"]),
        costs_values=SelectorGroup(["[class*='cost'] dd"]),
    ),
)


class YourSiteAdapter(SiteAdapter):
    """Adapter for YourSite.it.

    Uses config-driven parsing by default. Override methods below when the
    site needs logic that CSS selectors alone cannot express, such as:

    - Data loaded from ``<script>`` tags or JSON-LD instead of visible HTML.
    - Non-standard URL encoding or deep path nesting.
    - Infinite-scroll pagination instead of page query parameters.
    - Feature strings that require regex splitting.
    """

    def __init__(self) -> None:
        super().__init__(CONFIG)

    # Uncomment and implement as needed:
    #
    # def build_search_url(self, filters: SearchFilters) -> str:
    #     \"\"\"Override for non-standard URL building.\"\"\"
    #     ...
    #
    # def parse_search(self, html: str) -> list[ListingSummary]:
    #     \"\"\"Override for custom search result parsing.\"\"\"
    #     ...
    #
    # def parse_detail(self, html: str, url: str) -> ListingDetail:
    #     \"\"\"Override for custom detail page parsing.\"\"\"
    #     ...
