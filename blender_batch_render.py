import bpy
import os
import time

bl_info = {
    "name": "Batch Render Automation",
    "blender": (3, 0, 0),
    "category": "Render",
}

# ---------------------------------------------------------------------------
# Global State for Event-Driven Rendering
# ---------------------------------------------------------------------------
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
    original_settings = {}

# ---------------------------------------------------------------------------
# Dynamic External Collection Fetcher (With Caching to prevent UI lag)
# ---------------------------------------------------------------------------
_external_collection_cache = {} # filepath -> (mtime, list_of_items)

def get_external_collections(self, context):
    path = bpy.path.abspath(self.external_file)
    if not path or not os.path.exists(path):
        return [("NONE", "Select a valid .blend file", "")]
    if not path.lower().endswith(".blend"):
        return [("NONE", "Not a .blend file", "")]
        
    try:
        mtime = os.path.getmtime(path)
        if path in _external_collection_cache:
            cached_mtime, cached_items = _external_collection_cache[path]
            if cached_mtime == mtime:
                return cached_items
                
        with bpy.data.libraries.load(path) as (data_from, data_to):
            cols = data_from.collections
            if not cols:
                items = [("NONE", "No collections in file", "")]
            else:
                items = [(c, c, "") for c in cols]
                
            _external_collection_cache[path] = (mtime, items)
            return items
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return [("NONE", "Error reading file", "")]

# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
class BatchRenderTarget(bpy.types.PropertyGroup):
    source_type: bpy.props.EnumProperty(
        name="Source",
        items=[
            ('INTERNAL', "Current File", "Select a collection from the current file"),
            ('EXTERNAL', "External File", "Link or Append a collection from another file"),
        ]
    )
    internal_collection: bpy.props.PointerProperty(
        name="Collection",
        type=bpy.types.Collection
    )
    external_file: bpy.props.StringProperty(
        name="File",
        subtype='FILE_PATH'
    )
    external_collection_name: bpy.props.EnumProperty(
        name="Collection",
        items=get_external_collections
    )
    external_import_type: bpy.props.EnumProperty(
        name="Import",
        items=[
            ('APPEND', "Append", "Copy data into current file"),
            ('LINK', "Link", "Reference data from external file"),
        ]
    )
    use_custom_dir: bpy.props.BoolProperty(
        name="Custom Output Dir",
        default=False,
        description="Override the global output directory for this specific target"
    )
    custom_dir: bpy.props.StringProperty(
        name="Directory",
        subtype='DIR_PATH'
    )

class BatchRenderProperties(bpy.types.PropertyGroup):
    targets: bpy.props.CollectionProperty(type=BatchRenderTarget)
    active_target_index: bpy.props.IntProperty()
    
    output_dir: bpy.props.StringProperty(
        name="Output Directory",
        subtype='DIR_PATH',
        description="Folder where renders will be saved"
    )
    engine_mode: bpy.props.EnumProperty(
        name="Engine Mode",
        items=[
            ('RENDER', "Standard Render", "Render using Cycles/Eevee"),
            ('PLAYBLAST', "Playblast (Viewport)", "Ultra-fast viewport OpenGL render")
        ],
        default='RENDER',
        description="Choose between high quality render or fast viewport preview"
    )
    render_type: bpy.props.EnumProperty(
        name="Render Mode",
        items=[
            ('STILL', "Current Frame", "Render only the current frame"),
            ('ANIMATION', "Animation", "Render the active timeline range")
        ]
    )
    dual_output: bpy.props.BoolProperty(
        name="Auto-Composite Background",
        default=False,
        description="Run a 2-pass render to output both transparent and background-mixed PNGs"
    )
    skip_existing: bpy.props.BoolProperty(
        name="Skip Existing Frames (Resume)",
        default=False,
        description="If a file already exists at the output path, skip rendering it and move to the next frame"
    )
    bg_image_path: bpy.props.StringProperty(
        name="Background Image",
        subtype='FILE_PATH'
    )

# ---------------------------------------------------------------------------
# UI List Operations
# ---------------------------------------------------------------------------
class BATCHRENDER_UL_targets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if item.source_type == 'INTERNAL':
                if item.internal_collection:
                    layout.label(text=item.internal_collection.name, icon='OUTLINER_COLLECTION')
                else:
                    layout.label(text="(No Collection Selected)", icon='ERROR')
            else:
                name = item.external_collection_name if item.external_collection_name != "NONE" else "(Select Collection)"
                layout.label(text=f"Ext: {name}", icon='LINKED')

class BATCHRENDER_OT_add_target(bpy.types.Operator):
    bl_idname = "batchrender.add_target"
    bl_label = "Add Target"
    
    def execute(self, context):
        context.scene.batch_render_props.targets.add()
        context.scene.batch_render_props.active_target_index = len(context.scene.batch_render_props.targets) - 1
        return {'FINISHED'}

class BATCHRENDER_OT_remove_target(bpy.types.Operator):
    bl_idname = "batchrender.remove_target"
    bl_label = "Remove Target"
    
    def execute(self, context):
        props = context.scene.batch_render_props
        idx = props.active_target_index
        if 0 <= idx < len(props.targets):
            props.targets.remove(idx)
            props.active_target_index = min(max(0, idx - 1), len(props.targets) - 1)
        return {'FINISHED'}

# ---------------------------------------------------------------------------
# Auto-Compositor
# ---------------------------------------------------------------------------
def _auto_composite_image(context, fg_path, bg_path, output_path, res_x, res_y, res_pct):
    if not os.path.exists(fg_path):
        return
        
    try:
        fg_img = bpy.data.images.load(fg_path)
    except: return
    try:
        bg_img = bpy.data.images.load(bg_path)
    except:
        bpy.data.images.remove(fg_img)
        return

    try: fg_img.colorspace_settings.name = 'sRGB'
    except: pass
    try: fg_img.alpha_mode = 'STRAIGHT'
    except: pass
    try: bg_img.colorspace_settings.name = 'sRGB'
    except: pass
    try: bg_img.alpha_mode = 'STRAIGHT'
    except: pass

    temp_scene = bpy.data.scenes.new(name="Temp_AutoCompositor")
    temp_scene.render.resolution_x = res_x
    temp_scene.render.resolution_y = res_y
    temp_scene.render.resolution_percentage = res_pct
    
    try: temp_scene.view_settings.view_transform = 'Standard'
    except Exception: pass
    
    temp_scene.render.image_settings.file_format = 'PNG'
    temp_scene.render.image_settings.color_mode = 'RGBA'
    temp_scene.render.filepath = output_path
    temp_scene.use_nodes = True
    
    if hasattr(temp_scene, 'compositing_node_group'):
        tree = bpy.data.node_groups.new(name=".Temp_CompTree", type="CompositorNodeTree")
        temp_scene.compositing_node_group = tree
    else:
        tree = temp_scene.node_tree
        tree.nodes.clear()

    fg_node = tree.nodes.new("CompositorNodeImage")
    fg_node.image = fg_img
    bg_node = tree.nodes.new("CompositorNodeImage")
    bg_node.image = bg_img
    
    scale_node = tree.nodes.new("CompositorNodeScale")
    try: scale_node.space = 'RENDER_SIZE'
    except: pass
    try: scale_node.frame_method = 'CROP'
    except: pass
    
    possible_mix_types = [
        "CompositorNodeMixColor",
        "CompositorNodeMix",
        "CompositorNodeMixRGB",
        "ShaderNodeMix",
        "ShaderNodeMixRGB"
    ]
    mix_node = None
    for ntype in possible_mix_types:
        try:
            mix_node = tree.nodes.new(ntype)
            break
        except: continue
            
    if mix_node is None:
        return
        
    try: mix_node.data_type = 'RGBA'
    except: pass
    try: mix_node.blend_type = 'MIX'
    except: pass
    
    fac_socket = mix_node.inputs.get("Factor") or mix_node.inputs.get("Fac") or mix_node.inputs[0]
    color_sockets = [s for s in mix_node.inputs if s.type == 'RGBA' and not s.hide]
    if len(color_sockets) >= 2:
        bg_socket = color_sockets[0]
        fg_socket = color_sockets[1]
    else:
        bg_socket = mix_node.inputs.get("A") or mix_node.inputs.get("Image 1") or mix_node.inputs[1]
        fg_socket = mix_node.inputs.get("B") or mix_node.inputs.get("Image 2") or mix_node.inputs[2]

    if hasattr(temp_scene, 'compositing_node_group'):
        group_out = tree.nodes.new("NodeGroupOutput")
        tree.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    else:
        group_out = tree.nodes.new("CompositorNodeComposite")

    links = tree.links
    links.new(bg_node.outputs['Image'], scale_node.inputs['Image'])
    links.new(fg_node.outputs['Alpha'], fac_socket)
    links.new(scale_node.outputs['Image'], bg_socket)
    links.new(fg_node.outputs['Image'], fg_socket)
    links.new(mix_node.outputs.get("Result") or mix_node.outputs.get("Image") or mix_node.outputs[0], group_out.inputs[0])
    
    # Flag to prevent the global render_complete handler from firing for this composite render
    BatchRenderState.is_compositing = True
    bpy.ops.render.render(write_still=True, scene=temp_scene.name)
    BatchRenderState.is_compositing = False
    
    bpy.data.images.remove(fg_img)
    bpy.data.images.remove(bg_img)
    if hasattr(temp_scene, 'compositing_node_group'):
        bpy.data.node_groups.remove(tree)
    bpy.data.scenes.remove(temp_scene)

# ---------------------------------------------------------------------------
# Event-Driven Render Handlers
# ---------------------------------------------------------------------------
def restore_environment():
    BatchRenderState.is_running = False
    
    for obj, vis in BatchRenderState.original_visibility.items():
        try:
            obj.hide_render = vis['hide_render']
            obj.hide_viewport = vis['hide_viewport']
        except ReferenceError: pass
        
    for col, vis in BatchRenderState.original_col_visibility.items():
        try:
            col.hide_render = vis['hide_render']
            col.hide_viewport = vis['hide_viewport']
        except ReferenceError: pass
        
    scene = bpy.context.scene
    for k, v in BatchRenderState.original_settings.items():
        try:
            if k == 'filepath': scene.render.filepath = v
            elif k == 'film_transparent': scene.render.film_transparent = v
            elif k == 'use_compositing': scene.render.use_compositing = v
            elif k == 'file_format': scene.render.image_settings.file_format = v
            elif k == 'color_mode': scene.render.image_settings.color_mode = v
        except: pass

    # Clean up any deferred loaded items
    for item in BatchRenderState.queue:
        if item.get('is_deferred') and 'loaded_data' in item:
            data = item['loaded_data']
            if item['deferred_type'] == 'COLLECTION':
                try:
                    for obj in list(data.all_objects):
                        bpy.data.objects.remove(obj, do_unlink=True)
                    bpy.data.collections.remove(data)
                except: pass
            elif item['deferred_type'] == 'OBJECT':
                try: bpy.data.objects.remove(data, do_unlink=True)
                except: pass
                
    # Clean up internal imported collections (if any)
    for col in BatchRenderState.imported_collections:
        try:
            for obj in list(col.all_objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(col)
        except: pass
        
    # Purge any remaining orphaned meshes, materials, and textures from RAM
    try: bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except: pass
        
    BatchRenderState.imported_collections.clear()
    BatchRenderState.queue.clear()
    
    # Detach handlers so they don't consume passive resources
    if on_render_complete in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(on_render_complete)
    if on_render_cancel in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.remove(on_render_cancel)
        
    print("Batch Rendering Finished or Cancelled.")

def trigger_next_render():
    if not BatchRenderState.is_running:
        return None
        
    queue = BatchRenderState.queue
    idx = BatchRenderState.current_index
    
    if idx >= len(queue):
        restore_environment()
        return None
        
    item = queue[idx]
    frame = BatchRenderState.current_frame
    
    # Loop rapidly to skip over frames that already exist (if skip_existing is enabled)
    while True:
        if frame > item['frame_end']:
            # Clean up the current deferred item before moving to the next!
            if item.get('is_deferred') and 'loaded_data' in item:
                data = item['loaded_data']
                if item['deferred_type'] == 'COLLECTION':
                    try:
                        for obj in list(data.all_objects):
                            bpy.data.objects.remove(obj, do_unlink=True)
                        bpy.data.collections.remove(data)
                    except: pass
                elif item['deferred_type'] == 'OBJECT':
                    try: bpy.data.objects.remove(data, do_unlink=True)
                    except: pass
                item.pop('loaded_data', None)
                
                # Immediately flush RAM
                try: bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
                except: pass

            # Move to next item in queue
            BatchRenderState.current_index += 1
            if BatchRenderState.current_index >= len(queue):
                restore_environment()
                return None
            
            BatchRenderState.current_frame = queue[BatchRenderState.current_index]['frame_start']
            item = queue[BatchRenderState.current_index]
            frame = BatchRenderState.current_frame
            # Continue the while loop for the new item
            continue
            
        # Determine paths for the current frame
        frame_str = f"{frame:04d}"
        
        if item['is_animation']:
            obj_base_dir = os.path.join(item.get('output_dir', BatchRenderState.output_dir), item['name'])
            if BatchRenderState.dual_output:
                obj_no_bg_dir = os.path.join(obj_base_dir, "no_bg")
                obj_with_bg_dir = os.path.join(obj_base_dir, "with_bg")
                os.makedirs(obj_no_bg_dir, exist_ok=True)
                os.makedirs(obj_with_bg_dir, exist_ok=True)
                no_bg_path = os.path.join(obj_no_bg_dir, f"{frame_str}.png")
                item['with_bg_path'] = os.path.join(obj_with_bg_dir, f"{frame_str}.png")
            else:
                os.makedirs(obj_base_dir, exist_ok=True)
                no_bg_path = os.path.join(obj_base_dir, f"{frame_str}.png")
        else:
            # Still
            if BatchRenderState.dual_output:
                no_bg_dir = os.path.join(item.get('output_dir', BatchRenderState.output_dir), "no_bg")
                with_bg_dir = os.path.join(item.get('output_dir', BatchRenderState.output_dir), "with_bg")
                os.makedirs(no_bg_dir, exist_ok=True)
                os.makedirs(with_bg_dir, exist_ok=True)
                no_bg_path = os.path.join(no_bg_dir, f"{item['name']}_{frame_str}.png")
                item['with_bg_path'] = os.path.join(with_bg_dir, f"{item['name']}_{frame_str}.png")
            else:
                out_dir = item.get('output_dir', BatchRenderState.output_dir)
                os.makedirs(out_dir, exist_ok=True)
                no_bg_path = os.path.join(out_dir, f"{item['name']}_{frame_str}.png")
                
        item['no_bg_path'] = no_bg_path
        
        # Check if we should skip this frame
        if BatchRenderState.skip_existing:
            files_exist = os.path.exists(item['no_bg_path'])
            if BatchRenderState.dual_output:
                files_exist = files_exist and os.path.exists(item['with_bg_path'])
                
            if files_exist:
                print(f"Skipping existing frame: {item['name']} - Frame {frame}")
                frame += 1
                BatchRenderState.current_frame = frame
                continue # Rapidly check next frame
                
        # If we reach here, we found a frame we need to render! Break the rapid-skip loop.
        break
    if item.get('is_deferred') and 'loaded_data' not in item:
        path = item['external_file']
        import_type = item['external_import_type']
        try:
            with bpy.data.libraries.load(path, link=(import_type == 'LINK')) as (df, dt):
                if item['deferred_type'] == 'COLLECTION' and item['name'] in df.collections:
                    dt.collections.append(item['name'])
                elif item['deferred_type'] == 'OBJECT' and item['name'] in df.objects:
                    dt.objects.append(item['name'])
                    
            if item['deferred_type'] == 'COLLECTION' and dt.collections:
                imported_col = dt.collections[0]
                bpy.context.scene.collection.children.link(imported_col)
                item['loaded_data'] = imported_col
                item['objects'] = list(imported_col.all_objects)
            elif item['deferred_type'] == 'OBJECT' and dt.objects:
                imported_obj = dt.objects[0]
                bpy.context.scene.collection.objects.link(imported_obj)
                item['loaded_data'] = imported_obj
                item['objects'] = [imported_obj]
                
            # Register new objects for visibility tracking so they aren't hidden globally
            for obj in item.get('objects', []):
                if obj not in BatchRenderState.original_visibility:
                    BatchRenderState.original_visibility[obj] = {
                        'hide_render': obj.hide_render,
                        'hide_viewport': obj.hide_viewport
                    }
                for col in obj.users_collection:
                    if col not in BatchRenderState.original_col_visibility:
                        BatchRenderState.original_col_visibility[col] = {
                            'hide_render': col.hide_render,
                            'hide_viewport': col.hide_viewport
                        }
        except Exception as e:
            print(f"Failed to load deferred item {item['name']}: {e}")
            item['objects'] = []
        
    # Set visibility for this item ONLY
    for obj, vis in BatchRenderState.original_visibility.items():
        try:
            obj.hide_render = True
            obj.hide_viewport = True
        except ReferenceError: pass
        
    for col, vis in BatchRenderState.original_col_visibility.items():
        try:
            col.hide_render = True
            col.hide_viewport = True
        except ReferenceError: pass
        
    for obj in item['objects']:
        try:
            obj.hide_render = False
            obj.hide_viewport = False
            for col in obj.users_collection:
                col.hide_render = False
                col.hide_viewport = False
        except ReferenceError: pass
        
    scene = bpy.context.scene
    is_video = scene.render.image_settings.file_format in {'FFMPEG', 'AVI_JPEG', 'AVI_RAW'}
    is_playblast = (BatchRenderState.engine_mode == 'PLAYBLAST')
    
    # If the user selected Playblast or Video, Dual Output compositor is not supported
    if is_playblast or is_video:
        BatchRenderState.dual_output = False
        
    if item['is_animation'] and is_video:
        # For video formats, we must render the entire frame range in one operator call
        out_dir = item.get('output_dir', BatchRenderState.output_dir)
        os.makedirs(out_dir, exist_ok=True)
        ext = ".mp4" if scene.render.image_settings.file_format == 'FFMPEG' else ".avi"
        no_bg_path = os.path.join(out_dir, item['name'] + "_")
        item['no_bg_path'] = no_bg_path
        
        scene.frame_start = item['frame_start']
        scene.frame_end = item['frame_end']
        scene.render.filepath = no_bg_path
        
        if BatchRenderState.skip_existing:
            # Check if any video with this prefix already exists
            existing = [f for f in os.listdir(out_dir) if f.startswith(item['name'] + "_") and f.endswith(ext)]
            if existing:
                print(f"Skipping existing video: {item['name']}")
                BatchRenderState.current_frame = item['frame_end'] + 1
                return 0.1
                
        print(f"Batch Render Video: {item['name']}")
        BatchRenderState.current_frame = item['frame_end'] + 1 # Fast forward state
        
        try:
            if is_playblast:
                area = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None)
                region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
                if area and region:
                    with bpy.context.temp_override(area=area, region=region):
                        ret = bpy.ops.render.opengl('EXEC_DEFAULT', animation=True, view_context=True)
                else:
                    ret = bpy.ops.render.opengl('EXEC_DEFAULT', animation=True, view_context=False)
                
                # OpenGL does not fire render_complete handlers, so we must manually advance the queue
                bpy.app.timers.register(handle_render_finished, first_interval=0.1)
                return None
            else:
                ret = bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
                
            if 'RUNNING_MODAL' not in ret and 'FINISHED' not in ret:
                BatchRenderState.current_frame = item['frame_start']
                print(f"Render engine locked {ret}. Retrying in 2 seconds...")
                return 2.0
        except Exception as e:
            BatchRenderState.current_frame = item['frame_start']
            print(f"Render error: {e}. Retrying in 2 seconds...")
            return 2.0
            
        return None

    # Handle image sequence renders (Frame by Frame)
    scene.frame_set(frame)
    scene.render.filepath = no_bg_path
    
    print(f"Batch Render: {item['name']} - Frame {frame}")
    
    try:
        if is_playblast:
            area = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None)
            region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
            if area and region:
                with bpy.context.temp_override(area=area, region=region):
                    ret = bpy.ops.render.opengl('EXEC_DEFAULT', write_still=True, view_context=True)
            else:
                ret = bpy.ops.render.opengl('EXEC_DEFAULT', write_still=True, view_context=False)
                
            # OpenGL does not fire render_complete handlers, so we must manually advance the queue
            bpy.app.timers.register(handle_render_finished, first_interval=0.1)
            return None
        else:
            ret = bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)
            
        if 'RUNNING_MODAL' not in ret and 'FINISHED' not in ret:
            print(f"Render engine locked or rejected the render {ret}. Retrying in 2 seconds...")
            return 2.0 # Wait 2 seconds and let the timer retry this exact same frame
    except Exception as e:
        print(f"Render execution error: {e}. Retrying in 2 seconds...")
        return 2.0
        
    return None

@bpy.app.handlers.persistent
def on_render_complete(scene):
    # Ignore if not running, or if this render was just the auto-compositor pass
    if not BatchRenderState.is_running or BatchRenderState.is_compositing:
        return
        
    # Ensure that any deferred logic runs on the main thread, not in the handler context
    pass

def handle_render_finished():
    if not BatchRenderState.is_running:
        return None
        
    item = BatchRenderState.queue[BatchRenderState.current_index]
    if BatchRenderState.dual_output:
        try:
            _auto_composite_image(
                bpy.context,
                item['no_bg_path'],
                BatchRenderState.bg_path,
                item['with_bg_path'],
                BatchRenderState.res_x,
                BatchRenderState.res_y,
                BatchRenderState.res_pct
            )
        except Exception as e:
            print(f"Auto-Compositor error on frame {BatchRenderState.current_frame}: {e}")
            
    BatchRenderState.current_frame += 1
    bpy.app.timers.register(trigger_next_render, first_interval=0.1)
    return None

@bpy.app.handlers.persistent
def on_render_complete(scene):
    # Ignore if not running, or if this render was just the auto-compositor pass
    if not BatchRenderState.is_running or BatchRenderState.is_compositing:
        return
        
    # Offload the compositing and next-frame trigger to the main thread!
    # Calling bpy.ops.render.render directly inside this handler crashes Blender's Dependency Graph.
    bpy.app.timers.register(handle_render_finished, first_interval=0.1)

@bpy.app.handlers.persistent
def on_render_cancel(scene):
    if BatchRenderState.is_running:
        print("Batch Render Cancelled by User.")
        restore_environment()

# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------
class BATCHRENDER_OT_run(bpy.types.Operator):
    bl_idname = "render.batch_run"
    bl_label = "Batch Render Models"
    bl_description = "Render the queue. Press ESC during render to cancel."

    def get_sub_collections(self, parent_col):
        # Build queue items for all sub-collections
        items = []
        loose_objects = list(parent_col.objects)
        
        for sub_col in parent_col.children:
            objs = list(sub_col.all_objects)
            if objs:
                items.append({'name': sub_col.name, 'objects': objs})
            # Remove sub-collection objects from the loose objects pool
            for o in objs:
                if o in loose_objects:
                    loose_objects.remove(o)
                    
        # Add remaining loose objects as individual items
        for obj in loose_objects:
            items.append({'name': obj.name, 'objects': [obj]})
            
        return items

    def execute(self, context):
        if BatchRenderState.is_running:
            self.report({'WARNING'}, "Batch render is already running!")
            return {'CANCELLED'}
            
        props = context.scene.batch_render_props
        output_dir = bpy.path.abspath(props.output_dir)
        
        if not output_dir:
            self.report({'ERROR'}, "No output directory selected.")
            return {'CANCELLED'}
            
        if not props.targets:
            self.report({'ERROR'}, "Render targets list is empty.")
            return {'CANCELLED'}

        if props.dual_output:
            bg_path = bpy.path.abspath(props.bg_image_path)
            if not bg_path or not os.path.isfile(bg_path):
                self.report({'ERROR'}, "Dual Output enabled but no valid background image selected.")
                return {'CANCELLED'}
            BatchRenderState.bg_path = bg_path

        queue = []
        imported_cols = []
        
        for target in props.targets:
            target_out_dir = bpy.path.abspath(target.custom_dir) if target.use_custom_dir else output_dir
            if target.use_custom_dir and not target_out_dir:
                self.report({'WARNING'}, f"A target has Custom Directory enabled but no path is set. Falling back to global.")
                target_out_dir = output_dir

            if target.source_type == 'INTERNAL':
                if target.internal_collection:
                    sub_items = self.get_sub_collections(target.internal_collection)
                    for i in sub_items: i['output_dir'] = target_out_dir
                    queue.extend(sub_items)
            else:
                if target.external_collection_name != "NONE":
                    path = bpy.path.abspath(target.external_file)
                    try:
                        # Pre-scan: LINK the parent collection temporarily just to read its hierarchy
                        with bpy.data.libraries.load(path, link=True) as (df, dt):
                            if target.external_collection_name in df.collections:
                                dt.collections.append(target.external_collection_name)
                                
                        imported_col = dt.collections[0]
                        if imported_col:
                            sub_items = []
                            loose_obj_names = [o.name for o in imported_col.objects]
                            
                            for sub_col in imported_col.children:
                                sub_items.append({
                                    'name': sub_col.name,
                                    'is_deferred': True,
                                    'deferred_type': 'COLLECTION',
                                    'external_file': path,
                                    'external_import_type': target.external_import_type,
                                    'output_dir': target_out_dir,
                                    'objects': [] # Populated later during deferred load
                                })
                                for o in sub_col.all_objects:
                                    if o.name in loose_obj_names:
                                        loose_obj_names.remove(o.name)
                                        
                            for obj_name in loose_obj_names:
                                sub_items.append({
                                    'name': obj_name,
                                    'is_deferred': True,
                                    'deferred_type': 'OBJECT',
                                    'external_file': path,
                                    'external_import_type': target.external_import_type,
                                    'output_dir': target_out_dir,
                                    'objects': []
                                })
                                
                            queue.extend(sub_items)
                            
                            # Clean up the temporarily linked collection immediately
                            for obj in list(imported_col.all_objects):
                                bpy.data.objects.remove(obj, do_unlink=True)
                            bpy.data.collections.remove(imported_col)
                            
                            # Purge to keep RAM perfectly flat
                            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
                            
                    except Exception as e:
                        self.report({'WARNING'}, f"Failed to pre-scan {target.external_collection_name}: {e}")

        if not queue:
            self.report({'ERROR'}, "No objects found to render in the provided targets.")
            return {'CANCELLED'}
            
        # Register handlers if not already
        if on_render_complete not in bpy.app.handlers.render_complete:
            bpy.app.handlers.render_complete.append(on_render_complete)
        if on_render_cancel not in bpy.app.handlers.render_cancel:
            bpy.app.handlers.render_cancel.append(on_render_cancel)
            
        # Store State
        BatchRenderState.is_running = True
        BatchRenderState.engine_mode = props.engine_mode
        BatchRenderState.output_dir = output_dir
        BatchRenderState.dual_output = props.dual_output
        BatchRenderState.skip_existing = props.skip_existing
        BatchRenderState.res_x = context.scene.render.resolution_x
        BatchRenderState.res_y = context.scene.render.resolution_y
        BatchRenderState.res_pct = context.scene.render.resolution_percentage
        BatchRenderState.imported_collections = imported_cols
        
        # Original Settings
        BatchRenderState.original_settings = {
            'filepath': context.scene.render.filepath,
            'film_transparent': context.scene.render.film_transparent,
            'use_compositing': context.scene.render.use_compositing,
            'file_format': context.scene.render.image_settings.file_format,
            'color_mode': context.scene.render.image_settings.color_mode
        }
        
        # Setup hide state ONLY for objects and collections in the queue
        BatchRenderState.original_visibility.clear()
        BatchRenderState.original_col_visibility.clear()
        for item in queue:
            for obj in item['objects']:
                if obj not in BatchRenderState.original_visibility:
                    BatchRenderState.original_visibility[obj] = {
                        'hide_render': obj.hide_render,
                        'hide_viewport': obj.hide_viewport
                    }
                for col in obj.users_collection:
                    if col not in BatchRenderState.original_col_visibility:
                        BatchRenderState.original_col_visibility[col] = {
                            'hide_render': col.hide_render,
                            'hide_viewport': col.hide_viewport
                        }
                    
        # Apply strict render settings for Dual Output
        if props.dual_output:
            context.scene.render.film_transparent = True
            context.scene.render.use_compositing = False
            try:
                context.scene.render.image_settings.file_format = 'PNG'
                context.scene.render.image_settings.color_mode = 'RGBA'
            except TypeError:
                pass

        # Build Queue Timing
        is_anim = (props.render_type == 'ANIMATION')
        f_start = context.scene.frame_start if is_anim else context.scene.frame_current
        f_end = context.scene.frame_end if is_anim else context.scene.frame_current
        
        for item in queue:
            item['frame_start'] = f_start
            item['frame_end'] = f_end
            item['is_animation'] = is_anim
            
        BatchRenderState.queue = queue
        BatchRenderState.current_index = 0
        BatchRenderState.current_frame = f_start
        
        self.report({'INFO'}, f"Starting Event-Driven Batch Render ({len(queue)} targets).")
        bpy.app.timers.register(trigger_next_render, first_interval=0.1)
        
        return {'FINISHED'}

# ---------------------------------------------------------------------------
# Force Stop / Clear Operator
# ---------------------------------------------------------------------------
class BATCHRENDER_OT_clear(bpy.types.Operator):
    bl_idname = "render.batch_clear"
    bl_label = "Force Stop / Clear State"
    bl_description = "Use this to force unlock the addon if it gets stuck in 'running' state"

    def execute(self, context):
        if BatchRenderState.is_running:
            restore_environment()
        BatchRenderState.is_running = False
        self.report({'INFO'}, "Batch Render state force cleared.")
        return {'FINISHED'}

# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
class BATCHRENDER_PT_panel(bpy.types.Panel):
    bl_label = "Batch Render Automation"
    bl_idname = "BATCHRENDER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Batch Render'

    def draw(self, context):
        layout = self.layout
        props = context.scene.batch_render_props

        layout.label(text="Render Targets:")
        row = layout.row()
        row.template_list("BATCHRENDER_UL_targets", "", props, "targets", props, "active_target_index", rows=3)
        col = row.column(align=True)
        col.operator("batchrender.add_target", text="", icon='ADD')
        col.operator("batchrender.remove_target", text="", icon='REMOVE')
        
        if len(props.targets) > 0 and props.active_target_index < len(props.targets):
            target = props.targets[props.active_target_index]
            box = layout.box()
            box.prop(target, "source_type")
            if target.source_type == 'INTERNAL':
                box.prop(target, "internal_collection")
            else:
                box.prop(target, "external_file")
                box.prop(target, "external_collection_name")
                box.prop(target, "external_import_type")
                
            box.prop(target, "use_custom_dir")
            if target.use_custom_dir:
                box.prop(target, "custom_dir")

        layout.separator()
        layout.prop(props, "output_dir")

        layout.separator()
        col = layout.column()
        col.label(text="Settings:")
        col.prop(props, "engine_mode")
        col.prop(props, "render_type")
        col.prop(props, "skip_existing")

        if props.engine_mode != 'PLAYBLAST':
            layout.separator()
            box = layout.box()
            box.prop(props, "dual_output")
            if props.dual_output:
                box.prop(props, "bg_image_path", icon='IMAGE_DATA')
            box.label(text="Outputs: with_bg/ and no_bg/ sub-folders", icon='INFO')

        layout.separator()
        row = layout.row()
        row.scale_y = 1.5
        row.operator(
            "render.batch_run",
            icon='RENDER_STILL' if props.render_type == 'STILL' else 'RENDER_ANIMATION',
        )
        
        if BatchRenderState.is_running:
            layout.separator()
            row = layout.row()
            row.operator("render.batch_clear", icon='CANCEL')

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
classes = (
    BatchRenderTarget,
    BatchRenderProperties,
    BATCHRENDER_UL_targets,
    BATCHRENDER_OT_add_target,
    BATCHRENDER_OT_remove_target,
    BATCHRENDER_OT_run,
    BATCHRENDER_OT_clear,
    BATCHRENDER_PT_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.batch_render_props = bpy.props.PointerProperty(type=BatchRenderProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.batch_render_props

if __name__ == "__main__":
    register()
