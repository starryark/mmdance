"""Minimal VMD (MikuMikuDance motion) parser."""
import struct, collections

def _s(b):
    b = b.split(b'\0', 1)[0]
    try:
        return b.decode('shift_jis')
    except UnicodeDecodeError:
        return b.decode('shift_jis', errors='replace')

def read_vmd(path):
    with open(path, 'rb') as f:
        data = f.read()
    off = 0
    header = data[off:off+30]; off += 30
    model = _s(data[off:off+20]); off += 20
    n, = struct.unpack_from('<I', data, off); off += 4
    bones = []
    for _ in range(n):
        name = _s(data[off:off+15]); off += 15
        frame, = struct.unpack_from('<I', data, off); off += 4
        loc = struct.unpack_from('<3f', data, off); off += 12
        rot = struct.unpack_from('<4f', data, off); off += 16  # x y z w
        interp = data[off:off+64]; off += 64
        bones.append((name, frame, loc, rot, interp))
    morphs = []
    if off < len(data):
        n, = struct.unpack_from('<I', data, off); off += 4
        for _ in range(n):
            name = _s(data[off:off+15]); off += 15
            frame, w = struct.unpack_from('<If', data, off); off += 8
            morphs.append((name, frame, w))
    cams = []
    if off < len(data):
        n, = struct.unpack_from('<I', data, off); off += 4
        for _ in range(n):
            frame, dist = struct.unpack_from('<If', data, off); off += 8
            pos = struct.unpack_from('<3f', data, off); off += 12
            rot = struct.unpack_from('<3f', data, off); off += 12
            interp = data[off:off+24]; off += 24
            fov, persp = struct.unpack_from('<IB', data, off); off += 5
            cams.append((frame, dist, pos, rot, interp, fov, persp))
    return dict(header=header, model=model, bones=bones, morphs=morphs, cams=cams)

if __name__ == '__main__':
    import sys; sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        v = read_vmd(p)
        print('==', p, 'model:', v['model'])
        bc = collections.Counter(b[0] for b in v['bones'])
        bf = [b[1] for b in v['bones']]
        print(' bone keys', len(v['bones']), 'bones', len(bc), 'frames', (min(bf), max(bf)) if bf else None)
        for k, c in bc.most_common():
            fr = [b[1] for b in v['bones'] if b[0] == k]
            nonzero_loc = any(any(abs(x) > 1e-4 for x in b[2]) for b in v['bones'] if b[0] == k)
            print('   ', repr(k), c, 'frames', min(fr), max(fr), 'LOC' if nonzero_loc else '')
        mc = collections.Counter(m[0] for m in v['morphs'])
        mf = [m[1] for m in v['morphs']]
        print(' morph keys', len(v['morphs']), 'frames', (min(mf), max(mf)) if mf else None)
        for k, c in mc.most_common():
            # a capture-made facial track can be wrong (a squint read as closed eyes): show the values
            w = [m[2] for m in v['morphs'] if m[0] == k]
            print('   ', repr(k), c, 'weight %.2f..%.2f, above 0.5 on %d%% of keys'
                  % (min(w), max(w), round(100 * sum(x > 0.5 for x in w) / len(w))))
        if v['cams']:
            cf = [c[0] for c in v['cams']]
            print(' cam keys', len(v['cams']), 'frames', min(cf), max(cf))
