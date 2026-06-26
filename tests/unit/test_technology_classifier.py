from __future__ import annotations

from nexus.targets.catalogue import TechnologyCatalogue
from nexus.targets.classifier import TechnologyClassifier


def test_catalogue_incluye_las_cuatro_familias_iniciales():
    catalogue = TechnologyCatalogue()

    assert "compute.linux" in catalogue.ids()
    assert "compute.windows" in catalogue.ids()
    assert "network.firewall.fortinet" in catalogue.ids()
    assert "network.switch.cisco" in catalogue.ids()


def test_classifier_detecta_linux_por_texto():
    classifier = TechnologyClassifier()

    resolution = classifier.classify("diagnostica el servidor linux web-prod-01 que va lento")

    assert resolution is not None
    assert resolution.technology_key == "compute.linux"
    assert resolution.access_key == "ssh"
    assert resolution.target_hint == "web-prod-01"


def test_classifier_detecta_windows_por_powershell():
    classifier = TechnologyClassifier()

    resolution = classifier.classify("revisa el windows server app-win-02 por powershell")

    assert resolution is not None
    assert resolution.technology_key == "compute.windows"
    assert resolution.access_key == "winrm"


def test_classifier_detecta_fortinet_por_metadata():
    classifier = TechnologyClassifier()

    resolution = classifier.classify(
        "hay una alerta critica de firewall",
        metadata={"labels": {"vendor": "fortinet", "device_type": "fortigate"}},
    )

    assert resolution is not None
    assert resolution.technology_key == "network.firewall.fortinet"
    assert resolution.access_key == "fortios-api"


def test_classifier_detecta_cisco_switch_por_texto():
    classifier = TechnologyClassifier()

    resolution = classifier.classify("mira el switch cisco de core porque una vlan no levanta")

    assert resolution is not None
    assert resolution.technology_key == "network.switch.cisco"
    assert resolution.access_key == "network-cli"
