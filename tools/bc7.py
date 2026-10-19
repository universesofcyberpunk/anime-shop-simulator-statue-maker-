# Statue Maker: heykel dokularini BC7'ye cevirir (ModDev\Files\Bc7\bc7_convert.py ile ayni dosya bicimi; CustomStatues'teki
# Bc7Tex.cs okur). "<doku>.png" -> "<doku>.bc7"; .bc7 varsa oyun PNG'yi hic cozmez, ekran kartinda 4 kat az yer kaplar.
# Dosya: "BC7T" | int32 surum (1) | int32 genislik | int32 yukseklik | int32 mip sayisi | tum mip'lerin BC7 bloklari (alttan uste, sRGB)
import io, math, os, struct
import numpy as np
from PIL import Image
try:
    import etcpak
except Exception:          # etcpak yoksa dokular PNG kalir (oyun PNG'yi de okur)
    etcpak = None

MAGIC = b"BC7T"


def available(): return etcpak is not None


def _mips(w, h):
    n = int(math.floor(math.log2(max(w, h)))) + 1
    return [(max(1, w >> i), max(1, h >> i)) for i in range(n)]


def _level(img):
    w, h = img.size
    bw, bh = (w + 3) // 4 * 4, (h + 3) // 4 * 4
    if (bw, bh) != (w, h):   # 1x1, 2x2 gibi kucuk mip'ler: blok boyutuna kenar tekrariyla doldur
        data = np.pad(np.asarray(img), ((0, bh - h), (0, bw - w), (0, 0)), mode="edge").tobytes()
    else:
        data = img.tobytes()
    return etcpak.compress_bc7(data, bw, bh)


def convert(src, dst):
    img = Image.open(src); img.load(); img = img.convert("RGBA")
    w, h = img.size
    nw, nh = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
    if (nw, nh) != (w, h): img = img.resize((nw, nh), Image.LANCZOS); w, h = nw, nh
    img = img.transpose(Image.FLIP_TOP_BOTTOM)   # Unity: ilk satir en alttaki
    sizes = _mips(w, h)
    out = io.BytesIO()
    out.write(MAGIC + struct.pack("<iiii", 1, w, h, len(sizes)))
    level = img
    for i, (mw, mh) in enumerate(sizes):
        if i > 0: level = level.resize((mw, mh), Image.BOX)
        blocks = _level(level)
        if len(blocks) != ((mw + 3) // 4) * ((mh + 3) // 4) * 16: raise RuntimeError(f"mip {i}: wrong block size")
        out.write(blocks)
    with open(dst, "wb") as f: f.write(out.getvalue())


def convert_folder(folder, log=print):
    """modelin kullandigi PNG/JPG dokulari .bc7 yap, kaynagi sil (icon.png kalir). (cevrilen, toplam) doner."""
    if etcpak is None: return 0, 0
    blob = b""
    for f in ("model.statue", "model.skin"):
        p = os.path.join(folder, f)
        if os.path.exists(p): blob += open(p, "rb").read()
    done = total = 0
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith((".png", ".jpg", ".jpeg")) or f.lower() == "icon.png": continue
        if f.encode("utf-8") not in blob: continue
        total += 1
        src = os.path.join(folder, f)
        try:
            convert(src, os.path.splitext(src)[0] + ".bc7"); os.remove(src); done += 1
        except Exception as e:
            log(f"BC7: {f} cevrilemedi ({e}), PNG kaldi")
    return done, total
