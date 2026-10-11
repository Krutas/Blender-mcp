"""Measurement helpers shared by the figure tests.

These live in one place so that "the area of a face" and "the radius of a ring"
mean exactly one thing across the suite. Four subtly different copies of an area
function would each eventually disagree with the others about a degenerate face,
which is precisely the case being guarded.
"""

from __future__ import annotations


def polygon_area_3d(face, verts) -> float:
    """Area of a planar-or-not polygon given as vertex indices.

    Uses the magnitude of the summed cross products rather than the shoelace
    formula so a slightly non-planar face -- which a lofted or boolean-derived
    mesh always has -- still reports a meaningful positive area instead of
    projecting to nothing.
    """
    n = len(face)
    total = (0.0, 0.0, 0.0)
    for i in range(n):
        a = verts[face[i]]
        b = verts[face[(i + 1) % n]]
        total = (
            total[0] + a[1] * b[2] - a[2] * b[1],
            total[1] + a[2] * b[0] - a[0] * b[2],
            total[2] + a[0] * b[1] - a[1] * b[0],
        )
    return 0.5 * (total[0] ** 2 + total[1] ** 2 + total[2] ** 2) ** 0.5


def mean_ring_radius(row) -> float:
    """Mean distance from the ring's centroid, taken about the row's own centre.

    Measuring about the centroid rather than the origin keeps this honest for a
    limb ring that sits well away from x=y=0.
    """
    n = len(row)
    cx = sum(p[0] for p in row) / n
    cy = sum(p[1] for p in row) / n
    cz = sum(p[2] for p in row) / n
    return sum(
        ((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2) ** 0.5 for p in row
    ) / n


def ring_rows(part) -> list[list[tuple]]:
    """Group a part's vertices into rings, ordered along its chain.

    A lofted part stores one arc-length parameter ``t`` per vertex, and every
    vertex in one ring shares a ``t``, so grouping by first-appearance order
    reconstructs the rings without the part having to store ring boundaries.
    """
    seen: list[float] = []
    rows: list[list[tuple]] = []
    for t, v in zip(part.ts, part.verts):
        for i, existing in enumerate(seen):
            if abs(existing - t) < 1e-9:
                rows[i].append(v)
                break
        else:
            seen.append(t)
            rows.append([v])
    return rows


def mesh_manifold_edge_count(mesh) -> int:
    """Number of edges not shared by exactly two faces.

    A closed manifold mesh scores zero. This is how the head is checked for
    being one continuous surface rather than several shells sitting near each
    other, which is the exact defect the previous primitive build had.
    """
    counts: dict[tuple[int, int], int] = {}
    for face in mesh["faces"]:
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            key = (a, b) if a < b else (b, a)
            counts[key] = counts.get(key, 0) + 1
    return sum(1 for c in counts.values() if c != 2)
