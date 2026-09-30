"""tests/unit/test_regulations_repository.py

RegulationsRepository — catalogo de normativas -> sectores reales, mismo
patron que GrantsRepository/SalesVerticalsRepository. Cubre la semilla
real (NIS2) y el CRUD manual (sin lifecycle de descubrimiento, a
diferencia de grants — una directiva no caduca como un programa de
ayudas).
"""

from __future__ import annotations

from nexus.prospecting.regulations import RegulationsRepository


def _repo(tmp_path) -> RegulationsRepository:
    return RegulationsRepository(tmp_path)


def test_seeds_real_nis2_regulation_on_first_use(tmp_path):
    repo = _repo(tmp_path)
    slugs = {r.slug for r in repo.list_all()}
    assert slugs == {"nis2"}
    nis2 = repo.get("nis2")
    assert nis2.activo is True
    assert len(nis2.sectores) >= 10  # NIS2 cubre muchos sectores reales (Anexos I y II)
    assert "energía" in " ".join(nis2.sectores)
    assert "administraciones públicas" in nis2.sectores


def test_list_active_excludes_deactivated(tmp_path):
    repo = _repo(tmp_path)
    repo.set_activo("nis2", False)

    assert repo.list_active() == []
    assert repo.get("nis2").activo is False


def test_upsert_adds_new_regulation(tmp_path):
    repo = _repo(tmp_path)

    repo.upsert(
        slug="ens",
        nombre="Esquema Nacional de Seguridad",
        sectores=["administraciones públicas", "proveedores de servicios a la administración pública"],
        criterios="Aplica a entidades del sector publico y sus proveedores de servicios TIC.",
    )

    regs = {r.slug for r in repo.list_active()}
    assert regs == {"nis2", "ens"}


def test_upsert_is_idempotent_by_slug(tmp_path):
    repo = _repo(tmp_path)

    repo.upsert(slug="ens", nombre="ENS v1", sectores=["a"])
    repo.upsert(slug="ens", nombre="ENS v2", sectores=["a", "b"])

    assert len(repo.list_all()) == 2  # nis2 + ens, no duplicado
    assert repo.get("ens").nombre == "ENS v2"
    assert repo.get("ens").sectores == ["a", "b"]


def test_find_by_query_matches_by_partial_name_or_slug(tmp_path):
    repo = _repo(tmp_path)

    assert repo.find_by_query("la NIS2").slug == "nis2"
    assert repo.find_by_query("normativa de ciberseguridad NIS2").slug == "nis2"
    assert repo.find_by_query("nis2").slug == "nis2"


def test_find_by_query_returns_none_when_nothing_real_matches(tmp_path):
    repo = _repo(tmp_path)

    assert repo.find_by_query("una ley totalmente distinta que no existe") is None


def test_delete_removes_regulation(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert(slug="temporal", nombre="Temporal", sectores=["x"])

    repo.delete("temporal")

    assert repo.get("temporal") is None


def test_seed_is_idempotent_across_repository_instances(tmp_path):
    first = RegulationsRepository(tmp_path)
    first.upsert(slug="ens", nombre="ENS", sectores=["a"])
    second = RegulationsRepository(tmp_path)

    assert {r.slug for r in second.list_all()} == {"nis2", "ens"}
