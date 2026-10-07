# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 3
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Skenix",
    "author": "Lidarium",
    "version": (6, 7, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Skenix | Shortcut: Shift + Space",
    "description": "Smart Push/Pull Prototype (Pure BMesh Engine)",
    "category": "Mesh",
}

import bpy
import bmesh
from mathutils import Vector

# ---------------------------------------------------------------------------
# Smart Router Push/Pull Engine
# ---------------------------------------------------------------------------

class MESH_OT_modeling_push_pull(bpy.types.Operator):
    """Push/Pull face SketchUp-style using perfectly seamless Hybrid architecture"""
    bl_idname = "mesh.modeling_push_pull"
    bl_label = "Push / Pull Face"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None and context.mode == "EDIT_MESH")

    def invoke(self, context, event):
        if context.space_data.type != 'VIEW_3D':
            self.report({'WARNING'}, "Must be in 3D View")
            return {'CANCELLED'}

        self.main_obj = context.active_object
        if not self.main_obj or self.main_obj.type != 'MESH':
            self.report({'WARNING'}, "Active object must be a Mesh")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(self.main_obj.data)
        selected_faces = [f for f in bm.faces if f.select]
        if not selected_faces:
            self.report({'WARNING'}, "No face selected! Please select a face to Push/Pull.")
            return {'CANCELLED'}

        active_face = selected_faces[-1]
        self.orig_normal = active_face.normal.copy().normalized()
        self.orig_center = active_face.calc_center_median()

        # Duplicate the face to act as a visual guide and temporary boolean cutter
        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')

        self.cutter_obj = [obj for obj in context.selected_objects if obj != self.main_obj][0]

        bpy.ops.object.select_all(action='DESELECT')
        self.cutter_obj.select_set(True)
        context.view_layer.objects.active = self.cutter_obj

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

        # Create custom orientation to lock the interactive tool to the face normal
        try:
            bpy.ops.transform.create_orientation(name="PushPull", use=True, overwrite=True)
        except Exception:
            pass

        # Hand full control to the native extrude tool for perfect Blender snapping
        bpy.ops.mesh.extrude_region_move(
            'INVOKE_DEFAULT',
            TRANSFORM_OT_translate={
                'orient_type': 'PushPull',
                'constraint_axis': (False, False, True)
            }
        )

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Synchronous execution on mouse release
        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'RELEASE':
            # Use a timer to delay execution of post_process safely outside the current event loop execution,
            # allowing native operator undo pushes to complete before changing object mode / deleting objects
            bpy.app.timers.register(self.post_process, first_interval=0.01)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'RELEASE':
            self.cancel_op()
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def post_process(self):
        """Engine Router: Executes Scalar BMesh Manifold or Exact Booleans based on User Toggle."""
        context = bpy.context
        if not self.cutter_obj or self.cutter_obj.name not in bpy.data.objects:
            return None

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        context.view_layer.objects.active = self.cutter_obj
        bpy.ops.object.mode_set(mode='EDIT')
        bm_c = bmesh.from_edit_mesh(self.cutter_obj.data)

        # Calculate how far the native tool extruded the cutter geometry
        # We find the vertex with the maximum absolute offset along the normal.
        max_offset = 0.0
        for v in bm_c.verts:
            proj = (v.co - self.orig_center).dot(self.orig_normal)
            if abs(proj) > abs(max_offset):
                max_offset = proj

        offset_val = max_offset

        # Abort if the user didn't move the mouse
        if abs(offset_val) < 0.0001:
            bpy.ops.object.mode_set(mode='OBJECT')
            self.cancel_op()
            return None

        # Determine which mode to run based purely on pull/push direction
        is_outward = offset_val > 0.0001

        # ---------------------------------------------------------
        # MODE A: OUTWARD PULL (Native + Dynamic Weld)
        # ---------------------------------------------------------
        if is_outward:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(self.cutter_obj, do_unlink=True)

            context.view_layer.objects.active = self.main_obj
            bpy.ops.object.mode_set(mode='EDIT')

            bm = bmesh.from_edit_mesh(self.main_obj.data)
            bm.faces.ensure_lookup_table()

            # Find the exact original face on the main object
            orig_face = None
            for f in bm.faces:
                if f.is_valid and (f.calc_center_median() - self.orig_center).length < 0.001:
                    orig_face = f
                    break

            if orig_face:
                # 1. Mathematically extrude the face, deleting the original face automatically to avoid internal faces.
                res = bmesh.ops.extrude_discrete_faces(bm, faces=[orig_face])

                # Retrieve the newly generated cap face from the result
                new_faces = res.get('faces', [])
                if new_faces:
                    new_cap_face = new_faces[0]

                    # 2. SCALAR FIX: Translate the new cap face by the exact scalar distance along the normal.
                    for v in new_cap_face.verts:
                        v.co += self.orig_normal * offset_val

                    # Dynamic topology cleanup for outward pull:
                    # Check for adjacent coplanar faces and weld/merge them
                    # Find faces that are coplanar with the newly extruded side faces

                    # Update normals so we can compare
                    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
                    bm.faces.ensure_lookup_table()

                    # Optional: We could do a more complex coplanar merge here natively in BMesh,
                    # but dissolving limits and removing doubles usually handles most cases.
                    # For extra safety, we ensure auto-merge properties are respected
                    # or explicitly call bmesh.ops.dissolve_limit.

                # 3. Clean up and melt coplanar seams
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

                # Apply bmesh dissolve to perfectly melt all flat seams left by the extrusion
                bmesh.ops.dissolve_limit(bm, angle_limit=0.01745, verts=bm.verts, edges=bm.edges)

                bmesh.update_edit_mesh(self.main_obj.data)

                # Super-Cleanup Topology Pass
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    # Dissolve flat surfaces to combine them
                    bpy.ops.mesh.dissolve_limited(angle_limit=0.01745)
                    # Use intersect to cut any overlapping faces that might have been pulled through others
                    bpy.ops.mesh.intersect(mode='SELECT')
                    # Remove any doubles created by intersect
                    bpy.ops.mesh.remove_doubles(threshold=0.001)
                    # Dissolve again just in case
                    bpy.ops.mesh.dissolve_limited(angle_limit=0.01745)
                except Exception:
                    pass
                bpy.ops.mesh.select_all(action='DESELECT')
            return

        # ---------------------------------------------------------
        # MODE B: INWARD PUSH (Pure BMesh Sweep Raycast & Cut)
        # ---------------------------------------------------------
        if not is_outward:
            import mathutils
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(self.cutter_obj, do_unlink=True)
            context.view_layer.objects.active = self.main_obj
            bpy.ops.object.mode_set(mode='EDIT')

            bm = bmesh.from_edit_mesh(self.main_obj.data)
            bm.faces.ensure_lookup_table()

            # Find the original face
            orig_face = None
            for f in bm.faces:
                if f.is_valid and (f.calc_center_median() - self.orig_center).length < 0.001:
                    orig_face = f
                    break

            if not orig_face:
                return None

            # Construct BVH tree to find what we hit
            bvh = mathutils.bvhtree.BVHTree.FromBMesh(bm)
            ray_dir = self.orig_normal * -1.0 # pushing inward

            # Cast ray from a bit inside to avoid hitting the pushing face itself
            ray_origin = orig_face.calc_center_median() + (ray_dir * 0.001)
            hit_loc, hit_normal, hit_index, hit_dist = bvh.ray_cast(ray_origin, ray_dir)

            push_dist = abs(offset_val)
            hit_wall = False
            hit_face = None

            if hit_loc is not None:
                # If we pushed far enough to reach or pass the back wall
                if push_dist >= hit_dist - 0.002: # small tolerance
                    hit_wall = True
                    hit_face = bm.faces[hit_index]

            if hit_wall and hit_face:
                # We hit the back wall! Surgically cut the footprint using bmesh intersect booleans.

                # First, extrude the face mathematically and push it completely through the wall
                res = bmesh.ops.extrude_discrete_faces(bm, faces=[orig_face])
                new_faces = res.get('faces', [])
                if not new_faces:
                    return None
                new_cap = new_faces[0]

                # Push past the hit location to create a clean intersection volume
                overshoot = 1.0
                push_vector = ray_dir * (hit_dist + overshoot)
                for v in new_cap.verts:
                    v.co += push_vector

                # Store the newly extruded geometry that forms the "cutter" shape
                extruded_faces = set([new_cap])
                extruded_faces.update([f for f in bm.faces if f.select and f != new_cap and f != orig_face])

                # BMesh Boolean Difference
                # Note: bmesh boolean operations act on the entire mesh, but we need to isolate the operation
                # to the main mesh and the newly extruded tube.
                # Since bmesh boolean isn't robust directly on the same edit mesh without splitting,
                # we'll use BMesh bisect strictly on the hit_face but in a safer way,
                # or rely on Blender's native boolean if BMesh boolean fails.
                # However, for a pure BMesh sweep engine:

                # We use bmesh.ops.bisect_plane on the hit face to cut the footprint cleanly.

                geom_to_cut = [hit_face] + list(hit_face.edges) + list(hit_face.verts)

                for edge in new_cap.edges:
                    edge_dir = (edge.verts[1].co - edge.verts[0].co).normalized()
                    # Plane pointing outwards from the footprint
                    plane_no = edge_dir.cross(ray_dir).normalized()
                    plane_co = edge.verts[0].co - (ray_dir * overshoot) # shift plane back to the original wall

                    try:
                        bisect_res = bmesh.ops.bisect_plane(
                            bm,
                            geom=geom_to_cut,
                            plane_co=plane_co,
                            plane_no=plane_no,
                            clear_inner=False,
                            clear_outer=False
                        )
                        new_geom = bisect_res.get('geom_inner', []) + bisect_res.get('geom_outer', []) + bisect_res.get('geom_cut', [])
                        valid_geom = [g for g in geom_to_cut if g.is_valid]
                        geom_to_cut = list(set(valid_geom + new_geom))
                    except Exception:
                        pass

                # Snap the cap exactly to the wall now
                for v in new_cap.verts:
                    v.co -= (ray_dir * overshoot)
                    v.co += (ray_dir * 0.001) # tiny inset to ensure cleanly inside

                # Find faces inside the footprint on the wall
                faces_to_delete = []
                bottom_faces = [g for g in geom_to_cut if isinstance(g, bmesh.types.BMFace) and g.is_valid]

                for f in bottom_faces:
                    is_inside = True
                    center = f.calc_center_median()
                    for edge in new_cap.edges:
                        edge_dir = (edge.verts[1].co - edge.verts[0].co).normalized()
                        plane_no = edge_dir.cross(ray_dir).normalized()
                        plane_co = edge.verts[0].co
                        dist = (center - plane_co).dot(plane_no)
                        if dist > 0.001:
                            is_inside = False
                            break

                    if is_inside:
                        faces_to_delete.append(f)

                # Get boundaries of the hole to bridge
                hole_edges = set()
                for f in faces_to_delete:
                    for e in f.edges:
                        linked_faces = e.link_faces
                        if any(lf not in faces_to_delete for lf in linked_faces):
                            hole_edges.add(e)

                cap_edges = set(new_cap.edges)

                try:
                    bmesh.ops.delete(bm, geom=faces_to_delete + [new_cap], context='FACES_ONLY')
                except Exception:
                    pass

                edges_to_bridge = list(hole_edges) + list(cap_edges)
                try:
                    bmesh.ops.bridge_loops(bm, edges=edges_to_bridge)
                except Exception:
                    pass

                # Update mesh
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
                bmesh.update_edit_mesh(self.main_obj.data)

                # Clean up
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    bpy.ops.mesh.dissolve_limited(angle_limit=0.01745)
                except Exception:
                    pass
                bpy.ops.mesh.select_all(action='DESELECT')

            else:
                # Normal inward push (didn't hit a wall)
                res = bmesh.ops.extrude_discrete_faces(bm, faces=[orig_face])
                new_faces = res.get('faces', [])
                if new_faces:
                    new_cap = new_faces[0]
                    for v in new_cap.verts:
                        v.co += self.orig_normal * offset_val

                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
                bmesh.ops.dissolve_limit(bm, angle_limit=0.01745, verts=bm.verts, edges=bm.edges)
                bmesh.update_edit_mesh(self.main_obj.data)

                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    bpy.ops.mesh.dissolve_limited(angle_limit=0.01745)
                except Exception:
                    pass
                bpy.ops.mesh.select_all(action='DESELECT')

            return

    def cancel_op(self):
        """Abort operation cleanly synchronously."""
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if self.cutter_obj and self.cutter_obj.name in bpy.data.objects:
            bpy.data.objects.remove(self.cutter_obj, do_unlink=True)

        bpy.context.view_layer.objects.active = self.main_obj
        bpy.ops.object.mode_set(mode='EDIT')
        return

# ---------------------------------------------------------------------------
# UI: Floating Pie Toolbar (Shift + Space)
# ---------------------------------------------------------------------------

class VIEW3D_MT_modeling_floating_pie(bpy.types.Menu):
    bl_label = "Skenix"
    bl_idname = "VIEW3D_MT_modeling_floating_pie"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        pie.operator("mesh.modeling_push_pull", text="Push / Pull Face", icon='EXPORT')
        pie.operator("mesh.inset", text="Offset (Inset)", icon='MOD_OFFSET')
        pie.operator("mesh.dissolve_limited", text="Eraser (Clean Seams)", icon='TRASH')
        pie.operator("mesh.knife_tool", text="Line / Pencil (Knife)", icon='GREASEPENCIL')
        pie.operator("paint.ruler_add", text="Tape Measure", icon='ARROW_LEFTRIGHT')
        pie.operator("mesh.remove_doubles", text="Merge Doubles", icon='SNAP_VERTEX')

        tool_settings = context.tool_settings
        icon_weld = 'CHECKBOX_HLT' if tool_settings.use_mesh_automerge else 'CHECKBOX_DEHLT'
        pie.prop(tool_settings, "use_mesh_automerge", text="Auto-Merge & Split", icon=icon_weld)

        pie.operator("mesh.normals_make_consistent", text="Fix Normals", icon='NORMALS_FACE').inside = False

# ---------------------------------------------------------------------------
# UI: Sidebar N-Panel ("Modeling Tools" Tab)
# ---------------------------------------------------------------------------

class VIEW3D_PT_modeling_panel(bpy.types.Panel):
    bl_label = "Skenix"
    bl_idname = "VIEW3D_PT_modeling_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Skenix"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.label(text="Primary Tools:", icon='TOOL_SETTINGS')
        col.operator("mesh.modeling_push_pull", text="Push / Pull Face", icon='EXPORT')
        col.operator("mesh.inset", text="Offset (Inset)", icon='MOD_OFFSET')
        col.operator("mesh.knife_tool", text="Line / Pencil (Knife)", icon='GREASEPENCIL')
        col.operator("mesh.dissolve_limited", text="Eraser (Dissolve)", icon='TRASH')

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Surface Auto-Weld Mode:", icon='AUTOMERGE_ON')
        tool_settings = context.tool_settings
        col.prop(tool_settings, "use_mesh_automerge", text="Auto-Merge")
        if hasattr(tool_settings, "use_mesh_automerge_and_split"):
            col.prop(tool_settings, "use_mesh_automerge_and_split", text="Split Edges & Faces")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Utility & Cleanup:", icon='ORIENTATION_NORMAL')
        col.operator("mesh.normals_make_consistent", text="Recalculate Normals", icon='NORMALS_FACE').inside = False
        col.operator("mesh.remove_doubles", text="Merge By Distance", icon='SNAP_VERTEX')

# ---------------------------------------------------------------------------
# Keymap Registration
# ---------------------------------------------------------------------------

addon_keymaps = []

def register():
    bpy.utils.register_class(MESH_OT_modeling_push_pull)
    bpy.utils.register_class(VIEW3D_MT_modeling_floating_pie)
    bpy.utils.register_class(VIEW3D_PT_modeling_panel)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Mesh', space_type='EMPTY')
        kmi = km.keymap_items.new("wm.call_menu_pie", type='SPACE', value='PRESS', shift=True)
        kmi.properties.name = VIEW3D_MT_modeling_floating_pie.bl_idname
        addon_keymaps.append((km, kmi))

def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(VIEW3D_PT_modeling_panel)
    bpy.utils.unregister_class(VIEW3D_MT_modeling_floating_pie)
    bpy.utils.unregister_class(MESH_OT_modeling_push_pull)

if __name__ == "__main__":
    register()
