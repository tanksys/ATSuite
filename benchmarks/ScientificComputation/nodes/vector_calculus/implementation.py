import json
from typing import Any, Optional

import sympy as sp
from sympy import parse_expr
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    standard_transformations,
)
from sympy.vector import CoordSys3D, Del, directional_derivative

from atsuite_sdk.abstract import registry


C = CoordSys3D("C")
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
_SCALAR_LOCAL_NS = {"x": C.x, "y": C.y, "z": C.z, "sin": sp.sin, "cos": sp.cos}


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _success(result: Any, **extra: Any) -> str:
    payload = {"isError": False, "result": _to_jsonable(result)}
    payload.update({key: _to_jsonable(value) for key, value in extra.items()})
    return json.dumps(payload, ensure_ascii=False)


def _error(tool: str, exc: Exception, **extra: Any) -> str:
    payload = {"isError": True, "error": str(exc), "tool": tool}
    payload.update({key: _to_jsonable(value) for key, value in extra.items()})
    return json.dumps(payload, ensure_ascii=False)


def _parse_scalar_expr(f_str: str):
    return parse_expr(f_str, local_dict=_SCALAR_LOCAL_NS, transformations=_TRANSFORMS)


def _parse_vector_field(f_str: str):
    raw = f_str.strip().strip("[]")
    comps_str = [component.strip() for component in raw.split(",")]
    if len(comps_str) != 3:
        raise ValueError("Vector field must contain exactly three components.")
    comp_syms = [parse_expr(expr, local_dict=_SCALAR_LOCAL_NS, transformations=_TRANSFORMS) for expr in comps_str]
    return comp_syms[0] * C.i + comp_syms[1] * C.j + comp_syms[2] * C.k


@registry.tool()
def scicom_gradient(f_str: str, uid: Optional[str] = None) -> str:
    try:
        scalar = _parse_scalar_expr(f_str)
        variables = [var for var in (C.x, C.y, C.z) if var in scalar.free_symbols]
        if not variables:
            return _success("Matrix([[0]])", tool="scicom_gradient")
        gradient = sp.Matrix([scalar]).jacobian(variables)
        return _success(str(gradient), tool="scicom_gradient")
    except Exception as exc:
        return _error("scicom_gradient", exc)


@registry.tool()
def scicom_curl(f_str: str, point: Optional[list[float]] = None, uid: Optional[str] = None) -> str:
    try:
        field = _parse_vector_field(f_str)
        curl_sym = Del().cross(field).doit()
        result = {"curl_sym": str(curl_sym)}
        if point is not None:
            variables = [C.x, C.y, C.z]
            comps = [curl_sym.dot(direction) for direction in (C.i, C.j, C.k)]
            lamb = sp.lambdify(variables, sp.Matrix(comps), "numpy")
            result["curl_val"] = [float(value) for value in lamb(*point)]
        return _success(result, tool="scicom_curl")
    except Exception as exc:
        return _error("scicom_curl", exc)


@registry.tool()
def scicom_divergence(f_str: str, point: Optional[list[float]] = None, uid: Optional[str] = None) -> str:
    try:
        field = _parse_vector_field(f_str)
        divergence_sym = Del().dot(field, doit=True)
        result = {"divergence_sym": str(divergence_sym)}
        if point is not None:
            lamb = sp.lambdify([C.x, C.y, C.z], divergence_sym, "numpy")
            result["divergence_val"] = float(lamb(*point))
        return _success(result, tool="scicom_divergence")
    except Exception as exc:
        return _error("scicom_divergence", exc)


@registry.tool()
def scicom_laplacian(f_str: str, is_vector: bool = False, uid: Optional[str] = None) -> str:
    try:
        if not is_vector:
            scalar = _parse_scalar_expr(f_str)
            return _success(str(Del().dot(Del()(scalar)).doit()), tool="scicom_laplacian")

        field = _parse_vector_field(f_str)
        components = list(field.to_matrix(C))
        result = [Del().dot(Del()(component)).doit() for component in components]
        return _success(str(result), tool="scicom_laplacian")
    except Exception as exc:
        return _error("scicom_laplacian", exc)


@registry.tool()
def scicom_directional_deriv(
    f_str: str,
    u: list[float],
    unit: bool = True,
    uid: Optional[str] = None,
) -> str:
    try:
        scalar = _parse_scalar_expr(f_str)
        vector = u[0] * C.i + u[1] * C.j + u[2] * C.k
        if unit:
            vector = vector.normalize()
        result = directional_derivative(scalar, vector).doit()
        return _success(str(result), tool="scicom_directional_deriv")
    except Exception as exc:
        return _error("scicom_directional_deriv", exc)
