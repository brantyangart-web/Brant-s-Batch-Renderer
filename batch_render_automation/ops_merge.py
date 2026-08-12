import bpy
import os
import tempfile
from .ops_versioning import BATCHRENDER_OT_activate_version

class BATCHRENDER_OT_batch_merge_versions(bpy.types.Operator):
    bl_idname = "batchrender.batch_merge_versions"
    bl_label = "Batch Merge & Save Versions"
    bl_description = "Iterate through all versions, merge them, and output to a folder or collection"
    bl_options = {'REGISTER', 'UNDO'}
    
    output_mode: bpy.props.EnumProperty(
        name="Output Mode",
        items=[
            ('COLLECTION', "To Collection", "Place all merged models into a specific collection"),
            ('FOLDER_OBJ', "Export to Folder (OBJ)", "Export all merged models to a folder as .obj"),
            ('FOLDER_FBX', "Export to Folder (FBX)", "Export all merged models to a folder as .fbx"),
        ],
        default='COLLECTION'
    )
    
    target_collection: bpy.props.PointerProperty(
        name="Target Collection",
        type=bpy.types.Collection
    )
    
    export_dir: bpy.props.StringProperty(
        name="Export Directory",
        subtype='DIR_PATH'
    )
    
    voxel_size: bpy.props.FloatProperty(
        name="Voxel Size",
        default=0.03,
        min=0.001,
        precision=3
    )
    
    smooth_iters: bpy.props.IntProperty(
        name="Smooth Iterations",
        default=10,
        min=0
    )

    @classmethod
    def poll(cls, context):
        return context.scene.batch_versions and len(context.scene.batch_versions) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "output_mode")
        if self.output_mode == 'COLLECTION':
            layout.prop(self, "target_collection")
        else:
            layout.prop(self, "export_dir")
            
        layout.separator()
        layout.prop(self, "voxel_size")
        layout.prop(self, "smooth_iters")

    def execute(self, context):
        scene = context.scene
        
        if self.output_mode != 'COLLECTION' and not self.export_dir:
            self.report({'ERROR'}, "Please specify an export directory.")
            return {'CANCELLED'}
            
        if self.output_mode == 'COLLECTION' and not self.target_collection:
            self.report({'ERROR'}, "Please specify a target collection.")
            return {'CANCELLED'}

        temp_dir = tempfile.gettempdir()
        temp_obj_path = os.path.join(temp_dir, "batchrender_temp_merge.obj")
        
        export_dir_abs = bpy.path.abspath(self.export_dir) if self.export_dir else ""
        
        # Save current active version to restore later
        original_active_idx = scene.active_batch_version_index

        for i, version in enumerate(scene.batch_versions):
            # 1. Isolate the version
            bpy.ops.batchrender.activate_version(version_index=i)
            
            # 2. Select all visible mesh objects in this version
            bpy.ops.object.select_all(action='DESELECT')
            valid_objects = []
            
            for item in version.collections:
                if item.collection:
                    for obj in item.collection.all_objects:
                        if obj.type == 'MESH' and not obj.hide_get() and not obj.hide_render:
                            obj.select_set(True)
                            valid_objects.append(obj)
                            
            if not valid_objects:
                self.report({'WARNING'}, f"Version '{version.name}' has no visible meshes. Skipping.")
                continue
                
            context.view_layer.objects.active = valid_objects[0]
            
            # Store original materials from the active object
            original_materials = []
            if context.active_object and hasattr(context.active_object.data, "materials"):
                original_materials = [m for m in context.active_object.data.materials]
                
            # 3. Export to Temp OBJ (Bakes modifiers)
            try:
                if hasattr(bpy.ops.wm, "obj_export"):
                    bpy.ops.wm.obj_export(filepath=temp_obj_path, export_selected_objects=True, export_materials=False)
                else:
                    bpy.ops.export_scene.obj(filepath=temp_obj_path, use_selection=True, use_materials=False)
            except Exception as e:
                self.report({'ERROR'}, f"Failed to export {version.name}: {e}")
                continue
                
            # We DO NOT delete original objects for batch version merging!
            # We want to keep the scene intact.
            bpy.ops.object.select_all(action='DESELECT')
            
            # 4. Import the baked mesh
            try:
                if hasattr(bpy.ops.wm, "obj_import"):
                    bpy.ops.wm.obj_import(filepath=temp_obj_path)
                else:
                    bpy.ops.import_scene.obj(filepath=temp_obj_path)
            except Exception as e:
                self.report({'ERROR'}, f"Failed to import {version.name}: {e}")
                continue
                
            new_selected = context.selected_objects
            if not new_selected:
                continue
                
            context.view_layer.objects.active = new_selected[0]
            if len(new_selected) > 1:
                bpy.ops.object.join()
                
            merged_obj = context.active_object
            merged_obj.name = version.name
            
            # 5. Apply Remesh and Smooth
            remesh_mod = merged_obj.modifiers.new(name="Remesh", type='REMESH')
            remesh_mod.mode = 'VOXEL'
            remesh_mod.voxel_size = self.voxel_size
            
            if self.smooth_iters > 0:
                smooth_mod = merged_obj.modifiers.new(name="Smooth", type='SMOOTH')
                smooth_mod.iterations = self.smooth_iters
                
            # Restore materials
            if hasattr(merged_obj.data, "materials"):
                merged_obj.data.materials.clear()
                for mat in original_materials:
                    if mat: merged_obj.data.materials.append(mat)
                    
            # 6. Apply all modifiers (Realize the remesh)
            # Since we might export it immediately, it's safer to apply them.
            if self.output_mode != 'COLLECTION':
                bpy.ops.object.convert(target='MESH')
            
            # 7. Output Routing
            if self.output_mode == 'COLLECTION':
                # Link to target collection
                for col in merged_obj.users_collection:
                    col.objects.unlink(merged_obj)
                self.target_collection.objects.link(merged_obj)
            else:
                # Export to folder
                safe_name = "".join([c for c in version.name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                
                if self.output_mode == 'FOLDER_OBJ':
                    out_path = os.path.join(export_dir_abs, f"{safe_name}.obj")
                    if hasattr(bpy.ops.wm, "obj_export"):
                        bpy.ops.wm.obj_export(filepath=out_path, export_selected_objects=True)
                    else:
                        bpy.ops.export_scene.obj(filepath=out_path, use_selection=True)
                elif self.output_mode == 'FOLDER_FBX':
                    out_path = os.path.join(export_dir_abs, f"{safe_name}.fbx")
                    bpy.ops.export_scene.fbx(filepath=out_path, use_selection=True)
                
                # Delete the temporary merged object since we exported it
                bpy.ops.object.delete()
                
        # Cleanup temp file
        if os.path.exists(temp_obj_path):
            try: os.remove(temp_obj_path)
            except: pass
            
        temp_mtl_path = temp_obj_path.replace(".obj", ".mtl")
        if os.path.exists(temp_mtl_path):
            try: os.remove(temp_mtl_path)
            except: pass
            
        # Restore original version
        if original_active_idx >= 0 and original_active_idx < len(scene.batch_versions):
            bpy.ops.batchrender.activate_version(version_index=original_active_idx)

        self.report({'INFO'}, "Batch Merge Complete!")
        return {'FINISHED'}

classes = (
    BATCHRENDER_OT_batch_merge_versions,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
