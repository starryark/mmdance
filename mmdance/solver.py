"""Position-based simulation of the skirt, overskirt and hair bone lattices (pure numpy).

Particles are the joints of the physics bone chains. Each lattice has its root row pinned to
a body bone (Hips for the skirt, Head for the hair). Per substep:
  * inertia with drag, and "rest-equilibrium" gravity: g_world - R_root * g_world, so the
    modelled rest shape is the equilibrium while upright, and real gravity takes over as the
    body tips over (lying down, deep bends);
  * either jointed chains (`relative`: each joint springs toward its rest angle relative to its
    simulated parent, with a hard angular limit, as MMD rigid-body skirts / DynamicBone do) or a
    goal spring toward the rest shape carried by the root; plus a tether (maximum deviation);
  * chain-length constraints (inextensible), ring constraints (a stretch/squash band), bending;
  * capsule colliders on the body (edges too, so limbs cannot slip between particles), the
    floor, rounded-box furniture colliders, and for hair/panels the skirt surface;
  * inelastic contacts: a push out of a collider does not turn into velocity.
"""
import numpy as np

# body bones (Mixamo role names) the simulation follows: lattice roots and collider capsules
TRACK = ['Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head']
for _s in ('Left', 'Right'):
    TRACK += [_s + n for n in ('Shoulder', 'Arm', 'ForeArm', 'Hand', 'HandMiddle3', 'UpLeg', 'Leg', 'Foot', 'ToeBase')]


def quat_from_mat(m):
    """Rotation matrix (3x3) -> quaternion (w, x, y, z)."""
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        return np.array([0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s])
    i = np.argmax(np.diag(m))
    if i == 0:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return np.array([(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s])
    if i == 1:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return np.array([(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s])
    s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return np.array([(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s])


def mat_from_quat(q):
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def slerp(q0, q1, a):
    d = np.dot(q0, q1)
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + a * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - a) * th) * q0 + np.sin(a * th) * q1) / np.sin(th)


def lerp_mat4(m0, m1, a):
    """Interpolate rigid 4x4 transforms (slerp rotation, lerp translation)."""
    out = np.eye(4)
    out[:3, :3] = mat_from_quat(slerp(quat_from_mat(m0[:3, :3]), quat_from_mat(m1[:3, :3]), a))
    out[:3, 3] = m0[:3, 3] * (1 - a) + m1[:3, 3] * a
    return out


class Lattice:
    """Particles of one bone lattice. pts_rest: (ncol, nrow, 3) with per-column lengths."""

    def __init__(self, name, pts_rest, lens, root_rest, wrap, params, radius):
        self.name = name
        self.ncol = pts_rest.shape[0]
        self.lens = np.asarray(lens)
        self.wrap = wrap
        self.p = params
        idx = []
        for c in range(self.ncol):
            for k in range(self.lens[c]):
                idx.append((c, k))
        self.idx = idx
        self.id_of = {ck: i for i, ck in enumerate(idx)}
        self.n = len(idx)
        self.rest = np.array([pts_rest[c, k] for c, k in idx])
        self.row = np.array([k for c, k in idx])
        self.pinned = self.row == 0
        inv = np.linalg.inv(root_rest)
        self.local = (inv[:3, :3] @ self.rest.T).T + inv[:3, 3]        # rest in root-bone space
        self.radius = np.broadcast_to(np.asarray(radius, float), (self.n,)).copy()
        # constraints
        ch, ring = [], []
        for c in range(self.ncol):
            for k in range(self.lens[c] - 1):
                ch.append((self.id_of[(c, k)], self.id_of[(c, k + 1)]))
            for k in range(1, self.lens[c]):
                c2 = (c + 1) % self.ncol if wrap else c + 1
                if c2 < self.ncol and (c2, k) in self.id_of and c2 != c:
                    ring.append((self.id_of[(c, k)], self.id_of[(c2, k)]))
        # bending: skip-one pairs along chains and around rings
        bch, brg = [], []
        for c in range(self.ncol):
            for k in range(1, self.lens[c] - 1):
                bch.append((self.id_of[(c, k - 1)], self.id_of[(c, k + 1)]))
            for k in range(1, self.lens[c]):
                cm, cp = (c - 1) % self.ncol if wrap else c - 1, (c + 1) % self.ncol if wrap else c + 1
                if 0 <= cm < self.ncol and 0 <= cp < self.ncol and (cm, k) in self.id_of and (cp, k) in self.id_of and cm != cp:
                    brg.append((self.id_of[(cm, k)], self.id_of[(cp, k)]))
        self.bend_chain = np.array(bch) if bch else np.zeros((0, 2), int)
        self.bend_ring = np.array(brg) if brg else np.zeros((0, 2), int)
        self.bend_chain_len = (np.linalg.norm(self.rest[self.bend_chain[:, 0]] - self.rest[self.bend_chain[:, 1]], axis=1)
                               if len(self.bend_chain) else np.zeros(0))
        self.bend_ring_len = (np.linalg.norm(self.rest[self.bend_ring[:, 0]] - self.rest[self.bend_ring[:, 1]], axis=1)
                              if len(self.bend_ring) else np.zeros(0))
        self.parent = np.array([self.id_of[(c, k - 1)] if k > 0 else -1 for c, k in idx])
        self.off_local = np.zeros((self.n, 3))
        nonroot = self.parent >= 0
        self.off_local[nonroot] = self.local[nonroot] - self.local[self.parent[nonroot]]
        self.seg_len = np.linalg.norm(self.off_local, axis=1)
        self.chain = np.array(ch)
        self.ring = np.array(ring) if ring else np.zeros((0, 2), int)
        self.chain_len = np.linalg.norm(self.rest[self.chain[:, 0]] - self.rest[self.chain[:, 1]], axis=1)
        self.ring_len = (np.linalg.norm(self.rest[self.ring[:, 0]] - self.rest[self.ring[:, 1]], axis=1)
                         if len(self.ring) else np.zeros(0))
        self.x = None
        self.xprev = None
        self.side = None
        self.side_e = None
        self.nsign = 1.0
        if wrap and len(set(self.lens.tolist())) == 1:
            n = self.grid_normals(self.rest)
            radial = self.rest.copy()
            radial[:, 2] = 0
            radial[:, :2] -= radial[:, :2].mean(0)
            self.nsign = 1.0 if (n * radial).sum() > 0 else -1.0

    def grid_normals(self, x):
        """Outward surface normals for a full wrap-around grid (the skirt)."""
        X = x.reshape(self.ncol, self.lens[0], 3)
        t = np.empty_like(X)
        t[:, 1:-1] = X[:, 2:] - X[:, :-2]
        t[:, 0] = X[:, 1] - X[:, 0]
        t[:, -1] = X[:, -1] - X[:, -2]
        lat = np.roll(X, -1, axis=0) - np.roll(X, 1, axis=0)
        n = np.cross(t, lat) * self.nsign
        n /= np.maximum(np.linalg.norm(n, axis=2)[..., None], 1e-9)
        return n.reshape(-1, 3)

    def goals(self, root):
        return (root[:3, :3] @ self.local.T).T + root[:3, 3]

    def init(self, root):
        self.x = self.goals(root)
        self.xprev = self.x.copy()


def solve_dist(x, pairs, rest, inv_mass, stiff, mode='both', lo=None, hi=None):
    """Distance constraints with an allowed band [lo*rest, hi*rest]; `stiff` may be per pair."""
    if not len(pairs):
        return
    bands = {'both': (1.0, 1.0), 'max': (0.0, 1.0), 'squash': (0.6, 1.0), 'min': (1.0, 1e9)}
    l0, h0 = bands.get(mode, (1.0, 1.0))
    lo = l0 if lo is None else lo
    hi = h0 if hi is None else hi
    a, b = pairs[:, 0], pairs[:, 1]
    d = x[b] - x[a]
    L = np.linalg.norm(d, axis=1) + 1e-9
    err = L - np.clip(L, lo * rest, hi * rest)
    wa, wb = inv_mass[a], inv_mass[b]
    ws = wa + wb + 1e-9
    corr = (stiff * err / L / ws)[:, None] * d
    np.add.at(x, a, corr * wa[:, None])
    np.add.at(x, b, -corr * wb[:, None])


def _closest(points, A, B):
    """Closest points on capsule axes. points (N,3), A/B (C,3) -> q (N,C,3)."""
    AB = B - A
    L2 = np.maximum((AB * AB).sum(1), 1e-12)
    t = np.clip(np.einsum('nck,ck->nc', points[:, None, :] - A[None], AB) / L2, 0.0, 1.0)
    return A[None] + t[..., None] * AB[None]


def _side_dirs(d, dist, side, lim):
    """Unit push directions that keep each point on the side of the capsule it came from.

    side: (N,C,3) remembered unit directions (zero = unknown). Returns (dir, effective penetration).
    A point that crossed the capsule axis while still close to it is sent back to its old side.
    """
    unit = d / np.maximum(dist[..., None], 1e-7)
    known = (side * side).sum(2) > 0.5
    crossed = known & ((unit * side).sum(2) < 0.0) & (dist < lim + 0.05)
    direc = np.where(crossed[..., None], side, unit)
    pen = np.where(crossed, lim + dist, lim - dist)
    return direc, pen, crossed


def _outer_dirs(d, dist, nrm, lim, capture=0.02):
    """Push directions that always put a point on the outer side (normal side) of a limb.

    d: (N,C,3) offsets from capsule axes, nrm: (N,3) outward surface normals of the lattice.
    Points on the inner side (the limb has come through the fabric) are mirrored back out
    if they are within `capture` of the limb surface.
    """
    unit = d / np.maximum(dist[..., None], 1e-7)
    side = (unit * nrm[:, None, :]).sum(2)
    inner = side < 0.0
    mirrored = unit - 2.0 * side[..., None] * nrm[:, None, :]
    mirrored /= np.maximum(np.linalg.norm(mirrored, axis=2)[..., None], 1e-7)
    direc = np.where(inner[..., None], mirrored, unit)
    pen = np.where(inner & (dist < lim + capture), lim - dist + 2e-3, lim - dist)
    pen = np.where(inner & (dist < lim + capture), np.maximum(pen, 1e-3), pen)
    return direc, pen


def _update_side(side, x, q, lim):
    d = x[:, None, :] - q
    dist = np.linalg.norm(d, axis=2)
    near = dist < lim + 0.08
    far = dist > lim + 0.2
    unit = d / np.maximum(dist[..., None], 1e-7)
    side[near] = unit[near]
    side[far] = 0.0


def _caps_arrays(caps):
    return (np.array([c[0] for c in caps]), np.array([c[1] for c in caps]), np.array([c[2] for c in caps]))


def _choose_dirs(d, dist, lim, side, nrm, trust):
    """Outer-side rule where the fabric surface is trustworthy, side memory elsewhere."""
    if side is not None:
        d_s, p_s, _ = _side_dirs(d, dist, side, lim)
    else:
        d_s, p_s = d / np.maximum(dist[..., None], 1e-7), lim - dist
    if nrm is None:
        return d_s, p_s
    d_o, p_o = _outer_dirs(d, dist, nrm, lim)
    t = trust[:, None]
    return np.where(t[..., None], d_o, d_s), np.where(t, p_o, p_s)


def collide_capsules(x, rad, caps, active=None, side=None, nrm=None, trust=None):
    """Push points out of the most-penetrated capsule (vectorised over all capsules).

    With `side` (N,C,3 state), points never tunnel through a limb: they leave on the side
    they were on before.
    """
    if not caps:
        return
    A, B, R = _caps_arrays(caps)
    q = _closest(x, A, B)
    d = x[:, None, :] - q
    dist = np.linalg.norm(d, axis=2)
    lim = R[None] + rad[:, None]
    direc, pen = _choose_dirs(d, dist, lim, side, nrm, trust)
    j = pen.argmax(1)
    n = np.arange(len(x))
    hit = pen[n, j] > 0
    if active is not None:
        hit &= active
    if hit.any():
        x[hit] = q[n, j][hit] + direc[n, j][hit] * lim[n, j][hit][:, None]
    if side is not None:
        _update_side(side, x, _closest(x, A, B), lim)


def collide_edges(x, pairs, rad_pair, caps, inv_mass, side=None, nrm=None, trust=None):
    """Push lattice edges (via their midpoints) out of capsules so limbs cannot slip between particles."""
    if not len(pairs) or not caps:
        return
    A, B, R = _caps_arrays(caps)
    a, b = pairs[:, 0], pairs[:, 1]
    m = 0.5 * (x[a] + x[b])
    q = _closest(m, A, B)
    d = m[:, None, :] - q
    dist = np.linalg.norm(d, axis=2)
    lim = R[None] + rad_pair[:, None]
    ne, te = None, None
    if nrm is not None:
        ne = nrm[a] + nrm[b]
        ne /= np.maximum(np.linalg.norm(ne, axis=1)[:, None], 1e-7)
        te = trust[a] & trust[b]
    direc, pen = _choose_dirs(d, dist, lim, side, ne, te)
    j = pen.argmax(1)
    n = np.arange(len(m))
    hit = pen[n, j] > 0
    if hit.any():
        target = q[n, j][hit] + direc[n, j][hit] * lim[n, j][hit][:, None]
        push = target - m[hit]
        wa, wb = inv_mass[a[hit]], inv_mass[b[hit]]
        s = 2.0 / np.maximum(wa + wb, 1e-6)          # move the midpoint by exactly `push`
        np.add.at(x, a[hit], push * (wa * s)[:, None])
        np.add.at(x, b[hit], push * (wb * s)[:, None])
    if side is not None:
        m = 0.5 * (x[a] + x[b])
        _update_side(side, m, _closest(m, A, B), lim)


def collide_floor_bed(x, rad, boxes):
    np.maximum(x[:, 2], rad, out=x[:, 2])
    if not boxes:
        return
    if isinstance(boxes[0], (int, float)):
        boxes = [boxes]
    for b in boxes:
        _collide_box(x, rad, b)


def _collide_box(x, rad, bed, rb=0.025):
    """Rounded-box collider: distance to the box shrunk by rb, so the push direction turns smoothly
    round the edges instead of jumping between faces (no flicker at the desk/sofa edges)."""
    x0, x1, y0, y1, top = bed
    lo = np.array([x0 + rb, y0 + rb, -1.0])
    hi = np.array([x1 - rb, y1 - rb, top - rb])
    near = (x[:, 0] > x0 - rad - 0.01) & (x[:, 0] < x1 + rad + 0.01) & (x[:, 1] > y0 - rad - 0.01) &            (x[:, 1] < y1 + rad + 0.01) & (x[:, 2] < top + rad + 0.01)
    if not near.any():
        return
    p = x[near]
    r = rad[near]
    q = np.clip(p, lo, hi)
    d = p - q
    dl = np.linalg.norm(d, axis=1)
    lim = rb + r
    inside = dl < 1e-7                                   # deep inside the core: leave through the top
    hit = (dl < lim) & ~inside
    if hit.any():
        p[hit] = q[hit] + d[hit] / dl[hit, None] * lim[hit, None]
    if inside.any():
        p[inside, 2] = top + r[inside]
    x[near] = p


def skirt_surface_push(hx, hrad, skirt, Dm, outer, axis_xy):
    """Keep hair particles outside the skirt's outer surface.

    Dm maps rest-world -> current world for the hips (hips_world @ hips_rest^-1). In rest-world
    coordinates the skirt columns sit at fixed angles around a vertical axis, so for each hair
    particle we interpolate the current skirt radius at its angle/height and push it out radially.
    """
    R = Dm[:3, :3]
    o = Dm[:3, 3]
    hl = (hx - o) @ R                              # current world -> rest-world frame
    S = ((skirt.x - o) @ R).reshape(skirt.ncol, skirt.lens[0], 3)
    ax = np.array([axis_xy[0], axis_xy[1]])
    rel = S[..., :2] - ax
    r = np.linalg.norm(rel, axis=2)
    h = S[..., 2]
    relh = hl[:, :2] - ax
    rh = np.linalg.norm(relh, axis=1)
    ah = np.arctan2(relh[:, 0], -relh[:, 1])
    hh = hl[:, 2]
    ncol, nrow = skirt.ncol, skirt.lens[0]
    step = 2 * np.pi / ncol
    f = (ah % (2 * np.pi)) / step
    c0 = np.floor(f).astype(int) % ncol
    c1 = (c0 + 1) % ncol
    a = f - np.floor(f)
    out = np.zeros(len(hx))
    valid = np.ones(len(hx), bool)
    for cc, w in ((c0, 1 - a), (c1, a)):
        hc = h[cc]
        rc = r[cc] + outer[cc]
        rr = np.full(len(hx), np.nan)
        for k in range(nrow - 1):
            top, bot = hc[:, k], hc[:, k + 1]
            m = (hh <= top) & (hh >= bot) & np.isnan(rr)
            t = np.where(m, (top - hh) / np.maximum(top - bot, 1e-6), 0)
            rr = np.where(m, rc[:, k] * (1 - t) + rc[:, k + 1] * t, rr)
        valid &= ~np.isnan(rr)
        out += w * np.nan_to_num(rr, nan=0.0)
    need = valid & (rh < out + hrad)
    if need.any():
        dirn = relh[need] / np.maximum(rh[need, None], 1e-6)
        newl = hl[need].copy()
        target = ax + dirn * (out[need] + hrad[need])[:, None]
        step = target - newl[:, :2]
        sl = np.linalg.norm(step, axis=1)
        step *= np.minimum(1.0, 0.02 / np.maximum(sl, 1e-9))[:, None]
        newl[:, :2] += step
        hx[need] = newl @ R.T + o


class Sim:
    def __init__(self, fps, substeps, gravity, boxes):
        self.dt = 1.0 / (fps * substeps)
        self.substeps = substeps
        self.g = np.array([0, 0, -gravity])
        self.bed = boxes or None                  # box colliders (x0, x1, y0, y1, top)

    def step_lattice(self, L, root, root_rest_rot, caps, extra=None, iters=4):
        p = L.p
        dt = self.dt
        goals = L.goals(root)
        # rest-equilibrium gravity: only the change of gravity relative to the body acts while the
        # body is upright; as it tips over (lying, deep bends) real gravity and drape take over
        Rrel = root[:3, :3] @ root_rest_rot.T
        up = max(0.0, Rrel[2, 2])
        u = up * up
        acc = self.g - Rrel @ self.g * (p['gravity_comp'] * u)
        v = (L.x - L.xprev) * (1.0 - p['drag'])
        # clamp velocity relative to the body (kills pops without touching normal swing)
        if getattr(L, 'goals_prev', None) is not None:
            gv = goals - L.goals_prev
            rel = v - gv
            rl = np.linalg.norm(rel, axis=1)
            vmax = p.get('vmax', 0.2) / self.substeps
            fast = rl > vmax
            if fast.any():
                v[fast] = gv[fast] + rel[fast] * (vmax / rl[fast])[:, None]
        L.goals_prev = goals
        L.xprev = L.x.copy()
        x = L.x + v + acc * dt * dt
        x[L.pinned] = goals[L.pinned]
        if p.get('relative'):
            # each joint springs toward its rest angle relative to its simulated parent
            Rr = root[:3, :3]
            off = L.off_local @ Rr.T
            ke = p['elastic_sub']
            for k in range(1, L.row.max() + 1):
                m = L.row == k
                tgt = x[L.parent[m]] + off[m]
                x[m] += (tgt - x[m]) * ke[k]
        else:
            # goal spring (stiffness given per frame -> per substep)
            kg = p['goal_sub'][L.row][:, None] * (p['goal_lying'] + (1 - p['goal_lying']) * u)
            x += (goals - x) * kg
        inv_mass = np.where(L.pinned, 0.0, 1.0)
        col_dx = np.zeros_like(x)                 # displacement caused by collisions this step
        for _ in range(iters):
            solve_dist(x, L.chain, L.chain_len, inv_mass, 1.0, 'both')
            if p.get('relative'):
                # angular limit: a joint may deviate from its rest direction (relative to the
                # simulated parent) by at most the chord stiff_lim * segment length
                Rr = root[:3, :3]
                off = L.off_local @ Rr.T
                for k in range(1, L.row.max() + 1):
                    m = np.nonzero(L.row == k)[0]
                    tgt = x[L.parent[m]] + off[m]
                    d = x[m] - tgt
                    dl = np.linalg.norm(d, axis=1)
                    lim = p['stiff_lim'][k] * L.seg_len[m] * (1.0 + p.get('lying_relax', 0.6) * (1 - u))
                    over = dl > lim
                    if over.any():
                        mm = m[over]
                        x[mm] = tgt[over] + d[over] * (lim[over] / dl[over])[:, None]
            if len(L.ring):
                rs = np.asarray(p['ring_stiff'], float)
                rs = rs[L.row[L.ring[:, 0]]] if rs.ndim else rs
                if p['ring_mode'] == 'range':
                    solve_dist(x, L.ring, L.ring_len, inv_mass, rs, lo=p['ring_min'], hi=p['ring_max'])
                else:
                    solve_dist(x, L.ring, L.ring_len, inv_mass, rs, p['ring_mode'])
            if p.get('bend_chain', 0) > 0 and len(L.bend_chain):
                solve_dist(x, L.bend_chain, L.bend_chain_len, inv_mass, p['bend_chain'], lo=p.get('bend_min', 0.92), hi=1e9)
            if p.get('bend_ring', 0) > 0 and len(L.bend_ring):
                solve_dist(x, L.bend_ring, L.bend_ring_len, inv_mass, p['bend_ring'], lo=p.get('bend_ring_min', 0.8), hi=1e9)
            # tether to the goal
            dev = x - goals
            dl = np.linalg.norm(dev, axis=1)
            lim = p['tether'][L.row] * (1.0 + 1.5 * (1 - u))
            over = dl > lim
            if over.any():
                # rate-limited projection: a particle a limb lets go of eases back over a couple of
                # frames instead of teleporting; hard stop at twice the limit
                tgt = goals[over] + dev[over] * (lim[over] / dl[over])[:, None]
                step = tgt - x[over]
                sl = np.linalg.norm(step, axis=1)
                rate = p.get('tether_rate', 0.004)
                x[over] += step * np.minimum(1.0, rate / np.maximum(sl, 1e-9))[:, None]
                dev = x - goals
                dl = np.linalg.norm(dev, axis=1)
                hard = dl > 2 * lim
                if hard.any():
                    x[hard] = goals[hard] + dev[hard] * (2 * lim[hard] / dl[hard])[:, None]
            if L.side is None or L.side.shape[1] != len(caps):
                L.side = np.zeros((L.n, len(caps), 3))
                L.side_e = [np.zeros((len(pr), len(caps), 3)) for pr in (L.chain, L.ring)]
            nrm, trust = None, None
            if p.get('outer_rule'):
                nrm = L.grid_normals(x)
                # radial direction from the lattice axis (root ring centre, body up-axis)
                c0 = x[L.pinned].mean(0)
                upv = Rrel[:, 2]
                rv = x - c0
                rv -= (rv @ upv)[:, None] * upv
                rv /= np.maximum(np.linalg.norm(rv, axis=1)[:, None], 1e-7)
                trust = ((nrm * rv).sum(1) > 0.5) & (u > 0.8)
            before = x.copy()
            before_all = x.copy()
            collide_capsules(x, L.radius, caps, active=~L.pinned, side=L.side, nrm=nrm, trust=trust)
            if p.get('edge_collide'):
                for pairs, se in zip((L.chain, L.ring), L.side_e):
                    if len(pairs):
                        rp = 0.5 * (L.radius[pairs[:, 0]] + L.radius[pairs[:, 1]])
                        collide_edges(x, pairs, rp, caps, inv_mass, side=se, nrm=nrm, trust=trust)
            if extra is not None:
                extra(x)
            # cap collision corrections per iteration so nothing teleports
            dx = x - before
            dn = np.linalg.norm(dx, axis=1)
            cap = p.get('max_push', 1e9)
            big = dn > cap
            if big.any():
                x[big] = before[big] + dx[big] * (cap / dn[big])[:, None]
            collide_floor_bed(x, L.radius, self.bed)
            col_dx += x - before_all
            x[L.pinned] = goals[L.pinned]
        # contacts are inelastic: the push out of a limb/furniture does not become velocity
        L.xprev = L.xprev + col_dx * p.get('absorb', 0.85)
        L.x = x
