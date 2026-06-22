import base64
import json
from io import BytesIO
from typing import Optional

import numpy as np
import sympy as sp
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure
from sympy import parse_expr, symbols
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    standard_transformations,
)

from atsuite_sdk.abstract import registry


_X, _Y, _Z = symbols("x y z")
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
_LOCAL_NS = {"x": _X, "y": _Y, "z": _Z, "sin": sp.sin, "cos": sp.cos}


class _SimpleImage:
    def __init__(self, data: bytes, format: str) -> None:
        self.data = data
        self.format = format


def _effective_plot_grid(grid: int) -> int:
    return max(int(grid), 200) * 3


def _effective_vector_field_density(n: int) -> int:
    return max(int(n), 10) * 2


def _plot_vector_field(
    f_str: str,
    bounds: tuple[int, int, int, int, int, int] = (-1, 1, -1, 1, -1, 1),
    n: int = 10,
) -> _SimpleImage:
    raw = f_str.strip().lstrip("[").rstrip("]")
    u_s, v_s, w_s = [item.strip() for item in raw.split(",")]
    u_expr = parse_expr(u_s, local_dict=_LOCAL_NS, transformations=_TRANSFORMS)
    v_expr = parse_expr(v_s, local_dict=_LOCAL_NS, transformations=_TRANSFORMS)
    w_expr = parse_expr(w_s, local_dict=_LOCAL_NS, transformations=_TRANSFORMS)
    u_fn = sp.lambdify((_X, _Y, _Z), u_expr, "numpy")
    v_fn = sp.lambdify((_X, _Y, _Z), v_expr, "numpy")
    w_fn = sp.lambdify((_X, _Y, _Z), w_expr, "numpy")

    effective_n = _effective_vector_field_density(n)
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    X, Y, Z = np.meshgrid(
        np.linspace(xmin, xmax, effective_n),
        np.linspace(ymin, ymax, effective_n),
        np.linspace(zmin, zmax, effective_n),
        indexing="ij",
    )
    U = np.asarray(u_fn(X, Y, Z), dtype=float)
    V = np.asarray(v_fn(X, Y, Z), dtype=float)
    W = np.asarray(w_fn(X, Y, Z), dtype=float)
    magnitude = np.sqrt(U * U + V * V + W * W)
    nonzero = magnitude > 0
    scaled_u = np.where(nonzero, U / magnitude, 0.0)
    scaled_v = np.where(nonzero, V / magnitude, 0.0)
    scaled_w = np.where(nonzero, W / magnitude, 0.0)

    fig = Figure(figsize=(8, 6))
    canvas = FigureCanvas(fig)
    ax = fig.add_subplot(projection="3d")
    ax.quiver(X, Y, Z, scaled_u, scaled_v, scaled_w, length=0.1, normalize=True, color="blue")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.set_title(f"3D Vector Field: {f_str}")

    buffer = BytesIO()
    canvas.print_png(buffer)
    return _SimpleImage(data=buffer.getvalue(), format="png")


def _plot_function(
    expr_str: str,
    xlim: tuple[int, int] = (-5, 5),
    ylim: tuple[int, int] = (-5, 5),
    grid: int = 200,
) -> _SimpleImage:
    expr = parse_expr(expr_str, transformations=_TRANSFORMS, local_dict=_LOCAL_NS)
    vars_used = expr.free_symbols
    effective_grid = _effective_plot_grid(grid)

    if vars_used == {sp.symbols("x")} or vars_used == set():
        f_num = sp.lambdify(_X, expr, modules=["numpy"])
        xs = np.linspace(xlim[0], xlim[1], effective_grid)
        ys = np.asarray(f_num(xs), dtype=float)
        if ys.ndim > 0 and ys.size > 1:
            _ = np.gradient(ys, xs)
        fig = Figure()
        ax = fig.add_subplot()
        ax.plot(xs, ys)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("x")
        ax.set_ylabel(expr_str)
        ax.set_title(f"f(x) = {expr_str}")
    elif vars_used >= {sp.symbols("x"), sp.symbols("y")}:
        f_num = sp.lambdify((_X, _Y), expr, modules=["numpy"])
        xs = np.linspace(xlim[0], xlim[1], effective_grid)
        ys = np.linspace(ylim[0], ylim[1], effective_grid) if ylim is not None else xs
        X, Y = np.meshgrid(xs, ys)
        Z = np.asarray(f_num(X, Y), dtype=float)
        grad_x, grad_y = np.gradient(Z)
        _ = np.sqrt(grad_x * grad_x + grad_y * grad_y)
        fig = Figure()
        ax = fig.add_subplot(projection="3d")
        surface = ax.plot_surface(X, Y, Z, cmap="viridis")
        fig.colorbar(surface, ax=ax, shrink=0.6)
        ax.set_title(f"f(x, y) = {expr_str}")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
        ax.set_zlabel(expr_str)
    else:
        raise ValueError("Plot only supports functions in x (2D) or x and y (3D).")

    buffer = BytesIO()
    canvas = FigureCanvas(fig)
    canvas.print_png(buffer)
    return _SimpleImage(data=buffer.getvalue(), format="png")


@registry.tool()
def scicom_plot_vector_field(
    f_str: str,
    bounds: list[int] = (-1, 1, -1, 1, -1, 1),
    n: int = 10,
    uid: Optional[str] = None,
) -> str:
    try:
        image = _plot_vector_field(f_str, tuple(bounds), n)
        encoded = base64.b64encode(image.data).decode("utf-8")
        return json.dumps(
            {
                "isError": False,
                "result": {"image_base64": encoded, "format": image.format},
                "tool": "scicom_plot_vector_field",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"isError": True, "error": str(exc), "tool": "scicom_plot_vector_field"},
            ensure_ascii=False,
        )


@registry.tool()
def scicom_plot_function(
    expr_str: str,
    xlim: list[int] = (-5, 5),
    ylim: list[int] = (-5, 5),
    grid: int = 200,
    uid: Optional[str] = None,
) -> str:
    try:
        image = _plot_function(expr_str, tuple(xlim), tuple(ylim), grid)
        encoded = base64.b64encode(image.data).decode("utf-8")
        return json.dumps(
            {
                "isError": False,
                "result": {"image_base64": encoded, "format": image.format},
                "tool": "scicom_plot_function",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"isError": True, "error": str(exc), "tool": "scicom_plot_function"},
            ensure_ascii=False,
        )
