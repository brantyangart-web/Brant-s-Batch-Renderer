bl_info = {
    "name": "Batch Render Automation",
    "blender": (3, 0, 0),
    "category": "Render",
}

import bpy

if "bpy" in locals() and "properties" in locals():
    import importlib
    importlib.reload(properties)
    importlib.reload(ui)
    importlib.reload(ops_render)
    importlib.reload(ops_versioning)
    importlib.reload(ops_merge)
else:
    from . import properties, ui, ops_render, ops_versioning, ops_merge

modules = [properties, ui, ops_render, ops_versioning, ops_merge]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()

if __name__ == "__main__":
    register()
