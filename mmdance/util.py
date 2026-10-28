"""Blender-side helpers shared by the stages (run inside Blender)."""
import hashlib
import importlib.util
import os

import numpy as np
import bpy


def project_module(cfg, path):
    """A Python file named in the config (relative to project.toml, e.g. "room.py" or
    "../other_project/hat.py"), imported by path. Projects share code by pointing at one file."""
    full = cfg.resolve(path)
    tag = hashlib.sha1(full.encode()).hexdigest()[:8]
    name = 'mmdance_project_' + os.path.splitext(os.path.basename(full))[0] + '_' + tag
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def new_action(obj, name, id_type='OBJECT', id_data=None):
    """Create a slotted action on `id_data` (defaults to obj) and return (action, channelbag)."""
    target = id_data if id_data is not None else obj
    old = target.animation_data.action if target.animation_data else None
    act = bpy.data.actions.new(name)
    slot = act.slots.new(id_type=id_type, name=target.name)
    layer = act.layers.new('Layer')
    strip = layer.strips.new(type='KEYFRAME')
    cbag = strip.channelbag(slot, ensure=True)
    target.animation_data_create()
    target.animation_data.action = act
    target.animation_data.action_slot = slot
    if old is not None and old.users == 0:
        bpy.data.actions.remove(old)
    return act, cbag


def channelbag(id_data):
    ad = id_data.animation_data
    return ad.action.layers[0].strips[0].channelbag(ad.action_slot)


def put_curve(cbag, path, index, frames, values, group=None, interp=1):
    """Write a dense F-curve. interp: 0 constant, 1 linear, 2 bezier."""
    fc = cbag.fcurves.new(path, index=index)
    if group:
        g = cbag.groups.get(group) or cbag.groups.new(group)
        fc.group = g
    n = len(frames)
    fc.keyframe_points.add(n)
    co = np.empty(2 * n, dtype=np.float32)
    co[0::2] = frames
    co[1::2] = values
    fc.keyframe_points.foreach_set('co', co)
    fc.keyframe_points.foreach_set('interpolation', [interp] * n)
    fc.update()
    return fc


def rig_and_body(cfg):
    """The character's armature and main skinned mesh (named in the config, or found)."""
    objs = bpy.data.objects
    if cfg.character.rig:
        rig = objs[cfg.character.rig]
    else:
        arms = [o for o in objs if o.type == 'ARMATURE' and not o.name.startswith('MMD_')]
        if len(arms) != 1:
            raise RuntimeError(f'set character.rig: found armatures {[o.name for o in arms]}')
        rig = arms[0]
    if cfg.character.body:
        body = objs[cfg.character.body]
    else:
        meshes = [o for o in objs if o.type == 'MESH' and
                  (o.parent is rig or any(m.type == 'ARMATURE' and m.object is rig for m in o.modifiers))]
        if not meshes:
            raise RuntimeError('set character.body: no mesh is deformed by the rig')
        body = max(meshes, key=lambda o: len(o.data.vertices))
    return rig, body


def frames(cfg):
    return np.arange(cfg.project.frame_start, cfg.project.frame_end + 1, dtype=np.float32)


def nframes(cfg):
    return cfg.project.frame_end - cfg.project.frame_start + 1


def collection(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def hide_others(keep):
    """Hide every other object from the depsgraph (fast frame sampling); returns them to restore."""
    hidden = []
    for o in bpy.context.scene.objects:
        if o is not keep and not o.hide_viewport:
            o.hide_viewport = True
            hidden.append(o)
    return hidden


def mmd_importer():
    try:
        from bl_ext.blender_org.mmd_tools.core.vmd.importer import VMDImporter
    except ImportError:
        try:
            from mmd_tools.core.vmd.importer import VMDImporter
        except ImportError:
            raise RuntimeError('mmd_tools is not installed: Edit > Preferences > Get Extensions > "MMD Tools"') from None
    return VMDImporter
