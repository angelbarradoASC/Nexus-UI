"""tests/unit/test_grants_repository.py

GrantsRepository — catalogo de ayudas/subvenciones, mismo patron que
SalesVerticalsRepository. Cubre la semilla real (Kit Consulting, CDTI,
Aragón PYME Digitalización) y el flujo de descubrimiento automatico:
nada descubierto entra activo directamente, siempre pendiente_revision.
"""

from __future__ import annotations

from nexus.prospecting.grants import GrantsRepository


def _repo(tmp_path) -> GrantsRepository:
    return GrantsRepository(tmp_path)


def test_seeds_real_grants_on_first_use(tmp_path):
    repo = _repo(tmp_path)
    slugs = {g.slug for g in repo.list_all()}
    assert slugs == {"kit_consulting", "cdti_innovacion", "aragon_pyme_digitalizacion"}
    assert all(g.estado == "activo" for g in repo.list_all())
    assert all(g.fuente == "semilla_inicial" for g in repo.list_all())


def test_kit_consulting_employee_range_matches_real_program(tmp_path):
    repo = _repo(tmp_path)
    kit = repo.get("kit_consulting")
    assert kit.min_employees == 10
    assert kit.max_employees == 249


def test_list_active_filters_by_ambito(tmp_path):
    repo = _repo(tmp_path)
    estatal_only = repo.list_active(ambito="estatal")
    assert {g.slug for g in estatal_only} == {"kit_consulting", "cdti_innovacion"}

    both = repo.list_active(ambito=["estatal", "aragon"])
    assert len(both) == 3


def test_list_active_excludes_expired_and_pending(tmp_path):
    repo = _repo(tmp_path)
    repo.set_estado("kit_consulting", "expirado")
    repo.upsert_discovered(slug="nueva", nombre="Nueva Ayuda", ambito="estatal")

    active = repo.list_active()

    assert "kit_consulting" not in {g.slug for g in active}
    assert "nueva" not in {g.slug for g in active}


def test_discovered_grant_starts_as_pending_review_never_active(tmp_path):
    repo = _repo(tmp_path)

    grant = repo.upsert_discovered(
        slug="programa_nuevo", nombre="Programa Nuevo IA", ambito="estatal",
        criterios="empresas tecnologicas", min_employees=20, max_employees=100,
    )

    assert grant.estado == "pendiente_revision"
    assert grant.fuente == "descubrimiento_automatico"
    assert grant in repo.list_pending_review()
    assert grant not in repo.list_active()


def test_approve_moves_pending_to_active(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_discovered(slug="programa_nuevo", nombre="Programa Nuevo", ambito="estatal")

    repo.set_estado("programa_nuevo", "activo")

    assert repo.get("programa_nuevo").estado == "activo"
    assert repo.get("programa_nuevo") in repo.list_active()


def test_reject_deletes_pending_grant(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_discovered(slug="programa_falso", nombre="Programa Falso", ambito="estatal")

    repo.delete("programa_falso")

    assert repo.get("programa_falso") is None


def test_find_by_name_matches_slightly_different_wording(tmp_path):
    repo = _repo(tmp_path)
    found = repo.find_by_name("Programa Kit Consulting")
    assert found is not None
    assert found.slug == "kit_consulting"


def test_find_by_name_returns_none_when_no_real_match(tmp_path):
    repo = _repo(tmp_path)
    assert repo.find_by_name("Ayuda Totalmente Distinta") is None


def test_set_estado_rejects_invalid_value(tmp_path):
    repo = _repo(tmp_path)
    try:
        repo.set_estado("kit_consulting", "no_es_un_estado_valido")
        assert False, "deberia haber lanzado ValueError"
    except ValueError:
        pass
