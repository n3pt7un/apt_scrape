"""Unit tests for ImmobiliareAdapter parsing and URL building (no network)."""

from apt_scrape.sites import SearchFilters, get_adapter

_HTML = """
<html><body>
  <nav><ul>
    <li class="nd-list__item"><a href="https://www.immobiliare.it/">Home</a></li>
    <li class="nd-list__item"><a href="/affitto-appartamenti/bologna/murri-massarenti/con-ascensore/">Ascensore</a></li>
  </ul></nav>
  <ul>
    <li class="nd-list__item ListItem_item__card__XyZ12">
      <a class="Title_title__AbC34" href="https://www.immobiliare.it/annunci/123456/">
        Bilocale via Massarenti 10, Massarenti, Bologna
      </a>
      <div class="Price_price__QwE56"><span>€ 950/mese</span></div>
    </li>
  </ul>
  <footer><ul>
    <li class="nd-list__item"><a href="/info/chi-siamo/">Chi siamo</a></li>
  </ul></footer>
</body></html>
"""


def test_parse_search_drops_nav_and_footer_links():
    listings = get_adapter("immobiliare").parse_search(_HTML)
    assert [ls.url for ls in listings] == ["https://www.immobiliare.it/annunci/123456/"]
    assert listings[0].price == "€ 950/mese"


def test_build_search_url_omits_zero_bounds():
    url = get_adapter("immobiliare").build_search_url(
        SearchFilters(city="bologna", min_price=0, max_price=1200, min_sqm=0, min_rooms=1, page=2)
    )
    assert "superficieMinima" not in url
    assert "prezzoMinimo" not in url
    assert "prezzoMassimo=1200" in url
    assert "localiMinimo=1" in url
    assert "pag=2" in url
