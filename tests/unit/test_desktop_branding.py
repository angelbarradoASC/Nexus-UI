from desktop.branding import resolve_branding_icon, resolve_windows_icon


def test_resolve_windows_icon_prioritizes_anchor_ico():
    icon = resolve_windows_icon()
    assert icon is not None
    assert icon.name == "nexus_anchor.ico"


def test_resolve_branding_icon_prioritizes_anchor_asset():
    icon = resolve_branding_icon()
    assert icon is not None
    assert icon.name in {"nexus_anchor.ico", "nexus_anchor.png"}
