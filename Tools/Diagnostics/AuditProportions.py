"""Measure old joint fitting against native Titus proportions without asset copies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sm2", type=Path, required=True)
    parser.add_argument("--ff7", type=Path, required=True)
    parser.add_argument("--asset-parser", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("Reports/proportions-audit.json"))
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(project / "Reference/PreviousProject/Tools/Pipeline"),
                    str(project / "Tools/Content"), str(args.asset_parser),
                    str(project / "Source/Characters/Titus/Proportions")]
    import sm2tpl
    import titus_mesh
    from ff7rpaks import FF7RPaks
    from MemoryUnrealAsset import MemoryUnrealAsset
    from DonorSkeletonPose import DonorSkeletonPose, SkeletonPose

    # Only use historical readers and the old fit function for comparison.
    template_bytes, geometry_bytes = titus_mesh.read_titus_files(args.sm2)
    template = sm2tpl.read_template(template_bytes)
    host = FF7RPaks(args.ff7)
    asset = "End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard/Model/PC0000_00_Skeleton"
    parts = {asset + suffix: host.read(asset + suffix) for suffix in (".uasset", ".uexp")}
    skeleton = MemoryUnrealAsset(parts).read(asset).uexp.skeleton
    bone_rows = json.loads((project / "Reference/PreviousProject/Sheets/bone_map.json").read_text())["rows"]
    old_fit = titus_mesh.fit_skeleton(template, skeleton.bones, bone_rows)
    names = [node.name for node in template.objects[:template.n_bones]]
    indices = {name: index for index, name in enumerate(names)}
    parents = tuple(node.parent if 0 <= node.parent < template.n_bones else -1
                    for node in template.objects[:template.n_bones])
    conversion = np.eye(4)
    conversion[:3, :3] = titus_mesh.SM2_TO_UE * 100.0
    native_globals = np.array([
        conversion @ np.array(node.matrix_lt).reshape(4, 4).T @ np.linalg.inv(conversion)
        for node in template.objects[:template.n_bones]
    ])
    pose = DonorSkeletonPose(SkeletonPose(parents, native_globals))
    recomposed = pose.compose()
    pose_error = float(np.max(np.abs(recomposed - native_globals)))
    host_globals = titus_mesh.cloud_bind_globals(skeleton.bones)
    host_by_name = {bone.name: host_globals[index][:3, 3]
                    for index, bone in enumerate(skeleton.bones)}

    measurements = []
    pairs = [
        ("head_to_ankle", "HEAD", "FOOT1L", "C_Head_a", "L_Foot_a"),
        ("shoulder_span", "ARM1L", "ARM1R", "L_UpperArm_a", "R_UpperArm_a"),
        ("left_upper_arm", "ARM1L", "ARM2L", "L_UpperArm_a", "L_Forearm_a"),
        ("left_forearm", "ARM2L", "HANDL", "L_Forearm_a", "L_Hand_a"),
        ("chest_to_hip", "CHEST", "CENTRE", "C_Spine_d", "C_Hip_a"),
    ]
    for label, start, end, host_start, host_end in pairs:
        native_length = float(np.linalg.norm(native_globals[indices[end], :3, 3] -
                                              native_globals[indices[start], :3, 3]))
        host_length = float(np.linalg.norm(host_by_name[host_end] - host_by_name[host_start]))
        measurements.append({"measurement": label, "native_cm": native_length,
                             "cloud_cm": host_length,
                             "old_scaled_native_cm": native_length * old_fit.scale,
                             "segment_mismatch_cm": native_length * old_fit.scale - host_length})

    tested_vertices = 0
    max_skin_error = 0.0
    for split_index in range(len(template.splits)):
        part = sm2tpl.decode_split(template, geometry_bytes, split_index)
        if not part.weights or not part.positions:
            continue
        count = min(2048, len(part.positions))
        positions = np.array(part.positions[:count], dtype=np.float64)
        positions = (titus_mesh.SM2_TO_UE @ positions.T).T * 100.0
        joints = np.zeros((count, 8), dtype=np.int64)
        weights = np.zeros((count, 8), dtype=np.float64)
        for vertex, influences in enumerate(part.weights[:count]):
            for slot, (joint, weight) in enumerate(influences[:8]):
                joints[vertex, slot] = joint
                weights[vertex, slot] = weight
        valid = weights.sum(axis=1) > 0
        if not valid.any():
            continue
        output = pose.skin(positions[valid], joints[valid], weights[valid], recomposed)
        max_skin_error = max(max_skin_error, float(np.max(np.abs(output - positions[valid]))))
        tested_vertices += int(valid.sum())
        if tested_vertices >= 10000:
            break

    if pose_error > 1e-7 or max_skin_error > 1e-6 or tested_vertices == 0:
        raise RuntimeError(f"Native proportion check failed: pose={pose_error}, skin={max_skin_error}, vertices={tested_vertices}")
    report = {
        "donor_bones": template.n_bones, "host_bones": len(skeleton.bones),
        "old_uniform_scale": old_fit.scale,
        "measurements": measurements,
        "native_pose_recompose_max_error": pose_error,
        "bind_skinning_max_error_cm": max_skin_error,
        "tested_vertices": tested_vertices,
        "game_content_written": False,
        "host_live_correction_applied": False,
        "in_game_corrected_result_verified": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
