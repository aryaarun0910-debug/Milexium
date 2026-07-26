"""Every real dataset in this repository declares its rights (ADR-0053).

The repo has two data trees with different origins: `data/curated/` (the original
product, hand-acquired before the estate discipline existed) and `data/` (the
governed estate, which refuses a byte without declared rights). The gap worth
closing was never "two folders" -- it was that one tree held real TLC/MTA/Chicago
data with NO rights record while the other refused to.

These tests hold that closed. They deliberately do NOT assert anything about
file LOCATION: `data/curated/` paths are pinned by sha256 in the evidence registry
and read directly by the forecast, leakage and teardown suites, so moving them
would break recorded provenance to buy tidiness.
"""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from themis.estate.manifest import load_manifest

_REPO = Path(__file__).resolve().parents[3]
_CATALOG = _REPO / "data" / "acquired" / "catalog"
_REALDATA_MANIFESTS = sorted(_CATALOG.glob("realdata-*.manifest.json"))

_PLACEHOLDERS = ("tbd", "unknown", "todo", "change-me", "n/a", "?")


def test_the_realdata_governance_manifests_exist() -> None:
    """If this fails, talos/tools/build_realdata_manifests.py has not been run."""
    assert _REALDATA_MANIFESTS, "no realdata-* governance manifests found"


@pytest.mark.parametrize("path", _REALDATA_MANIFESTS, ids=lambda p: p.stem)
def test_each_manifest_loads_and_declares_real_rights(path: Path) -> None:
    """`load_manifest` enforces the schema; this adds the check it cannot make --
    that the rights field says something, rather than parking a placeholder."""
    manifest = load_manifest(path)

    rights = manifest.license_and_commercial_rights.strip()
    assert len(rights) > 40, f"{path.stem}: rights text is too thin to be a real declaration"
    assert not any(p in rights.lower() for p in _PLACEHOLDERS), (
        f"{path.stem}: rights field contains a placeholder"
    )
    # commercial position must be addressed explicitly -- it is the question a
    # reviewer actually asks, and silence reads as "nobody checked"
    assert "commercial" in rights.lower()


@lru_cache(maxsize=1)
def _tracked_paths() -> frozenset[str]:
    """Everything git tracks, as forward-slash repo-relative strings."""
    out = subprocess.run(
        ["git", "-C", str(_REPO), "ls-files"], capture_output=True, text=True, check=False
    ).stdout
    return frozenset(out.splitlines())


@lru_cache(maxsize=1)
def _tracked_dirs() -> frozenset[str]:
    """Every directory git tracks something inside, as a repo-relative prefix."""
    dirs: set[str] = set()
    for t in _tracked_paths():
        parts = t.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return frozenset(dirs)


def _recorded_paths(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        line.split("already_present_at:", 1)[1].strip()
        for line in payload.get("derived_artifacts", [])
        if isinstance(line, str) and line.startswith("already_present_at:")
    ]


@lru_cache(maxsize=1)
def _all_recorded_paths() -> tuple[str, ...]:
    return tuple(
        sorted({rel for m in _REALDATA_MANIFESTS for rel in _recorded_paths(m)})
    )


@lru_cache(maxsize=1)
def _ignore_rules() -> dict[str, tuple[str, str]]:
    """{recorded path: (file the rule lives in, the rule)} for ignored paths.

    `check-ignore -v` names the SOURCE of the rule, which matters: a path hidden
    only by `.git/info/exclude` or a user's global ignore file is invisible to CI
    and cannot excuse anything.
    """
    paths = _all_recorded_paths()
    if not paths:
        return {}
    # paths go in as argv, NOT --stdin: on Windows a text-mode pipe rewrites "\n"
    # to "\r\n", git then sees a trailing "\r" in every path and C-quotes it back,
    # and every lookup silently misses. That miss is exactly how this check would
    # go vacuous a second time, so the seam is kept out of the pipe.
    out = subprocess.run(
        ["git", "-C", str(_REPO), "check-ignore", "-v", "--", *paths],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    rules: dict[str, tuple[str, str]] = {}
    for line in out.splitlines():
        source, _, name = line.partition("\t")
        src_file, _, pattern = source.rpartition(":")
        src_file = src_file.rsplit(":", 1)[0]  # strip the line number
        rules[name.strip().strip('"')] = (src_file.replace("\\", "/"), pattern)
    return rules


def _is_tracked(rel: str) -> bool:
    norm = rel.rstrip("/")
    return norm in _tracked_paths() or norm in _tracked_dirs()


def _nearest_tracked_ancestor(rel: str) -> str | None:
    """The closest parent directory git actually tracks content inside.

    That directory DOES exist on a clean checkout, so it is the one part of an
    otherwise-ignored path that CI can still hold to account.
    """
    parts = rel.rstrip("/").split("/")
    for i in range(len(parts) - 1, 0, -1):
        anc = "/".join(parts[:i])
        if anc in _tracked_dirs():
            return anc
    return None


def _zone_is_materialised(rel: str) -> list[str]:
    """Other recorded, gitignored paths sharing this path's zone that ARE here.

    If a sibling dataset's ignored bytes are present, this checkout is one where
    the ignored estate has been fetched -- so "absent by design" stops being an
    available excuse for this path.
    """
    zone = _nearest_tracked_ancestor(rel)
    if zone is None:
        return []
    return [
        peer
        for peer in _all_recorded_paths()
        if peer != rel
        and not _is_tracked(peer)
        and _nearest_tracked_ancestor(peer) == zone
        and (_REPO / peer).exists()
    ]


def test_the_ignore_rule_lookup_actually_resolves_paths() -> None:
    """Guards the plumbing the existence test leans on, not the policy.

    If `_ignore_rules()` ever comes back empty or short, every ignored path falls
    into the "no rule found" branch and the test still passes wherever the bytes
    happen to be present -- green for the wrong reason. That is not theoretical:
    the first draft of this fix piped paths through `--stdin` in text mode, which
    on Windows appended "\\r" to each one and returned zero usable rules.

    So the batched lookup is cross-checked against a second, independent
    invocation: `check-ignore -q`, one path at a time, exit status only.
    """
    resolved = _ignore_rules()
    ignored_here = [
        rel
        for rel in _all_recorded_paths()
        if subprocess.run(
            ["git", "-C", str(_REPO), "check-ignore", "-q", "--", rel], check=False
        ).returncode
        == 0
    ]
    assert ignored_here, (
        "no recorded path is gitignored -- then the 'absent by design' branch of "
        "the existence test is dead code and should be deleted, not trusted"
    )
    missing = [rel for rel in ignored_here if rel not in resolved]
    assert not missing, (
        f"the batched ignore-rule lookup lost {len(missing)} of {len(ignored_here)} "
        f"ignored paths: {missing}. The existence test would treat these as "
        "unexplained rather than absent-by-design, or pass them on presence alone."
    )


@pytest.mark.parametrize("path", _REALDATA_MANIFESTS, ids=lambda p: p.stem)
def test_each_manifest_points_at_paths_that_actually_exist(path: Path) -> None:
    """A governance record pointing at nothing is worse than none, because it
    looks like coverage.

    PORTABILITY: the estate deliberately gitignores raw zones and the large
    panels (`data/acquired/README.md`), so on a clean CI checkout those paths genuinely do
    not exist -- asserting otherwise fails for a reason that has nothing to do
    with governance. This is the same class of mistake as the CRLF/LF panel-hash
    drift CI caught earlier: locally valid, not portable.

    The earlier repair asserted existence only for git-TRACKED paths and let the
    rest through. That left the hole an audit walked straight into: three of
    these five manifests name no tracked path at all, so pointing one at a
    nonexistent ignored directory changed nothing and the record still certified.
    "Not asserted here" had quietly become "asserted nowhere".

    What is actually checkable, per recorded path, in BOTH environments:

    * TRACKED           -> must exist. A committed file deleted or renamed out
                           from under the record still fails, everywhere.
    * NEITHER tracked
      NOR ignored       -> must exist. Git would be tracking these bytes if they
                           were there; nothing explains the absence.
    * IGNORED, present  -> verified here: the bytes are on this disk.
    * IGNORED, absent   -> the absence must be EXPLAINED and ANCHORED:
                           (a) a committed `.gitignore` rule covers it -- a local
                               exclude cannot launder a fictional path; and
                           (b) the nearest directory git tracks content inside
                               exists, so the record lands somewhere real; and
                           (c) no sibling dataset's ignored bytes are present in
                               the same zone. If they are, this checkout HAS the
                               ignored estate, and an absent path here is a
                               record of bytes nobody holds -- not portability.

    Only (c)'s "clean checkout" branch leaves a path unverified, and it says so.
    """
    recorded = _recorded_paths(path)
    assert recorded, f"{path.stem}: records no path"

    verified: list[str] = []
    unverifiable: list[str] = []

    for rel in recorded:
        present = (_REPO / rel).exists()

        if _is_tracked(rel):
            assert present, (
                f"{path.stem}: CASE tracked-but-missing -- {rel} is git-tracked, so it "
                "must be in every checkout, and it is not. The record names a committed "
                "file that has been deleted or renamed."
            )
            verified.append(rel)
            continue

        rule = _ignore_rules().get(rel)
        if rule is None:
            assert present, (
                f"{path.stem}: CASE unexplained-absence -- {rel} is neither tracked by "
                "git nor covered by any ignore rule, and it does not exist. Git would "
                "be tracking these bytes if they were ever here; the record names "
                "nothing."
            )
            verified.append(rel)
            continue

        source_file, pattern = rule
        assert source_file in _tracked_paths(), (
            f"{path.stem}: CASE uncommitted-excuse -- {rel} is absent-by-design only "
            f"because of `{pattern}` in {source_file}, which git does not track. A "
            "local exclude is invisible to CI and cannot justify a governance record."
        )

        if present:
            verified.append(rel)
            continue

        zone = _nearest_tracked_ancestor(rel)
        assert zone is not None and (_REPO / zone).exists(), (
            f"{path.stem}: CASE unanchored -- {rel} is absent and so is the nearest "
            f"directory git tracks content inside ({zone!r}). The record does not land "
            "anywhere real, in any checkout."
        )

        peers = _zone_is_materialised(rel)
        assert not peers, (
            f"{path.stem}: CASE fictional-in-a-materialised-zone -- {rel} is absent, but "
            f"this checkout HAS the ignored estate under {zone}/ (present: "
            f"{', '.join(sorted(peers))}). 'Gitignored, so absent by design' is not "
            "available as an excuse here: the bytes this record names are the ones "
            "nobody has."
        )
        unverifiable.append(rel)

    # Not an assertion -- there is nothing left to assert. On a checkout where the
    # ignored estate was never fetched, an ignored leaf is unverifiable and saying
    # otherwise would be the same lie in the other direction. It is reported so the
    # gap is visible in `-rP` output rather than implied by a green tick.
    if not verified:
        print(
            f"\n{path.stem}: NO PATH VERIFIED IN THIS CHECKOUT. Every recorded path is "
            f"gitignored and absent ({', '.join(unverifiable)}); each is anchored to an "
            "existing tracked directory and explained by a committed ignore rule, which "
            "is all a checkout without the bytes can establish. Run on a checkout with "
            "the estate fetched to verify presence."
        )


@pytest.mark.parametrize("path", _REALDATA_MANIFESTS, ids=lambda p: p.stem)
def test_no_acquired_record_is_forged_for_a_hand_acquired_dataset(path: Path) -> None:
    """These datasets did NOT go through themis.estate.acquire.

    An `.acquired.json` beside them would assert a free-space guard, a quarantine
    step and a checksum-verified promotion that never happened -- forging exactly
    the provenance the estate exists to make trustworthy. The manifest describes
    rights; it must not imply an acquisition.
    """
    acquired = _CATALOG / f"{path.stem.replace('.manifest', '')}.acquired.json"
    assert not acquired.exists(), (
        f"{acquired.name} exists -- that would claim an acquisition through the "
        "governed pipeline which never took place"
    )
