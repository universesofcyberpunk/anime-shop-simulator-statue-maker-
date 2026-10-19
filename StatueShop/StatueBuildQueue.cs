// StatueBuildQueue - heykel modlari acilista sirayla kurulur.
// Eskiden butun heykel modlari (40+ mod, ~90 cekirdek) sahne acildiktan 3 sn sonra AYNI karede kuruluyordu:
// her biri oyunun tum tanimlarini tariyor ve dokularini yukluyordu -> birkac saniyelik donma.
// Simdi ortak bir sira var (AppDomain uzerinden, butun heykel modlari gorur): her cekirdek bir sonraki bos zamani alir,
// cekirdekler Spacing arayla kurulur. Ilk gelen hemen kurulur.
// Her heykel modunda bu dosyanin ayni kopyasi var; degisiklik ModDev\Files\Bc7\StatueBuildQueue.cs'den dagitilir.

using System;
using System.Collections.Generic;
using UnityEngine;

internal static class StatueBuildQueue
{
    const string Key = "Fabianens.StatueBuildQueue.Next";
    const float Spacing = 0.05f;
    static readonly HashSet<object> _waiting = new();

    // true: simdi kur. false: sira bekleniyor, nextCheck sira zamanina ayarlandi.
    public static bool MyTurn(object owner, ref float nextCheck)
    {
        if (_waiting.Remove(owner)) return true;
        float now = Time.unscaledTime;
        var d = AppDomain.CurrentDomain;
        float next = 0f;
        try { if (d.GetData(Key) is float f) next = f; } catch { }
        float slot = Math.Max(now, next);
        try { d.SetData(Key, slot + Spacing); } catch { }
        if (slot <= now) return true;
        _waiting.Add(owner);
        nextCheck = slot;
        return false;
    }
}
