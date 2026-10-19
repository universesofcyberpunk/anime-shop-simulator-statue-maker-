import struct, numpy as np
def rs(f):
    n = struct.unpack('<i', f.read(4))[0]; return f.read(n).decode('utf-8')
def stat2(p):
    f = open(p, 'rb'); assert f.read(5) == b'STAT2'
    n = struct.unpack('<i', f.read(4))[0]; parts = []
    for _ in range(n):
        name = rs(f); tex = rs(f); am, ds = f.read(1)[0], f.read(1)[0]
        bc = struct.unpack('<4f', f.read(16)); et = rs(f); em = struct.unpack('<3f', f.read(12)); met, sm = struct.unpack('<2f', f.read(8))
        v = struct.unpack('<i', f.read(4))[0]
        P = np.frombuffer(f.read(12*v), np.float32).reshape(-1, 3); N = np.frombuffer(f.read(12*v), np.float32).reshape(-1, 3); U = np.frombuffer(f.read(8*v), np.float32).reshape(-1, 2)
        ic = struct.unpack('<i', f.read(4))[0]; I = np.frombuffer(f.read(4*ic), np.int32)
        parts.append(dict(name=name, tex=tex, am=am, ds=ds, bc=bc, et=et, em=em, met=met, sm=sm, P=P, N=N, U=U, I=I))
    return parts

def skin(p):
    f = open(p, 'rb'); magic = f.read(5)
    S = lambda fmt: struct.unpack('<' + fmt, f.read(struct.calcsize('<' + fmt)))
    sc, cx, fl, cz = S('4f'); nn = S('i')[0]; nodes = []
    for _ in range(nn):
        name = rs(f); par = S('i')[0]; T = S('3f'); R = S('4f'); Sc = S('3f'); nodes.append((name, par, T, R, Sc))
    ns = S('i')[0]; skins = []
    for _ in range(ns):
        jc = S('i')[0]; J = S('%di' % jc); B = np.array(S('%df' % (16 * jc))).reshape(jc, 4, 4); skins.append((J, B))
    nm = S('i')[0]; meshes = []
    for _ in range(nm):
        name = rs(f); tex = rs(f); clip = f.read(1)[0]; ds = f.read(1)[0]; sk = S('i')[0]
        if magic == b'SKIN2' and False: pass
        v = S('i')[0]
        P = np.frombuffer(f.read(12*v), np.float32).reshape(-1, 3); N = np.frombuffer(f.read(12*v), np.float32).reshape(-1, 3); U = np.frombuffer(f.read(8*v), np.float32).reshape(-1, 2)
        J = np.frombuffer(f.read(16*v), np.int32).reshape(-1, 4); W = np.frombuffer(f.read(16*v), np.float32).reshape(-1, 4)
        ic = S('i')[0]; I = np.frombuffer(f.read(4*ic), np.int32)
        meshes.append(dict(name=name, tex=tex, clip=clip, ds=ds, sk=sk, P=P, N=N, U=U, J=J, W=W, I=I))
    nclips = 1 if magic == b'SKIN1' else S('i')[0]; clips = []
    for _ in range(nclips):
        cname = 'Animation' if magic == b'SKIN1' else rs(f)
        fps = S('f')[0]; fr = S('i')[0]; nc = S('i')[0]; ch = []
        for _ in range(nc):
            node = S('i')[0]; path = f.read(1)[0]; k = 4 if path == 1 else 3
            ch.append((node, path, np.frombuffer(f.read(4 * fr * k), np.float32).reshape(fr, k)))
        clips.append((cname, fps, fr, ch))
    rest = f.read()
    return dict(magic=magic, scale=sc, cx=cx, floor=fl, cz=cz, nodes=nodes, skins=skins, meshes=meshes, clips=clips, rest=len(rest))
