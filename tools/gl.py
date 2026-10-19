import json, zipfile, struct, numpy as np, posixpath
CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

class G:
    def __init__(self, zpath):
        self.z = zipfile.ZipFile(zpath)
        names = self.z.namelist()
        gl = [n for n in names if n.lower().endswith('.gltf')]
        if gl:
            self.base = posixpath.dirname(gl[0])
            self.j = json.loads(self.z.read(gl[0]).decode('utf-8'))
            self.bufs = []
            for b in self.j.get('buffers', []):
                self.bufs.append(self.z.read(posixpath.join(self.base, b['uri']) if self.base else b['uri']))
        else:
            glb = [n for n in names if n.lower().endswith('.glb')][0]
            data = self.z.read(glb); self.base = ''
            ln = struct.unpack_from('<I', data, 12)[0]
            self.j = json.loads(data[20:20 + ln])
            o = 20 + ln
            bl = struct.unpack_from('<I', data, o)[0]
            self.bufs = [data[o + 8:o + 8 + bl]]
        self.license = ''
        for n in names:
            if n.lower().endswith('license.txt'):
                self.license = self.z.read(n).decode('utf-8', 'ignore')

    def acc(self, i):
        a = self.j['accessors'][i]
        n = NC[a['type']]; dt = CT[a['componentType']]; cnt = a['count']
        if 'bufferView' in a:
            bv = self.j['bufferViews'][a['bufferView']]
            buf = self.bufs[bv.get('buffer', 0)]
            off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
            isz = np.dtype(dt).itemsize
            stride = bv.get('byteStride', 0) or n * isz
            if stride == n * isz:
                arr = np.frombuffer(buf, dt, cnt * n, off).reshape(cnt, n).copy()
            else:
                raw = np.frombuffer(buf, np.uint8, stride * (cnt - 1) + n * isz, off)
                arr = np.lib.stride_tricks.as_strided(raw, (cnt, n * isz), (stride, 1)).copy().view(dt).reshape(cnt, n)
        else:
            arr = np.zeros((cnt, n), dt)
        if 'sparse' in a:
            sp = a['sparse']
            ib = self.j['bufferViews'][sp['indices']['bufferView']]
            idx = np.frombuffer(self.bufs[ib.get('buffer', 0)], CT[sp['indices']['componentType']], sp['count'], ib.get('byteOffset', 0) + sp['indices'].get('byteOffset', 0))
            vb = self.j['bufferViews'][sp['values']['bufferView']]
            val = np.frombuffer(self.bufs[vb.get('buffer', 0)], dt, sp['count'] * n, vb.get('byteOffset', 0) + sp['values'].get('byteOffset', 0)).reshape(-1, n)
            arr = arr.copy(); arr[idx] = val
        if a.get('normalized') and dt != np.float32:
            arr = arr.astype(np.float32) / np.iinfo(dt).max
        return arr

    def image_bytes(self, ti):
        tex = self.j['textures'][ti]
        src = tex.get('source')
        if src is None:
            for k, v in tex.get('extensions', {}).items():
                if 'source' in v: src = v['source']
        img = self.j['images'][src]
        if 'uri' in img:
            from urllib.parse import unquote
            p = unquote(img['uri']); p = posixpath.join(self.base, p) if self.base else p
            return self.z.read(p), img.get('name') or posixpath.basename(p)
        bv = self.j['bufferViews'][img['bufferView']]
        return self.bufs[bv.get('buffer', 0)][bv.get('byteOffset', 0):bv.get('byteOffset', 0) + bv['byteLength']], img.get('name', 'img%d' % src)

def q2m(q):
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def m2trs(m):
    t = m[:3, 3].copy()
    r = m[:3, :3].copy()
    s = np.linalg.norm(r, axis=0)
    if np.linalg.det(r) < 0: s[0] = -s[0]
    r = r / s
    # quaternion from rotation matrix
    tr = np.trace(r)
    if tr > 0:
        S = np.sqrt(tr + 1.0) * 2; w = 0.25 * S; x = (r[2,1]-r[1,2]) / S; y = (r[0,2]-r[2,0]) / S; z = (r[1,0]-r[0,1]) / S
    elif r[0,0] > r[1,1] and r[0,0] > r[2,2]:
        S = np.sqrt(1.0 + r[0,0] - r[1,1] - r[2,2]) * 2; w = (r[2,1]-r[1,2]) / S; x = 0.25 * S; y = (r[0,1]+r[1,0]) / S; z = (r[0,2]+r[2,0]) / S
    elif r[1,1] > r[2,2]:
        S = np.sqrt(1.0 + r[1,1] - r[0,0] - r[2,2]) * 2; w = (r[0,2]-r[2,0]) / S; x = (r[0,1]+r[1,0]) / S; y = 0.25 * S; z = (r[1,2]+r[2,1]) / S
    else:
        S = np.sqrt(1.0 + r[2,2] - r[0,0] - r[1,1]) * 2; w = (r[1,0]-r[0,1]) / S; x = (r[0,2]+r[2,0]) / S; y = (r[1,2]+r[2,1]) / S; z = 0.25 * S
    q = np.array([x, y, z, w]); q /= np.linalg.norm(q)
    return t, q, s

def node_local(n):
    if 'matrix' in n:
        return np.array(n['matrix'], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    t = n.get('translation', [0, 0, 0]); r = n.get('rotation', [0, 0, 0, 1]); s = n.get('scale', [1, 1, 1])
    m[:3, :3] = q2m(r) * np.array(s)
    m[:3, 3] = t
    return m

def trs(n):
    if 'matrix' in n:
        return m2trs(node_local(n))
    return np.array(n.get('translation', [0, 0, 0]), float), np.array(n.get('rotation', [0, 0, 0, 1]), float), np.array(n.get('scale', [1, 1, 1]), float)

def parents(j):
    p = [-1] * len(j.get('nodes', []))
    for i, n in enumerate(j.get('nodes', [])):
        for c in n.get('children', []): p[c] = i
    return p

def world_mats(j, locals_=None):
    nodes = j['nodes']; par = parents(j)
    loc = locals_ if locals_ is not None else [node_local(n) for n in nodes]
    W = [None] * len(nodes)
    def w(i):
        if W[i] is None:
            W[i] = loc[i] if par[i] < 0 else w(par[i]) @ loc[i]
        return W[i]
    for i in range(len(nodes)): w(i)
    return W

def scene_nodes(j):
    sc = j.get('scenes', [{}])[j.get('scene', 0)] if j.get('scenes') else {'nodes': [i for i, p in enumerate(parents(j)) if p < 0]}
    out = []
    st = list(sc.get('nodes', []))
    while st:
        i = st.pop(); out.append(i); st.extend(j['nodes'][i].get('children', []))
    return out
