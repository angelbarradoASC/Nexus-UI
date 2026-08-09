from __future__ import annotations

from nexus.prospecting.extractors import WebProspectExtractor, _default_obscura_binary


def test_default_obscura_binary_points_at_vendor_dir():
    binary = _default_obscura_binary()
    assert binary.parent.name == "obscura"
    assert binary.parent.parent.name == "vendor"


def test_resolve_obscura_binary_returns_none_when_missing(tmp_path):
    extractor = WebProspectExtractor(obscura_binary_path=str(tmp_path / "does-not-exist"))
    assert extractor._resolve_obscura_binary() is None


def test_resolve_obscura_binary_returns_configured_path_when_present(tmp_path):
    fake_binary = tmp_path / "obscura"
    fake_binary.write_text("fake")
    extractor = WebProspectExtractor(obscura_binary_path=str(fake_binary))
    assert extractor._resolve_obscura_binary() == fake_binary


def test_select_candidate_links_matches_hint_in_href_or_label():
    extractor = WebProspectExtractor()
    links = [
        {"href": "https://example.com/contacto", "text": "Escribenos"},
        {"href": "https://example.com/nosotros", "text": "Contacta con el equipo"},
        {"href": "https://example.com/blog/post-1", "text": "Ultimas noticias"},
        {"href": "tel:+34976221392", "text": "Llamar"},
    ]
    selected = extractor._select_candidate_links(links, hints=["contacto", "contact"])
    assert selected == ["https://example.com/contacto", "https://example.com/nosotros"]


def test_select_candidate_links_ignores_non_http_hrefs():
    extractor = WebProspectExtractor()
    links = [{"href": "javascript:void(0)", "text": "contacto"}, {"href": "mailto:hola@example.com", "text": "contacto"}]
    assert extractor._select_candidate_links(links, hints=["contacto"]) == []


def test_build_result_from_pages_uses_document_title_and_merges_pages():
    """El nombre sale directamente de document.title (renderizado real, via
    Obscura) en vez de heuristicas sobre texto libre — evita el bug de coger
    leyendas de widgets (video, banners) como si fueran el nombre del negocio.
    """
    extractor = WebProspectExtractor()
    pages = [
        {
            "_page_url": "https://www.asesoriaascaso.com",
            "title": "Asesoría Laboral Ascaso | C/ San Ignacio de Loyola, 6 - ZARAGOZA",
            "text": "Reproductor de video Asesoria Laboral Ascaso",
            "links": [{"href": "https://www.facebook.com/asesoriaascaso", "text": "Facebook"}],
        },
        {
            "_page_url": "https://www.asesoriaascaso.com/contacto",
            "title": "Contacto",
            "text": "Escribenos a info@asesoriaascaso.com o llama al 976221392",
            "links": [],
        },
    ]
    result = extractor._build_result_from_pages("https://www.asesoriaascaso.com", pages, [])
    assert result["name"] == "Asesoría Laboral Ascaso"
    assert result["emails"] == ["info@asesoriaascaso.com"]
    assert result["phones"] == ["976221392"]
    assert result["social_links"] == ["https://www.facebook.com/asesoriaascaso"]
    assert "https://www.asesoriaascaso.com/contacto" in result["evidence_urls"]


def test_build_result_from_pages_empty_list_returns_safe_defaults():
    extractor = WebProspectExtractor()
    result = extractor._build_result_from_pages("https://example.com", [], [])
    assert result["name"] == "Example"
    assert result["emails"] == []
    assert result["source_url"] == "https://example.com"
