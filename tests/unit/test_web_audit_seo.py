"""tests/unit/test_web_audit_seo.py

Tests unitarios para las señales SEO añadidas a WebAuditor._build_findings —
meta description, canonical, H1, Open Graph, datos estructurados y
sitemap/robots.txt. Prueba _build_findings directamente (funcion pura sobre
el dict crudo del eval), sin tocar Obscura/subprocess.
"""

from __future__ import annotations

from nexus.prospecting.web_audit import WebAuditor


def _good_raw(**overrides) -> dict:
    """Pagina sin ningun problema SEO — usado como base y para overrides
    puntuales que introducen exactamente un fallo a la vez."""
    base = {
        "load_time_ms": 1200,
        "ttfb_ms": 200,
        "has_viewport_meta": True,
        "is_https": True,
        "images_total": 2,
        "images_without_alt": 0,
        "has_contact_form": True,
        "has_whatsapp": True,
        "has_phone_link": True,
        "has_cta": True,
        "title_length": 40,
        "meta_description_length": 140,
        "has_canonical": True,
        "h1_count": 1,
        "has_og_tags": True,
        "has_structured_data": True,
        "sitemap_reachable": True,
    }
    base.update(overrides)
    return base


def test_no_seo_findings_when_everything_is_correct():
    findings = WebAuditor()._build_findings(_good_raw())
    assert findings["findings"] == []


def test_missing_meta_description_flagged():
    result = WebAuditor()._build_findings(_good_raw(meta_description_length=0))
    assert any("meta description" in f.lower() for f in result["findings"])
    assert result["seo"]["meta_description_length"] == 0


def test_meta_description_too_long_flagged():
    result = WebAuditor()._build_findings(_good_raw(meta_description_length=220))
    assert any("demasiado larga" in f for f in result["findings"])


def test_missing_canonical_flagged():
    result = WebAuditor()._build_findings(_good_raw(has_canonical=False))
    assert any("canonical" in f.lower() for f in result["findings"])
    assert result["seo"]["has_canonical"] is False


def test_zero_h1_flagged():
    result = WebAuditor()._build_findings(_good_raw(h1_count=0))
    assert any("no tiene ningun h1" in f.lower() for f in result["findings"])


def test_multiple_h1_flagged():
    result = WebAuditor()._build_findings(_good_raw(h1_count=3))
    assert any("3 h1" in f.lower() for f in result["findings"])


def test_missing_og_tags_flagged():
    result = WebAuditor()._build_findings(_good_raw(has_og_tags=False))
    assert any("open graph" in f.lower() for f in result["findings"])


def test_missing_structured_data_flagged():
    result = WebAuditor()._build_findings(_good_raw(has_structured_data=False))
    assert any("datos estructurados" in f.lower() for f in result["findings"])


def test_sitemap_not_reachable_flagged():
    result = WebAuditor()._build_findings(_good_raw(sitemap_reachable=False))
    assert any("sitemap" in f.lower() for f in result["findings"])


def test_seo_subdict_shape():
    result = WebAuditor()._build_findings(_good_raw())
    assert result["seo"] == {
        "meta_description_length": 140,
        "has_canonical": True,
        "h1_count": 1,
        "has_og_tags": True,
        "has_structured_data": True,
        "sitemap_reachable": True,
    }
