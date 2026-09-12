import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "zvertbotvps" / "normalize.py"
_SPEC = importlib.util.spec_from_file_location("zvertbotvps_normalize", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
normalize_status = _MODULE.normalize_status


def test_normalize_status_uses_awg_clients_as_peers_when_peers_missing():
    raw = {
        "server": {"ip": "31.77.218.240"},
        "awg": {
            "clients": [
                {
                    "name": "Valya",
                    "ip": "10.66.66.4",
                    "online": False,
                    "total": "68.70 GB",
                }
            ],
        },
        "xray": {"clients": []},
    }

    data = normalize_status(raw)

    assert data["awg"]["peers"][0]["name"] == "Valya"
    assert data["awg"]["clients"][0]["name"] == "Valya"
    assert data["xray"]["clients"] == []


def test_normalize_status_preserves_awg_peer_fields_and_enriches_client():
    raw = {
        "server": {"ip": "31.77.218.240"},
        "awg": {
            "clients": [
                {
                    "name": "Valya",
                    "ip": "10.66.66.4",
                    "total": "68.70 GB",
                    "online": True,
                    "last_ip": "192.0.2.10",
                }
            ],
            "peers": [
                {
                    "ip": "10.66.66.4",
                    "endpoint": "192.0.2.10:443",
                }
            ],
        },
        "xray": {"clients": []},
    }

    data = normalize_status(raw)

    peer = data["awg"]["peers"][0]
    assert peer["name"] == "Valya"
    assert peer["total"] == "68.70 GB"
    assert peer["online"] is True
    assert peer["endpoint"] == "192.0.2.10:443"


def test_normalize_status_preserves_updated_at_without_legacy_aliases():
    raw = {
        "server": {"ip": "192.0.2.1"},
        "updated_at": "2026-09-12T10:00:00+03:00",
    }

    data = normalize_status(raw)

    assert data["updated_at"] == "2026-09-12T10:00:00+03:00"
    assert "vps_stats_last_check" not in data
    assert "check_timestamp" not in data
