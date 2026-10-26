"""Unit tests that run in system Python (no Blender): python -m unittest discover tests"""
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mmdance import config, solver, vmd  # noqa: E402


def write_vmd(path, bones=(), morphs=(), cams=()):
    """A minimal VMD file: bones (name, frame, loc, rot), morphs (name, frame, weight), cams (frame, dist)."""
    def name(s, n):
        b = s.encode('shift_jis')
        return b + b'\0' * (n - len(b))
    out = bytearray(b'Vocaloid Motion Data 0002\0\0\0\0\0' + name('model', 20))
    out += struct.pack('<I', len(bones))
    for n, f, loc, rot in bones:
        out += name(n, 15) + struct.pack('<I3f4f', f, *loc, *rot) + bytes(64)
    out += struct.pack('<I', len(morphs))
    for n, f, w in morphs:
        out += name(n, 15) + struct.pack('<If', f, w)
    out += struct.pack('<I', len(cams))
    for f, dist in cams:
        out += struct.pack('<If3f3f', f, dist, 0, 10, 0, 0, 0, 0) + bytes(24) + struct.pack('<IB', 30, 0)
    with open(path, 'wb') as fh:
        fh.write(out)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.toml = os.path.join(self.dir, 'project.toml')
        with open(self.toml, 'w', encoding='utf-8') as f:
            f.write('[project]\nname = "T"\n[motion]\nvmd = "source/m.vmd"\n[skirt]\nenabled = true\n'
                    '[bones]\nprefix = "J_"\n[bones.map]\nHips = "pelvis"\n')

    def test_defaults_and_overrides(self):
        cfg = config.load(self.toml)
        self.assertEqual(cfg.project.name, 'T')
        self.assertTrue(cfg.skirt.enabled)
        self.assertEqual(cfg.skirt.columns, 24)                    # from defaults.toml
        self.assertEqual(cfg.physics.skirt.elastic[0], 1.0)
        self.assertEqual(cfg.path('motion.vmd'), os.path.normpath(os.path.join(self.dir, 'source/m.vmd')))
        self.assertEqual(cfg.path('camera.vmd'), '')

    def test_bone_map(self):
        cfg = config.load(self.toml)
        self.assertEqual(cfg.bone('Hips'), 'pelvis')
        self.assertEqual(cfg.bone('LeftArm'), 'J_LeftArm')
        self.assertEqual(cfg.role('pelvis'), 'Hips')
        self.assertEqual(cfg.role('J_LeftArm'), 'LeftArm')
        self.assertIsNone(cfg.role('Skirt_00_0'))

    def test_local_override(self):
        elsewhere = os.path.join(tempfile.mkdtemp(), 'cache')          # an absolute path on any OS
        with open(os.path.join(self.dir, 'project.local.toml'), 'w') as f:
            f.write('[paths]\ncache = "%s"\n' % elsewhere.replace(os.sep, '/'))
        cfg = config.load(self.toml)
        self.assertEqual(cfg.path('paths.cache'), os.path.normpath(elsewhere))
        self.assertEqual(cfg.project.name, 'T')                         # the rest still comes from project.toml

    def test_key_changes_with_input(self):
        cfg = config.load(self.toml)
        self.assertEqual(cfg.key(1, [2.0, 3]), cfg.key(1, [2.0, 3]))
        self.assertNotEqual(cfg.key(1, [2.0, 3]), cfg.key(1, [2.0, 3.0001]))


class TestVmd(unittest.TestCase):
    def test_roundtrip(self):
        path = os.path.join(tempfile.mkdtemp(), 'x.vmd')
        write_vmd(path, bones=[('センター', 0, (0, 1, 0), (0, 0, 0, 1)), ('右足ＩＫ', 120, (1, 0, 0), (0, 0, 0, 1))],
                  morphs=[('まばたき', 10, 1.0), ('あ', 20, 0.5)], cams=[(0, -45.0), (60, -30.0)])
        v = vmd.read_vmd(path)
        self.assertEqual([b[0] for b in v['bones']], ['センター', '右足ＩＫ'])
        self.assertEqual(max(b[1] for b in v['bones']), 120)
        self.assertEqual(v['morphs'][0][:2], ('まばたき', 10))
        self.assertAlmostEqual(v['morphs'][1][2], 0.5)
        self.assertEqual(len(v['cams']), 2)


class TestSolver(unittest.TestCase):
    """A small skirt-like lattice hanging from a pinned ring."""

    def lattice(self, relative=True):
        ncol, nrow = 8, 5
        pts = np.zeros((ncol, nrow, 3))
        for c in range(ncol):
            a = 2 * np.pi * c / ncol
            for k in range(nrow):
                r = 0.1 + 0.03 * k
                pts[c, k] = (r * np.sin(a), -r * np.cos(a), 0.6 - 0.08 * k)
        p = dict(relative=relative, elastic=np.array([1.0, .3, .16, .1, .08]), stiff_lim=np.array([0, .55, .65, .75, .85]),
                 goal=np.zeros(nrow), tether=np.array([0, .2, .35, .5, .65]), drag=0.02, gravity_comp=0.85, goal_lying=1.0,
                 ring_mode='range', ring_min=0.82, ring_max=1.35, ring_stiff=0.5, bend_chain=0.25, bend_min=0.95,
                 edge_collide=True)
        sub = 8
        p['goal_sub'] = 1 - (1 - np.clip(p['goal'], 0, 0.999)) ** (1 / sub)
        p['goal_sub'][0] = 1
        p['elastic_sub'] = 1 - (1 - np.clip(p['elastic'], 0, 0.999)) ** (1 / sub)
        L = solver.Lattice('t', pts, np.full(ncol, nrow), np.eye(4), True, p, 0.01)
        L.init(np.eye(4))
        return L, solver.Sim(30, sub, 9.81, [])

    def test_rest_is_equilibrium_upright(self):
        L, sim = self.lattice()
        for _ in range(8 * 30):
            sim.step_lattice(L, np.eye(4), np.eye(3), [])
        self.assertLess(np.abs(L.x - L.rest).max(), 0.01)          # gravity compensation holds the rest shape

    def test_spin_lags_but_stays_bounded(self):
        L, sim = self.lattice()
        yaw = 0.0
        for f in range(60):                                         # spin the root at 6 deg/frame
            for s in range(8):
                yaw += np.radians(6) / 8
                R = np.eye(4)
                R[:3, :3] = [[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]]
                sim.step_lattice(L, R, np.eye(3), [])
        goals = L.goals(R)
        hem = L.row == L.row.max()
        lag = np.linalg.norm(L.x[hem] - goals[hem], axis=1).mean()
        self.assertGreater(lag, 0.005)                              # the hem trails the turn
        seg = np.linalg.norm(L.x[L.chain[:, 1]] - L.x[L.chain[:, 0]], axis=1)
        self.assertLess(np.abs(seg - L.chain_len).max(), 0.01)      # chains stay inextensible
        self.assertTrue(np.isfinite(L.x).all())

    def test_capsule_and_floor_collision(self):
        L, sim = self.lattice()
        cap = [(np.array([0.0, -0.25, 0.30]), np.array([0.0, 0.25, 0.30]), 0.05)]   # a bar through the hem
        for _ in range(8 * 20):
            sim.step_lattice(L, np.eye(4), np.eye(3), cap)
        a, b, r = cap[0]
        q = solver._closest(L.x, a[None], b[None])[:, 0]
        d = np.linalg.norm(L.x - q, axis=1)
        self.assertGreater(d[~L.pinned].min(), r + L.radius[0] - 2e-3)
        self.assertGreaterEqual(L.x[:, 2].min(), L.radius.min() - 1e-9)


if __name__ == '__main__':
    unittest.main()
