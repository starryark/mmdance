"""Split the gown into its fabric layers: inner skirt vs. outer overskirt panels.

A skirt vertex belongs to the outer layer when, looking inward toward the body axis, there is
another skirt surface beneath it (within 1-9 cm). The label is cleaned by majority vote over the
mesh neighbourhood, then softened into a blend band. Used by rig.py.
"""
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

AXIS_XY = (0.0, -0.02)


def classify_layers(ob, skirt_idx, ztop=0.60, axis_xy=AXIS_XY, allow=None):
    """allow: optional per-vertex mask of where an outer layer may be (e.g. only the apron)."""
    me = ob.data
    skirt = set(int(i) for i in skirt_idx)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    faces = [f for f in bm.faces if all(v.index in skirt for v in f.verts)]
    bm_s = bmesh.new()
    vmap = {}
    for f in faces:
        vs = []
        for v in f.verts:
            if v.index not in vmap:
                vmap[v.index] = bm_s.verts.new(v.co)
            vs.append(vmap[v.index])
        try:
            bm_s.faces.new(vs)
        except ValueError:
            pass
    bm_s.verts.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm_s)
    outer = np.zeros(len(me.vertices), np.float32)
    for vi in skirt:
        co = bm.verts[vi].co
        if co.z > ztop or (allow is not None and not allow[vi]):
            continue
        d = Vector((axis_xy[0] - co.x, axis_xy[1] - co.y, 0.0))
        if d.length < 1e-4:
            continue
        d.normalize()
        hit = tree.ray_cast(co + d * 0.006, d, 0.09)
        if hit[0] is not None:
            outer[vi] = 1.0
    # smooth the label over the mesh (two majority passes), then a soft blend band
    adj = [[] for _ in range(len(me.vertices))]
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        if a in skirt and b in skirt:
            adj[a].append(b)
            adj[b].append(a)
    lab = outer.copy()
    for _ in range(2):
        new = lab.copy()
        for vi in skirt:
            if adj[vi]:
                new[vi] = 1.0 if np.mean([lab[j] for j in adj[vi]] + [lab[vi]]) > 0.5 else 0.0
        lab = new
    soft = lab.copy()
    for _ in range(3):
        new = soft.copy()
        for vi in skirt:
            if adj[vi]:
                new[vi] = 0.5 * soft[vi] + 0.5 * np.mean([soft[j] for j in adj[vi]])
        soft = new
    bm.free()
    bm_s.free()
    return lab, soft

