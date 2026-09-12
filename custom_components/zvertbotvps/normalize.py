from __future__ import annotations

from copy import deepcopy
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def normalize_status(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the VPS status payload while preserving its public contract."""
    data = deepcopy(raw)
    data["server"] = _dict(data.get("server"))
    data["system"] = _dict(data.get("system"))
    data["services"] = _dict(data.get("services"))
    data["backup"] = _dict(data.get("backup"))
    data["fail2ban"] = _dict(data.get("fail2ban"))
    data["connections"] = _list(data.get("connections"))

    awg = _dict(data.get("awg"))
    xray = _dict(data.get("xray"))

    # Accept the transitional flat form as well.
    if not awg and isinstance(data.get("awg_clients"), list):
        awg = {"clients": data["awg_clients"]}
    if not xray and isinstance(data.get("xray_clients"), list):
        xray = {"clients": data["xray_clients"]}

    awg["clients"] = _list(awg.get("clients"))
    xray["clients"] = _list(xray.get("clients"))

    # The dashboard expects `peers` to contain the complete AWG client
    # presentation data. Some payloads provide peers and the enriched client
    # registry separately, so merge the two collections by IP/name instead of
    # choosing one and silently dropping fields such as online/last_ip/GeoIP.
    raw_peers = _list(awg.get("peers"))
    clients = awg["clients"]
    client_by_ip = {str(item.get("ip")): item for item in clients if item.get("ip")}
    client_by_name = {str(item.get("name")): item for item in clients if item.get("name")}

    peers = []
    for peer in raw_peers or clients:
        enriched = dict(peer)
        match = client_by_ip.get(str(peer.get("ip"))) if peer.get("ip") else None
        if match is None and peer.get("name"):
            match = client_by_name.get(str(peer.get("name")))
        if match:
            merged = dict(match)
            merged.update(enriched)
            enriched = merged
        peers.append(enriched)

    awg["peers"] = peers

    data["awg"] = awg
    data["xray"] = xray

    return data
