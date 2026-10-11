"""Minimal 3-vector helpers, in plain tuples.

The figure package must run under Blender *and* under pytest with no Blender
present, so this module deliberately avoids ``mathutils``. Vectors are 3-tuples
of float throughout.

Every function here is written to be total: degenerate input returns a
well-defined answer rather than raising or returning NaN. A zero-length segment
or a zero vector is reachable from any bad pose edit, and NaN propagating into
the Skin modifier surfaces hours later as an invisible body in a render, with no
trace pointing back to the arithmetic that produced it.
"""

from __future__ import annotations

Vec3 = tuple[float, float, float]


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(a: Vec3) -> float:
    return dot(a, a) ** 0.5


def dist(a: Vec3, b: Vec3) -> float:
    return length(sub(a, b))


def norm(a: Vec3) -> Vec3:
    """Unit vector. Returns ``(1, 0, 0)`` for a zero vector rather than raising.

    Callers cannot distinguish "the difference was genuinely zero" from "the
    input was garbage", so this must not blow up on them: returning a stable
    unit axis keeps the failure downstream and visible instead of here.
    """
    n = length(a)
    if n == 0.0:
        return (1.0, 0.0, 0.0)
    return scale(a, 1.0 / n)


def lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def closest_point_on_segment(p: Vec3, a: Vec3, b: Vec3) -> Vec3:
    """Point on segment ``ab`` nearest to ``p``, clamped to the endpoints.

    Returns ``a`` unchanged for a degenerate segment rather than dividing by a
    zero-length direction vector.
    """
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom == 0.0:
        return a
    t = dot(sub(p, a), ab) / denom
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    return add(a, scale(ab, t))


def lerp_chain(points: list[Vec3], t: float, params: list[float] | None = None) -> Vec3:
    """Point at normalized position ``t`` along a polyline.

    Without ``params`` the parameter is normalized by *segment index*: ``t=0``
    is the first point, ``t=1`` the last, and each segment owns an equal slice.
    That is what the skin weighting wants -- the knee lands at ``t=0.5`` of a
    thigh/shin chain whether or not the two bones happen to be the same length,
    because the blend should follow the joint, not the geometry.

    With ``params`` supplied (non-uniform normalized values, such as the head's
    station table), the polyline is interpolated against those instead, which is
    what lets a caller express "halfway up the skull" against unevenly spaced
    control stations.

    ``t`` is clamped to ``[0, 1]`` before use so a vertex that overshoots the
    end of a chain lands on the end rather than extrapolating off it.
    """
    if len(points) == 1:
        return points[0]
    if params is None:
        params = [i / (len(points) - 1) for i in range(len(points))]
    else:
        lo, hi = params[0], params[-1]
        if hi == lo:
            return points[0]
        params = [(v - lo) / (hi - lo) for v in params]

    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    for i in range(len(points) - 1):
        a, b = params[i], params[i + 1]
        if t <= b or i == len(points) - 2:
            span = b - a
            f = 0.0 if span == 0.0 else (t - a) / span
            return lerp(points[i], points[i + 1], f)
    return points[-1]
