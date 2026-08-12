import bpy
from .properties import BatchRenderState

class BATCHRENDER_OT_add_version(bpy.types.Operator):
    bl_idname = "batchrender.add_version"
    bl_label = "Add Version"
    
    def execute(self, context):
        context.scene.batch_versions.add()
        context.scene.active_batch_version_index = len(context.scene.batch_versions) - 1
        return {'FINISHED'}

class BATCHRENDER_OT_remove_version(bpy.types.Operator):
    bl_idname = "batchrender.remove_version"
    bl_label = "Remove Version"
    
    def execute(self, context):
        idx = context.scene.active_batch_version_index
        if idx >= 0 and idx < len(context.scene.batch_versions):
            context.scene.batch_versions.remove(idx)
            context.scene.active_batch_version_index = max(0, idx - 1)
        return {'FINISHED'}

class BATCHRENDER_OT_duplicate_version(bpy.types.Operator):
    bl_idname = "batchrender.duplicate_version"
    bl_label = "Duplicate Version"
    
    def execute(self, context):
        idx = context.scene.active_batch_version_index
        if idx >= 0 and idx < len(context.scene.batch_versions):
            old_version = context.scene.batch_versions[idx]
            
            new_version = context.scene.batch_versions.add()
            new_version.name = old_version.name + " Copy"
            
            for item in old_version.collections:
                new_item = new_version.collections.add()
                new_item.collection = item.collection
                
            context.scene.active_batch_version_index = len(context.scene.batch_versions) - 1
        return {'FINISHED'}

class BATCHRENDER_OT_add_version_collection(bpy.types.Operator):
    bl_idname = "batchrender.add_version_collection"
    bl_label = "Add Selected Collection"
    
    def execute(self, context):
        idx = context.scene.active_batch_version_index
        if idx >= 0 and idx < len(context.scene.batch_versions):
            version = context.scene.batch_versions[idx]
            
            # If there's an active object, add its users_collection, or just add a blank one
            new_item = version.collections.add()
            
            if context.active_object and context.active_object.users_collection:
                new_item.collection = context.active_object.users_collection[0]
                
            version.active_collection_index = len(version.collections) - 1
        return {'FINISHED'}

class BATCHRENDER_OT_remove_version_collection(bpy.types.Operator):
    bl_idname = "batchrender.remove_version_collection"
    bl_label = "Remove Collection"
    
    def execute(self, context):
        idx = context.scene.active_batch_version_index
        if idx >= 0 and idx < len(context.scene.batch_versions):
            version = context.scene.batch_versions[idx]
            col_idx = version.active_collection_index
            if col_idx >= 0 and col_idx < len(version.collections):
                version.collections.remove(col_idx)
                version.active_collection_index = max(0, col_idx - 1)
        return {'FINISHED'}

def get_layer_collection_path(layer_col, target_col, path):
    if layer_col.collection == target_col:
        return path + [layer_col]
    for child in layer_col.children:
        res = get_layer_collection_path(child, target_col, path + [layer_col])
        if res: return res
    return None

class BATCHRENDER_OT_activate_version(bpy.types.Operator):
    bl_idname = "batchrender.activate_version"
    bl_label = "Activate Version"
    bl_description = "Un-hide all collections in this version, and hide collections belonging to other versions"
    
    version_index: bpy.props.IntProperty()
    
    def execute(self, context):
        scene = context.scene
        if self.version_index < 0 or self.version_index >= len(scene.batch_versions):
            return {'CANCELLED'}
            
        target_version = scene.batch_versions[self.version_index]
        scene.active_batch_version_index = self.version_index
        
        # 1. Hide ALL collections belonging to ALL versions (to isolate)
        for v in scene.batch_versions:
            for item in v.collections:
                if item.collection:
                    item.collection.hide_render = True
                    item.collection.hide_viewport = True
                    lc_path = get_layer_collection_path(context.view_layer.layer_collection, item.collection, [])
                    if lc_path:
                        lc_path[-1].exclude = True
                        
        # 2. Unhide collections for the TARGET version
        for item in target_version.collections:
            if item.collection:
                item.collection.hide_render = False
                item.collection.hide_viewport = False
                lc_path = get_layer_collection_path(context.view_layer.layer_collection, item.collection, [])
                if lc_path:
                    lc_path[-1].exclude = False
                    
        self.report({'INFO'}, f"Activated Version: {target_version.name}")
        return {'FINISHED'}

classes = (
    BATCHRENDER_OT_add_version,
    BATCHRENDER_OT_remove_version,
    BATCHRENDER_OT_duplicate_version,
    BATCHRENDER_OT_add_version_collection,
    BATCHRENDER_OT_remove_version_collection,
    BATCHRENDER_OT_activate_version
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
