"""apt_scrape.sites.casa — Adapter for Casa.it.

URL pattern: ``/{operation}/residenziale/{city}/?prezzo_min=X&prezzo_max=Y&...``
Config:      ``apt_scrape/sites/configs/casa.yaml``
"""

from pathlib import Path

from .base import SiteAdapter, load_config_from_yaml

_CONFIG_PATH = Path(__file__).parent / "configs" / "casa.yaml"


class CasaAdapter(SiteAdapter):
    """Adapter for Casa.it — Italy's oldest real estate portal (est. 1996).

    Uses fully config-driven parsing. The URL structure places all property
    types under the fixed path segment ``residenziale``, so the
    ``property_type_map`` in the YAML config collapses every property type
    to that value.
    """

    def __init__(self) -> None:
        super().__init__(load_config_from_yaml(_CONFIG_PATH))
