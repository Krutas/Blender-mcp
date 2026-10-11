"""Tests for the tuple vector helpers the figure math is built on.

The helpers exist so the rest of ``figure`` can run without ``mathutils``. The
degenerate cases are the point of most of these: a zero-length segment or a
zero vector is reachable from any bad pose edit, and the alternative -- letting
a division by zero produce NaN -- surfaces hours later as an invisible body in a
render rather than at the call site.
"""

from __future__ import annotations

import figure.vector as vector


def test_norm_of_zero_vector_returns_unit_x():
    assert vector.norm((0.0, 0.0, 0.0)) == (1.0, 0.0, 0.0)


def test_closest_point_on_segment_clamps_to_endpoints():
    a, b = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
    assert vector.closest_point_on_segment((-1.0, 2.0, 0.0), a, b) == (0.0, 0.0, 0.0)
    assert vector.closest_point_on_segment((2.0, 2.0, 0.0), a, b) == (1.0, 0.0, 0.0)


def test_closest_point_on_segment_projects_interior_point():
    a, b = (0.0, 0.0, 0.0), (2.0, 0.0, 0.0)
    assert vector.closest_point_on_segment((1.0, 5.0, 0.0), a, b) == (1.0, 0.0, 0.0)


def test_closest_point_on_degenerate_segment_returns_that_point():
    a = b = (0.3, 0.4, 0.5)
    assert vector.closest_point_on_segment((9.0, 9.0, 9.0), a, b) == a


def test_lerp_chain_interpolates_within_a_segment():
    pts = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 4.0, 0.0)]
    assert vector.lerp_chain(pts, 0.25) == (1.0, 0.0, 0.0)
    assert vector.lerp_chain(pts, 0.5) == (2.0, 0.0, 0.0)
    assert vector.lerp_chain(pts, 0.75) == (2.0, 2.0, 0.0)


def test_lerp_chain_clamps_outside_zero_to_one():
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    assert vector.lerp_chain(pts, -0.5) == (0.0, 0.0, 0.0)
    assert vector.lerp_chain(pts, 2.0) == (1.0, 0.0, 0.0)
