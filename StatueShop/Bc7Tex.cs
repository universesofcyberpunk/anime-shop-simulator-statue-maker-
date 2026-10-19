// Bc7Tex - onceden BC7'ye cevrilmis heykel dokularini yukler (ModDev\Tools\Bc7\bc7_convert.py uretir).
// "<doku>.png" yerine ayni klasorde "<doku>.bc7" varsa PNG cozulmeden dogrudan ekran kartina yuklenir:
// RGBA32'ye gore 4 kat az ekran karti bellegi, acilista PNG cozme yok. Dosya yoksa / bozuksa null doner, mod PNG'ye duser.
// Her heykel modunda bu dosyanin ayni kopyasi var (modlar birbirine bagli degil); degisiklik Tools\Bc7\Bc7Tex.cs'den dagitilir.
//
// Dosya: "BC7T" | int32 surum (1) | int32 genislik | int32 yukseklik | int32 mip sayisi | tum mip'lerin BC7 bloklari (alttan uste, sRGB)

using System;
using System.IO;
using UnityEngine;

internal static class Bc7Tex
{
    static bool? _supported;

    public static Texture2D Load(string pngPath)
    {
        try
        {
            string p = Path.ChangeExtension(pngPath, ".bc7");
            if (!File.Exists(p)) return null;
            if (_supported == null) _supported = SystemInfo.SupportsTextureFormat(TextureFormat.BC7);
            if (_supported == false) return null;
            byte[] b = File.ReadAllBytes(p);
            if (b.Length < 20 || b[0] != (byte)'B' || b[1] != (byte)'C' || b[2] != (byte)'7' || b[3] != (byte)'T') return null;
            int ver = BitConverter.ToInt32(b, 4), w = BitConverter.ToInt32(b, 8), h = BitConverter.ToInt32(b, 12), mips = BitConverter.ToInt32(b, 16);
            if (ver != 1 || w <= 0 || h <= 0 || mips <= 0 || mips > 16) return null;
            long need = 0;
            for (int i = 0; i < mips; i++)
            {
                int mw = Math.Max(1, w >> i), mh = Math.Max(1, h >> i);
                need += (long)((mw + 3) / 4) * ((mh + 3) / 4) * 16;
            }
            if (b.Length - 20 != need) return null;
            var data = new byte[need];
            Buffer.BlockCopy(b, 20, data, 0, data.Length);
            var t = new Texture2D(w, h, TextureFormat.BC7, mips, false);
            t.LoadRawTextureData(data);
            t.Apply(false, true);   // CPU kopyasi tutulmaz
            return t;
        }
        catch { return null; }
    }
}
