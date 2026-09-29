"""tests/unit/test_text_split_categories.py

split_target_categories() — trocea una descripcion libre multi-categoria
("peluquerias, talleres mecanicos y restaurantes") en frases individuales,
la pieza que arregla el bug real de la Campaña: una sola query mezclando
varias categorias devuelve paginas de listados en vez de negocios reales
(ver tests de service.generate_queries para el caso de uso completo).
"""

from __future__ import annotations

from nexus.utils.text import split_target_categories


def test_splits_on_commas_and_spanish_conjunctions():
    result = split_target_categories("peluquerias, talleres mecanicos y restaurantes")
    assert result == ["peluquerias", "talleres mecanicos", "restaurantes"]


def test_splits_on_e_before_i_sound():
    result = split_target_categories("tiendas e inmobiliarias")
    assert result == ["tiendas", "inmobiliarias"]


def test_single_category_returns_single_item_list():
    assert split_target_categories("peluquerias") == ["peluquerias"]


def test_empty_text_returns_empty_list():
    assert split_target_categories("") == []
    assert split_target_categories("   ") == []
    assert split_target_categories(None) == []  # type: ignore[arg-type]


def test_caps_at_max_categories():
    text = "uno, dos, tres, cuatro, cinco, seis"
    result = split_target_categories(text, max_categories=3)
    assert result == ["uno", "dos", "tres"]


def test_strips_whitespace_and_trailing_periods():
    result = split_target_categories(" peluquerias ,  talleres. ")
    assert result == ["peluquerias", "talleres"]


def test_keeps_multi_word_category_phrases_intact():
    """El separador es " y "/" e "/"," — el resto de palabras de una misma
    categoria (aqui "agencias inmobiliarias") no se trocea."""
    result = split_target_categories("agencias inmobiliarias y portales")
    assert result == ["agencias inmobiliarias", "portales"]
