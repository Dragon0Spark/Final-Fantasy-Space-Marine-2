"""Render a quick front/side preview of an OBJ in Blender (background mode).

Usage: blender -b --factory-startup -P blender_preview_obj.py -- <in.obj> <out.png>
"""
import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=src, forward_axis="NEGATIVE_Z", up_axis="Y")
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]

mat = bpy.data.materials.new("clay")
mat.diffuse_color = (0.55, 0.6, 0.7, 1.0)
for o in objs:
    o.data.materials.clear()
    o.data.materials.append(mat)

mins = [min(min((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in objs) for i in range(3)]
maxs = [max(max((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in objs) for i in range(3)]
center = [(a + b) / 2 for a, b in zip(mins, maxs)]
height = maxs[2] - mins[2]

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.render.resolution_x = 900
scene.render.resolution_y = 900
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("w")

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = height * 1.15
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

views = [("front", (0, -1, 0)), ("side", (1, 0, 0)), ("back", (0, 1, 0))]
paths = []
for name, d in views:
    cam.location = (center[0] + d[0] * 10, center[1] + d[1] * 10, center[2])
    direction = [-d[0], -d[1], 0.0]
    yaw = math.atan2(direction[1], direction[0]) - math.pi / 2
    cam.rotation_euler = (math.pi / 2, 0.0, yaw)
    path = out.replace(".png", f"_{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    paths.append(path)
print("rendered", paths)
