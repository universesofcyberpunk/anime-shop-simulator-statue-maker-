# glTF/GLB (zip veya dosya) -> model.statue (STAT2, sabit) ya da model.skin (SKIN2, animasyonlu, GameStatuePack sablonu)
import sys, os, io, json, struct, re, zipfile, posixpath
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
import gl

FLIP = np.diag([-1.0, 1, 1, 1])


class Src(gl.G):
    """gl.G ama dosya yolundan da (glb/gltf) okuyabilir"""
    def __init__(self, path, exclude=None):
        """exclude: heykele alinmayacak parcalar (materyal sirasi, materyalsiz = -1); None -> otomatik (gorunmeyen / efekt)"""
        if path.lower().endswith('.zip'):
            super().__init__(path)
        else:
            self._load(path)
        self._prims = [list(me['primitives']) for me in self.j.get('meshes', [])]   # set_exclude hep bunlardan baslar
        self.auto_exclude = invisible_parts(self.j)
        self.set_exclude(self.auto_exclude if exclude is None else exclude)
        self.merged = merge_split_clips(self.j)

    def set_exclude(self, keys):
        """parcalari ac / kapat (on izlemede tikla kapat); kapali parca ne cizilir ne boya / ortalamaya girer"""
        keys = {int(k) for k in keys}
        for me, prs in zip(self.j.get('meshes', []), self._prims):
            me['primitives'] = [pr for pr in prs if part_key(pr) not in keys]
        self.exclude = keys
        mats = self.j.get('materials', [])
        self.dropped = [mat_name(mats, k) for k in sorted(keys)]

    def _load(self, path):
        d = os.path.dirname(path)
        self.license = ''
        lp = os.path.join(d, 'license.txt')
        if os.path.exists(lp): self.license = open(lp, encoding='utf-8', errors='ignore').read()
        data = open(path, 'rb').read()
        self.z = None; self.base = d
        if path.lower().endswith('.glb'):
            ln = struct.unpack_from('<I', data, 12)[0]
            self.j = json.loads(data[20:20 + ln])
            o = 20 + ln
            bl = struct.unpack_from('<I', data, o)[0]
            self.bufs = [data[o + 8:o + 8 + bl]]
        else:
            self.j = json.loads(data.decode('utf-8'))
            self.bufs = [open(os.path.join(d, b['uri']), 'rb').read() for b in self.j.get('buffers', [])]

    def image_bytes(self, ti):
        if self.z is not None: return super().image_bytes(ti)
        tex = self.j['textures'][ti]
        src = tex.get('source')
        if src is None:
            for k, v in tex.get('extensions', {}).items():
                if 'source' in v: src = v['source']
        img = self.j['images'][src]
        if 'uri' in img:
            from urllib.parse import unquote
            p = os.path.join(self.base, unquote(img['uri']))
            return open(p, 'rb').read(), img.get('name') or os.path.basename(p)
        bv = self.j['bufferViews'][img['bufferView']]
        o = bv.get('byteOffset', 0)
        return self.bufs[bv.get('buffer', 0)][o:o + bv['byteLength']], img.get('name', 'img%d' % src)


def _mat_alpha(m):
    """(gorunur mu, dokulu mu): BLEND/MASK materyalin ana renk alfasi"""
    pb = m.get('pbrMetallicRoughness', {}); sg = m.get('extensions', {}).get('KHR_materials_pbrSpecularGlossiness')
    bc = (sg.get('diffuseFactor') if sg else pb.get('baseColorFactor')) or [1, 1, 1, 1]
    textured = (sg.get('diffuseTexture') if sg else pb.get('baseColorTexture')) is not None
    return float(bc[3]) if len(bc) > 3 else 1.0, textured


def part_key(pr):
    m = pr.get('material'); return -1 if m is None else int(m)


def mat_name(mats, k):
    return 'default' if k < 0 or k >= len(mats) else (mats[k].get('name') or 'mat%d' % k)


def invisible_parts(j):
    """otomatik kapatilan parcalar (sinirlari / boyu bozmasinlar): saydam modda ana renk alfasi ~0 olanlar ve dokusu kaybolmus
    efekt kartlari (dokusuz BLEND: alfa < 0.5 ya da varsayilan 0.8 gri; or. oyun modellerindeki lobi isik halkalari, nota isaretleri).
    Her sey saydamsa bos kume (model bos kalmasin)."""
    mats = j.get('materials', []); bad = set()
    for mi, m in enumerate(mats):
        am = m.get('alphaMode', 'OPAQUE')
        if am == 'OPAQUE' or 'KHR_materials_transmission' in m.get('extensions', {}): continue
        a, textured = _mat_alpha(m)
        bc = (m.get('pbrMetallicRoughness', {}).get('baseColorFactor') or [1, 1, 1, 1])[:3]
        lost = not textured and all(abs(float(v) - 0.8) < 0.01 for v in bc)    # 0.8 gri: dokusu kaybolmus (Blender varsayilani)
        if a < 0.02 or (am == 'MASK' and a < float(m.get('alphaCutoff', 0.5))) or (am == 'BLEND' and not textured and (a < 0.5 or lost)):
            bad.add(mi)
    used = {part_key(pr) for me in j.get('meshes', []) for pr in me['primitives'] if pr.get('mode', 4) == 4}
    if not (used - bad): return set()
    return bad & used


def parts_info(g):
    """formdaki parca listesi: materyal basina [key, ad, ucgen, otomatik kapali mi, uzak mi]. Uzak: dinlenme pozunda en buyuk
    gorunur parcanin (govde) kutusuna (yarisi kadar genisletilmis) hic degmeyen parca (arka plan levhasi, kopuk efekt) - sadece isaret."""
    keep = set(g.exclude); g.set_exclude(set())
    try:
        tris, box = {}, {}
        for (mi, P, N, U, I) in posed_geometry(g, [gl.node_local(n) for n in g.j.get('nodes', [])]):
            k = -1 if mi is None else int(mi)
            tris[k] = tris.get(k, 0) + len(I) // 3
            lo, hi = P.min(0), P.max(0)
            if k in box: lo, hi = np.minimum(lo, box[k][0]), np.maximum(hi, box[k][1])
            box[k] = (lo, hi)
    finally:
        g.set_exclude(keep)
    vis = [k for k in tris if k not in g.auto_exclude] or list(tris)
    main = max(vis, key=lambda k: tris[k])
    lo, hi = box[main]; pad = 0.5 * float((hi - lo).max())
    lo, hi = lo - pad, hi + pad
    mats = g.j.get('materials', []); res = []
    for k in sorted(tris, key=lambda k: -tris[k]):
        a, b = box[k]
        far = bool(np.any(b < lo) or np.any(a > hi))
        res.append([k, mat_name(mats, k), tris[k], k in g.auto_exclude, far])
    return res


def merge_split_clips(j):
    """Sketchfab / Unity ciktilarinda bir animasyon kemik kemik bolunur: "Govde|Come|Base Layer", "Bone_Bow01|Come|Base Layer" ...
    Ayni ortadaki ada sahip parcalari tek animasyonda birlestirir (yoksa secilmeyen parcalar - silah, sac - dinlenme pozunda kalir).
    Birlestirilen animasyon adlari doner."""
    anims = j.get('animations', [])
    groups = {}
    for k, an in enumerate(anims):
        parts = (an.get('name') or '').split('|')
        if len(parts) < 3: return []
        groups.setdefault('|'.join(parts[1:-1]), []).append(k)
    if len(groups) == len(anims): return []
    new = []
    for name, ks in groups.items():
        samplers, channels = [], []
        for k in ks:
            an = anims[k]; o = len(samplers)
            samplers += an['samplers']
            for ch in an['channels']:
                c = dict(ch); c['sampler'] = ch['sampler'] + o; channels.append(c)
        new.append({'name': name, 'samplers': samplers, 'channels': channels})
    j['animations'] = new
    return [n for n, ks in groups.items() if len(ks) > 1]


def safe(s):
    s = re.sub(r'[^A-Za-z0-9_.-]+', '_', s or 'tex').strip('_')
    return s[:40] or 'tex'


# ------------------------------------------------------------------ materials / textures

class TexOut:
    def __init__(self, g, outdir, maxsize, skin_mode):
        self.g, self.out, self.max, self.skin_mode = g, outdir, maxsize, skin_mode
        self.cache = {}; self.names = set(); self.bytes = 0

    def _name(self, base, ext):
        base = safe(os.path.splitext(base)[0]); n = base + ext; i = 1
        while n.lower() in self.names: n = '%s_%d%s' % (base, i, ext); i += 1
        self.names.add(n.lower()); return n

    def save(self, ti, factor=(1, 1, 1, 1), need_alpha=False, emissive=False):
        key = (ti, tuple(np.round(factor, 3)), need_alpha, emissive)
        if key in self.cache: return self.cache[key]
        data, nm = self.g.image_bytes(ti)
        im = Image.open(io.BytesIO(data)); im.load()
        im = im.convert('RGBA')
        if max(im.size) > self.max:
            s = self.max / max(im.size)
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
        f = np.array(factor, float)
        if np.any(np.abs(f - 1) > 1e-3):
            a = np.asarray(im).astype(np.float32) * f[None, None, :4] if len(f) == 4 else np.asarray(im).astype(np.float32) * np.r_[f, 1][None, None]
            im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), 'RGBA')
        if need_alpha and np.asarray(im)[..., 3].min() < 250:
            n = self._name(nm, '.png'); im.save(os.path.join(self.out, n), optimize=True)
        else:
            n = self._name(nm, '.jpg'); im.convert('RGB').save(os.path.join(self.out, n), quality=92)
        self.bytes += os.path.getsize(os.path.join(self.out, n))
        self.cache[key] = n
        return n

    def color(self, rgba):
        c = '%02x%02x%02x' % tuple(int(round(max(0, min(1, v)) * 255)) for v in rgba[:3])
        n = 'color_%s.png' % c
        if n.lower() not in self.names:
            self.names.add(n.lower())
            Image.new('RGB', (4, 4), tuple(int(round(max(0, min(1, v)) * 255)) for v in rgba[:3])).save(os.path.join(self.out, n))
        return n


def material(g, mi, tex, opts):
    """-> dict(name, texture, alpha(0/1/2), ds, basecolor(4), emtex, emissive(3), metallic, smoothness)"""
    j = g.j
    if mi is None:
        return dict(name='default', texture='', alpha=0, ds=False, bc=[0.8, 0.8, 0.8, 1], emtex='', em=[0, 0, 0], met=0.0, sm=0.3)
    m = j['materials'][mi]
    ext = m.get('extensions', {})
    pb = m.get('pbrMetallicRoughness', {})
    sg = ext.get('KHR_materials_pbrSpecularGlossiness')
    if sg:
        bc = list(sg.get('diffuseFactor', [1, 1, 1, 1])); bt = sg.get('diffuseTexture')
        met = 0.0; sm = float(sg.get('glossinessFactor', 1.0)) * 0.5
    else:
        bc = list(pb.get('baseColorFactor', [1, 1, 1, 1])); bt = pb.get('baseColorTexture')
        met = float(pb.get('metallicFactor', 1.0)); rough = float(pb.get('roughnessFactor', 1.0))
        if 'metallicRoughnessTexture' in pb: met *= 0.3; rough = max(rough, 0.6)
        sm = max(0.0, min(0.6, 1.0 - rough))
        met = min(met, 0.6)
    if 'KHR_materials_unlit' in ext: met, sm = 0.0, 0.1
    am = m.get('alphaMode', 'OPAQUE')
    alpha = {'OPAQUE': 0, 'MASK': 1, 'BLEND': 2}.get(am, 0)
    if 'KHR_materials_transmission' in ext and alpha == 0 and bc[3] > 0.99: pass
    ds = bool(m.get('doubleSided', False))
    # "isiksiz" modeller (Sketchfab taramalari / pisirilmis modeller): ana renk siyah, butun renk emissive dokusunda.
    # Oyun emissive'i figurde kullanmadigi icin figur simsiyah cikiyordu: o dokuyu ana renk say.
    emf = list(m.get('emissiveFactor', [0, 0, 0]))
    if bt is None and 'emissiveTexture' in m and max(bc[:3]) < 0.05 and max(emf) > 0.01:
        bt = m['emissiveTexture']; bc = [min(1.0, float(v)) for v in emf] + [bc[3]]
        met, sm = 0.0, 0.1
    texname = ''
    if bt is not None and 'index' in bt:
        try:
            if opts['skin']:
                texname = tex.save(bt['index'], bc, need_alpha=alpha != 0)
                bc = [1, 1, 1, bc[3]]
            else:
                texname = tex.save(bt['index'], (1, 1, 1, 1), need_alpha=alpha != 0)
        except Exception as e:
            print('  ! texture', e); texname = ''
    if not texname and opts['skin']:
        texname = tex.color(bc)
    em = list(m.get('emissiveFactor', [0, 0, 0]))
    es = ext.get('KHR_materials_emissive_strength', {}).get('emissiveStrength', 1.0)
    em = [min(4.0, v * es) for v in em]
    emtex = ''
    if sum(em) > 0.01 and 'emissiveTexture' in m and not opts['skin']:
        try: emtex = tex.save(m['emissiveTexture']['index'])
        except Exception as e: print('  ! emissive', e)
    # BLEND -> STAT2: gercek saydamlik yalnizca cok saydamsa; aksi halde kesik (cutout)
    # opts['blend']: manifestte "blend": true olan heykel (alev, hologram gibi): BLEND gercek yari saydam kalir (SKIN2'de 3)
    if alpha == 2 and opts.get('blend'):
        alpha = 3 if opts['skin'] else 2
    elif alpha == 2 and texname and not opts['skin']:
        alpha = 2 if bc[3] < 0.95 else 1
    return dict(name=m.get('name') or 'mat%d' % mi, texture=texname, alpha=alpha, ds=ds, bc=bc, emtex=emtex, em=em, met=met, sm=sm)


def uv_transform(g, mi, uv):
    if mi is None: return uv
    m = g.j['materials'][mi]
    pb = m.get('pbrMetallicRoughness', {}); sg = m.get('extensions', {}).get('KHR_materials_pbrSpecularGlossiness', {})
    bt = pb.get('baseColorTexture') or sg.get('diffuseTexture') or {}
    tt = bt.get('extensions', {}).get('KHR_texture_transform')
    if not tt: return uv
    o = np.array(tt.get('offset', [0, 0])); s = np.array(tt.get('scale', [1, 1])); r = tt.get('rotation', 0.0)
    c, sn = np.cos(r), np.sin(r)
    x = uv[:, 0] * s[0]; y = uv[:, 1] * s[1]
    return np.c_[c * x + sn * y + o[0], -sn * x + c * y + o[1]]


def uvset(g, mi):
    if mi is None: return 0
    m = g.j['materials'][mi]
    pb = m.get('pbrMetallicRoughness', {}); sg = m.get('extensions', {}).get('KHR_materials_pbrSpecularGlossiness', {})
    bt = pb.get('baseColorTexture') or sg.get('diffuseTexture') or {}
    return bt.get('texCoord', 0)


def prim_data(g, pr, mi):
    a = pr['attributes']
    P = g.acc(a['POSITION']).astype(np.float64)
    N = g.acc(a['NORMAL']).astype(np.float64) if 'NORMAL' in a else None
    ts = uvset(g, mi)
    key = 'TEXCOORD_%d' % ts if 'TEXCOORD_%d' % ts in a else 'TEXCOORD_0'
    U = g.acc(a[key]).astype(np.float64) if key in a else np.zeros((len(P), 2))
    U = uv_transform(g, mi, U)
    I = g.acc(pr['indices']).ravel().astype(np.int64) if 'indices' in pr else np.arange(len(P))
    I = I[:len(I) // 3 * 3]
    return P, N, U, I


def calc_normals(P, I):
    N = np.zeros_like(P)
    t = I.reshape(-1, 3)
    fn = np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]])
    for k in range(3): np.add.at(N, t[:, k], fn)
    l = np.linalg.norm(N, axis=1, keepdims=True); l[l == 0] = 1
    return N / l


def joints_weights(g, pr):
    a = pr['attributes']
    Js, Ws = [], []
    k = 0
    while 'JOINTS_%d' % k in a:
        Js.append(g.acc(a['JOINTS_%d' % k]).astype(np.int64)); Ws.append(g.acc(a['WEIGHTS_%d' % k]).astype(np.float64)); k += 1
    J = np.concatenate(Js, 1); W = np.concatenate(Ws, 1)
    if J.shape[1] > 4:
        o = np.argsort(-W, 1)[:, :4]
        J = np.take_along_axis(J, o, 1); W = np.take_along_axis(W, o, 1)
    s = W.sum(1, keepdims=True); s[s == 0] = 1
    return J, W / s


# ------------------------------------------------------------------ animation sampling

def quat_norm(q):
    l = np.linalg.norm(q, axis=-1, keepdims=True); l[l == 0] = 1; return q / l


def sample(g, sampler, path, times):
    inp = g.acc(sampler['input']).ravel().astype(np.float64)
    out = g.acc(sampler['output']).astype(np.float64)
    interp = sampler.get('interpolation', 'LINEAR')
    if interp == 'CUBICSPLINE':
        out = out.reshape(len(inp), 3, -1)[:, 1, :]
    out = out.reshape(len(inp), -1)
    if len(inp) == 1: return np.repeat(out[:1], len(times), 0)
    idx = np.clip(np.searchsorted(inp, times, 'right') - 1, 0, len(inp) - 2)
    t0, t1 = inp[idx], inp[idx + 1]
    a = np.clip((times - t0) / np.maximum(t1 - t0, 1e-9), 0, 1)[:, None]
    if interp == 'STEP': a = (times[:, None] >= t1[:, None]).astype(float)
    v0, v1 = out[idx], out[idx + 1]
    if path == 'rotation':
        d = (v0 * v1).sum(1, keepdims=True); v1 = np.where(d < 0, -v1, v1)
        return quat_norm(v0 + (v1 - v0) * a)
    return v0 + (v1 - v0) * a


def anim_range(g, an):
    mn, mx = 1e9, 0.0
    for s in an['samplers']:
        a = g.j['accessors'][s['input']]
        mn = min(mn, float(a['min'][0])); mx = max(mx, float(a['max'][0]))
    return mn, mx


def clip_frames(g, an, fps=30.0):
    """(baslangic zamani, kare sayisi): model.skin'e yazilan kareler; kare k = baslangic + k / fps"""
    mn, mx = anim_range(g, an)
    dur = max(mx - mn, 1.0 / fps)
    return mn, max(1, int(round(dur * fps)))


def node_locals_at(g, an, t, base_trs):
    """base_trs: list of (T,R,S) rest; returns list of local 4x4 at time t"""
    trs = [list(x) for x in base_trs]
    if an is not None:
        for ch in an['channels']:
            n = ch['target'].get('node'); p = ch['target']['path']
            if n is None or p == 'weights': continue
            v = sample(g, an['samplers'][ch['sampler']], p, np.array([t]))[0]
            trs[n][{'translation': 0, 'rotation': 1, 'scale': 2}[p]] = v
    out = []
    for T, R, S in trs:
        m = np.eye(4); m[:3, :3] = gl.q2m(R) * S; m[:3, 3] = T; out.append(m)
    return out


# ------------------------------------------------------------------ geometry collection

def posed_geometry(g, locals_):
    """world-space (glTF coords) geometry per primitive, rest/posed"""
    j = g.j
    W = gl.world_mats(j, locals_)
    res = []; g.vcol = []
    for i in gl.scene_nodes(j):
        n = j['nodes'][i]
        if 'mesh' not in n: continue
        for pr in j['meshes'][n['mesh']]['primitives']:
            if pr.get('mode', 4) != 4: continue
            mi = pr.get('material')
            P, N, U, I = prim_data(g, pr, mi)
            if N is None: N = calc_normals(P, I)
            if 'skin' in n and 'JOINTS_0' in pr['attributes']:
                sk = j['skins'][n['skin']]
                ib = g.acc(sk['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1) if 'inverseBindMatrices' in sk else np.tile(np.eye(4), (len(sk['joints']), 1, 1))
                M = np.stack([W[jn] @ ib[k] for k, jn in enumerate(sk['joints'])])
                J, Wt = joints_weights(g, pr)
                Mv = np.einsum('vk,vkij->vij', Wt, M[J])
                P = np.einsum('vij,vj->vi', Mv[:, :3, :3], P) + Mv[:, :3, 3]
                N = np.einsum('vij,vj->vi', Mv[:, :3, :3], N)
            else:
                M = W[i]
                P = P @ M[:3, :3].T + M[:3, 3]
                nm = np.linalg.inv(M[:3, :3]).T
                N = N @ nm.T
            l = np.linalg.norm(N, axis=1, keepdims=True); l[l == 0] = 1; N = N / l
            if np.linalg.det(M[:3, :3] if M.ndim == 2 else np.eye(3)) < 0: I = I.reshape(-1, 3)[:, ::-1].ravel()
            res.append((mi, P, N, U, I)); g.vcol.append(vertex_colors(g, pr))
    return res


def vertex_colors(g, pr):
    """COLOR_0 -> (n,4) lineer 0..1 ya da None"""
    if 'COLOR_0' not in pr['attributes']: return None
    ai = pr['attributes']['COLOR_0']; a = g.j['accessors'][ai]
    C = g.acc(ai).astype(np.float64)
    ct = a['componentType']
    if ct == 5121: C /= 255.0
    elif ct == 5123: C /= 65535.0
    if C.shape[1] == 3: C = np.c_[C, np.ones(len(C))]
    return np.clip(C, 0, 1)


def bake_vcol(tex, base, P, N, C, I, bc):
    """kose renkli (dokusuz) parca: her ucgen kendi 4x4 dokusel blogunda duz renk; ucgenler ayrilir.
    Oyunun shader'i kose rengini kullanmadigi icin renk boyle dokuya tasinir."""
    t = I.reshape(-1, 3); nt = len(t)
    col = C[t].mean(1)[:, :3] * np.array(bc[:3])[None]
    srgb = np.where(col <= 0.0031308, col * 12.92, 1.055 * np.power(np.clip(col, 0, 1), 1 / 2.4) - 0.055)
    S = 64
    while (S // 4) ** 2 < nt: S *= 2
    nb = S // 4
    img = np.full((S, S, 3), 255, np.uint8)
    k = np.arange(nt); bx, by = k % nb, k // nb
    blk = np.clip(np.round(srgb * 255), 0, 255).astype(np.uint8)
    v = img.reshape(nb, 4, nb, 4, 3)
    v[by, :, bx, :, :] = blk[:, None, None, :]
    # write_stat2 v'yi ters cevirir (1-v); goruntu satiri y=0 ustte
    u = np.c_[(bx * 4 + 2) / S, (by * 4 + 2) / S]
    U = np.repeat(u, 3, axis=0)
    n = tex._name(base + '_vcol', '.png')
    Image.fromarray(img, 'RGB').save(os.path.join(tex.out, n), optimize=True)
    tex.bytes += os.path.getsize(os.path.join(tex.out, n))
    idx = t.ravel()
    return n, P[idx], N[idx], U, np.arange(len(idx))


def rest_trs(g):
    return [gl.trs(n) for n in g.j.get('nodes', [])]


# ------------------------------------------------------------------ STAT2

def wstr(f, s):
    b = s.encode('utf-8'); f.write(struct.pack('<i', len(b))); f.write(b)


def write_stat2(path, parts):
    with open(path, 'wb') as f:
        f.write(b'STAT2'); f.write(struct.pack('<i', len(parts)))
        for p in parts:
            m = p['mat']
            wstr(f, m['name']); wstr(f, m['texture'])
            f.write(bytes([m['alpha'], 1 if m['ds'] else 0]))
            f.write(struct.pack('<4f', *m['bc'])); wstr(f, m['emtex'])
            f.write(struct.pack('<3f', *m['em'])); f.write(struct.pack('<2f', m['met'], m['sm']))
            P, N, U, I = p['P'], p['N'], p['U'], p['I']
            f.write(struct.pack('<i', len(P)))
            f.write(P.astype('<f4').tobytes()); f.write(N.astype('<f4').tobytes())
            f.write(np.c_[U[:, 0], 1 - U[:, 1]].astype('<f4').tobytes())
            f.write(struct.pack('<i', len(I))); f.write(I.astype('<i4').tobytes())


def to_unity(P, N, I):
    P = P.copy(); N = N.copy(); P[:, 0] *= -1; N[:, 0] *= -1
    I = I.reshape(-1, 3)[:, [0, 2, 1]].ravel()
    return P, N, I


def convert_static(src, outdir, height=None, size=None, maxtex=2048, clip=None, clip_time=0.0, upright=False, part_colors=None, blend=False, drop_parts=None, up='Y', exclude=None):
    g = Src(src, exclude)
    apply_up(g.j, up)   # Statue Maker: modelin yukari ekseni / on izlemede elle cevrilen yon (3x3)
    tex = TexOut(g, outdir, maxtex, False)
    base = rest_trs(g)
    an = None
    if clip is not None and g.j.get('animations'):
        an = g.j['animations'][clip]
    locs = node_locals_at(g, an, clip_time, base) if an is not None else [gl.node_local(n) for n in g.j.get('nodes', [])]
    geo = posed_geometry(g, locs)
    if drop_parts:
        # atilacak materyal adlari (or. modelin altindaki dev zemin plakasi); sinirlar da onlarsiz hesaplanir
        keep = [k for k, x in enumerate(geo) if x[0] is None or g.j['materials'][x[0]].get('name') not in drop_parts]
        geo = [geo[k] for k in keep]; g.vcol = [g.vcol[k] for k in keep]
    allP = np.concatenate([x[1] for x in geo])
    if upright:
        # silah/esya: en uzun ekseni dik dursun (kaidede ayakta)
        e0 = allP.max(0) - allP.min(0); ax = int(np.argmax(e0))
        R = None
        if ax == 0: R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)
        elif ax == 2: R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
        if R is not None:
            geo = [(mi, P @ R.T, N @ R.T, U, I) for mi, P, N, U, I in geo]
            allP = np.concatenate([x[1] for x in geo])
    lo, hi = allP.min(0), allP.max(0)
    ext = hi - lo
    if height: s = height / max(ext[1], 1e-9)
    elif size: s = size / max(ext.max(), 1e-9)
    else: s = 1.0
    c = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    groups = {}
    for (mi, P, N, U, I), C in zip(geo, g.vcol):
        groups.setdefault(mi, []).append((P, N, U, I, C))
    parts = []; tris = 0
    for mi, lst in groups.items():
        mat = material(g, mi, tex, {'skin': False, 'blend': blend})
        Ps, Ns, Us, Is, Cs, o = [], [], [], [], [], 0
        for P, N, U, I, C in lst:
            Ps.append((P - c) * s); Ns.append(N); Us.append(U); Is.append(I + o); o += len(P)
            Cs.append(C if C is not None else np.ones((len(P), 4)))
        P, N, I = to_unity(np.concatenate(Ps), np.concatenate(Ns), np.concatenate(Is))
        C = np.concatenate(Cs)
        # kullanilmayan vertexleri at
        used = np.unique(I); remap = np.full(len(P), -1); remap[used] = np.arange(len(used))
        P, N, U, C, I = P[used], N[used], np.concatenate(Us)[used], C[used], remap[I]
        # dokusuz ama kose renkli parca (renk COLOR_0'da): rengi dokuya pisir; tamamen beyaz kose rengi atlanir
        vc = not mat['texture'] and any(x[4] is not None for x in lst) and mat['name'] not in (part_colors or {})
        if vc and np.ptp(C[:, :3], 0).max() <= 0.02:
            # tek renk: doku gerekmez, rengi ana renge kat (Unity SetColor sRGB bekler; kose rengi lineer)
            col = np.clip(np.array(mat['bc'][:3]) * C[:, :3].mean(0), 0, 1)
            col = np.where(col <= 0.0031308, col * 12.92, 1.055 * np.power(col, 1 / 2.4) - 0.055)
            mat['bc'] = [float(v) for v in col] + [mat['bc'][3]]
        elif vc:
            mat['texture'], P, N, U, I = bake_vcol(tex, mat['name'], P, N, C, I, mat['bc'])
            mat['bc'] = [1, 1, 1, mat['bc'][3]]
        # elle verilen renk (kaynakta rengi olmayan modeller): materyal adi -> [r, g, b] sRGB, istege bagli [.., metallic, smoothness]
        pc = (part_colors or {}).get(mat['name'])
        if pc:
            mat['texture'] = ''; mat['bc'] = [float(v) for v in pc[:3]] + [mat['bc'][3]]
            if len(pc) >= 5: mat['met'], mat['sm'] = float(pc[3]), float(pc[4])
        parts.append(dict(mat=mat, P=P, N=N, U=U, I=I))
        tris += len(I) // 3
    write_stat2(os.path.join(outdir, 'model.statue'), parts)
    if g.license: open(os.path.join(outdir, 'license.txt'), 'w', encoding='utf-8').write(g.license)
    dims = (hi - lo) * s
    return dict(kind='still', tris=tris, parts=len(parts), dims=[round(float(x), 3) for x in dims], texbytes=tex.bytes)


# ------------------------------------------------------------------ yukari ekseni (Z-up / yan yatmis modeller)

def _rot(axis, deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    if axis == 'x': return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# modelin hangi ekseni yukari -> onu glTF +Y'ye ceviren dondurme. Z-up icin -90 X: yuz (-Y, yere bakan) one (+Z) gelir
UP_ROT = {'Y': np.eye(3), '-Y': _rot('z', 180), 'Z': _rot('x', -90), '-Z': _rot('x', 90), 'X': _rot('z', 90), '-X': _rot('z', -90)}


def _skel_up(g):
    """dinlenme pozundaki iskeletten yukari yonu (bas - ayaklar ya da bas - kalca); iskelet yoksa None"""
    j = g.j; nodes = j.get('nodes', [])
    if not j.get('skins'): return None
    joints = sorted({x for sk in j['skins'] for x in sk['joints']})
    W = gl.world_mats(j)
    names = {i: (nodes[i].get('name') or '').lower() for i in joints}
    ok = lambda nm: 'end' not in nm and 'top' not in nm and 'nub' not in nm
    head = next((i for i in joints if 'head' in names[i] and ok(names[i])), None)
    if head is None: return None
    feet = [i for i in joints if any(k in names[i] for k in ('foot', 'toe', 'ankle')) and ok(names[i])]
    hips = next((i for i in joints if any(k in names[i] for k in ('hips', 'pelvis')) and ok(names[i])), None)
    low = np.mean([W[i][:3, 3] for i in feet], 0) if feet else W[hips][:3, 3] if hips is not None else None
    if low is None: return None
    v = W[head][:3, 3] - low
    pts = np.array([W[i][:3, 3] for i in joints]); span = float(np.ptp(pts, 0).max()) or 1.0
    return v / np.linalg.norm(v) if np.linalg.norm(v) > 0.15 * span else None


def _shape(g):
    """(uzunluklar, taban): %0.5-%99.5 araligindaki boyutlar (tek tuk uzak parca yaniltmasin) ve her uc yuzdeki duz
    alan orani ('-Y': altta, yere paralel yuzeyler; heykel kaidesi / zemin / ayak tabani)"""
    C, A, N = [], [], []
    for mi, P, Nv, U, I in posed_geometry(g, [gl.node_local(n) for n in g.j.get('nodes', [])]):
        t = I.reshape(-1, 3); c = np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]]); a = np.linalg.norm(c, axis=1)
        ok = a > 0; C.append(P[t[ok]].mean(1)); A.append(a[ok]); N.append(c[ok] / a[ok, None])
    C, A, N = np.concatenate(C), np.concatenate(A), np.concatenate(N)
    lo, hi = np.percentile(C, 0.5, 0), np.percentile(C, 99.5, 0); e = hi - lo; near = 0.04 * np.linalg.norm(e)
    base = {}
    for k, ax in enumerate('XYZ'):
        flat = np.abs(N[:, k]) > 0.85
        base['-' + ax] = A[flat & (np.abs(C[:, k] - lo[k]) < near)].sum() / A.sum()
        base[ax] = A[flat & (np.abs(C[:, k] - hi[k]) < near)].sum() / A.sum()
    return e, base


def detect_up(g):
    """(eksen, nasil): modelin yukari ekseni ('Y' = oldugu gibi). Once iskelet (dinlenme pozu: kasitli yatan pozlar
    animasyonda oldugu icin yaniltmaz). Iskelet yoksa sekil: duz kaide / zemin Z ucundaysa ya da model Z boyunca
    belirgin uzunsa ve altta (-Y) kaide yoksa Z-up (Blender / 3ds Max / ZBrush OBJ ciktilari: bas +Z, yuz yere).
    X boyunca yatan modelin isareti bilinemedigi icin dokunulmaz; o durumda formdan elle secilir."""
    v = _skel_up(g)
    if v is not None:
        k = int(np.argmax(np.abs(v)))
        if abs(v[k]) < 0.7: return 'Y', 'skeleton tilted, kept'
        ax = ('-' if v[k] < 0 else '') + 'XYZ'[k]
        return ax, 'skeleton'
    try: e, b = _shape(g)
    except Exception: return 'Y', 'no geometry'
    # Y boyunca belirgin uzun model zaten ayakta: sirt / pelerin gibi duz yuzeyler "Z tarafinda kaide" sanilmasin (Boa Hancock)
    if e[1] >= 1.4 * max(e[0], e[2]): return 'Y', 'tall along Y, kept'
    zb = max(b['Z'], b['-Z'])
    sign = '-Z' if b['Z'] > 2 * b['-Z'] and b['Z'] > 0.08 else 'Z'      # kaide +Z ucundaysa bas -Z'de
    if zb > 0.15 and zb > 3 * b['-Y']: return sign, 'base on Z side'
    if e[2] > 1.4 * e[1] and e[2] >= 1.1 * e[0]:
        if b['-Y'] > 0.08 and b['-Y'] > 2 * zb: return 'Y', 'long along Z but stands on a base, kept'
        return sign, 'long along Z'
    if e[0] > 1.4 * e[1] and e[0] > e[2]: return 'Y', 'lies along X, kept'
    return 'Y', 'shape'


def apply_up(j, ax):
    """yeni kok dugum ekler: sahne kokleri (ve sahne disindaki iskelet kokleri) onun altina girer, model ayaga kalkar.
    Animasyon kanallari eski dugumlerde kaldigi icin bozulmaz. ax: eksen adi ('Z' ...) ya da on izlemeden gelen 3x3 dondurme."""
    R = UP_ROT.get(ax) if isinstance(ax, str) else np.asarray(ax, float)
    if R is None or np.allclose(R, np.eye(3), atol=1e-6): return False
    nodes = j.setdefault('nodes', []); par = gl.parents(j)
    if j.get('scenes'): sc = j['scenes'][j.get('scene', 0)]
    else:
        sc = {'nodes': [i for i, p in enumerate(par) if p < 0]}; j['scenes'] = [sc]; j['scene'] = 0
    roots = list(sc.get('nodes', []))
    for sk in j.get('skins', []):
        for r in sk['joints']:
            while par[r] >= 0: r = par[r]
            if r not in roots: roots.append(r)
    m = np.eye(4); m[:3, :3] = R
    nodes.append({'name': 'StatueMaker_Up', 'rotation': [float(x) for x in gl.m2trs(m)[1]], 'children': roots})
    sc['nodes'] = [len(nodes) - 1]
    return True


# ------------------------------------------------------------------ SKIN2 (GameStatuePack sablonu)

def _add_upright_root(g):
    """sahne koklerinin ustune donus dugumu: en uzun eksen Y olsun (convert_static upright ile ayni)"""
    j = g.j
    geo = posed_geometry(g, [gl.node_local(n) for n in j.get('nodes', [])])
    allP = np.concatenate([x[1] for x in geo]); e0 = allP.max(0) - allP.min(0); ax = int(np.argmax(e0))
    if ax == 1: return
    # convert_static: ax 0 -> Rz(+90), ax 2 -> Rx(-90)
    h = np.sqrt(0.5)
    q = [0.0, 0.0, h, h] if ax == 0 else [-h, 0.0, 0.0, h]
    sc = j['scenes'][j.get('scene', 0)]
    j['nodes'].append({'name': 'Upright', 'rotation': q, 'children': list(sc['nodes'])})
    sc['nodes'] = [len(j['nodes']) - 1]


def write_stub_stat2(path):
    """hareketli parcali heykel icin bos sabit model (tek gorunmez ucgen)"""
    write_stat2(path, [dict(mat=dict(name='stub', texture='', alpha=0, ds=False, bc=[1, 1, 1, 1], emtex='', em=[0, 0, 0], met=0.0, sm=0.0),
                            P=np.zeros((3, 3)), N=np.tile([0.0, 1.0, 0.0], (3, 1)), U=np.zeros((3, 2)), I=np.arange(3))])


def load_override(path):
    """Blender'da azaltilmis geometri: dugum adi -> [(materyal adi, P, N, U, I)]"""
    d = Src(path); res = {}
    for i, n in enumerate(d.j.get('nodes', [])):
        if 'mesh' not in n: continue
        for pr in d.j['meshes'][n['mesh']]['primitives']:
            if pr.get('mode', 4) != 4: continue
            mi = pr.get('material')
            mname = d.j['materials'][mi].get('name') if mi is not None else None
            P, N, U, I = prim_data(d, pr, mi)
            if N is None: N = calc_normals(P, I)
            res.setdefault(n.get('name'), []).append((mname, P, N, U, I))
    return res


def convert_anim(src, outdir, clips, height=None, size=None, maxtex=2048, fps=30.0, bounds_clip=0, geo_override=None, blend=False,
                 upright=False, part_fmt=False, up='Y', exclude=None):
    """clips: list of (anim index, display name)
    upright: en uzun eksen dik dursun (silahlar; convert_static ile ayni kural), koke bir donus dugumu eklenir
    part_fmt: sabit heykel cekirdeklerinin "hareketli parca" bicimi (model.statue yaninda model.skin: sinirlar,
              parca basina renk/emissive/metal, tek klip)"""
    g = Src(src, exclude); j = g.j
    apply_up(j, up)
    if upright: _add_upright_root(g)
    ovr = load_override(geo_override) if geo_override else None
    if ovr is not None:
        from scipy.spatial import cKDTree
    tex = TexOut(g, outdir, maxtex, True)
    nodes = j['nodes']; par = gl.parents(j)
    base = rest_trs(g)
    scene = set(gl.scene_nodes(j))

    # skins: glTF skins + rigid mesh nodes
    skins = []  # (joints, bindposes 4x4 glTF)
    skin_map = {}
    for si, sk in enumerate(j.get('skins', [])):
        ib = g.acc(sk['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1) if 'inverseBindMatrices' in sk else np.tile(np.eye(4), (len(sk['joints']), 1, 1))
        skin_map[si] = len(skins); skins.append((list(sk['joints']), ib))
    meshes = []
    Wrest = gl.world_mats(j, [gl.node_local(nd) for nd in nodes])
    for i in sorted(scene):
        n = nodes[i]
        if 'mesh' not in n: continue
        for pi, pr in enumerate(j['meshes'][n['mesh']]['primitives']):
            if pr.get('mode', 4) != 4: continue
            mi = pr.get('material')
            P, N, U, I = prim_data(g, pr, mi)
            if N is None: N = calc_normals(P, I)
            if 'skin' in n and 'JOINTS_0' in pr['attributes']:
                J, W = joints_weights(g, pr); si = skin_map[n['skin']]
                nj = len(skins[si][0]); J = np.clip(J, 0, nj - 1)
                if ovr is not None and n.get('name') in ovr:
                    mname = j['materials'][mi].get('name') if mi is not None else None
                    lst = ovr[n.get('name')]
                    k = next((q for q, x in enumerate(lst) if x[0] == mname), None)
                    if k is not None:
                        _, P2, N2, U2, I2 = lst.pop(k)
                        lo0, hi0 = P.min(0), P.max(0); ext0 = max(float((hi0 - lo0).max()), 1e-9)
                        if np.abs(P2.min(0) - lo0).max() > 0.05 * ext0 or np.abs(P2.max(0) - hi0).max() > 0.05 * ext0:
                            raise RuntimeError('decimated geometry does not line up with the source (%s)' % n.get('name'))
                        _, idx = cKDTree(P).query(P2)
                        P, N, U, I, J, W = P2, N2, U2, I2, J[idx], W[idx]
            else:
                if ovr is not None and n.get('name') in ovr:
                    mname = j['materials'][mi].get('name') if mi is not None else None
                    lst = ovr[n.get('name')]
                    k = next((q for q, x in enumerate(lst) if x[0] == mname), None)
                    if k is not None:
                        _, P2, N2, U2, I2 = lst.pop(k)
                        lo0, hi0 = P.min(0), P.max(0); ext0 = max(float((hi0 - lo0).max()), 1e-9)
                        if np.abs(P2.min(0) - lo0).max() > 0.05 * ext0 or np.abs(P2.max(0) - hi0).max() > 0.05 * ext0:
                            raise RuntimeError('decimated geometry does not line up with the source (%s)' % n.get('name'))
                        P, N, U, I = P2, N2, U2, I2
                si = len(skins); skins.append(([i], np.eye(4)[None]))
                J = np.zeros((len(P), 4), np.int64); W = np.zeros((len(P), 4)); W[:, 0] = 1
            meshes.append(dict(node=i, mi=mi, P=P, N=N, U=U, I=I, J=J, W=W, skin=si))

    # bounds: kare 0 (bounds_clip)
    an0 = j['animations'][clips[bounds_clip][0]] if clips else None
    t0 = anim_range(g, an0)[0] if an0 else 0.0
    locs = node_locals_at(g, an0, t0, base)
    Wm = gl.world_mats(j, locs)
    pts = []
    for m in meshes:
        jn, ib = skins[m['skin']]
        M = np.stack([Wm[x] @ ib[k] for k, x in enumerate(jn)])
        Mv = np.einsum('vk,vkij->vij', m['W'], M[m['J']])
        pts.append(np.einsum('vij,vj->vi', Mv[:, :3, :3], m['P']) + Mv[:, :3, 3])
    allP = np.concatenate(pts); allP[:, 0] *= -1
    lo, hi = allP.min(0), allP.max(0); ext = hi - lo
    if height: scale = height / max(ext[1], 1e-9)
    elif size: scale = size / max(ext.max(), 1e-9)
    else: scale = 1.0
    cx, floor, cz = (lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2

    # clips
    clip_data = []
    for ai, name in clips:
        an = j['animations'][ai]
        mn, frames = clip_frames(g, an, fps)
        times = mn + np.arange(frames) / fps
        chans = []
        for ch in an['channels']:
            n = ch['target'].get('node'); p = ch['target']['path']
            if n is None or p == 'weights': continue
            v = sample(g, an['samplers'][ch['sampler']], p, times)
            path = {'translation': 0, 'rotation': 1, 'scale': 2}[p]
            if path == 0: v = v * [-1, 1, 1]
            if path == 1: v = v * [1, -1, -1, 1]
            rest = np.array(base[n][path], float)
            if path == 0: rest = rest * [-1, 1, 1]
            if path == 1:
                rest = rest * [1, -1, -1, 1]
                d = np.abs((v * rest).sum(1))
                if np.all(d > 1 - 1e-6): continue
            elif np.all(np.abs(v - rest) < 1e-5): continue
            chans.append((n, path, v.astype('<f4')))
        clip_data.append((name, fps, frames, chans))

    path = os.path.join(outdir, 'model.skin')
    tris = 0
    with open(path, 'wb') as f:
        f.write(b'SKIN2'); f.write(struct.pack('<4f', scale, cx, floor, cz))
        if part_fmt:
            bcen = (lo + hi) / 2; bsz = (hi - lo) * 1.5 + 1e-3
            f.write(struct.pack('<3f', *bcen)); f.write(struct.pack('<3f', *bsz))
        f.write(struct.pack('<i', len(nodes)))
        for i, n in enumerate(nodes):
            T, R, S = base[i]
            wstr(f, n.get('name') or 'n%d' % i); f.write(struct.pack('<i', par[i]))
            f.write(struct.pack('<3f', -T[0], T[1], T[2])); f.write(struct.pack('<4f', R[0], -R[1], -R[2], R[3])); f.write(struct.pack('<3f', *S))
        f.write(struct.pack('<i', len(skins)))
        for jn, ib in skins:
            f.write(struct.pack('<i', len(jn))); f.write(np.array(jn, '<i4').tobytes())
            for k in range(len(jn)):
                f.write((FLIP @ ib[k] @ FLIP).astype('<f4').ravel().tobytes())   # satir satir
        f.write(struct.pack('<i', len(meshes)))
        for m in meshes:
            mat = material(g, m['mi'], tex, {'skin': True, 'blend': blend})
            wstr(f, mat['name']); wstr(f, mat['texture'])
            al = mat['alpha']
            if part_fmt: al = 2 if al == 3 else (1 if al == 2 else al)   # sabit cekirdekte 2 = gercek saydam
            f.write(bytes([al, 1 if mat['ds'] else 0])); f.write(struct.pack('<i', m['skin']))
            if part_fmt:
                f.write(struct.pack('<4f', *mat['bc'])); wstr(f, '')
                f.write(struct.pack('<3f', *mat['em'])); f.write(struct.pack('<2f', mat['met'], mat['sm']))
            P, N, I = to_unity(m['P'], m['N'], m['I'])
            f.write(struct.pack('<i', len(P)))
            f.write(P.astype('<f4').tobytes()); f.write(N.astype('<f4').tobytes())
            f.write(np.c_[m['U'][:, 0], 1 - m['U'][:, 1]].astype('<f4').tobytes())
            f.write(m['J'].astype('<i4').tobytes()); f.write(m['W'].astype('<f4').tobytes())
            f.write(struct.pack('<i', len(I))); f.write(I.astype('<i4').tobytes())
            tris += len(I) // 3
        if part_fmt:
            name, fp, fr, chans = clip_data[0]
            f.write(struct.pack('<f', fp)); f.write(struct.pack('<i', fr)); f.write(struct.pack('<i', len(chans)))
            for n, p, v in chans:
                f.write(struct.pack('<i', n)); f.write(bytes([p])); f.write(v.tobytes())
        else:
            f.write(struct.pack('<i', len(clip_data)))
            for name, fp, fr, chans in clip_data:
                wstr(f, name); f.write(struct.pack('<f', fp)); f.write(struct.pack('<i', fr)); f.write(struct.pack('<i', len(chans)))
                for n, p, v in chans:
                    f.write(struct.pack('<i', n)); f.write(bytes([p])); f.write(v.tobytes())
    if g.license: open(os.path.join(outdir, 'license.txt'), 'w', encoding='utf-8').write(g.license)
    return dict(kind='anim', tris=tris, parts=len(meshes), dims=[round(float(x), 3) for x in ext * scale],
                clips=[(c[0], round(c[2] / c[1], 1), len(c[3])) for c in clip_data], texbytes=tex.bytes, nodes=len(nodes),
                scale=float(scale), cx=float(cx), floor=float(floor), cz=float(cz), lo=[float(x) for x in lo], hi=[float(x) for x in hi])
