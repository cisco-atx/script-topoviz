"""Network topology discovery and graph builder.

This module handles device discovery and builds a topology graph using
multithreaded execution. It connects to network devices, collects
inventory, CDP, MAC, and ARP data, and constructs a graph representation
of the network, classifying nodes into layers and generating positions.

File path: workers.py
"""

import re
from concurrent.futures import ThreadPoolExecutor

import networkx as nx
from netcore import GenericHandler


def discover_device(device, ctx):
    """Discover a single device and return nodes and links."""
    nodes = {}
    links = []

    ctx.log(f"Connecting to {device}")

    connector = ctx.config.get("connector", {})

    proxy = None
    if connector.get("jumphost_ip"):
        proxy = {
            "hostname": connector["jumphost_ip"],
            "username": connector["jumphost_username"],
            "password": connector["jumphost_password"],
        }

    try:
        conn = GenericHandler(
            hostname=device,
            username=connector["network_username"],
            password=connector["network_password"],
            proxy=proxy,
            handler="NETMIKO",
            read_timeout_override=1000,
        )

        hostname = conn.base_prompt

        inventory = conn.sendCommand("show inventory", autoParse=True)
        cdp = conn.sendCommand("show cdp neighbors", autoParse=True)
        mac_data = conn.sendCommand(
            "show mac address-table", autoParse=True
        )
        arp = conn.sendCommand("show ip arp", autoParse=True)

        ctx.log(f"{hostname}: Data collected")

        chassis = next(
            (i for i in inventory if i.get("name") == "Chassis"), {}
        )
        model = chassis.get("pid", "Unknown")

        nodes[hostname] = {
            "hostname": hostname,
            "model": model,
            "type": "network",
        }

        cdp_ports = set()

        for neighbor in cdp:
            raw_to_device = neighbor.get("neighbor", "").split(".")[0]
            to_device = re.split(
                r"\s*\(", raw_to_device
            )[0].strip()

            from_port = neighbor.get("local_interface")
            to_port = neighbor.get("remote_interface")

            if not from_port or not to_port:
                continue

            cdp_ports.add(from_port)

            if to_device not in nodes:
                nodes[to_device] = {
                    "hostname": to_device,
                    "model": neighbor.get("platform", "Unknown"),
                    "type": "network",
                }

            links.append(
                {
                    "from_device": hostname,
                    "from_port": from_port,
                    "to_device": to_device,
                    "to_port": to_port,
                }
            )

        ctx.log(f"{hostname}: CDP processed")

        arp_map = {
            entry.get("mac_address"): entry.get("ip_address")
            for entry in arp
            if entry.get("mac_address") and entry.get("ip_address")
        }

        for entry in mac_data:
            mac_address = entry.get("mac_address")
            interface = entry.get("ports")

            if not mac_address or not interface:
                continue

            if interface in cdp_ports:
                continue

            if any(
                    x in interface.lower()
                    for x in ["vlan", "po", "loopback", "sup-eth"]
            ):
                continue

            endpoint_id = arp_map.get(mac_address, mac_address)

            if endpoint_id not in nodes:
                nodes[endpoint_id] = {
                    "hostname": endpoint_id,
                    "model": "",
                    "parent": hostname,
                    "type": "endpoint",
                }

            nodes[hostname]["type"] = "access"

            links.append(
                {
                    "from_device": hostname,
                    "from_port": interface,
                    "to_device": endpoint_id,
                    "to_port": "",
                }
            )

        conn.close()
        ctx.log(f"{hostname}: Endpoint processed")

    except Exception as exc:
        raise

    return nodes, links


def run_topology(devices, ctx):
    """Run topology discovery across devices and build graph."""
    results = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(discover_device, d, ctx) for d in devices
        ]
        for future in futures:
            results.append(future.result())

    graph = nx.MultiDiGraph()
    seen_links = set()

    for nodes, links in results:
        for hostname, data in nodes.items():
            if hostname in graph:
                existing_type = graph.nodes[hostname].get(
                    "type", "network"
                )
                new_type = data.get("type", "network")

                if (
                        existing_type == "network"
                        and new_type != "network"
                ):
                    graph.nodes[hostname]["type"] = new_type
            else:
                graph.add_node(hostname, **data)

        for link in links:
            a = link["from_device"]
            b = link["to_device"]
            from_port = link["from_port"]
            to_port = link["to_port"]

            normalized = tuple(
                sorted([(a, from_port), (b, to_port)])
            )

            if normalized in seen_links:
                continue

            seen_links.add(normalized)

            graph.add_edge(
                a,
                b,
                from_port=from_port,
                to_port=to_port,
            )

    layers = {
        "core": [],
        "distribution": [],
        "access": [],
        "endpoint": [],
    }

    for node, data in graph.nodes(data=True):
        if data.get("type") == "endpoint":
            layers["endpoint"].append(node)
            continue

        neighbors = list(graph.neighbors(node))
        endpoint_links = any(
            graph.nodes[n].get("type") == "endpoint"
            for n in neighbors
        )

        if endpoint_links:
            layers["access"].append(node)
        elif len(neighbors) > 2:
            layers["core"].append(node)
        else:
            layers["distribution"].append(node)

    horizontal_spacing = 1000
    vertical_spacing = 600

    y_levels = {"core": 1, "distribution": 2, "access": 3}

    final_nodes = []

    for layer in ["core", "distribution", "access"]:
        nodes_in_layer = layers[layer]
        count = len(nodes_in_layer)

        if not count:
            continue

        start_x = -((count - 1) * horizontal_spacing) / 2

        for i, node in enumerate(nodes_in_layer):
            data = graph.nodes[node]

            x = start_x + (i * horizontal_spacing)
            y = y_levels[layer] * vertical_spacing

            final_nodes.append(
                {
                    "data": {
                        "id": node,
                        "model": data.get("model", ""),
                        "type": data.get("type", "network"),
                    },
                    "position": {"x": x, "y": y},
                }
            )

    for endpoint in layers["endpoint"]:
        parent = graph.nodes[endpoint].get("parent")

        if not parent:
            continue

        parent_node = next(
            (
                n
                for n in final_nodes
                if n["data"]["id"] == parent
            ),
            None,
        )

        if not parent_node:
            continue

        parent_x = parent_node["position"]["x"]
        parent_y = parent_node["position"]["y"]

        siblings = [
            n
            for n in final_nodes
            if graph.nodes.get(n["data"]["id"], {}).get("parent")
               == parent
        ]

        offset = (len(siblings)) * 120 - 60

        final_nodes.append(
            {
                "data": {
                    "id": endpoint,
                    "model": "",
                    "type": "endpoint",
                },
                "position": {
                    "x": parent_x + offset,
                    "y": parent_y + vertical_spacing,
                },
            }
        )

    final_edges = []

    for source, target, key, data in graph.edges(keys=True, data=True):
        edge_id = (
            f"{source}-{target}-"
            f"{data.get('from_port', '')}-"
            f"{data.get('to_port', '')}"
        )

        final_edges.append(
            {
                "data": {
                    "id": edge_id,
                    "source": source,
                    "target": target,
                    "from_port": data.get("from_port", ""),
                    "to_port": data.get("to_port", ""),
                }
            }
        )

    return {"nodes": final_nodes, "edges": final_edges}
