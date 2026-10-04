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
    "version": (6, 7, 0),
    "blender": (2, 91, 0),
    "location": "View3D > Sidebar (N) > Skenix | Shortcut: Shift + Space",
    "description": "Smart Push/Pull (Scalar-Math Native Extrude + CSG Toggles)",
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
            self.post_process()
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'RELEASE':
            self.cancel_op()
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def post_process(self):
        """Engine Router: Executes Scalar BMesh Manifold or Exact Booleans based on User Toggle."""
        context = bpy.context
        if not self.cutter_obj or self.cutter_obj.name not in bpy.data.objects:
            return

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
            return

        # Determine which engine to run based on UI switch
        engine_mode = context.scene.push_pull_engine
        run_native = False
        run_csg = False

        if engine_mode == 'AUTO':
            if offset_val > 0.0001:
                run_native = True
            else:
                run_csg = True
        elif engine_mode == 'NATIVE':
            run_native = True
        elif engine_mode == 'CSG':
            run_csg = True

        # ---------------------------------------------------------
        # ENGINE A: PURE SCALAR BMESH EXTRUDE (Native)
        # ---------------------------------------------------------
        if run_native:
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
                # 1. Mathematically extrude the face.
                res = bmesh.ops.extrude_face_region(bm, geom=[orig_face])

                # In BMesh, extrude_face_region preserves the original face as the cap of the extrusion,
                # and creates new side faces connecting the original position to the cap.
                # 2. SCALAR FIX: Translate the cap face (orig_face) by the exact scalar distance along the normal.
                for v in orig_face.verts:
                    v.co += self.orig_normal * offset_val

                # 3. Clean up the internal geometry left behind by the region extrusion
                # Actually, extrude_face_region doesn't leave an internal face at the base when extruding a single face.
                # Deleting orig_face would remove the cap, creating a hollow box.
                # So we simply remove doubles and recalculate normals.


                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
                bmesh.update_edit_mesh(self.main_obj.data)

                # Super-Cleanup Topology Pass
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    bpy.ops.mesh.dissolve_limited(angle_limit=0.01745)
                except Exception:
                    pass
                bpy.ops.mesh.select_all(action='DESELECT')
            return

        # ---------------------------------------------------------
        # ENGINE B: EXACT CSG BOOLEAN DIFFERENCE (Cut)
        # ---------------------------------------------------------
        if run_csg:
            # 1. Cap the open back of the cutter to make it a perfectly manifold solid block
            boundary_edges = [e for e in bm_c.edges if e.is_boundary]
            if boundary_edges:
                bmesh.ops.hole_fill(bm_c, edges=boundary_edges)

            # 2. OVERLAP TRICK: Break mathematical coplanarity by shifting the base
            min_dist = float('inf')
            base_face = None
            for f in bm_c.faces:
                dist = (f.calc_center_median() - self.orig_center).length
                if dist < min_dist:
                    min_dist = dist
                    base_face = f

            if base_face:
                for v in base_face.verts:
                    if offset_val > 0.0001:
                        # UNION (Outward Pull): Push base face slightly into the solid mesh to guarantee overlap.
                        # This overlap ensures that the exact boolean solver registers it as a true union
                        # and doesn't leave non-manifold seams at flush boundaries, which allows dissolve_limited
                        # to melt the lines.
                        v.co -= self.orig_normal * 0.005 # 5mm overlap
                    else:
                        # DIFFERENCE (Inward Push): Pull base face 2cm OUT into empty space
                        v.co += self.orig_normal * 0.02

            bmesh.ops.recalc_face_normals(bm_c, faces=bm_c.faces)
            bmesh.update_edit_mesh(self.cutter_obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

            # 3. Apply EXACT CSG Boolean
            context.view_layer.objects.active = self.main_obj
            bool_mod = self.main_obj.modifiers.new("PPCut", 'BOOLEAN')
            bool_mod.object = self.cutter_obj
            bool_mod.solver = 'EXACT'

            if offset_val > 0.0001:
                bool_mod.operation = 'UNION'
            else:
                bool_mod.operation = 'DIFFERENCE'

            try:
                bpy.ops.object.modifier_apply(modifier=bool_mod.name)
            except Exception:
                pass

            bpy.data.objects.remove(self.cutter_obj, do_unlink=True)

            # 4. Deep Clean Topology Pass
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.remove_doubles(threshold=0.001)
            bpy.ops.mesh.normals_make_consistent(inside=False)

            # Destroy internal faces left by Boolean solver so edge seams can dissolve
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_interior_faces()
            bpy.ops.mesh.delete(type='FACE')

            # Melt all coplanar seams perfectly
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
        col.label(text="Push/Pull Engine:", icon='MOD_BOOLEAN')
        col.prop(context.scene, "push_pull_engine", expand=True)

        layout.separator()
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
    bpy.types.Scene.push_pull_engine = bpy.props.EnumProperty(
        name="Engine",
        description="Select the mathematical engine used for Push/Pull",
        items=[
            ('AUTO', "Auto", "Smart Routing: Native for Outward, CSG for Inward"),
            ('NATIVE', "Native", "Force Native Extrude Manifold"),
            ('CSG', "CSG", "Force Exact Boolean Architecture")
        ],
        default='AUTO'
    )

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
    del bpy.types.Scene.push_pull_engine

    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(VIEW3D_PT_modeling_panel)
    bpy.utils.unregister_class(VIEW3D_MT_modeling_floating_pie)
    bpy.utils.unregister_class(MESH_OT_modeling_push_pull)

if __name__ == "__main__":
    register()
