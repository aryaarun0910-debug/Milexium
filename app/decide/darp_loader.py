"""Loader/parser for Cordeau-format dial-a-ride benchmark instances.

The format (Cordeau 2006; the type-a/type-b instance files):

    K n T Q L                      # vehicles, requests, max route duration,
                                   #   vehicle capacity, max ride time
    id x y d q e l                 # node 0  = start depot
    ...                            # nodes 1..n   = pickups   (load +q)
    ...                            # nodes n+1..2n = drop-offs (load -q)
    id x y d q e l                 # node 2n+1 = end depot

`d` is service duration, `q` the (signed) load, `[e, l]` the time window; all
times are minutes and travel time between two nodes equals the Euclidean
distance between their coordinates.

This module is pure parsing plus a small helper to locate the instance archive
that `app.estate.acquire` promoted into `data/benchmarks/` (read from the
committed catalog record, so nothing hard-codes the content-addressed filename).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Iterator

from app.decide.darp_ir import DarpInstance, DarpNode

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG = _REPO_ROOT / "data" / "catalog"


def parse_instance(text: str, *, name: str) -> DarpInstance:
    """Parse the text of one Cordeau-format instance into a `DarpInstance`."""
    rows = [ln.split() for ln in text.splitlines() if ln.strip()]
    if not rows:
        raise ValueError(f"{name}: empty instance")
    header = rows[0]
    if len(header) < 5:
        raise ValueError(f"{name}: header must have at least 5 fields (K n T Q L), got {header!r}")
    num_vehicles = int(header[0])
    num_requests = int(header[1])
    max_route_duration = float(header[2])
    vehicle_capacity = int(header[3])
    max_ride_time = float(header[4])

    node_rows = rows[1:]
    nodes: list[DarpNode] = []
    for row in node_rows:
        if len(row) < 7:
            raise ValueError(f"{name}: node line must have 7 fields (id x y d q e l), got {row!r}")
        nodes.append(
            DarpNode(
                node_id=int(float(row[0])),
                x=float(row[1]),
                y=float(row[2]),
                service_duration=float(row[3]),
                load=int(float(row[4])),
                tw_start=float(row[5]),
                tw_end=float(row[6]),
            )
        )
    return DarpInstance.build(
        name=name,
        num_vehicles=num_vehicles,
        num_requests=num_requests,
        max_route_duration=max_route_duration,
        vehicle_capacity=vehicle_capacity,
        max_ride_time=max_ride_time,
        nodes=nodes,
    )


def load_instance_file(path: str | Path) -> DarpInstance:
    p = Path(path)
    return parse_instance(p.read_text(encoding="utf-8"), name=p.stem)


def _member_name(member: str) -> str:
    """basename of a zip member without a trailing .txt (the instance id)."""
    stem = member.rsplit("/", 1)[-1]
    return stem[:-4] if stem.endswith(".txt") else stem


def list_zip_instances(zip_path: str | Path) -> list[str]:
    """Instance ids inside a benchmark zip, sorted (e.g. ['a2-16', 'a2-20', ...])."""
    with zipfile.ZipFile(zip_path) as z:
        names = [_member_name(m) for m in z.namelist() if not m.endswith("/")]
    return sorted(names)


def load_zip_instance(zip_path: str | Path, name: str) -> DarpInstance:
    """Load one named instance (e.g. 'a2-16') from a benchmark zip."""
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            if member.endswith("/"):
                continue
            if _member_name(member) == name:
                return parse_instance(z.read(member).decode("utf-8"), name=name)
    raise KeyError(f"instance {name!r} not found in {zip_path}")


def iter_zip_instances(zip_path: str | Path) -> Iterator[tuple[str, DarpInstance]]:
    """Yield (name, instance) for every member of a benchmark zip, name-sorted."""
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.namelist() if not m.endswith("/")]
        for member in sorted(members, key=_member_name):
            name = _member_name(member)
            yield name, parse_instance(z.read(member).decode("utf-8"), name=name)


def find_benchmark_archive(dataset_id: str = "cordeau-darp") -> Path | None:
    """Return the promoted raw-archive path for an acquired benchmark dataset by
    reading its committed catalog record, or None if it was never acquired (so
    callers -- harness and tests -- can skip cleanly when the data is absent)."""
    acquired = _CATALOG / f"{dataset_id}.acquired.json"
    if not acquired.exists():
        return None
    entry = json.loads(acquired.read_text(encoding="utf-8"))
    raw_path = _REPO_ROOT / entry["raw_path"]
    return raw_path if raw_path.exists() else None
