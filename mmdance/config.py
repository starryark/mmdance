"""Project configuration: one project.toml per animation, merged over defaults.toml.

Pure Python (no bpy), so the Blender stages and the system-Python tools share it.

    cfg = config.load('projects/my_dance/project.toml')
    cfg.motion.scale, cfg.path('paths.cache'), cfg.bone('LeftUpLeg')
"""
import copy
import hashlib
import json
import os
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = os.path.join(HERE, 'defaults.toml')


class Section(dict):
    """A dict whose keys can also be read as attributes (cfg.skirt.rows_z)."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(f'config has no key {k!r} (have: {", ".join(self)})') from None

    def __setattr__(self, k, v):
        self[k] = v


def _wrap(d):
    if isinstance(d, dict):
        return Section({k: _wrap(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_wrap(v) for v in d]
    return d


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(Section):
    @property
    def root(self):
        return self['_root']

    def path(self, key):
        """Absolute path of a path-valued config key ('paths.cache', 'motion.vmd'); '' if unset."""
        node = self
        for part in key.split('.'):
            node = node[part]
        return self.resolve(node)

    def resolve(self, p):
        """A path written in the config (relative to project.toml) as an absolute path."""
        return os.path.normpath(os.path.join(self.root, p)) if p else ''

    def cache(self, name):
        d = self.path('paths.cache')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def textures(self, name=''):
        d = self.path('paths.textures')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name) if name else d

    def bone(self, role):
        """Rig bone name for a Mixamo role name ('Hips', 'LeftUpLeg', 'RightHandIndex1', ...)."""
        m = self['bones'].get('map') or {}
        return m.get(role, self['bones']['prefix'] + role)

    def role(self, bone_name):
        """Inverse of bone(): the Mixamo role of a rig bone, or None."""
        inv = getattr(self, '_inv_map', None)
        if inv is None:
            inv = {v: k for k, v in (self['bones'].get('map') or {}).items()}
            dict.__setitem__(self, '_inv_map', inv)
        if bone_name in inv:
            return inv[bone_name]
        p = self['bones']['prefix']
        if bone_name.startswith(p):
            return bone_name[len(p):]
        return None

    def key(self, *parts):
        """Short content hash for cache file names."""
        h = hashlib.sha1(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode('utf-8'))
        return h.hexdigest()[:10]


def file_key(path):
    """Content hash of a file ('' if it does not exist)."""
    if not path or not os.path.exists(path):
        return ''
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:10]


def load(path):
    """defaults.toml < project.toml < project.local.toml (machine-specific paths, not committed)."""
    path = os.path.abspath(path)
    with open(DEFAULTS, 'rb') as f:
        merged = tomllib.load(f)
    local = os.path.splitext(path)[0] + '.local.toml'
    for p in (path, local):
        if os.path.exists(p):
            with open(p, 'rb') as f:
                merged = _merge(merged, tomllib.load(f))
    cfg = Config(_wrap(merged))
    dict.__setitem__(cfg, '_root', os.path.dirname(path))
    dict.__setitem__(cfg, '_file', path)
    return cfg
