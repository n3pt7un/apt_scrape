"""apt_scrape.tui.app — Main Textual application."""

from textual._work_decorator import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)


class ScrapeDashboard(App):
    """Terminal dashboard for apt_scrape."""

    CSS = """
    #log-panel {
        height: 1fr;
        border: solid green;
    }
    #listings-table {
        height: 2fr;
    }
    #progress-bar {
        height: 3;
        margin: 1 2;
    }
    #status-bar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 2;
    }
    .section-title {
        text-style: bold;
        margin: 1 0;
        padding: 0 2;
    }
    #controls Horizontal {
        height: auto;
        margin: 0 1;
    }
    #config-tab Horizontal {
        height: 3;
        margin: 0 2;
    }
    #config-tab Label {
        width: 20;
        padding: 1 0;
    }
    #jobs-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "start_scrape", "Start Scrape"),
        ("d", "toggle_dark", "Dark Mode"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("Scrape", id="scrape-tab"):
                with Vertical():
                    with Horizontal(id="controls"):
                        yield Select(
                            [("Immobiliare.it", "immobiliare"), ("Casa.it", "casa"), ("Idealista", "idealista")],
                            prompt="Site",
                            id="site-select",
                        )
                        yield Input(placeholder="City (e.g. milano)", id="city-input")
                        yield Input(placeholder="Area (optional)", id="area-input")
                    yield ProgressBar(total=100, id="progress-bar", show_eta=True)
                    yield Static("Ready", id="status-bar")
                    yield DataTable(id="listings-table")
            with TabPane("Logs", id="logs-tab"):
                yield RichLog(id="log-panel", highlight=True, markup=True)
            with TabPane("Monitor", id="monitor-tab"):
                with Vertical():
                    yield Static("Job History", classes="section-title")
                    yield DataTable(id="jobs-table")
                    yield Static("", id="job-stats")
            with TabPane("Config", id="config-tab"):
                with Vertical():
                    yield Static("Scraping Configuration", classes="section-title")
                    with Horizontal():
                        yield Label("Max Pages:")
                        yield Input(value="3", id="max-pages-input", type="integer")
                    with Horizontal():
                        yield Label("Detail Enrichment:")
                        yield Switch(value=True, id="enrich-switch")
                    with Horizontal():
                        yield Label("AI Analysis:")
                        yield Switch(value=False, id="analyse-switch")
                    with Horizontal():
                        yield Label("Push to Notion:")
                        yield Switch(value=False, id="notion-switch")
                    with Horizontal():
                        yield Label("Operation:")
                        yield Select(
                            [("Affitto (Rent)", "affitto"), ("Vendita (Sale)", "vendita")],
                            value="affitto",
                            id="operation-select",
                        )
                    with Horizontal():
                        yield Label("Min Price (€):")
                        yield Input(placeholder="0", id="min-price-input", type="integer")
                    with Horizontal():
                        yield Label("Max Price (€):")
                        yield Input(placeholder="2000", id="max-price-input", type="integer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#listings-table", DataTable)
        table.add_columns("Score", "Title", "Price", "SQM", "Rooms", "Address", "URL")

        jobs_table = self.query_one("#jobs-table", DataTable)
        jobs_table.add_columns("Time", "Site", "City", "Listings", "Enriched", "Score", "Status")

    @property
    def log_panel(self) -> RichLog:
        return self.query_one("#log-panel", RichLog)

    def action_start_scrape(self) -> None:
        """Trigger a scrape job in the background."""
        site = self.query_one("#site-select", Select).value
        city = self.query_one("#city-input", Input).value
        area = self.query_one("#area-input", Input).value
        max_pages = int(self.query_one("#max-pages-input", Input).value or "1")
        include_details = self.query_one("#enrich-switch", Switch).value
        analyse = self.query_one("#analyse-switch", Switch).value
        push_notion = self.query_one("#notion-switch", Switch).value
        operation = self.query_one("#operation-select", Select).value
        min_price = self.query_one("#min-price-input", Input).value
        max_price = self.query_one("#max-price-input", Input).value

        if not city:
            self.log_panel.write("[red]Error: City is required[/red]")
            return

        self.log_panel.write(f"Starting scrape: {site} / {city} / {area or '(all)'} ({max_pages} pages)")
        self.query_one("#status-bar", Static).update(f"Scraping {city}...")
        self._run_scrape(site, city, area or None, max_pages, include_details,
                         analyse, push_notion, operation,
                         int(min_price) if min_price else None,
                         int(max_price) if max_price else None)

    @work(exclusive=True, group="scrape")
    async def _run_scrape(self, site: str, city: str, area: str | None,
                          max_pages: int = 1, include_details: bool = False,
                          analyse: bool = False, push_notion: bool = False,
                          operation: str = "affitto",
                          min_price: int | None = None, max_price: int | None = None) -> None:
        """Background worker: run the scrape pipeline."""
        from apt_scrape.server import fetcher
        from apt_scrape.sites import SearchFilters, get_adapter
        from apt_scrape.pipeline import Pipeline
        from apt_scrape.stages import DedupStage, EnrichStage, AnalyseStage, NotionPushStage

        adapter = get_adapter(site)
        all_listings = []

        # Scrape pages
        for page_num in range(1, max_pages + 1):
            filters = SearchFilters(city=city, area=area, operation=operation,
                                    min_price=min_price, max_price=max_price, page=page_num)
            url = adapter.build_search_url(filters)
            self.log_panel.write(f"Page {page_num}/{max_pages}: {url}")

            try:
                html = await fetcher.fetch_with_retry(
                    url, wait_selector=adapter.config.search_wait_selector
                )
                listings = adapter.parse_search(html)
                if not listings:
                    self.log_panel.write(f"No listings on page {page_num}, stopping.")
                    break
                all_listings.extend(listings)
                self.log_panel.write(f"  → {len(listings)} listings")
            except Exception as exc:
                self.log_panel.write(f"[red]Page {page_num} error: {exc}[/red]")
                break

        if not all_listings:
            self.query_one("#status-bar", Static).update("No listings found")
            return

        # Build pipeline
        dedup = DedupStage()
        stages = [dedup]
        if include_details:
            stages.append(EnrichStage(fetcher, adapter))
        if analyse:
            try:
                from apt_scrape.analysis import load_preferences
                prefs = load_preferences()
                stages.append(AnalyseStage(prefs))
            except FileNotFoundError:
                self.log_panel.write("[yellow]preferences.txt not found — skipping analysis[/yellow]")
        if push_notion:
            stages.append(NotionPushStage())

        pipeline = Pipeline(stages)
        self.log_panel.write(f"Pipeline: {' → '.join(s.name for s in stages)}")

        # Push through pipeline
        table = self.query_one("#listings-table", DataTable)
        table.clear()
        progress = self.query_one("#progress-bar", ProgressBar)
        progress.update(total=len(all_listings), progress=0)

        for i, ls in enumerate(all_listings):
            listing_dict = ls.to_dict()
            listing_dict["_area"] = area or ""
            listing_dict["_city"] = city
            await pipeline.push(listing_dict)
            progress.update(progress=i + 1)
            # Add to table immediately (before enrichment)
            table.add_row(
                str(listing_dict.get("ai_score", "")),
                ls.title[:40],
                ls.price,
                ls.sqm,
                ls.rooms,
                ls.address[:30],
                ls.url[:50],
            )

        await pipeline.finish()
        stats = pipeline.stats()
        self.log_panel.write(f"Pipeline complete: {stats}")

        # Add to jobs table
        from datetime import datetime
        jobs_table = self.query_one("#jobs-table", DataTable)
        jobs_table.add_row(
            datetime.now().strftime("%H:%M"),
            site,
            city,
            str(len(all_listings)),
            str(stats.get("enrich", {}).get("processed", "-")),
            str(stats.get("analyse", {}).get("processed", "-")),
            "Done",
        )

        self.query_one("#status-bar", Static).update(
            f"Done: {dedup.unique_count} unique listings ({dedup.dupe_count} dupes removed)"
        )

    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"


def run_tui() -> None:
    """Entry point for the Textual TUI."""
    app = ScrapeDashboard()
    app.run()
