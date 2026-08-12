import bpy
import os
from .properties import BatchRenderState

class BATCHRENDER_UL_targets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            if item.target_type == 'INTERNAL':
                row.label(text=item.internal_collection.name if item.internal_collection else "No Collection", icon='OUTLINER_COLLECTION')
            else:
                name = os.path.basename(item.external_file) if item.external_file else "No File"
                row.label(text=f"[{item.external_import_type}] {name} -> {item.external_collection_name}", icon='LINK_BLEND')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_COLLECTION')

class BATCHRENDER_UL_versions(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "name", text="", emboss=False, icon='OUTLINER_OB_GROUP_INSTANCE')
            op = row.operator("batchrender.activate_version", text="", icon='RESTRICT_VIEW_OFF')
            op.version_index = index
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_OB_GROUP_INSTANCE')

class BATCHRENDER_UL_version_collections(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "collection", text="", emboss=False, icon='OUTLINER_COLLECTION')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_COLLECTION')

class BATCHRENDER_PT_panel(bpy.types.Panel):
    bl_label = "Batch Operations Hub"
    bl_idname = "BATCHRENDER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Batch Automation'

    def draw(self, context):
        layout = self.layout
        props = context.scene.batch_render_props
        
        # --- Batch Render Automation ---
        box = layout.box()
        box.label(text="Batch Render Automator", icon='RENDER_ANIMATION')
        
        box.prop(props, "output_dir")
        box.prop(props, "engine_mode")
        box.prop(props, "render_type")
        if props.render_type == 'STILL' and props.engine_mode == 'RENDER':
            box.prop(props, "skip_existing")
            
        box.separator()
        box.prop(props, "dual_output")
        if props.dual_output:
            box.prop(props, "bg_image_path")
            if props.engine_mode == 'PLAYBLAST':
                box.label(text="Dual Output is not supported in Playblast mode.", icon='ERROR')
        
        box.separator()
        box.label(text="Render Targets:")
        row = box.row()
        row.template_list("BATCHRENDER_UL_targets", "", props, "targets", props, "active_target_index")
        
        col = row.column(align=True)
        col.operator("batchrender.add_target", text="", icon='ADD')
        col.operator("batchrender.remove_target", text="", icon='REMOVE')
        
        if props.active_target_index >= 0 and props.active_target_index < len(props.targets):
            active_target = props.targets[props.active_target_index]
            target_box = box.box()
            target_box.prop(active_target, "target_type")
            target_box.prop(active_target, "use_custom_dir")
            if active_target.use_custom_dir:
                target_box.prop(active_target, "custom_dir")
                
            if active_target.target_type == 'INTERNAL':
                target_box.prop(active_target, "internal_collection")
            else:
                target_box.prop(active_target, "external_file")
                target_box.prop(active_target, "external_import_type")
                
                row = target_box.row()
                row.prop_search(active_target, "external_collection_name", context.scene, "batchrender_external_cols", text="Collection")
                row.operator("batchrender.fetch_external_collections", text="", icon='FILE_REFRESH')
                
        box.separator()
        
        if BatchRenderState.is_running:
            box.operator("batchrender.cancel", text="Cancel Batch Render", icon='CANCEL')
            box.label(text=f"Rendering Queue... Item {BatchRenderState.current_index + 1} / {len(BatchRenderState.queue)}", icon='INFO')
        else:
            box.operator("batchrender.run", text="START BATCH RENDER", icon='PLAY')

class BATCHRENDER_PT_versions(bpy.types.Panel):
    bl_label = "Batch Version Manager"
    bl_idname = "BATCHRENDER_PT_versions"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Batch Automation'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Variants / Versions:", icon='GROUP_VCOL')
        row = layout.row()
        row.template_list("BATCHRENDER_UL_versions", "", scene, "batch_versions", scene, "active_batch_version_index")
        
        col = row.column(align=True)
        col.operator("batchrender.add_version", text="", icon='ADD')
        col.operator("batchrender.remove_version", text="", icon='REMOVE')

        if scene.active_batch_version_index >= 0 and scene.active_batch_version_index < len(scene.batch_versions):
            active_version = scene.batch_versions[scene.active_batch_version_index]
            
            box = layout.box()
            box.label(text=f"Collections in '{active_version.name}':", icon='OUTLINER_COLLECTION')
            row = box.row()
            row.template_list("BATCHRENDER_UL_version_collections", "", active_version, "collections", active_version, "active_collection_index")
            
            col = row.column(align=True)
            col.operator("batchrender.add_version_collection", text="", icon='ADD')
            col.operator("batchrender.remove_version_collection", text="", icon='REMOVE')
            
        layout.separator()
        layout.label(text="Batch Operations:", icon='MODIFIER')
        layout.operator("batchrender.batch_merge_versions", text="Batch Merge Versions", icon='MOD_REMESH')

classes = (
    BATCHRENDER_UL_targets,
    BATCHRENDER_UL_versions,
    BATCHRENDER_UL_version_collections,
    BATCHRENDER_PT_panel,
    BATCHRENDER_PT_versions
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
