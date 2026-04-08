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
            with TabPane("Config", id="config-tab"):
                yield Static("Configuration panel — coming soon")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#listings-table", DataTable)
        table.add_columns("Score", "Title", "Price", "SQM", "Rooms", "Address", "URL")

    @property
    def log_panel(self) -> RichLog:
        return self.query_one("#log-panel", RichLog)

    def action_start_scrape(self) -> None:
        """Trigger a scrape job in the background."""
        site = self.query_one("#site-select", Select).value
        city = self.query_one("#city-input", Input).value
        area = self.query_one("#area-input", Input).value

        if not city:
            self.log_panel.write("[red]Error: City is required[/red]")
            return

        self.log_panel.write(f"Starting scrape: {site} / {city} / {area or '(all)'}")
        self.query_one("#status-bar", Static).update(f"Scraping {city}...")
        self._run_scrape(site, city, area or None)

    @work(exclusive=True, group="scrape")
    async def _run_scrape(self, site: str, city: str, area: str | None) -> None:
        """Background worker: run the scrape pipeline."""
        from apt_scrape.server import fetcher
        from apt_scrape.sites import SearchFilters, get_adapter

        adapter = get_adapter(site)
        filters = SearchFilters(city=city, area=area)
        url = adapter.build_search_url(filters)

        self.log_panel.write(f"Fetching: {url}")
        try:
            html = await fetcher.fetch_with_retry(
                url, wait_selector=adapter.config.search_wait_selector
            )
            listings = adapter.parse_search(html)
            self.log_panel.write(f"Found {len(listings)} listings")

            table = self.query_one("#listings-table", DataTable)
            for ls in listings:
                table.add_row(
                    "",  # Score (not yet analysed)
                    ls.title[:40],
                    ls.price,
                    ls.sqm,
                    ls.rooms,
                    ls.address[:30],
                    ls.url[:50],
                )

            progress = self.query_one("#progress-bar", ProgressBar)
            progress.update(total=len(listings), progress=len(listings))
            self.query_one("#status-bar", Static).update(
                f"Done: {len(listings)} listings from {adapter.config.display_name}"
            )
        except Exception as exc:
            self.log_panel.write(f"[red]Error: {exc}[/red]")
            self.query_one("#status-bar", Static).update("Error — check logs")

    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"


def run_tui() -> None:
    """Entry point for the Textual TUI."""
    app = ScrapeDashboard()
    app.run()
