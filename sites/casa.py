"""
sites.casa — Adapter for Casa.it

URL pattern: /{operation}/residenziale/{city}/?prezzo_min=X&prezzo_max=Y&...
Config:       sites/configs/casa.yaml
"""

from pathlib import Path

from .base import SiteAdapter, load_config_from_yaml

_CONFIG_PATH = Path(__file__).parent / "configs" / "casa.yaml"



class CasaAdapter(SiteAdapter):
    """Casa.it — Italy's oldest real estate portal (since 1996).

    Uses the default config-driven parsing. The URL structure uses
    "residenziale" as a fixed category in the path rather than property
    subtypes, so the property_type_map collapses all types to that.
    """

    def __init__(self):
        super().__init__(load_config_from_yaml(_CONFIG_PATH))
