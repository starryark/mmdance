"""Stage: the render camera.

The MMD camera motion (camera.vmd) is imported with mmd_tools as `Dance_Cam`. Without one, a
front camera follows the character across the floor. `camera.track` instead keys a camera from a
track file made outside Blender (a camera solved from the dance's reference video), and can move
the dancer with it. `[[camera.shots]]` add cameras of their own over a frame range (for instance
where the MMD camera was made for a different model and would end up inside a big skirt);
timeline markers switch between them.
"""
import bpy
import numpy as np
from mathutils import Vector

from .util import channelbag, hide_others, mmd_importer, new_action, put_curve, rig_and_body


def _coll():
    return bpy.data.collections.get('Cameras') or bpy.context.scene.collection


def mmd_camera(cfg):
    sc = bpy.context.scene
    for name in ('MMD_Camera', 'Dance_Cam', 'Dance_CamRig'):
        o = bpy.data.objects.get(name)
        if o:
            bpy.data.objects.remove(o)
    cam_data = bpy.data.cameras.new('Dance_Cam')
    cam = bpy.data.objects.new('Dance_Cam', cam_data)
    coll = _coll()
    coll.objects.link(cam)
    sc.frame_set(0)
    VMDImporter = mmd_importer()
    VMDImporter(cfg.path('camera.vmd'), scale=cfg.motion.scale, frame_margin=0).assign(cam)
    root = cam.parent                      # mmd_tools adds an 'MMD_Camera' empty that carries the motion
    root.name = 'Dance_CamRig'
    if root.users_collection[0] != coll:
        for c in root.users_collection:
            c.objects.unlink(root)
        coll.objects.link(root)
    return cam


def front_camera(cfg):
    """Front camera that follows the dancer across the floor (no camera VMD).

    It keeps a fixed offset from a smoothed path of the hips (1 s moving average), so the whole
    character stays in frame as the dance travels, without the camera shaking with every step.
    """
    rig, body = rig_and_body(cfg)
    zs = [(body.matrix_world @ v.co).z for v in body.data.vertices]
    h = max(zs) - min(zs)
    cam_data = bpy.data.cameras.new('Dance_Cam')
    cam = bpy.data.objects.new('Dance_Cam', cam_data)
    _coll().objects.link(cam)
    cam_data.lens = 50
    rx, ry = cfg.camera.resolution
    half_tan = cam_data.sensor_width / 2 / cam_data.lens * min(1.0, ry / rx)    # vertical half-FOV (tan)
    dist = 1.6 * h / (2 * half_tan)
    offset = Vector((0, -dist, 0.12 * h))
    cam.rotation_euler = (-offset).to_track_quat('-Z', 'Y').to_euler()
    # smoothed hips path over the frame range
    sc = bpy.context.scene
    hidden = hide_others(rig)
    hips = rig.pose.bones[cfg.bone('Hips')]
    f0, f1 = cfg.project.frame_start, cfg.project.frame_end
    xy = []
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        p = rig.matrix_world @ hips.head
        xy.append((p.x, p.y))
    for o in hidden:
        o.hide_viewport = False
    xy = np.array(xy)
    win = max(1, int(cfg.project.fps) // 2)
    pad = np.pad(xy, ((win, win), (0, 0)), mode='edge')
    kern = np.ones(2 * win + 1) / (2 * win + 1)
    sm = np.stack([np.convolve(pad[:, k], kern, mode='valid') for k in range(2)], 1)
    frames = np.arange(f0, f1 + 1, dtype=np.float32)
    _, cbag = new_action(cam, 'Front_Cam')
    loc = [sm[:, 0] + offset.x, sm[:, 1] + offset.y, np.full(len(sm), 0.5 * h + offset.z)]
    for k in range(3):
        put_curve(cbag, 'location', k, frames, loc[k])
    return cam


def track_camera(cfg, tr):
    """A camera keyed on every frame from `camera.track`: an .npz with frames (n,), loc (n, 3),
    quat (n, 4) as w x y z, lens and sensor (mm, horizontal)."""
    o = bpy.data.objects.get('Track_Cam')
    if o:
        bpy.data.objects.remove(o)
    cd = bpy.data.cameras.new('Track_Cam')
    cd.sensor_fit = 'HORIZONTAL'
    cd.sensor_width = float(tr['sensor'])
    cd.lens = float(tr['lens'])
    cam = bpy.data.objects.new('Track_Cam', cd)
    _coll().objects.link(cam)
    cam.rotation_mode = 'QUATERNION'
    _, cbag = new_action(cam, 'Track_Cam')
    frames = tr['frames'].astype(np.float32)
    for path, v in (('location', tr['loc']), ('rotation_quaternion', tr['quat'])):
        for k in range(v.shape[1]):
            put_curve(cbag, path, k, frames, v[:, k].astype(np.float32))
    return cam


def track_dancer(cfg, tr):
    """The rig object's place and heading on every frame from the track (rig_loc_<name>,
    rig_rotz_<name>; name = camera.track_dancer). A motion capture keeps the dancer facing the lens;
    when the real camera went round her, this turns her back with it. Called by the stage, after
    the steps: until then the rig object must stay at the origin, because the rig stage joins the
    rebuilt hands into the body through world matrices. The simulation runs in the rig's own frame
    and does not feel this turn."""
    who = cfg.camera.track_dancer
    rig, _ = rig_and_body(cfg)
    rig.rotation_mode = 'XYZ'
    rz = tr['rig_rotz_' + who]
    cbag = channelbag(rig)
    frames = tr['frames'].astype(np.float32)
    for path, v in (('location', tr['rig_loc_' + who]), ('rotation_euler', np.stack([0 * rz, 0 * rz, rz], 1))):
        for k in range(3):
            old = cbag.fcurves.find(path, index=k)
            if old is not None:
                cbag.fcurves.remove(old)
            put_curve(cbag, path, k, frames, v[:, k].astype(np.float32))


def shot(cfg, s):
    """A camera tracking a look-at target along keys [[frame, location, look_at], ...]."""
    name = s['name']
    for n in (name + '_Cam', name + '_Target'):
        o = bpy.data.objects.get(n)
        if o:
            bpy.data.objects.remove(o)
    coll = _coll()
    tgt = bpy.data.objects.new(name + '_Target', None)
    tgt.empty_display_size = 0.05
    coll.objects.link(tgt)
    cd = bpy.data.cameras.new(name + '_Cam')
    cam = bpy.data.objects.new(name + '_Cam', cd)
    coll.objects.link(cam)
    cd.lens = s.get('lens', 40)
    cd.sensor_fit = 'VERTICAL'
    cd.sensor_height = 24
    cd.clip_start, cd.clip_end = cfg.camera.clip
    if s.get('fstop', 0) > 0:
        cd.dof.use_dof = True
        cd.dof.focus_object = tgt
        cd.dof.aperture_fstop = s['fstop']
    con = cam.constraints.new('TRACK_TO')
    con.target = tgt
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    for f, loc, look in s['keys']:
        cam.location = loc
        cam.keyframe_insert('location', frame=f)
        tgt.location = look
        tgt.keyframe_insert('location', frame=f)
    # smooth, slow move: auto-clamped bezier, no overshoot
    for ob in (cam, tgt):
        for fc in ob.animation_data.action.layers[0].strips[0].channelbag(ob.animation_data.action_slot).fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'BEZIER'
                kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'
    return cam


def run(cfg):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = cfg.camera.resolution
    sc.render.resolution_percentage = 100
    if 'Cameras' not in bpy.data.collections:
        sc.collection.children.link(bpy.data.collections.new('Cameras'))
    if cfg.camera.track:
        cam = track_camera(cfg, np.load(cfg.path('camera.track')))
    else:
        cam = mmd_camera(cfg) if cfg.camera.vmd else front_camera(cfg)
    cam.data.clip_start, cam.data.clip_end = cfg.camera.clip
    sc.camera = cam
    shots = cfg.camera.get('shots') or []
    for m in list(sc.timeline_markers):
        if m.name.startswith('Shot_'):
            sc.timeline_markers.remove(m)
    for s in sorted(shots, key=lambda s: s['start']):
        c = shot(cfg, s)
        m = sc.timeline_markers.new('Shot_' + s['name'], frame=s['start'])
        m.camera = c
        if 'end' in s:
            m = sc.timeline_markers.new('Shot_' + s['name'] + '_end', frame=s['end'])
            m.camera = cam
        if s['start'] <= cfg.project.frame_start:
            sc.camera = c
    return cam
