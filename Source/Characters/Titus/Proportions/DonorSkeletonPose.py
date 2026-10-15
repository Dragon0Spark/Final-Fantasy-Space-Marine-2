"""Preserve Titus's bind proportions when composing or skinning his pose."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SkeletonPose:
    parents: tuple[int, ...]
    bind_globals: np.ndarray


class DonorSkeletonPose:
    def __init__(self, skeleton: SkeletonPose, unit_scale: float = 1.0) -> None:
        self.skeleton = skeleton
        self.unit_scale = unit_scale
        count = len(skeleton.parents)
        if unit_scale <= 0 or not np.isfinite(unit_scale):
            raise ValueError("Invalid uniform scale")
        if skeleton.bind_globals.shape != (count, 4, 4) or count == 0:
            raise ValueError("Invalid bind matrices")
        if not np.isfinite(skeleton.bind_globals).all():
            raise ValueError("Bind matrices must be finite")
        self.local_bind = np.empty_like(skeleton.bind_globals, dtype=np.float64)
        for index, parent in enumerate(skeleton.parents):
            if parent < -1 or parent >= count or parent == index:
                raise ValueError("Invalid parent index")
            if parent == -1:
                self.local_bind[index] = skeleton.bind_globals[index]
            else:
                self.local_bind[index] = np.linalg.solve(
                    skeleton.bind_globals[parent], skeleton.bind_globals[index])
        self.order = self.hierarchy_order()
        self.inverse_bind = np.linalg.inv(skeleton.bind_globals)

    def hierarchy_order(self) -> tuple[int, ...]:
        # Native donor indices are not topologically sorted.
        state = [0] * len(self.skeleton.parents)
        order = []

        def visit(index):
            if state[index] == 1:
                raise ValueError("Cyclic bone hierarchy")
            if state[index] == 2:
                return
            state[index] = 1
            parent = self.skeleton.parents[index]
            if parent >= 0:
                visit(parent)
            state[index] = 2
            order.append(index)

        for index in range(len(state)):
            visit(index)
        return tuple(order)

    def compose(self, local_rotations: np.ndarray | None = None,
                root_offset: np.ndarray | None = None) -> np.ndarray:
        # Native Titus translations define proportions. Never substitute Cloud joints.
        local = self.local_bind.copy()
        if local_rotations is not None:
            if local_rotations.shape != local[:, :3, :3].shape:
                raise ValueError("Rotation count does not match the donor skeleton")
            if not np.isfinite(local_rotations).all():
                raise ValueError("Rotations must be finite")
            gram = np.swapaxes(local_rotations, 1, 2) @ local_rotations
            if not np.allclose(gram, np.eye(3), atol=1e-5) or not np.allclose(
                    np.linalg.det(local_rotations), 1.0, atol=1e-5):
                raise ValueError("Bone rotations must not introduce scale or shear")
            local[:, :3, :3] = local_rotations
        result = np.empty_like(local)
        offset = np.zeros(3) if root_offset is None else np.asarray(root_offset, dtype=np.float64)
        if offset.shape != (3,) or not np.isfinite(offset).all():
            raise ValueError("Invalid root offset")
        for index in self.order:
            parent = self.skeleton.parents[index]
            if parent == -1:
                result[index] = local[index]
                result[index, :3, :] *= self.unit_scale
                result[index, :3, 3] += offset
            else:
                result[index] = result[parent] @ local[index]
        return result

    def skin(self, positions: np.ndarray, joints: np.ndarray, weights: np.ndarray,
             current_globals: np.ndarray) -> np.ndarray:
        if current_globals.shape != self.skeleton.bind_globals.shape:
            raise ValueError("Pose count does not match the donor skeleton")
        if joints.shape != weights.shape or joints.shape[0] != len(positions):
            raise ValueError("Invalid skinning influences")
        if positions.shape != (len(positions), 3) or not np.isfinite(positions).all():
            raise ValueError("Invalid vertex positions")
        if not np.issubdtype(joints.dtype, np.integer):
            raise ValueError("Joint indices must be integers")
        if (joints < 0).any() or (joints >= len(self.skeleton.parents)).any():
            raise ValueError("Joint index outside donor skeleton")
        if (weights < 0).any() or not np.isfinite(weights).all():
            raise ValueError("Invalid skinning weights")
        totals = weights.sum(axis=1)
        if (totals <= 0).any():
            raise ValueError("Unweighted vertices cannot be silently attached to root")
        transforms = current_globals @ self.inverse_bind
        homogeneous = np.column_stack((positions, np.ones(len(positions))))
        posed = np.einsum("vkij,vj->vki", transforms[joints], homogeneous)
        result = np.einsum("vki,vk->vi", posed, weights / totals[:, None])
        return result[:, :3]
