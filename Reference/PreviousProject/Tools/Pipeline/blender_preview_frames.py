"""Render several OBJ frames (same character) from the side and front into PNGs (Blender background).

Usage: blender -b --factory-startup -P blender_preview_frames.py -- <out dir> <frame.obj> [...]
Writes <out dir>/<obj stem>_side.png and _front.png.
"""
import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out_dir, objs = argv[0], argv[1:]

for path in objs:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=path, forward_axis="NEGATIVE_Z", up_axis="Y")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    mat = bpy.data.materials.new("clay")
    mat.diffuse_color = (0.35, 0.45, 0.8, 1.0)
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(mat)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 600
    scene.render.resolution_y = 700
    scene.world = bpy.data.worlds.new("w")
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 3.2
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    stem = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    for name, d in (("side", (1, 0, 0)), ("front", (0, -1, 0))):
        cam.location = (d[0] * 10, d[1] * 10, 1.3)
        yaw = math.atan2(-d[1], -d[0]) - math.pi / 2
        cam.rotation_euler = (math.pi / 2, 0.0, yaw)
        scene.render.filepath = f"{out_dir}/{stem}_{name}.png"
        bpy.ops.render.render(write_still=True)
print("done")
