# Figure Maker - Blender'siz islemler (exe icin): model.skin poligon azaltma + yazilim ile ikon cizimi
import os, struct, math
import numpy as np
from PIL import Image


# ------------------------------------------------------------------ model.skin okuma / yazma (sadece mesh bolumu degisir)

def _rs(b, o):
    n = struct.unpack_from('<i', b, o)[0]; return b[o + 4:o + 4 + n].decode('utf-8'), o + 4 + n


def _ws(s):
    e = s.encode('utf-8'); return struct.pack('<i', len(e)) + e


def read_meshes(path):
    """(on_kisim_baytlari, mesh listesi, arka_kisim_baytlari)"""
    b = open(path, 'rb').read()
    assert b[:5] in (b'SKIN1', b'SKIN2'), 'model.skin degil'
    o = 5 + 16
    nn = struct.unpack_from('<i', b, o)[0]; o += 4
    for _ in range(nn):
        _, o = _rs(b, o); o += 4 + 12 + 16 + 12
    ns = struct.unpack_from('<i', b, o)[0]; o += 4
    for _ in range(ns):
        jc = struct.unpack_from('<i', b, o)[0]; o += 4 + 4 * jc + 64 * jc
    pre = b[:o]
    nm = struct.unpack_from('<i', b, o)[0]; o += 4
    meshes = []
    for _ in range(nm):
        name, o = _rs(b, o); tex, o = _rs(b, o)
        clip, ds = b[o], b[o + 1]; o += 2
        sk = struct.unpack_from('<i', b, o)[0]; o += 4
        v = struct.unpack_from('<i', b, o)[0]; o += 4
        P = np.frombuffer(b, '<f4', v * 3, o).reshape(v, 3).copy(); o += 12 * v
        N = np.frombuffer(b, '<f4', v * 3, o).reshape(v, 3).copy(); o += 12 * v
        U = np.frombuffer(b, '<f4', v * 2, o).reshape(v, 2).copy(); o += 8 * v
        J = np.frombuffer(b, '<i4', v * 4, o).reshape(v, 4).copy(); o += 16 * v
        W = np.frombuffer(b, '<f4', v * 4, o).reshape(v, 4).copy(); o += 16 * v
        ic = struct.unpack_from('<i', b, o)[0]; o += 4
        I = np.frombuffer(b, '<i4', ic, o).copy(); o += 4 * ic
        meshes.append(dict(name=name, tex=tex, clip=clip, ds=ds, sk=sk, P=P, N=N, U=U, J=J, W=W, I=I))
    return pre, meshes, b[o:]


def write_meshes(path, pre, meshes, post):
    out = [pre, struct.pack('<i', len(meshes))]
    for m in meshes:
        out += [_ws(m['name']), _ws(m['tex']), bytes([m['clip'], m['ds']]), struct.pack('<i', m['sk']), struct.pack('<i', len(m['P'])),
                m['P'].astype('<f4').tobytes(), m['N'].astype('<f4').tobytes(), m['U'].astype('<f4').tobytes(),
                m['J'].astype('<i4').tobytes(), m['W'].astype('<f4').tobytes(), struct.pack('<i', len(m['I'])), m['I'].astype('<i4').tobytes()]
    out.append(post)
    open(path, 'wb').write(b''.join(out))


def _decimate_part(m, keep_ratio):
    """Tek parcayi azalt. UV dikislerindeki ayni konumlu vertexler kaynak yapilir (catlak acilmaz), sadelestirme
    o kaynakli mesh uzerinde yapilir; sonra her ucgenin her kosesine, ucgenin ait oldugu doku adasindan (bagli parca)
    UV / normal / agirlik geri verilir. Boylece ne dikis catlagi ne de baska adadan yanlis doku olur."""
    import fast_simplification
    from collections import Counter
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    P = m['P'].astype(np.float64); F = m['I'].reshape(-1, 3).astype(np.int64); n = len(P)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    isl = connected_components(coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)), directed=False)[1]
    span = float(np.ptp(P, 0).max()) or 1.0
    _, first, inv = np.unique(np.round(P / span * 1e6).astype(np.int64), axis=0, return_index=True, return_inverse=True)
    inv = np.asarray(inv).ravel(); Pw = P[first]; Fw = inv[F]
    Fw = Fw[(Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])]
    target = max(4, int(round(len(F) * keep_ratio)))
    if len(Fw) <= target: return False
    coll = fast_simplification.simplify(Pw, Fw, target_count=target, return_collapses=True)[2]
    if len(coll) == 0: return False
    P2, F2, mpw = fast_simplification.replay_simplification(Pw.astype(np.float32), Fw.astype(np.int32), coll)
    P2 = np.asarray(P2, np.float64); F2 = np.asarray(F2, np.int64); mpw = np.asarray(mpw, np.int64)
    jof = mpw[inv]                                        # orijinal vertex -> yeni vertex (-1: dustu)
    order = np.argsort(jof, kind='stable'); js = jof[order]
    lo = np.searchsorted(js, np.arange(len(P2))); hi = np.searchsorted(js, np.arange(len(P2)), side='right')
    dist = np.linalg.norm(P - P2[np.maximum(jof, 0)], axis=1)
    iorder = np.argsort(isl, kind='stable'); ilo = np.searchsorted(isl[iorder], np.arange(isl.max() + 1))
    ihi = np.searchsorted(isl[iorder], np.arange(isl.max() + 1), side='right')
    cache, trees = {}, {}
    def cands(j):
        c = cache.get(j)
        if c is None:
            ids = order[lo[j]:hi[j]]; c = {}
            for i in ids[np.argsort(dist[ids])]: c.setdefault(int(isl[i]), int(i))
            cache[j] = c
        return c
    def nearest_in(k, j):
        t = trees.get(k)
        if t is None:
            ids = iorder[ilo[k]:ihi[k]]; t = trees[k] = (cKDTree(P[ids]), ids)
        return int(t[1][t[0].query(P2[j])[1]])
    out, src, pos, tris = {}, [], [], []
    for tri in F2:
        cs = [cands(int(j)) for j in tri]
        cnt = Counter(k for c in cs for k in c)
        if not cnt: continue
        best = max(cnt.values()); k = min(x for x, v in cnt.items() if v == best)
        row = []
        for j, c in zip(tri, cs):
            i = c.get(k)
            if i is None: i = nearest_in(k, int(j))        # kose baska adanin vertexine coktu: bu adanin en yakin noktasi
            key = (int(j), i); x = out.get(key)
            if x is None: x = out[key] = len(src); src.append(i); pos.append(int(j))
            row.append(x)
        tris.append(row)
    src = np.array(src, np.int64)
    for kk in ('N', 'U', 'J', 'W'): m[kk] = m[kk][src]
    m['P'] = P2[np.array(pos, np.int64)].astype(np.float32)
    m['I'] = np.array(tris, np.int32).ravel()
    return True


def _merge_keys(path, meshes):
    """parca birlestirme anahtari: ayni doku / ayar ve ayni uzay. Iskeletli parcalar ayni skin'i, iskeletsiz (tek kemikli,
    birim bind) parcalar ayni dunya matrisini paylasiyorsa ve animasyonla oynatilmiyorsa birlesebilir."""
    import rd, gl
    d = rd.skin(path); nodes = d['nodes']
    loc = []
    for name, par, T, R, Sc in nodes:
        m = np.eye(4); m[:3, :3] = gl.q2m(np.array(R, float)) * np.array(Sc, float); m[:3, 3] = T; loc.append(m)
    W = [None] * len(nodes)
    def w(i):
        if W[i] is None: W[i] = loc[i] if nodes[i][1] < 0 else w(nodes[i][1]) @ loc[i]
        return W[i]
    animated = {n for c in d['clips'] for n, _, _ in c[3]}
    def moved(i):
        while i >= 0:
            if i in animated: return True
            i = nodes[i][1]
        return False
    keys = []
    for k, m in enumerate(meshes):
        J, B = d['skins'][m['sk']]
        if len(J) == 1 and np.allclose(B[0], np.eye(4), atol=1e-6) and not moved(J[0]):
            sp = ('rigid', tuple(np.round(w(J[0]), 5).ravel()))
        else:
            sp = ('skin', m['sk'])
        keys.append((m['tex'], m['clip'], m['ds']) + sp)
    return keys


def _merge_same(path, meshes):
    """ayni dokuyu / ayni uzayi kullanan parcalari tek mesh yap (kaynak modeller cogu zaman bir govdeyi 2-3 parcaya boler;
    parcalar ayri ayri azaltilinca aradaki sinirlarda delik acilir). FigureShop 32 bit indeks kullandigindan parca siniri gerekmez."""
    try: keys = _merge_keys(path, meshes)
    except Exception: return meshes
    groups, order = {}, []
    for k, m in zip(keys, meshes):
        if k not in groups: groups[k] = []; order.append(k)
        groups[k].append(m)
    out = []
    for k in order:
        g = groups[k]
        if len(g) == 1: out.append(g[0]); continue
        m = dict(g[0]); off = np.cumsum([0] + [len(x['P']) for x in g[:-1]])
        for kk in ('P', 'N', 'U', 'J', 'W'): m[kk] = np.concatenate([x[kk] for x in g])
        m['I'] = np.concatenate([x['I'] + o for x, o in zip(g, off)]).astype(np.int32)
        out.append(m)
    return out


def decimate_skin(path, budget):
    """ucgen butcesini asan model.skin'i azalt (kucuk parcalar oldugu gibi kalir).
    Eskiden azaltilan mesh'e konumca en yakin vertexin UV'si veriliyordu ve parcalar ayri ayri azaltiliyordu: UV dikislerinde
    oteki adanin dokusu secilip, parca sinirlarinda delik acilip figurlerde beyaz / koyu lekeler ve catlaklar cikiyordu.
    Simdi ayni dokulu parcalar birlestirilir, _decimate_part dikisleri kapali ve dogru tutar."""
    pre, meshes, post = read_meshes(path)
    tc = [len(m['I']) // 3 for m in meshes]; total = sum(tc)
    if total <= budget * 1.1: return total, total
    meshes = _merge_same(path, meshes)
    tc = [len(m['I']) // 3 for m in meshes]
    small = sum(t for t in tc if t < 3000)
    r = max(0.02, min(1.0, (budget - small) / max(1, total - small)))
    for m, t in zip(meshes, tc):
        if t >= 3000: _decimate_part(m, r)
    write_meshes(path, pre, meshes, post)
    return total, sum(len(m['I']) // 3 for m in meshes)


# ------------------------------------------------------------------ yazilim ikon cizici

def _tex(modeldir, name, cache):
    if name in cache: return cache[name]
    t = None
    p = os.path.join(modeldir, name) if name else None
    if p and os.path.exists(p):
        try: t = np.asarray(Image.open(p).convert('RGBA'), dtype=np.float32) / 255.0
        except Exception: t = None
    cache[name] = t
    return t


def render_icon(modeldir, out_png, yaw=25.0, size=256, ss=2, front=None, frame=0):
    """posed model.skin -> seffaf arka planli ikon (oyundaki ikonla ayni yon: on yuz -Z, hafif yandan ve yukaridan)"""
    import preview, rd
    d = rd.skin(os.path.join(modeldir, 'model.skin'))
    parts = preview.skin_pose(d, 0, frame)      # (name, tex, P, N, U, I) Unity koordinatlari; figure.json poseFrame
    allP = np.concatenate([p[2] for p in parts])
    lo, hi = allP.min(0), allP.max(0); ctr = (lo + hi) / 2; rad = np.linalg.norm(hi - lo) / 2
    yr, pr = math.radians(yaw), math.radians(12.0)
    if front is None: front = detect_front(modeldir, frame)[0]
    fa = math.atan2(front[0], front[1]) + yr   # on yonden yaw kadar yana
    fwd = np.array([math.sin(fa) * math.cos(pr), math.sin(pr), math.cos(fa) * math.cos(pr)])   # modelden kameraya
    cam = ctr + fwd * rad * 4.0
    zc = (ctr - cam); zc /= np.linalg.norm(zc)
    xc = np.cross([0, 1, 0], zc); xc /= np.linalg.norm(xc); yc = np.cross(zc, xc)
    R = np.stack([xc, yc, zc])
    S = size * ss
    def proj(P):
        q = (P - cam) @ R.T
        return q
    # kadraj: tum noktalar cercevenin %92'si
    q = proj(allP); f = 1.0
    sx, sy = q[:, 0] / q[:, 2], q[:, 1] / q[:, 2]
    span = max(sx.max() - sx.min(), sy.max() - sy.min()); cxo, cyo = (sx.max() + sx.min()) / 2, (sy.max() + sy.min()) / 2
    k = 0.92 * S / max(span, 1e-9)
    col = np.zeros((S, S, 3), np.float32); alpha = np.zeros((S, S), np.float32); zb = np.full((S, S), np.inf, np.float32)
    L = -zc + np.array([0.0, 0.6, 0.0]); L /= np.linalg.norm(L)
    cache = {}
    for name, tex, P, N, U, I in parts:
        if 'outline' in name.lower(): continue   # anime modellerin ters kabuk dis cizgisi: oyunda arka yuzu gizlenir, ikonda figuru siyaha boyar
        q = proj(P.astype(np.float64))
        X = (q[:, 0] / q[:, 2] - cxo) * k + S / 2; Y = S / 2 - (q[:, 1] / q[:, 2] - cyo) * k; Z = q[:, 2]
        Nn = N.astype(np.float64); Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
        sh = 0.42 + 0.58 * np.abs(Nn @ L)
        T = _tex(modeldir, tex, cache)
        tri = I.reshape(-1, 3)
        for a, b, c in tri:
            xa, xb, xc_ = X[a], X[b], X[c]; ya, yb, yc_ = Y[a], Y[b], Y[c]
            x0 = max(int(math.floor(min(xa, xb, xc_))), 0); x1 = min(int(math.ceil(max(xa, xb, xc_))), S - 1)
            y0 = max(int(math.floor(min(ya, yb, yc_))), 0); y1 = min(int(math.ceil(max(ya, yb, yc_))), S - 1)
            if x0 > x1 or y0 > y1: continue
            den = (yb - yc_) * (xa - xc_) + (xc_ - xb) * (ya - yc_)
            if abs(den) < 1e-12: continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((yb - yc_) * (gx - xc_) + (xc_ - xb) * (gy - yc_)) / den
            w1 = ((yc_ - ya) * (gx - xc_) + (xa - xc_) * (gy - yc_)) / den
            w2 = 1 - w0 - w1
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not m.any(): continue
            z = w0 * Z[a] + w1 * Z[b] + w2 * Z[c]
            sub = zb[y0:y1 + 1, x0:x1 + 1]
            m &= z < sub
            if not m.any(): continue
            s = w0 * sh[a] + w1 * sh[b] + w2 * sh[c]
            if T is not None:
                u = w0 * U[a, 0] + w1 * U[b, 0] + w2 * U[c, 0]; v = w0 * U[a, 1] + w1 * U[b, 1] + w2 * U[c, 1]
                th, tw = T.shape[:2]
                px = (np.mod(u, 1.0) * (tw - 1)).astype(np.int32); py = ((1.0 - np.mod(v, 1.0)) * (th - 1)).astype(np.int32)
                tc = T[py, px]
                m &= tc[..., 3] > 0.4
                if not m.any(): continue
                rgb = tc[..., :3]
            else:
                rgb = np.full(gx.shape + (3,), 0.8, np.float32)
            sub[m] = z[m]
            col[y0:y1 + 1, x0:x1 + 1][m] = (rgb * s[..., None])[m]
            alpha[y0:y1 + 1, x0:x1 + 1][m] = 1.0
    img = np.dstack([np.clip(col, 0, 1), alpha]) * 255
    Image.fromarray(img.astype(np.uint8), 'RGBA').resize((size, size), Image.LANCZOS).save(out_png)
    return True



# ------------------------------------------------------------------ figurun baktigi yon (ayak parmagi kemikleri / gozler)

def node_world(d, clip=0, frame=0):
    import gl
    nodes = d['nodes']; n = len(nodes)
    T = [np.array(x[2], float) for x in nodes]; Rq = [np.array(x[3], float) for x in nodes]; Sc = [np.array(x[4], float) for x in nodes]
    if d['clips']:
        name, fps, fr, ch = d['clips'][clip]
        for node, path, v in ch:
            val = v[min(frame, fr - 1)].astype(float)
            if path == 0: T[node] = val
            elif path == 1: Rq[node] = val / np.linalg.norm(val)
            else: Sc[node] = val
    W = [None] * n
    def w(i):
        if W[i] is None:
            m = np.eye(4); m[:3, :3] = gl.q2m(Rq[i]) * Sc[i]; m[:3, 3] = T[i]
            W[i] = m if nodes[i][1] < 0 else w(nodes[i][1]) @ m
        return W[i]
    off = np.eye(4); off[:3, 3] = [-d['cx'], -d['floor'], -d['cz']]
    sc = np.diag([d['scale']] * 3 + [1])
    return [(sc @ off @ w(i))[:3, 3] for i in range(n)]


def detect_front(modeldir, frame=0):
    """(fx, fz): figurun on yonu (model / oyun koordinatlari, XZ). Bulunamazsa (0, 1): iskeletsiz modellerin neredeyse
    hepsi (New Figure Pack'te 45/46) o yone bakiyor; eskiden (0, -1) idi ve figurler arkasi donuk cikiyordu"""
    import rd
    d = rd.skin(os.path.join(modeldir, 'model.skin'))
    names = [x[0].lower() for x in d['nodes']]; par = [x[1] for x in d['nodes']]
    pos = node_world(d, 0, frame)
    v = np.zeros(3); how = ''
    for i, nm in enumerate(names):
        if 'toe' in nm and 'end' not in nm and par[i] >= 0: v += pos[i] - pos[par[i]]
    if np.hypot(v[0], v[2]) > 1e-6: how = 'toe'
    else:
        head = next((i for i, nm in enumerate(names) if 'head' in nm and 'end' not in nm), None)
        eyes = [i for i, nm in enumerate(names) if 'eye' in nm and 'end' not in nm and 'brow' not in nm and 'lid' not in nm]
        if head is not None and eyes:
            v = np.mean([pos[i] for i in eyes], 0) - pos[head]; how = 'eye'
    l = np.hypot(v[0], v[2])
    if l < 1e-6: return (0.0, 1.0), 'default'
    return (float(v[0] / l), float(v[2] / l)), how


def rotation_for(front):
    """oyunda musteriye baktirmak icin RotationY (derece): FigureShop'ta on yuz -Z"""
    fx, fz = front
    a = math.degrees(math.atan2(fx, -fz))
    return float(round(a / 5.0) * 5.0) % 360.0
