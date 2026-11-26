# SPDX-License-Identifier: GPL-2.0-or-later

from contextlib import chdir, nullcontext, redirect_stdout
import io
from itertools import islice
from pathlib import Path
import tempfile

import bpy
from mathutils import Vector


def execute(code, inputs=None, outputs=None):
    if not isinstance(code, str):
        raise ValueError("script must be a string")
    namespace = {"__name__": "__main__", "bpy": bpy, "input_dir": inputs, "output_dir": outputs}
    log = io.StringIO()
    where = chdir(outputs) if outputs else nullcontext()
    with where, redirect_stdout(log):
        exec(compile(code, "<farm-worker>", "exec"), namespace)
        steps = namespace.get("farm_steps")
        iterator = iter(steps()) if steps is not None else None
    if iterator is not None:
        while True:
            with where, redirect_stdout(log):
                try:
                    next(iterator)
                except StopIteration:
                    break
            yield
    return {"executed": True, "result": log.getvalue()}


def render(params):
    scene = bpy.context.scene
    if bpy.app.is_job_running("RENDER"):
        raise ValueError("a render is already running")
    path = Path(bpy.path.abspath(params.get("filepath") or str(Path(tempfile.gettempdir()) / "farm-render.png")))
    if not path.is_absolute():
        raise ValueError("render filepath must be absolute")
    previous = scene.render.filepath
    done = []

    def completed(*_):
        done.append(True)

    def cancelled(*_):
        done.append(False)

    bpy.app.handlers.render_complete.append(completed)
    bpy.app.handlers.render_cancel.append(cancelled)
    try:
        scene.render.filepath = str(path)
        mode = "EXEC_DEFAULT" if bpy.app.background else "INVOKE_DEFAULT"
        status = bpy.ops.render.render(mode, write_still=True)
        if "RUNNING_MODAL" in status:
            while bpy.app.is_job_running("RENDER"):
                yield
        if "CANCELLED" in status or done != [True]:
            raise RuntimeError("render cancelled or failed")
        actual = str(path)
        if scene.render.use_file_extension:
            actual = bpy.path.ensure_ext(actual, scene.render.file_extension)
        if not Path(actual).is_file():
            raise RuntimeError("render produced no image")
        return {"filepath": actual}
    finally:
        bpy.app.handlers.render_complete.remove(completed)
        bpy.app.handlers.render_cancel.remove(cancelled)
        scene.render.filepath = previous


def command(request):
    kind = request.get("type")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    scene = bpy.context.scene
    if kind == "get_scene_info":
        return {"name": scene.name, "object_count": len(scene.objects), "materials_count": len(bpy.data.materials),
                "objects": [{"name": ob.name, "type": ob.type, "location": list(ob.location)}
                            for ob in islice(scene.objects, 10)]}
    if kind == "get_object_info":
        ob = scene.objects.get(params["name"])
        if ob is None:
            raise ValueError("object not found")
        info = {"name": ob.name, "type": ob.type, "location": list(ob.location),
                "rotation": list(ob.rotation_euler), "scale": list(ob.scale),
                "visible": ob.visible_get(), "materials": [s.material.name for s in ob.material_slots if s.material]}
        if ob.type == "MESH":
            points = [ob.matrix_world @ Vector(p) for p in ob.bound_box]
            info.update(world_bounding_box=[[f(p[i] for p in points) for i in range(3)] for f in (min, max)],
                        mesh={"vertices": len(ob.data.vertices), "edges": len(ob.data.edges),
                              "polygons": len(ob.data.polygons)})
        return info
    if kind == "execute_code":
        return (yield from execute(params["code"]))
    if kind == "render":
        return (yield from render(params))
    if kind in {"get_polyhaven_status", "get_hyper3d_status", "get_sketchfab_status", "get_hunyuan3d_status"}:
        return {"enabled": False}
    raise ValueError("unknown Blender command")
