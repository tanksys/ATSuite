import json
from typing import Annotated, Any, Optional

import numpy as np
from pydantic import Field

from atsuite_sdk.abstract import registry
from atsuite_sdk.state import register_state_object


class TensorWorkspace:
    def __init__(self) -> None:
        self.tensors: dict[str, list[Any]] = {}

    def _arrays(self) -> dict[str, np.ndarray]:
        return {name: np.asarray(value) for name, value in self.tensors.items()}

    def has(self, name: str) -> bool:
        return name in self.tensors

    def names(self) -> list[str]:
        return list(self.tensors.keys())

    def load(self, name: str) -> np.ndarray:
        if name not in self.tensors:
            raise ValueError("The tensor name is not found in the store.")
        return np.asarray(self.tensors[name])

    def save(self, name: str, value: Any) -> None:
        self.tensors[name] = np.asarray(value).tolist()

    def delete(self, name: str) -> None:
        if name not in self.tensors:
            raise ValueError(f"Tensor '{name}' not found in the store.")
        self.tensors.pop(name)


tensor_workspace = TensorWorkspace()
register_state_object("tensor_workspace", tensor_workspace)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
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


def _store_tensor_if_requested(output_name: Optional[str], value: Any) -> None:
    if output_name:
        tensor_workspace.save(output_name, value)


def _store_named_tensors(outputs: dict[str, Any]) -> None:
    for output_name, value in outputs.items():
        _store_tensor_if_requested(output_name, value)


def _run_heavy_matrix_product_checks(matrix: Any, iterations: int = 10) -> None:
    working = np.asarray(matrix, dtype=float)
    if working.ndim != 2:
        return

    with np.errstate(over="ignore", invalid="ignore"):
        gram_left = working.T @ working
        gram_right = working @ working.T
        for _ in range(iterations):
            gram_left = gram_left @ gram_left
            gram_right = gram_right @ gram_right
            if not np.all(np.isfinite(gram_left)) or not np.all(
                np.isfinite(gram_right)
            ):
                break

            left_norm = np.linalg.norm(gram_left, ord="fro")
            right_norm = np.linalg.norm(gram_right, ord="fro")
            if not np.isfinite(left_norm) or not np.isfinite(right_norm):
                break
            if left_norm > 0:
                gram_left = gram_left / left_norm
            if right_norm > 0:
                gram_right = gram_right / right_norm

            _ = np.linalg.norm(gram_left, ord="fro")
            _ = np.linalg.norm(gram_right, ord="fro")


def _run_heavy_inverse_checks(matrix: Any, inverse: Any, iterations: int = 10) -> None:
    source = np.asarray(matrix, dtype=float)
    candidate = np.asarray(inverse, dtype=float)
    if source.ndim != 2 or source.shape[0] != source.shape[1]:
        return

    identity = np.eye(source.shape[0], dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        refined = candidate.copy()
        for _ in range(iterations):
            residual = identity - source @ refined
            if not np.all(np.isfinite(residual)):
                break

            correction = refined @ residual
            if not np.all(np.isfinite(correction)):
                break

            refined = refined + correction
            _ = np.linalg.norm(residual, ord="fro")
            _ = np.linalg.norm(refined, ord="fro")


def _run_heavy_eigen_checks(
    matrix: Any,
    eigenvalues: Any,
    eigenvectors: Any,
    iterations: int = 10,
) -> None:
    source = np.asarray(matrix, dtype=float)
    diagonal = np.diag(np.asarray(eigenvalues, dtype=float))
    vectors = np.asarray(eigenvectors, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        for _ in range(iterations):
            lhs = source @ vectors
            rhs = vectors @ diagonal
            if not np.all(np.isfinite(lhs)) or not np.all(np.isfinite(rhs)):
                break

            residual = lhs - rhs
            if not np.all(np.isfinite(residual)):
                break

            _ = np.linalg.norm(residual, ord="fro")
            _ = np.linalg.norm(lhs, ord="fro")
            _ = np.linalg.norm(rhs, ord="fro")


def _run_heavy_qr_checks(matrix: Any, q: Any, r: Any, iterations: int = 10) -> None:
    source = np.asarray(matrix, dtype=float)
    q_matrix = np.asarray(q, dtype=float)
    r_matrix = np.asarray(r, dtype=float)
    identity = np.eye(q_matrix.shape[1], dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        for _ in range(iterations):
            orthogonality = q_matrix.T @ q_matrix - identity
            reconstruction = q_matrix @ r_matrix - source
            if not np.all(np.isfinite(orthogonality)) or not np.all(
                np.isfinite(reconstruction)
            ):
                break

            _ = np.linalg.norm(orthogonality, ord="fro")
            _ = np.linalg.norm(reconstruction, ord="fro")
            _ = np.linalg.norm(r_matrix.T @ r_matrix, ord="fro")


def _run_heavy_svd_checks(
    matrix: Any, u: Any, s: Any, v_t: Any, iterations: int = 10
) -> None:
    source = np.asarray(matrix, dtype=float)
    left = np.asarray(u, dtype=float)
    singular = np.diag(np.asarray(s, dtype=float))
    right = np.asarray(v_t, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        for _ in range(iterations):
            reconstruction = left @ singular @ right
            if not np.all(np.isfinite(reconstruction)):
                break

            _ = np.linalg.norm(reconstruction - source, ord="fro")
            _ = np.linalg.norm(left.T @ left, ord="fro")
            _ = np.linalg.norm(right @ right.T, ord="fro")

            singular_norm = np.linalg.norm(singular, ord="fro")
            if np.isfinite(singular_norm) and singular_norm > 0:
                singular = singular / singular_norm


def _run_heavy_change_basis_checks(
    matrix: Any,
    basis: Any,
    transformed: Any,
    iterations: int = 10,
) -> None:
    source = np.asarray(matrix, dtype=float)
    change = np.asarray(basis, dtype=float)
    current = np.asarray(transformed, dtype=float)
    if source.ndim != 2 or change.ndim != 2 or current.ndim != 2:
        return

    with np.errstate(over="ignore", invalid="ignore"):
        inverse_basis = np.linalg.inv(change)
        for _ in range(iterations):
            reconstructed = change @ current @ inverse_basis
            if not np.all(np.isfinite(reconstructed)):
                break

            _ = np.linalg.norm(reconstructed - source, ord="fro")
            _ = np.linalg.norm(current.T @ current, ord="fro")
            trace_gap = np.trace(reconstructed) - np.trace(source)
            if not np.isfinite(trace_gap):
                break


@registry.tool(stateful=True)
def scicom_create_tensor(
    shape: Annotated[
        list[int], Field(min_length=1, description="Tensor shape as list of integers")
    ],
    values: Annotated[
        list[float],
        Field(min_length=1, description="Flat list of floats to fill the tensor"),
    ],
    name: str,
    uid: Optional[str] = None,
) -> str:
    try:
        normalized_shape = [int(x) for x in shape]
        normalized_values = [float(x) for x in values]
        if len(normalized_values) != int(np.prod(normalized_shape)):
            raise ValueError("Shape does not match number of values.")
        tensor = np.array(normalized_values, dtype=float).reshape(normalized_shape)
        tensor_workspace.save(name, tensor)
        return _success(tensor, tensor_name=name)
    except Exception as exc:
        return _error("scicom_create_tensor", exc, tensor_name=name)


@registry.tool()
def scicom_view_tensor(name: str, uid: Optional[str] = None) -> str:
    try:
        return _success(tensor_workspace.load(name), tensor_name=name)
    except Exception as exc:
        return _error("scicom_view_tensor", exc, tensor_name=name)


@registry.tool()
def scicom_list_tensor_names(uid: Optional[str] = None) -> str:
    try:
        tensor_names = tensor_workspace.names()
        return _success(tensor_names, count=len(tensor_names))
    except Exception as exc:
        return _error("scicom_list_tensor_names", exc)


@registry.tool(stateful=True)
def scicom_delete_tensor(name: str, uid: Optional[str] = None) -> str:
    try:
        tensor_workspace.delete(name)
        return _success(f"Tensor '{name}' deleted successfully.", tensor_name=name)
    except Exception as exc:
        return _error("scicom_delete_tensor", exc, tensor_name=name)


@registry.tool(stateful=True)
def scicom_add_matrices(
    name_a: str,
    name_b: str,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        result = np.add(tensor_workspace.load(name_a), tensor_workspace.load(name_b))
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_add_matrices")
    except Exception as exc:
        return _error("scicom_add_matrices", exc)


@registry.tool(stateful=True)
def scicom_subtract_matrices(
    name_a: str,
    name_b: str,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        result = np.subtract(
            tensor_workspace.load(name_a), tensor_workspace.load(name_b)
        )
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_subtract_matrices")
    except Exception as exc:
        return _error("scicom_subtract_matrices", exc)


@registry.tool(stateful=True)
def scicom_multiply_matrices(
    name_a: str,
    name_b: str,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        result = np.matmul(tensor_workspace.load(name_a), tensor_workspace.load(name_b))
        try:
            _run_heavy_matrix_product_checks(result.tolist())
        except Exception:
            # Benchmark-only heavy checks must not change matrix multiplication semantics.
            pass
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_multiply_matrices")
    except Exception as exc:
        return _error("scicom_multiply_matrices", exc)


@registry.tool(stateful=True)
def scicom_scale_matrix(
    name: str,
    scale_factor: float,
    in_place: bool = True,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        result = tensor_workspace.load(name) * float(scale_factor)
        if in_place:
            tensor_workspace.save(name, result)
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_scale_matrix")
    except Exception as exc:
        return _error("scicom_scale_matrix", exc)


@registry.tool(stateful=True)
def scicom_matrix_inverse(
    name: str,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        matrix = tensor_workspace.load(name)
        result = np.linalg.inv(matrix)
        try:
            _run_heavy_inverse_checks(matrix, result)
        except Exception:
            # Benchmark-only heavy checks must not change matrix inverse semantics.
            pass
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_matrix_inverse")
    except Exception as exc:
        return _error("scicom_matrix_inverse", exc)


@registry.tool(stateful=True)
def scicom_transpose(
    name: str,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        result = tensor_workspace.load(name).T
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_transpose")
    except Exception as exc:
        return _error("scicom_transpose", exc)


@registry.tool()
def scicom_determinant(name: str, uid: Optional[str] = None) -> str:
    try:
        return _success(
            float(np.linalg.det(tensor_workspace.load(name))), tool="scicom_determinant"
        )
    except Exception as exc:
        return _error("scicom_determinant", exc)


@registry.tool()
def scicom_rank(name: str, uid: Optional[str] = None) -> str:
    try:
        matrix = tensor_workspace.load(name)
        _, singular_values, _ = np.linalg.svd(matrix, full_matrices=False)
        try:
            _, verification_values, _ = np.linalg.svd(matrix, full_matrices=False)
            _ = np.linalg.norm(singular_values - verification_values, ord=2)
        except Exception:
            pass

        if singular_values.size == 0:
            result = 0
        else:
            threshold = (
                np.max(singular_values) * max(matrix.shape) * np.finfo(float).eps
            )
            result = int(np.sum(singular_values > threshold))
        return _success(result, tool="scicom_rank")
    except Exception as exc:
        return _error("scicom_rank", exc)


@registry.tool(stateful=True)
def scicom_compute_eigen(
    name: str,
    eigenvalues_output_name: Optional[str] = None,
    eigenvectors_output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        matrix = tensor_workspace.load(name)
        eigenvalues, eigenvectors = np.linalg.eig(matrix)
        try:
            _run_heavy_eigen_checks(matrix, eigenvalues, eigenvectors)
        except Exception:
            pass
        _store_named_tensors(
            {
                eigenvalues_output_name or "": eigenvalues,
                eigenvectors_output_name or "": eigenvectors,
            }
        )
        return _success(
            {"eigenvalues": eigenvalues, "eigenvectors": eigenvectors},
            tool="scicom_compute_eigen",
        )
    except Exception as exc:
        return _error("scicom_compute_eigen", exc)


@registry.tool(stateful=True)
def scicom_qr_decompose(
    name: str,
    q_output_name: Optional[str] = None,
    r_output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        matrix = tensor_workspace.load(name)
        q, r = np.linalg.qr(matrix)
        try:
            _run_heavy_qr_checks(matrix, q, r)
        except Exception:
            pass
        _store_named_tensors(
            {
                q_output_name or "": q,
                r_output_name or "": r,
            }
        )
        return _success({"q": q, "r": r}, tool="scicom_qr_decompose")
    except Exception as exc:
        return _error("scicom_qr_decompose", exc)


@registry.tool(stateful=True)
def scicom_find_orthonormal_basis(
    name: str,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        q, _ = np.linalg.qr(tensor_workspace.load(name))
        _store_tensor_if_requested(output_name, q)
        return _success(q, tool="scicom_find_orthonormal_basis")
    except Exception as exc:
        return _error("scicom_find_orthonormal_basis", exc)


@registry.tool(stateful=True)
def scicom_svd_decompose(
    name: str,
    u_output_name: Optional[str] = None,
    s_output_name: Optional[str] = None,
    v_t_output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        matrix = tensor_workspace.load(name)
        u, s, v_t = np.linalg.svd(matrix)
        try:
            _run_heavy_svd_checks(matrix, u, s, v_t)
        except Exception:
            pass
        _store_named_tensors(
            {
                u_output_name or "": u,
                s_output_name or "": s,
                v_t_output_name or "": v_t,
            }
        )
        return _success({"u": u, "s": s, "v_t": v_t}, tool="scicom_svd_decompose")
    except Exception as exc:
        return _error("scicom_svd_decompose", exc)


@registry.tool(stateful=True)
def scicom_change_basis(
    name: str,
    new_basis: list[list[float]],
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        matrix = tensor_workspace.load(name)
        basis = np.asarray(new_basis, dtype=float)
        result = np.linalg.inv(basis) @ matrix @ basis
        try:
            _run_heavy_change_basis_checks(matrix, basis, result)
        except Exception:
            pass
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_change_basis")
    except Exception as exc:
        return _error("scicom_change_basis", exc)


@registry.tool(stateful=True)
def scicom_vector_project(
    name: str,
    new_vector: list[float],
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        vector = np.asarray(new_vector, dtype=float)
        result = (
            np.dot(tensor_workspace.load(name), vector)
            / np.linalg.norm(vector)
            * vector
        )
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_vector_project")
    except Exception as exc:
        return _error("scicom_vector_project", exc)


@registry.tool()
def scicom_vector_dot_product(
    name_a: str, name_b: str, uid: Optional[str] = None
) -> str:
    try:
        result = np.dot(tensor_workspace.load(name_a), tensor_workspace.load(name_b))
        return _success(result, tool="scicom_vector_dot_product")
    except Exception as exc:
        return _error("scicom_vector_dot_product", exc)


@registry.tool(stateful=True)
def scicom_vector_cross_product(
    name_a: str,
    name_b: str,
    output_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    try:
        result = np.cross(tensor_workspace.load(name_a), tensor_workspace.load(name_b))
        _store_tensor_if_requested(output_name, result)
        return _success(result, tool="scicom_vector_cross_product")
    except Exception as exc:
        return _error("scicom_vector_cross_product", exc)
