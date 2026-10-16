"""Tests del catalogo de ofertas de Assets Consultores (nexus.prospecting.offerings)."""

from __future__ import annotations

from nexus.prospecting.offerings import OfferingsRepository, build_offerings_block


def _repo(tmp_path) -> OfferingsRepository:
    return OfferingsRepository(tmp_path / "prospecting")


def test_seed_is_loaded_on_first_use(tmp_path):
    repo = _repo(tmp_path)

    slugs = {o.slug for o in repo.list_all()}

    assert {"assets_perfil", "seguridad_nis2", "aegis", "energia_ot_it", "observabilidad_nexus"} <= slugs


def test_seed_is_not_reapplied_over_user_edits(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert(slug="aegis", nombre="AEGIS editado", cautelas="mi cautela")

    reopened = _repo(tmp_path)

    assert reopened.get("aegis").nombre == "AEGIS editado"
    assert reopened.get("aegis").cautelas == "mi cautela"


def test_every_seeded_service_carries_a_caution_and_a_source_url(tmp_path):
    """La web no respalda sus cifras con clientes — ninguna oferta sembrada
    puede quedarse sin cautela ni sin enlace de origen."""
    repo = _repo(tmp_path)

    for offering in repo.list_all():
        assert offering.cautelas.strip(), f"{offering.slug} sin cautelas"
        assert offering.url.startswith("https://assetsconsultores.es"), f"{offering.slug} sin url de origen"


def test_aegis_does_not_offer_frameworks_that_are_only_roadmap(tmp_path):
    aegis = _repo(tmp_path).get("aegis")

    assert aegis.normativas == ["nis2"]
    assert "roadmap" in aegis.cautelas.lower()
    assert "patente" in aegis.cautelas.lower()


def test_set_activo_hides_offering_from_active_list(tmp_path):
    repo = _repo(tmp_path)

    repo.set_activo("outsourcing_monitorizacion", False)

    assert "outsourcing_monitorizacion" not in {o.slug for o in repo.list_active()}
    assert "outsourcing_monitorizacion" in {o.slug for o in repo.list_all()}


def test_block_lists_signals_and_cautions_but_not_the_profile(tmp_path):
    repo = _repo(tmp_path)

    block = build_offerings_block(repo.list_active())

    assert "slug=seguridad_nis2" in block
    assert "NO afirmar:" in block
    assert "encaja cuando:" in block
    assert "slug=assets_perfil" not in block


def test_block_for_empty_catalog_is_explicit():
    assert build_offerings_block([]) == "(sin ofertas en el catalogo)"
