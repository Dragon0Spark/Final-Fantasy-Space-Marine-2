"""Numeric invariants for a donor rig whose hierarchy is not index-sorted."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] /
                       "Source/Characters/Titus/Proportions"))
from DonorSkeletonPose import DonorSkeletonPose, SkeletonPose


class DonorSkeletonPoseTests(unittest.TestCase):
    def make_pose(self, scale=1.0):
        matrices = np.repeat(np.eye(4)[None, :, :], 3, axis=0)
        matrices[:, 0, 3] = [12, 10, 11]
        return DonorSkeletonPose(SkeletonPose((2, -1, 1), matrices), scale)

    def test_unsorted_parent_indices_recompose_exactly(self):
        pose = self.make_pose()
        np.testing.assert_allclose(pose.compose(), pose.skeleton.bind_globals)

    def test_joint_rotation_preserves_native_segment_lengths(self):
        pose = self.make_pose()
        rotations = np.repeat(np.eye(3)[None, :, :], 3, axis=0)
        rotations[2] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        output = pose.compose(rotations)
        np.testing.assert_allclose(output[0, :3, 3], [11, 1, 0], atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(output[0, :3, 3] - output[2, :3, 3]), 1.0)

    def test_uniform_scale_applies_to_geometry_and_joint_locations(self):
        pose = self.make_pose(2.0)
        offset = np.array([3, 4, 5])
        points = np.array([[12.5, 1.0, 0.0]])
        output = pose.skin(points, np.array([[0]]), np.array([[1.0]]), pose.compose(root_offset=offset))
        np.testing.assert_allclose(output, points * 2 + offset)

    def test_cycles_are_rejected(self):
        with self.assertRaises(ValueError):
            DonorSkeletonPose(SkeletonPose((1, 0), np.repeat(np.eye(4)[None, :, :], 2, axis=0)))

    def test_scale_and_shear_cannot_enter_as_bone_rotations(self):
        rotations = np.repeat(np.eye(3)[None, :, :], 3, axis=0)
        rotations[0, 0, 0] = 0.7
        with self.assertRaises(ValueError):
            self.make_pose().compose(rotations)

    def test_unweighted_vertices_are_rejected(self):
        pose = self.make_pose()
        with self.assertRaises(ValueError):
            pose.skin(np.array([[0.0, 0.0, 0.0]]), np.array([[0]]), np.array([[0.0]]), pose.compose())


if __name__ == "__main__":
    unittest.main()
