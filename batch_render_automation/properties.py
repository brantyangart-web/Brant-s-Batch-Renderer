import bpy
import os

class BatchRenderState:
    is_running = False
    is_compositing = False
    skip_existing = False
    engine_mode = 'RENDER'
    queue = [] # list of dicts: {'name': str, 'objects': list, 'frame_start': int, 'frame_end': int}
    current_index = 0
    current_frame = 0
    
    # Settings
    output_dir = ""
    dual_output = False
    bg_path = ""
    res_x = 1920
    res_y = 1080
    res_pct = 100
    
    # Cleanup
    imported_collections = [] # Collections appended/linked that need deletion
    original_visibility = {}
    original_col_visibility = {}
    original_layer_exclude = {}
    original_settings = {}

class BatchRenderTarget(bpy.types.PropertyGroup):
    target_type: bpy.props.EnumProperty(
        name="Target Type",
        description="Select whether the target is in this file or an external file",
        items=[
            ('INTERNAL', "Internal Collection", "A collection in the current file"),
            ('EXTERNAL', "External File", "Link/Append from another .blend file"),
        ],
        default='INTERNAL'
    )
    
    internal_collection: bpy.props.PointerProperty(
        name="Collection",
        type=bpy.types.Collection,
        description="The Master Collection containing the model sub-collections"
    )
    
    external_file: bpy.props.StringProperty(
        name="Blend File",
        subtype='FILE_PATH',
        description="Path to the external .blend file"
    )
    
    external_import_type: bpy.props.EnumProperty(
        name="Import Type",
        description="How to load the external data",
        items=[
            ('APPEND', "Append", "Fully copy the data into the current file (slower but safe)"),
            ('LINK', "Link", "Reference the data from the external file (faster, uses less memory)"),
        ],
        default='APPEND'
    )
    
    external_collection_name: bpy.props.StringProperty(
        name="Collection Name",
        description="Select the master collection from the external file"
    )
    
    use_custom_dir: bpy.props.BoolProperty(
        name="Use Custom Output",
        description="Override the global output directory for this specific target",
        default=False
    )
    custom_dir: bpy.props.StringProperty(
        name="Output Directory",
        subtype='DIR_PATH',
        description="Custom output directory for this target"
    )

class BatchVersionCollectionItem(bpy.types.PropertyGroup):
    collection: bpy.props.PointerProperty(
        name="Collection",
        type=bpy.types.Collection
    )

class BatchVersionItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(
        name="Version Name",
        default="New Version"
    )
    use_for_merge: bpy.props.BoolProperty(
        name="Use for Merge",
        description="Include this version when running Batch Merge",
        default=True
    )
    collections: bpy.props.CollectionProperty(type=BatchVersionCollectionItem)
    active_collection_index: bpy.props.IntProperty()

class BatchRenderProperties(bpy.types.PropertyGroup):
    output_dir: bpy.props.StringProperty(
        name="Global Output Directory",
        subtype='DIR_PATH',
        description="Global directory where rendered images will be saved"
    )
    
    render_type: bpy.props.EnumProperty(
        name="Render Type",
        items=[
            ('STILL', "Still Image", "Render the current frame"),
            ('ANIMATION', "Animation", "Render the scene frame range"),
        ],
        default='STILL'
    )
    
    engine_mode: bpy.props.EnumProperty(
        name="Engine Mode",
        description="Choose how to render the models",
        items=[
            ('RENDER', "Standard Render", "Use Scene Render Engine (Cycles/Eevee)"),
            ('PLAYBLAST', "Playblast (Viewport)", "Replicate View -> Render Playblast (Viewport shading)"),
        ],
        default='RENDER'
    )
    
    skip_existing: bpy.props.BoolProperty(
        name="Skip Existing Frames",
        description="Check the output directory and skip rendering if the frame already exists (useful for resuming crashes). Only supported for standard RENDER mode.",
        default=False
    )
    
    dual_output: bpy.props.BoolProperty(
        name="Two-Pass Auto Compositor",
        description="Automatically renders each model twice in a single click: once with a transparent background, and once composited over a selected background image.",
        default=False
    )
    
    bg_image_path: bpy.props.StringProperty(
        name="Background Image",
        subtype='FILE_PATH',
        description="The background image to composite the models over"
    )
    
    merge_output_mode: bpy.props.EnumProperty(
        name="Output Mode",
        items=[
            ('COLLECTION', "To Collection", "Place all merged models into a specific collection"),
            ('FOLDER_OBJ', "Export to Folder (OBJ)", "Export all merged models to a folder as .obj"),
            ('FOLDER_FBX', "Export to Folder (FBX)", "Export all merged models to a folder as .fbx"),
        ],
        default='COLLECTION'
    )
    
    merge_target_collection: bpy.props.PointerProperty(
        name="Target Collection",
        type=bpy.types.Collection
    )
    
    merge_export_dir: bpy.props.StringProperty(
        name="Export Directory",
        subtype='DIR_PATH'
    )
    
    merge_voxel_size: bpy.props.FloatProperty(
        name="Voxel Size",
        default=0.03,
        min=0.001,
        precision=3
    )
    
    merge_smooth_iters: bpy.props.IntProperty(
        name="Smooth Iterations",
        default=10,
        min=0
    )
    
    merge_apply_modifiers: bpy.props.BoolProperty(
        name="Apply Modifiers",
        description="Apply Remesh, Smooth, and Decimate to the mesh to save performance",
        default=True
    )
    
    merge_use_decimate: bpy.props.BoolProperty(
        name="Use Decimation",
        description="Add a Decimate modifier to reduce poly count after remeshing",
        default=False
    )
    
    merge_decimate_ratio: bpy.props.FloatProperty(
        name="Decimate Ratio",
        description="Ratio of faces to keep (e.g., 0.5 = 50%)",
        default=0.5,
        min=0.001,
        max=1.0,
        precision=3
    )

    targets: bpy.props.CollectionProperty(type=BatchRenderTarget)
    active_target_index: bpy.props.IntProperty()

classes = (
    BatchRenderTarget,
    BatchVersionCollectionItem,
    BatchVersionItem,
    BatchRenderProperties
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
        
    bpy.types.Scene.batch_render_props = bpy.props.PointerProperty(type=BatchRenderProperties)
    bpy.types.Scene.batch_versions = bpy.props.CollectionProperty(type=BatchVersionItem)
    bpy.types.Scene.active_batch_version_index = bpy.props.IntProperty()

def unregister():
    del bpy.types.Scene.active_batch_version_index
    del bpy.types.Scene.batch_versions
    del bpy.types.Scene.batch_render_props
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
