"""Piccola libreria vettoriale 3D (niente dipendenze esterne)."""
from __future__ import annotations

import math
from typing import Iterable, Sequence

Vec = tuple[float, float, float]

AXES: tuple[Vec, Vec, Vec] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
AXIS_NAMES = ("X", "Y", "Z")


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    n = norm(a)
    if n < 1e-15:
        return (0.0, 0.0, 1.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


def dist(a: Vec, b: Vec) -> float:
    return norm(sub(a, b))


def parallel(a: Vec, b: Vec, tol: float = 1e-4) -> bool:
    """True se i versori sono paralleli (stesso verso o opposto)."""
    return abs(abs(dot(a, b)) - 1.0) < tol


def same_dir(a: Vec, b: Vec, tol: float = 1e-4) -> bool:
    return dot(a, b) > 1.0 - tol


def perpendicular(a: Vec, b: Vec, tol: float = 1e-3) -> bool:
    return abs(dot(a, b)) < tol


def centroid(points: Sequence[Vec]) -> Vec:
    n = len(points)
    if n == 0:
        return (0.0, 0.0, 0.0)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n, sum(p[2] for p in points) / n)


def any_perpendicular(n: Vec) -> Vec:
    """Un versore perpendicolare a n (stabile numericamente)."""
    ax = min(range(3), key=lambda i: abs(n[i]))
    return unit(cross(n, AXES[ax]))


def plane_basis(n: Vec) -> tuple[Vec, Vec]:
    """Base (u, v) nel piano di normale n, allineata il più possibile agli assi macchina."""
    n = unit(n)
    # preferisci come u l'asse macchina "più giacente" nel piano
    best = max(AXES, key=lambda a: norm(sub(a, mul(n, dot(a, n)))))
    u = unit(sub(best, mul(n, dot(best, n))))
    v = cross(n, u)
    return u, v


def nearest_axis(v: Vec, exclude: Iterable[int] = ()) -> tuple[int, int]:
    """(indice asse 0..2, segno ±1) dell'asse macchina più vicino a v."""
    ex = set(exclude)
    best_i, best_s, best_d = 0, 1, -2.0
    for i in range(3):
        if i in ex:
            continue
        d = v[i]
        if abs(d) > best_d:
            best_i, best_s, best_d = i, (1 if d >= 0 else -1), abs(d)
    return best_i, best_s


def axis_label(i: int, s: int) -> str:
    return AXIS_NAMES[i] + ("PLUS" if s > 0 else "MINUS")


def solve3(m: Sequence[Sequence[float]], b: Sequence[float]) -> Vec | None:
    """Risolve m·x = b (3x3) con Cramer; None se singolare."""
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    if abs(d) < 1e-12:
        return None
    res = []
    for c in range(3):
        mc = [list(r) for r in m]
        for r in range(3):
            mc[r][c] = b[r]
        res.append(det(mc) / d)
    return (res[0], res[1], res[2])


def polygon_area_3d(points: Sequence[Vec], n: Vec) -> float:
    """Area (con segno rispetto a n) di un poligono planare - metodo di Newell."""
    if len(points) < 3:
        return 0.0
    acc = (0.0, 0.0, 0.0)
    for i in range(len(points)):
        acc = add(acc, cross(points[i], points[(i + 1) % len(points)]))
    return 0.5 * dot(acc, unit(n))


def point_in_polygon_2d(x: float, y: float, poly: Sequence[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = xi + (y - yi) * (xj - xi) / ((yj - yi) or 1e-30)
            if x < xc:
                inside = not inside
        j = i
    return inside


def dist_point_segment_2d(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def fmt(x: float, nd: int = 3) -> str:
    v = round(x, nd)
    if v == 0:
        v = 0.0  # evita "-0.000"
    return f"{v:.{nd}f}"


def fmt_vec(p: Vec, nd: int = 3) -> str:
    return ",".join(fmt(c, nd) for c in p)
