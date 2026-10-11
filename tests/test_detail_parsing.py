"""Detail-page and text-extraction parsing for the site adapters (no network)."""

import re

import pytest
from bs4 import BeautifulSoup

from apt_scrape.sites import get_adapter
from apt_scrape.sites.base import (
    clean_agency_name,
    extract_block_text,
    extract_post_date_text,
    extract_text,
    normalize_energy_class,
)


def _el(html: str):
    return BeautifulSoup(html, "lxml").body.contents[0]


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------


def test_extract_text_separates_inline_tags_but_keeps_units_attached():
    assert extract_text(_el("<a><b>Bilocale</b>via Massarenti 10</a>")) == "Bilocale via Massarenti 10"
    assert extract_text(_el("<div><span>€ 500</span><span>/mese</span></div>")) == "€ 500/mese"
    assert extract_text(_el("<div><span>Bologna</span><span>, Italia</span></div>")) == "Bologna, Italia"


def test_extract_block_text_keeps_lines_and_paragraphs():
    html = (
        "<div><p>Camera arredata.\n   Luminosa.</p><p>Dotazioni:<br>* Letto<br>* Armadio "
        "<b>capiente</b></p></div>"
    )
    assert extract_block_text(_el(html)) == (
        "Camera arredata. Luminosa.\n\nDotazioni:\n* Letto\n* Armadio capiente"
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Immobiliare ScarpinoMostra TelefonoImmobiliare Scarpino", "Immobiliare Scarpino"),
        ("Professionecasa Bologna San VitaleMostra Telefono", "Professionecasa Bologna San Vitale"),
        ("AgenziaBologna ImmobiliareMostra Telefono", "Bologna Immobiliare"),
        (
            "Morena Dall'olioMostra TelefonoServizi Casa di Morena Dall'Olio - Gruppo REagent.it",
            "Morena Dall'olio",
        ),
        ("Agenzia\nBologna Immobiliare\nMostra telefono", "Bologna Immobiliare"),
        ("Agenzia Rossi", "Agenzia Rossi"),
        ("", ""),
    ],
)
def test_clean_agency_name(raw, expected):
    assert clean_agency_name(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("G", "G"),
        ("a4", "A4"),
        ("Classe A+", "A+"),
        ("classe energetica: B", "B"),
        ("G 175,00 kWh/m² anno", "G"),
        ("In attesa di certificazione", "In attesa di certificazione"),
        ("A norma di legge", ""),
        ("Prestazione energetica e consumi", ""),
        ("", ""),
    ],
)
def test_normalize_energy_class(raw, expected):
    assert normalize_energy_class(raw) == expected


def test_post_date_ignores_bare_relative_words_in_free_text():
    assert extract_post_date_text("Appartamento libero da oggi, zona servita") == ""


def test_post_date_relative_is_resolved_to_an_absolute_date():
    value = extract_post_date_text("Pubblicato oggi da Agenzia X")
    assert re.fullmatch(r"Pubblicato il \d{2}/\d{2}/\d{4}", value)


def test_post_date_dated_pattern_wins():
    text = "Pubblicato oggi ... Annuncio aggiornato il 06/10/2026"
    assert extract_post_date_text(text) == "Annuncio aggiornato il 06/10/2026"


def test_post_date_bare_relative_only_when_allowed():
    assert extract_post_date_text("ieri") == ""
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", extract_post_date_text("ieri", allow_bare_relative=True))


def test_search_card_snippet_oggi_is_not_a_post_date():
    html = """
    <ul><li class="nd-list__item ListItem_item__card__X">
      <a class="Title_title__A" href="https://www.immobiliare.it/annunci/1/">Bilocale</a>
      <div class="Price_price__Q"><span>€ 900/mese</span></div>
      <p class="in-description">Disponibile da oggi, arredato.</p>
    </li></ul>
    """
    listing = get_adapter("immobiliare").parse_search(html)[0]
    assert listing.post_date == ""


# ---------------------------------------------------------------------------
# Immobiliare detail page
# ---------------------------------------------------------------------------

IMMOBILIARE_DETAIL = """
<html><head><title>Trilocale via Molise 3 - Immobiliare.it</title></head><body>
<h1 class="Title_title__a">Trilocale via Molise 3, Mazzini - Fossolo, Bologna</h1>
<div class="Price_price__b"><span>€ 500/mese</span></div>
<div class="ReadAll_readAll__c"><p>Camera in affitto.<br>Libera da subito.</p><p>Contratto transitorio.</p></div>
<div class="ListingPhotos_cont__d">
  <img src="https://pwm.im-cdn.it/image/2017568370/cover-m-c.jpg">
  <img src="https://pwm.im-cdn.it/image/2017568342/m-c.jpg">
  <img src="https://pwm.im-cdn.it/image/2017568408/xxs-c.jpg">
</div>
<section>
  <h2>Caratteristiche</h2>
  <dl class="FeaturesGrid_list__e">
    <dt>Piano</dt><dd>Piano rialzato</dd>
    <dt>Superficie</dt><dd>79 m² | commerciale 80 m²</dd>
    <dt>Arredato</dt><dd>Sì</dd>
  </dl>
  <h3>Altre caratteristiche</h3>
  <ul><li>Fibra ottica</li><li>Cantina</li></ul>
</section>
<section>
  <h2>Costi</h2>
  <dl class="Costs_list__f"><dt>Spese condominio</dt><dd>€ 40/mese</dd><dt>Cauzione</dt><dd>€ 100</dd></dl>
</section>
<section>
  <h2>Efficienza energetica</h2>
  <dl class="Energy_list__g"><dt>Classe energetica</dt><dd>E 175,00 kWh/m² anno</dd><dt>Piano</dt><dd>3</dd></dl>
</section>
<div class="ContactForm_agencyData__h">
  <p>Agenzia</p><p>Bologna Immobiliare</p><button>Mostra Telefono</button>
</div>
<p>Annuncio aggiornato il 06/10/2026</p>
</body></html>
"""


def test_immobiliare_parse_detail_reads_every_section():
    detail = get_adapter("immobiliare").parse_detail(IMMOBILIARE_DETAIL, "https://www.immobiliare.it/annunci/1/")
    assert detail.title.startswith("Trilocale via Molise 3")
    assert detail.price == "€ 500/mese"
    assert detail.description == "Camera in affitto.\nLibera da subito.\n\nContratto transitorio."
    # Every non-cost <dl> is merged; the first section wins on a repeated label.
    assert detail.extra_info["Piano"] == "Piano rialzato"
    assert detail.extra_info["Classe energetica"].startswith("E")
    assert detail.extra_info["Altre caratteristiche"] == "Fibra ottica, Cantina"
    assert "Cauzione" not in detail.extra_info
    assert detail.costs == {"Spese condominio": "€ 40/mese", "Cauzione": "€ 100"}
    assert detail.size == "79 m²"
    assert detail.floor == "Piano rialzato"
    assert detail.energy_class == "E"
    assert detail.agency == "Bologna Immobiliare"
    assert detail.photos == [
        "https://pwm.im-cdn.it/image/2017568370/r.jpg",
        "https://pwm.im-cdn.it/image/2017568342/r.jpg",
        "https://pwm.im-cdn.it/image/2017568408/r.jpg",
    ]
    assert detail.post_date == "Annuncio aggiornato il 06/10/2026"


def test_immobiliare_energy_falls_back_to_description():
    html = IMMOBILIARE_DETAIL.replace("<dt>Classe energetica</dt><dd>E 175,00 kWh/m² anno</dd>", "").replace(
        "Contratto transitorio.", "Contratto transitorio. APE: G"
    )
    detail = get_adapter("immobiliare").parse_detail(html, "https://www.immobiliare.it/annunci/1/")
    assert detail.energy_class == "G"


# ---------------------------------------------------------------------------
# Config-driven adapters (Idealista list mode, Casa derived costs)
# ---------------------------------------------------------------------------

IDEALISTA_DETAIL = """
<html><body>
<nav><ul><li>Accedi</li><li>Pubblica annuncio</li></ul></nav>
<h1>Bilocale in via Mazzini</h1>
<span class="info-data-price">900 €/mese</span>
<div class="info-features"><span>60 m²</span><span>2 locali</span><span>Piano 1</span></div>
<div class="details-property">
  <div class="details-property-feature-one"><ul>
    <li>60 m² commerciali</li><li>Arredato</li><li>Spese condominiali: 50 €</li>
  </ul></div>
</div>
<span class="icon-energy-c-8"></span>
<footer><ul><li>Privacy</li></ul></footer>
</body></html>
"""


def test_idealista_list_features_scoped_and_energy_from_class_name():
    detail = get_adapter("idealista").parse_detail(IDEALISTA_DETAIL, "https://www.idealista.it/immobile/1/")
    assert detail.extra_info["Spese condominiali"] == "50 €"
    items = detail.extra_info["Caratteristiche"]
    assert "Arredato" in items and "2 locali" in items
    assert "Accedi" not in items and "Privacy" not in items
    assert detail.costs == {"Spese condominiali": "50 €"}
    assert detail.energy_class == "C"


CASA_DETAIL = """
<html><body>
<h1 class="csapdp-infos__tit">Bilocale Bologna</h1>
<div class="csapdp-infos__price">€ 850</div>
<ul>
  <li class="chars_item"><span class="chars__lbl">Locali</span><span class="chars__cnt">2</span></li>
  <li class="chars_item"><span class="chars__lbl">Spese condominiali</span><span class="chars__cnt">€ 60</span></li>
  <li class="chars_item"><span class="chars__lbl">Classe energetica</span><span class="chars__cnt">D</span></li>
</ul>
</body></html>
"""


def test_casa_costs_derived_from_features_and_energy_by_label():
    detail = get_adapter("casa").parse_detail(CASA_DETAIL, "https://www.casa.it/immobili/1/")
    assert detail.extra_info["Locali"] == "2"
    assert detail.costs == {"Spese condominiali": "€ 60"}
    assert detail.energy_class == "D"
