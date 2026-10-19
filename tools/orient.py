# Figure Maker - formdaki on izleme: modeli nokta bulutu olarak hizlica cizer, fare ile cevrilen yonu (3x3) dondurur
# Koordinatlar glTF (sag el, +Y yukari). Kamera +Z'de, -Z'ye bakar: ekranda gorunen yuz oyunda musteriye bakan yuzdur.
import io, math
import numpy as np
from PIL import Image
import conv, gl


def rx(d):
    a = math.radians(d); c, s = math.cos(a), math.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def ry(d):
    a = math.radians(d); c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rz(d):
    a = math.radians(d); c, s = math.cos(a), math.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _base_tex(g, mi, cache):
    """materyalin ana renk dokusu (kucultulmus, float RGB) ve rengi"""
    if mi is None: return None, np.array([0.8, 0.8, 0.8])
    m = g.j['materials'][mi]
    pb = m.get('pbrMetallicRoughness', {}); sg = m.get('extensions', {}).get('KHR_materials_pbrSpecularGlossiness')
    bc = np.array((sg.get('diffuseFactor') if sg else pb.get('baseColorFactor')) or [1, 1, 1, 1], float)[:3]
    bt = (sg.get('diffuseTexture') if sg else pb.get('baseColorTexture'))
    if bt is None and 'emissiveTexture' in m and bc.max() < 0.05:     # isiksiz (emissive) modeller
        bt = m['emissiveTexture']; bc = np.ones(3)
    if not bt or 'index' not in bt: return None, bc
    k = bt['index']
    if k not in cache:
        try:
            im = Image.open(io.BytesIO(g.image_bytes(k)[0])).convert('RGB'); im.thumbnail((256, 256))
            cache[k] = np.asarray(im, np.float32) / 255.0
        except Exception: cache[k] = None
    return cache[k], bc


def load(g, anim=None, count=120000, frame=0, cache=None):
    """(P, C, N): pozdaki yuzeyden alana gore esit dagilmis noktalar, renkleri ve normalleri
    (koseler yerine yuzey: az poligonlu buyuk parcalar da dolu gorunur). frame: klibin karesi (30 fps, model.skin ile ayni);
    cache: dokular kareler arasinda tekrar okunmasin"""
    j = g.j
    an = j['animations'][anim] if anim is not None and j.get('animations') else None
    locs = conv.node_locals_at(g, an, conv.clip_frames(g, an)[0] + frame / 30.0, conv.rest_trs(g)) if an else [gl.node_local(n) for n in j.get('nodes', [])]
    prims = []
    for mi, P, N, U, I in conv.posed_geometry(g, locs):
        if mi is not None and 'outline' in (j['materials'][mi].get('name') or '').lower(): continue   # ters kabuk dis cizgi
        t = I.reshape(-1, 3)
        a = np.linalg.norm(np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]]), axis=1)
        if a.sum() > 0: prims.append((mi, P, N, U, t, a))
    total = sum(x[5].sum() for x in prims) or 1.0
    rng = np.random.default_rng(1); Ps, Cs, Ns = [], [], []
    if cache is None: cache = {}
    for mi, P, N, U, t, a in prims:
        n = max(1, int(round(count * a.sum() / total)))
        k = rng.choice(len(t), n, p=a / a.sum())
        r1, r2 = rng.random(n), rng.random(n); f = r1 + r2 > 1; r1[f], r2[f] = 1 - r1[f], 1 - r2[f]
        w = np.stack([1 - r1 - r2, r1, r2], 1)[:, :, None]
        tri = t[k]
        Ps.append((P[tri] * w).sum(1)); Ns.append((N[tri] * w).sum(1)); uu = (U[tri] * w).sum(1)
        T, bc = _base_tex(g, mi, cache)
        if T is not None:
            h, wd = T.shape[:2]
            px = (np.mod(uu[:, 0], 1.0) * (wd - 1)).astype(int); py = (np.mod(uu[:, 1], 1.0) * (h - 1)).astype(int)
            Cs.append(T[py, px] * bc)
        else:
            Cs.append(np.tile(bc, (n, 1)))
    P, C, N = np.concatenate(Ps), np.concatenate(Cs), np.concatenate(Ns)
    ctr = (P.min(0) + P.max(0)) / 2
    return P - ctr, np.clip(C, 0, 1), N


def front_yaw(g, R):
    """iskeletten (ayak parmagi / goz) yuzun yonu -> kameraya (+Z) cevirmek icin Y donusu (derece); iskelet yoksa 0"""
    j = g.j; nodes = j.get('nodes', [])
    if not j.get('skins'): return 0.0
    W = gl.world_mats(j); par = gl.parents(j)
    names = [(n.get('name') or '').lower() for n in nodes]
    v = np.zeros(3)
    for i, nm in enumerate(names):
        if 'toe' in nm and 'end' not in nm and par[i] >= 0: v += W[i][:3, 3] - W[par[i]][:3, 3]
    if np.hypot(*(R @ v)[[0, 2]]) < 1e-6:
        head = next((i for i, nm in enumerate(names) if 'head' in nm and 'end' not in nm), None)
        eyes = [i for i, nm in enumerate(names) if 'eye' in nm and 'end' not in nm and 'brow' not in nm and 'lid' not in nm]
        if head is None or not eyes: return 0.0
        v = np.mean([W[i][:3, 3] for i in eyes], 0) - W[head][:3, 3]
    v = R @ v
    if np.hypot(v[0], v[2]) < 1e-6: return 0.0
    return -math.degrees(math.atan2(v[0], v[2]))      # ry(yaw) @ v -> +Z


def initial(g, up='auto'):
    """otomatik baslangic yonu: yukari ekseni (detect_up ya da secilen) + iskeletten one cevirme"""
    up = str(up or 'auto').upper().replace('+', '')
    if up not in conv.UP_ROT: up = conv.detect_up(g)[0]
    R = conv.UP_ROT[up]
    return ry(front_yaw(g, R)) @ R


def snap(R):
    """yuvarlama hatasini temizle (90 derecelik adimlardan sonra tam 0 / 1)"""
    R = np.where(np.abs(R) < 1e-9, 0.0, R)
    u, _, vt = np.linalg.svd(R); return u @ vt


def render(P, C, N, R, w=300, h=380, pitch=12.0):
    """R ile dondurulmus noktalari onden (biraz yukaridan) ciz; zemin cizgisi ve golge ile"""
    Q = P @ R.T; Nn = N @ R.T
    floor = Q[:, 1].min()
    V = rx(pitch)                                       # kamera biraz yukarida: model hafif one egik gorunur
    S = Q @ V.T
    span = max(np.ptp(S[:, 0]), np.ptp(S[:, 1])) or 1.0
    k = 0.86 * min(w, h) / span
    cx, cy = (S[:, 0].max() + S[:, 0].min()) / 2, (S[:, 1].max() + S[:, 1].min()) / 2
    x = ((S[:, 0] - cx) * k + w / 2).astype(int); y = (h / 2 - (S[:, 1] - cy) * k).astype(int)
    img = np.zeros((h, w, 3), np.float32) + np.array([0.93, 0.94, 0.96], np.float32)
    # golge: zemindeki ayak izi
    gx = ((Q[:, 0] - cx) * k + w / 2).astype(int)
    gy = (h / 2 - ((np.full(len(Q), floor) * math.cos(math.radians(pitch)) - Q[:, 2] * math.sin(math.radians(pitch))) - cy) * k).astype(int)
    m = (gx >= 0) & (gx < w) & (gy >= 0) & (gy < h)
    img[gy[m], gx[m]] = [0.80, 0.81, 0.84]
    L = np.array([0.35, 0.6, 0.72]); L /= np.linalg.norm(L)
    sh = 0.45 + 0.55 * np.abs((Nn / np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)) @ L)
    col = C * sh[:, None]
    # yarim cozunurlukte tek gecis (yakindaki nokta en son yazilir), sonra buyutulur: noktalar arasi bosluk kalmaz
    hx, hy = (x // 2), (y // 2); W2, H2 = (w + 1) // 2, (h + 1) // 2
    small = np.asarray(Image.fromarray((img * 255).astype(np.uint8)).resize((W2, H2)), np.float32) / 255.0
    o = np.argsort(S[:, 2]); hx, hy, col = hx[o], hy[o], col[o]
    m = (hx >= 0) & (hx < W2) & (hy >= 0) & (hy < H2)
    small[hy[m], hx[m]] = col[m]
    return Image.fromarray((small * 255).astype(np.uint8), 'RGB').resize((w, h), Image.BILINEAR)
