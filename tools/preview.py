# model.statue / model.skin -> OBJ (Unity tarafindaki matematigi taklit ederek), Blender'da render icin
import sys, os, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import rd, gl


def skin_pose(d, clip=0, frame=0):
    nodes = d['nodes']; n = len(nodes)
    T = [np.array(x[2], float) for x in nodes]; R = [np.array(x[3], float) for x in nodes]; S = [np.array(x[4], float) for x in nodes]
    if d['clips']:
        name, fps, fr, ch = d['clips'][clip]
        for node, path, v in ch:
            val = v[min(frame, fr - 1)].astype(float)
            if path == 0: T[node] = val
            elif path == 1: R[node] = val / np.linalg.norm(val)
            else: S[node] = val
    loc = []
    for i in range(n):
        m = np.eye(4); m[:3, :3] = gl.q2m(R[i]) * S[i]; m[:3, 3] = T[i]; loc.append(m)
    W = [None] * n
    def w(i):
        if W[i] is None: W[i] = loc[i] if nodes[i][1] < 0 else w(nodes[i][1]) @ loc[i]
        return W[i]
    off = np.eye(4); off[:3, 3] = [-d['cx'], -d['floor'], -d['cz']]
    sc = np.diag([d['scale']] * 3 + [1])
    out = []
    for m in d['meshes']:
        J, B = d['skins'][m['sk']]
        M = np.stack([sc @ off @ w(J[k]) @ B[k] for k in range(len(J))])
        Mv = np.einsum('vk,vkij->vij', m['W'].astype(float), M[m['J']])
        P = np.einsum('vij,vj->vi', Mv[:, :3, :3], m['P'].astype(float)) + Mv[:, :3, 3]
        N = np.einsum('vij,vj->vi', Mv[:, :3, :3], m['N'].astype(float))
        out.append((m['name'], m['tex'], P, N, m['U'], m['I']))
    return out


def write_obj(path, parts, texdir):
    d = os.path.dirname(path); base = os.path.splitext(os.path.basename(path))[0]
    with open(os.path.join(d, base + '.mtl'), 'w') as f:
        for k, (name, tex, bc, P, N, U, I) in enumerate(parts):
            f.write('newmtl m%d\nKd %f %f %f\n' % (k, bc[0], bc[1], bc[2]))
            if tex: f.write('map_Kd %s\n' % os.path.join(texdir, tex).replace(os.sep, '/'))
    with open(path, 'w') as f:
        f.write('mtllib %s.mtl\n' % base); o = 1
        for k, (name, tex, bc, P, N, U, I) in enumerate(parts):
            P = P.copy(); N = N.copy(); P[:, 0] *= -1; N[:, 0] *= -1   # Unity (sol el) -> sag el
            np.savetxt(f, P, 'v %.5f %.5f %.5f'); np.savetxt(f, N, 'vn %.4f %.4f %.4f'); np.savetxt(f, U, 'vt %.5f %.5f')
            f.write('usemtl m%d\n' % k)
            t = I.reshape(-1, 3)[:, [0, 2, 1]] + o
            np.savetxt(f, np.c_[t[:, 0], t[:, 0], t[:, 0], t[:, 1], t[:, 1], t[:, 1], t[:, 2], t[:, 2], t[:, 2]], 'f %d/%d/%d %d/%d/%d %d/%d/%d')
            o += len(P)


def run(modeldir, out_obj, clip=0, frame=0):
    if os.path.exists(os.path.join(modeldir, 'model.skin')):
        d = rd.skin(os.path.join(modeldir, 'model.skin'))
        parts = [(n, t, (1, 1, 1), P, N, U, I) for n, t, P, N, U, I in skin_pose(d, clip, frame)]
    else:
        parts = [(p['name'], p['tex'], p['bc'], p['P'].astype(float), p['N'].astype(float), p['U'], p['I']) for p in rd.stat2(os.path.join(modeldir, 'model.statue'))]
    write_obj(out_obj, parts, modeldir)


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0, int(sys.argv[4]) if len(sys.argv) > 4 else 0)
