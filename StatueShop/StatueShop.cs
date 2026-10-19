// StatueShop - Fabianens Statue Shop (Anime Shop Simulator)
// Statue Maker'in urettigi heykel klasorlerini yukler: UserData\StatueShop\<klasor>\ statue.json + model.statue (+ model.skin) + icon.png + dokular.
// Kod degismeden yeni heykel eklenir: ID klasor adindan sabit uretilir, her heykelin F10 > Mod Ayarlari'nda ac/kapa ayari var.
// Gorsel / animasyon / dosya bicimleri GameStatues'in sabit heykel cekirdegiyle ayni (STAT2 + SKIN2 hareketli model).

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using HarmonyLib;
using MelonLoader;
using MelonLoader.Utils;
using UnityEngine;
using UnityEngine.Rendering;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppFishNet;
using Il2CppFishNet.Object;
using Il2CppI2.Loc;
using Il2CppProject.Code.Gameplay.Configs;
using Il2CppProject.Code.Gameplay.Definitions;
using Il2CppProject.Code.Gameplay.Player.Build;
using Il2CppProject.Code.Gameplay.UI.Computer;
using DDef = Il2CppProject.Code.Core.Utils.DataDefinition.DataDefinition;
using PickupDB = Il2CppProject.Code.Core.Utils.DataDefinition.DataDefinition<Il2CppProject.Code.Gameplay.Definitions.PickupDefinition>;
using BuildingDB = Il2CppProject.Code.Core.Utils.DataDefinition.DataDefinition<Il2CppProject.Code.Gameplay.Definitions.BuildingPieceDefinition>;

[assembly: MelonInfo(typeof(StatueShop.Core), "StatueShop", "1.0.0", "Fabianens")]
[assembly: MelonGame("OneMoreTime", "Anime Shop Simulator")]

namespace StatueShop
{
    internal class Item
    {
        public string Folder, Dir, Slug, NameEn, NameTr;
        public float Price;
        public int Level;
        public int PickupId, BuildingId;
        public MelonPreferences_Entry<bool> Enabled;
        public bool On => Enabled == null || Enabled.Value;
        public PickupDefinition Def;
        public BuildingPieceDefinition Bd;
        public NetworkObject Prefab;
        public string TermKey => "Buildings/cst_" + Slug;
    }

    public class Core : MelonMod
    {
        static readonly MelonLogger.Instance Log = new MelonLogger.Instance("StatueShop");
        const string RefTermKey = "Buildings/shelf_products_11";
        const string Category = "Statues";   // Mod Market: HEYKELLER filtresi
        // ModMarket'in gizli araligi (1777120000-1777199999) ve FigureShop paketleri (1777300000-1777999999) disinda
        const int IdBase = 1778100000, IdSlots = 80000;

        static readonly List<Item> Items = new();
        static readonly HashSet<int> _offIds = new();

        static MelonPreferences_Entry<int> _sourceId, _level;
        static MelonPreferences_Entry<float> _priceMul;
        static PickupDefinition _src;
        static IntPtr _registeredNm = IntPtr.Zero;
        static bool _built, _failed;
        static ProductsConfig _cfgCache;
        float _nextCheck;
        bool _sceneReady;
        static string _dataDir;
        static int _added;

        public override void OnInitializeMelon()
        {
            _dataDir = Path.Combine(MelonEnvironment.UserDataDirectory, "StatueShop");
            try { Directory.CreateDirectory(_dataDir); } catch { }
            var cat = MelonPreferences.CreateCategory("StatueShop", "Statue Shop");
            _sourceId = cat.CreateEntry("SourcePickupId", 2002347843, "ID of the vanilla item used as the base (life-size figure)");
            _priceMul = cat.CreateEntry("PriceMultiplier", 1.0f, "Multiply all statue prices");
            _level = cat.CreateEntry("Level", 1, "Unlock level (a statue's own statue.json \"level\" wins)");
            Discover(cat);
            if (Items.Count == 0) { _failed = true; Log.Msg($"No statues found in {_dataDir} (make them with Statue Maker)."); return; }
            RegisterWithModMarket();
            try
            {
                var m = AccessTools.Method(typeof(MenuOrdersWidget), nameof(MenuOrdersWidget.GetContentPickups));
                var post = new HarmonyMethod(typeof(Core).GetMethod(nameof(ContentPickupsPostfix), System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)) { priority = HarmonyLib.Priority.Last };
                if (m != null) HarmonyInstance.Patch(m, postfix: post);
            }
            catch (Exception e) { Log.Warning("Shop list patch: " + e.Message); }
            Log.Msg($"Ready. {Items.Count} statues ({Items.Count(x => !x.On)} turned off), data folder: {_dataDir}");
        }

        // UserData\StatueShop\<klasor>: model.statue olan her klasor bir heykel ("_" ile baslayanlar atlanir)
        static void Discover(MelonPreferences_Category cat)
        {
            Items.Clear(); _offIds.Clear();
            var used = new HashSet<int>();
            foreach (var dir in Directory.GetDirectories(_dataDir).OrderBy(d => Path.GetFileName(d), StringComparer.OrdinalIgnoreCase))
            {
                string folder = Path.GetFileName(dir);
                if (folder.StartsWith("_")) continue;
                if (!File.Exists(Path.Combine(dir, "model.statue"))) { Log.Warning($"'{folder}': model.statue missing, skipped."); continue; }
                var c = ReadJson(Path.Combine(dir, "statue.json"));
                var it = new Item
                {
                    Folder = folder, Dir = dir, Slug = Slug(folder),
                    NameEn = S(c, "nameEnglish", folder.Replace('_', ' ')),
                    Price = Math.Max(1f, F(c, "price", 15000f)),
                    Level = (int)F(c, "level", 0f),
                };
                it.NameTr = S(c, "nameTurkish", it.NameEn);
                // klasor adindan sabit ID (cakisirsa sonraki bos yuva); kayitlar bu ID'ye bagli: klasor adini degistirme
                int slot = (int)(Fnv(folder) % IdSlots);
                for (int tries = 0; tries < IdSlots; tries++, slot = (slot + 1) % IdSlots)
                {
                    int b = IdBase + slot * 10;
                    if (!used.Contains(b + 1)) { it.PickupId = b + 1; it.BuildingId = b + 2; break; }
                }
                used.Add(it.PickupId);
                bool def = !c.TryGetValue("enabled", out var en) || !en.Equals("false", StringComparison.OrdinalIgnoreCase);
                it.Enabled = cat.CreateEntry("Statue_" + it.Slug, def, "Statue: " + it.NameEn,
                    $"Sell '{it.NameEn}' on the MODS screen. Off = hidden from the shop; ones already placed stay. Restart needed.");
                if (!it.On) _offIds.Add(it.PickupId);
                if (c.TryGetValue("credits.title", out var ct) && ct.Length > 0) Log.Msg($"{folder}: \"{ct}\" by {S(c, "credits.author", "?")}, {S(c, "credits.license", "?")} {S(c, "credits.source", "")}");
                Items.Add(it);
            }
            Log.Msg("Statues: " + string.Join(", ", Items.Select(x => $"{x.Folder} ({x.PickupId}{(x.On ? "" : ", off")})")));
        }

        // kapali heykeller satin alma listesinde gorunmez (tanim kayitli kalir: yerlestirilmisler kaybolmaz)
        static void ContentPickupsPostfix(ref Il2CppSystem.Collections.Generic.List<PickupDefinition> __result)
        {
            if (_offIds.Count == 0 || __result == null) return;
            try
            {
                for (int i = __result.Count - 1; i >= 0; i--)
                {
                    var d = __result[i];
                    if (d != null && _offIds.Contains(SafeId(d))) __result.RemoveAt(i);
                }
            }
            catch { }
        }

        // Mod Market varsa: heykelleri sadece MODS sayfasinda sat (yoksa sessizce gec)
        void RegisterWithModMarket()
        {
            try
            {
                Type t = null;
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                    if (asm.GetName().Name == "ModMarket") { t = asm.GetType("ModMarket.Core"); break; }
                var m3 = t?.GetMethod("RegisterItem", new[] { typeof(int), typeof(string), typeof(bool) });
                var m2 = t?.GetMethod("RegisterItem", new[] { typeof(int), typeof(string) });
                if (m3 == null && m2 == null) { Log.Warning("Fabianens Mod Market not found - it is required to buy the statues."); return; }
                foreach (var it in Items)
                {
                    if (m3 != null) m3.Invoke(null, new object[] { it.PickupId, Category, true });
                    else m2.Invoke(null, new object[] { it.PickupId, Category });
                }
                Log.Msg("Registered with Mod Market (MODS page, Statues).");
            }
            catch (Exception e) { Log.Warning("Mod Market registration: " + e.Message); }
        }

        public override void OnSceneWasInitialized(int buildIndex, string sceneName)
        {
            _sceneReady = true;
            _nextCheck = Time.unscaledTime + 3f;
            if (_spread == 0) _spread = GetType().FullName.GetHashCode() | 1;
        }

        public override void OnUpdate()
        {
            if (_failed || !_sceneReady || Time.unscaledTime < _nextCheck) return;
            _nextCheck = Time.unscaledTime + (_built ? 15f + (_spread & 7) : 2f);
            try
            {
                if (!_built && StatueBuildQueue.MyTurn(this, ref _nextCheck)) TryBuild();   // heykel modlari sirayla kurulur (StatueBuildQueue.cs)
                if (_built) { EnsureRegistered(); EnsureNetworkPrefabs(); EnsureLocalization(); }
            }
            catch (Exception e)
            {
                _failed = true;
                Log.Error("Unexpected error, mod stopped: " + e);
            }
        }

        // ------------------------------------------------------------------ statue.json

        static string Slug(string s)
        {
            var sb = new StringBuilder();
            foreach (var ch in s) sb.Append(char.IsLetterOrDigit(ch) && ch < 128 ? char.ToLowerInvariant(ch) : '_');
            var r = sb.ToString().Trim('_');
            return r.Length == 0 ? "statue" : r;
        }

        static uint Fnv(string s)
        {
            uint h = 2166136261;
            foreach (var c in s.ToLowerInvariant()) { h ^= c; h *= 16777619; }
            return h;
        }

        // duz anahtar/deger; ic ice nesnelerin alanlari "nesne.alan" olarak okunur
        static Dictionary<string, string> ReadJson(string path)
        {
            var d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (!File.Exists(path)) return d;
            try
            {
                using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8),
                    new System.Text.Json.JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = System.Text.Json.JsonCommentHandling.Skip });
                void Walk(System.Text.Json.JsonElement e, string prefix)
                {
                    foreach (var p in e.EnumerateObject())
                    {
                        var v = p.Value;
                        string k = prefix.Length > 0 ? prefix + "." + p.Name : p.Name;
                        if (v.ValueKind == System.Text.Json.JsonValueKind.Object) { Walk(v, k); continue; }
                        d[k] = v.ValueKind == System.Text.Json.JsonValueKind.String ? v.GetString() ?? "" : v.GetRawText();
                    }
                }
                if (doc.RootElement.ValueKind == System.Text.Json.JsonValueKind.Object) Walk(doc.RootElement, "");
            }
            catch (Exception e) { Log.Warning("statue.json unreadable: " + path + " - " + e.Message); }
            return d;
        }

        static float F(Dictionary<string, string> d, string k, float def) =>
            d.TryGetValue(k, out var v) && float.TryParse(v.Replace(',', '.'), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var f) ? f : def;
        static string S(Dictionary<string, string> d, string k, string def) => d.TryGetValue(k, out var v) && v.Length > 0 ? v : def;

        // ------------------------------------------------------------------ build once

        void TryBuild()
        {
            var cfg = FindAll<ProductsConfig>().FirstOrDefault();
            var bcfg = FindAll<BuildingConfig>().FirstOrDefault();
            if (cfg == null || bcfg == null) return;
            var src = FindAll<PickupDefinition>().FirstOrDefault(d => SafeId(d) == _sourceId.Value);
            if (src == null) return;
            var srcBd = src.BuildingDefinition;
            if (srcBd == null || srcBd.Prefab == null) return;
            _src = src;

            var holder = new GameObject("StatueShop_Prefabs");
            holder.SetActive(false);
            UnityEngine.Object.DontDestroyOnLoad(holder);
            holder.hideFlags = HideFlags.HideAndDontSave;

            foreach (var it in Items)
            {
                try { BuildItem(it, src, srcBd, holder.transform, cfg, bcfg); }
                catch (Exception e) { Log.Error($"{it.NameEn}: {e}"); }
            }
            try { cfg.RebuildDefinitions(); } catch (Exception e) { Log.Warning("RebuildDefinitions: " + e.Message); }
            try { bcfg.Initialize(); } catch (Exception e) { Log.Warning("BuildingConfig.Initialize: " + e.Message); }

            _built = true;
            EnsureRegistered(log: true);
            EnsureLocalization(log: true);
            Log.Msg($"{_added}/{Items.Count} statues added.");
        }

        void BuildItem(Item it, PickupDefinition src, BuildingPieceDefinition srcBd, Transform holder, ProductsConfig cfg, BuildingConfig bcfg)
        {
            string dir = it.Dir;
            string model = Path.Combine(dir, "model.statue");
            if (!File.Exists(model)) { Log.Warning("Model missing: " + model); return; }

            var go = UnityEngine.Object.Instantiate<GameObject>(srcBd.Prefab.gameObject, holder);
            go.name = "Building_Decor_cst_" + it.Slug;
            BuildVisual(go, dir, model);

            it.Bd = UnityEngine.Object.Instantiate<BuildingPieceDefinition>(srcBd);
            it.Bd.name = "BuildingPiece_Decor_cst_" + it.Slug;
            it.Bd.hideFlags = HideFlags.DontUnloadUnusedAsset;
            it.Bd._id = it.BuildingId;
            it.Prefab = go.GetComponent<NetworkObject>();
            it.Bd._prefab = it.Prefab;
            var piece = go.GetComponent<BuildingPiece>();
            if (piece != null) piece._definition = it.Bd;

            it.Def = UnityEngine.Object.Instantiate<PickupDefinition>(src);
            it.Def.name = "Pickup_Decor_cst_" + it.Slug;
            it.Def.hideFlags = HideFlags.DontUnloadUnusedAsset;
            it.Def._id = it.PickupId;
            it.Def._buildingDefinition = it.Bd;
            it.Def._level = _level.Value;
            it.Def._price = Mathf.Round(it.Price * Mathf.Max(0.01f, _priceMul.Value));
            if (it.Level > 0) it.Def._level = it.Level;
                        it.Def._notAvailable = false;
            it.Def._nameKey = it.TermKey;
            ApplyIcon(it, Path.Combine(dir, "icon.png"));

            try { it.Prefab.SetInitializedValues(null, true); }
            catch (Exception e) { Log.Warning("SetInitializedValues: " + e.Message); }

            int lists = 0;
            lists += AddIfSourceIn(cfg._furnitureDefinitions, it);
            lists += AddIfSourceIn(cfg._decor2FloorDefinitions, it);
            if (lists == 0 && cfg._furnitureDefinitions != null) cfg._furnitureDefinitions.Add(it.Def);

            bcfg._allBuildingPieces = Append(bcfg._allBuildingPieces, it.Bd);
            if (Has(bcfg._availableStore, srcBd)) bcfg._availableStore = Append(bcfg._availableStore, it.Bd);
            if (Has(bcfg._availableStorage, srcBd)) bcfg._availableStorage = Append(bcfg._availableStorage, it.Bd);
            if (Has(bcfg._availableOutside, srcBd)) bcfg._availableOutside = Append(bcfg._availableOutside, it.Bd);
            if (Has(bcfg._available2Floor, srcBd)) bcfg._available2Floor = Append(bcfg._available2Floor, it.Bd);
            if (!Has(bcfg._availableStore, it.Bd) && !Has(bcfg._availableOutside, it.Bd) && !Has(bcfg._available2Floor, it.Bd))
                bcfg._availableStore = Append(bcfg._availableStore, it.Bd);
            _added++;
        }

        int AddIfSourceIn(Il2CppSystem.Collections.Generic.List<PickupDefinition> list, Item it)
        {
            if (list == null || !ContainsId(list, SafeId(_src))) return 0;
            if (!ContainsId(list, it.PickupId)) list.Add(it.Def);
            return 1;
        }

        // ------------------------------------------------------------------ visual

        void BuildVisual(GameObject go, string dir, string modelPath)
        {
            var root = go.transform;
            var oldRenderers = new List<Renderer>();
            foreach (var r in go.GetComponentsInChildren<Renderer>(true))
            {
                string n = r.gameObject.name ?? "";
                if (n.IndexOf("border", StringComparison.OrdinalIgnoreCase) < 0) oldRenderers.Add(r);
            }
            var oldB = MeshBounds(go, root, oldRenderers);
            foreach (var r in oldRenderers) { r.enabled = false; r.forceRenderingOff = true; }

            var data = Stat2File.Load(modelPath);
            var mesh = data.BuildMesh();
            var obj = new GameObject("GSPS_Model");
            obj.transform.SetParent(root, false);
            var ls = root.lossyScale;
            obj.transform.localScale = new Vector3(1f / Nz(ls.x), 1f / Nz(ls.y), 1f / Nz(ls.z));
            obj.transform.localPosition = oldRenderers.Count > 0 ? new Vector3(oldB.center.x, oldB.min.y, oldB.center.z) : Vector3.zero;
            try { obj.layer = oldRenderers.Count > 0 ? oldRenderers[0].gameObject.layer : go.layer; } catch { }

            obj.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mr = obj.AddComponent<MeshRenderer>();
            Material baseMat = null;
            foreach (var r in oldRenderers) { try { if (r.sharedMaterial != null) { baseMat = r.sharedMaterial; break; } } catch { } }
            var mats = new Il2CppReferenceArray<Material>(data.Parts.Count);
            for (int i = 0; i < data.Parts.Count; i++) mats[i] = MakeMaterial(baseMat, data.Parts[i], dir);
            mr.sharedMaterials = mats;
            mr.shadowCastingMode = ShadowCastingMode.On;
            mr.receiveShadows = true;

            var nb = MeshBounds(obj, root, new List<Renderer> { mr });

            // hareketli parca (or. Rift Sword): model.skin varsa kaidenin ustune iskeletli model
            string skinPath = Path.Combine(dir, "model.skin");
            if (File.Exists(skinPath))
            {
                try
                {
                    var sb = BuildSkinned(obj, root, dir, skinPath, baseMat);
                    nb.Encapsulate(sb.min); nb.Encapsulate(sb.max);
                }
                catch (Exception e) { Log.Error("Animated model: " + e); }
            }
            FitColliders(go, root, nb);
        }

        static readonly Dictionary<string, SkinFile> _skins = new();

        Bounds BuildSkinned(GameObject parent, Transform root, string dir, string path, Material baseMat)
        {
            string key = Path.GetFileName(dir);
            if (!_skins.TryGetValue(key, out var data)) { data = SkinFile.Load(path); _skins[key] = data; }
            int layer = parent.layer;

            var anim = new GameObject(AnimPrefix + key);
            anim.layer = layer;
            anim.transform.SetParent(parent.transform, false);
            anim.transform.localScale = Vector3.one * data.Scale;

            var skel = new GameObject("Skeleton");
            skel.layer = layer;
            skel.transform.SetParent(anim.transform, false);
            skel.transform.localPosition = new Vector3(-data.CenterX, -data.Floor, -data.CenterZ);
            var nodes = new Transform[data.Nodes.Count];
            for (int i = 0; i < nodes.Length; i++) { var g = new GameObject("n" + i); g.layer = layer; nodes[i] = g.transform; }
            for (int i = 0; i < nodes.Length; i++)
            {
                var nd = data.Nodes[i];
                nodes[i].SetParent(nd.Parent >= 0 ? nodes[nd.Parent] : skel.transform, false);
                nodes[i].localPosition = nd.T; nodes[i].localRotation = nd.R; nodes[i].localScale = nd.S;
            }
            data.Apply(nodes, 0f);

            for (int mi = 0; mi < data.Meshes.Count; mi++)
            {
                var m = data.Meshes[mi];
                var sk = data.Skins[m.Skin];
                var mo = new GameObject("Mesh" + mi);
                mo.layer = layer;
                mo.transform.SetParent(anim.transform, false);
                var smr = mo.AddComponent<SkinnedMeshRenderer>();
                var bones = new Il2CppReferenceArray<Transform>(sk.Joints.Length);
                for (int j = 0; j < sk.Joints.Length; j++) bones[j] = nodes[sk.Joints[j]];
                var builtMesh = m.BuildMesh(sk.BindPoses);
                smr.sharedMesh = builtMesh;
                _meshKey[builtMesh.Pointer] = key;   // animasyon taramasi bu meshleri arar
                smr.bones = bones;
                smr.rootBone = skel.transform;
                smr.quality = SkinQuality.Bone4;
                smr.updateWhenOffscreen = false;
                smr.localBounds = new Bounds(data.BoundsCenter, data.BoundsSize);
                var part = new Stat2Part
                {
                    Name = m.Name, Texture = m.Texture, EmissiveTexture = m.EmissiveTexture, AlphaMode = m.Clip,
                    DoubleSided = m.DoubleSided, BaseColor = m.BaseColor, Emissive = m.Emissive, Metallic = m.Metallic, Smoothness = m.Smoothness
                };
                smr.sharedMaterial = MakeMaterial(baseMat, part, dir);
                smr.shadowCastingMode = ShadowCastingMode.On;
                smr.receiveShadows = true;
            }

            // carpisma icin sinirlar (root uzayinda)
            var c = data.BoundsCenter; var e = data.BoundsSize * 0.5f;
            var mn = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue); var mx = -mn;
            for (int i = 0; i < 8; i++)
            {
                var pt = c + new Vector3((i & 1) == 0 ? -e.x : e.x, (i & 2) == 0 ? -e.y : e.y, (i & 4) == 0 ? -e.z : e.z);
                var rp = root.InverseTransformPoint(skel.transform.TransformPoint(pt));
                mn = Vector3.Min(mn, rp); mx = Vector3.Max(mx, rp);
            }
            var res = new Bounds(); res.SetMinMax(mn, mx);
            Log.Msg($"{key}: animated model, {data.Meshes.Count} parts, {data.Frames} frames.");
            return res;
        }

        // ------------------------------------------------------------------ animasyon

        const string AnimPrefix = "RGS_Anim_";
        readonly List<(Transform root, Transform[] nodes, SkinFile skin, float offset, Renderer vis)> _animated = new();
        // sabit (hic degismeyen) kanallari bir kere uygulanmis modeller
        readonly HashSet<IntPtr> _posed = new();
        int _spread;
        float _nextAnimScan;
        int _animErr;

        public override void OnLateUpdate()
        {
            if (!_built || _skins.Count == 0) return;
            try
            {
                if (Time.unscaledTime >= _nextAnimScan) { _nextAnimScan = Time.unscaledTime + 4f; ScanAnimated(); }
                if (_animated.Count == 0) return;
                var cam = Camera.main;
                Vector3 camPos = cam != null ? cam.transform.position : Vector3.zero;
                foreach (var a in _animated)
                {
                    if (a.root == null) continue;
                    // kameraya (ya da golgeye) girmeyen modelin kemiklerini oynatma
                    if (a.vis != null && !a.vis.isVisible) continue;
                    if (cam != null && (a.root.position - camPos).sqrMagnitude > 30f * 30f) continue;
                    float dur = a.skin.Frames / a.skin.Fps;
                    a.skin.Apply(a.nodes, (Time.time + a.offset) % dur, _posed.Add(a.root.Pointer));
                }
            }
            catch (Exception e) { if (_animErr++ < 3) Log.Warning("Animation: " + e.Message); }
        }

        readonly Dictionary<IntPtr, Transform[]> _nodeCache = new();
        static bool NodesValid(Transform[] nodes, Transform root)
        {
            foreach (var t in nodes) if (t != null) return t.IsChildOf(root);
            return false;
        }

        // Animasyonlu modelleri bul. Eskiden sahnedeki TUM mobilyalar (BuildingPiece) taraniyordu: buyuk dukkanda
        // 25-80 ms suruyor, 4 sn'de bir oyunu takiltiyordu. Artik sadece SkinnedMeshRenderer'lar (cok daha az) taraniyor
        // ve bizim meshimizi kullananlar seciliyor.
        static readonly Dictionary<IntPtr, string> _meshKey = new();
        void ScanAnimated()
        {
            _animated.Clear();
            if (_meshKey.Count == 0) return;
            var byMesh = SharedSmrScan();
            var seen = new HashSet<IntPtr>();
            foreach (var mk in _meshKey)
            {
                if (!byMesh.TryGetValue(mk.Key, out var smrs)) continue;
                if (!_skins.TryGetValue(mk.Value, out var skin)) continue;
                foreach (var smr in smrs)
                {
                    if (smr == null) continue;   // sahne degistiyse yok edilmis olabilir
                    var anim = smr.transform.parent;
                    if (anim == null || !seen.Add(anim.Pointer)) continue;
                    // kemik listesi her taramada bastan kurulmasin: daha once bulunduysa onu kullan
                    if (!_nodeCache.TryGetValue(anim.Pointer, out var nodes) || nodes.Length != skin.Nodes.Count || !NodesValid(nodes, anim))
                    {
                        var skel = anim.Find("Skeleton");
                        if (skel == null) continue;
                        nodes = new Transform[skin.Nodes.Count];
                        foreach (var tr in skel.GetComponentsInChildren<Transform>(true))
                        {
                            var n = tr.gameObject.name;
                            if (n.Length > 1 && n[0] == 'n' && int.TryParse(n.Substring(1), out int idx) && idx >= 0 && idx < nodes.Length) nodes[idx] = tr;
                        }
                        _nodeCache[anim.Pointer] = nodes;
                        _posed.Remove(anim.Pointer);
                    }
                    float off = (Mathf.Abs(anim.GetInstanceID()) % 1000) / 1000f * (skin.Frames / skin.Fps);
                    _animated.Add((anim, nodes, skin, off, smr));
                }
            }
            foreach (var dead in _nodeCache.Keys.Where(x => !seen.Contains(x)).ToList()) _nodeCache.Remove(dead);
            _posed.RemoveWhere(p => !seen.Contains(p));
        }

        // Sahnedeki SkinnedMeshRenderer taramasi TUM heykel modlari arasinda paylasilir (AppDomain uzerinden).
        // Eskiden 40+ heykel modu 4 sn'de bir ayni karede ayri ayri FindObjectsOfType yapiyordu (belirgin takilma).
        // Simdi ~4 sn'de bir tek tarama yapilir, sonuc mesh'e gore gruplanir, diger modlar hazir sonucu kullanir.
        const string SharedScanKey = "Fabianens.StatueSmrScan.v1";
        static Dictionary<IntPtr, List<SkinnedMeshRenderer>> SharedSmrScan()
        {
            float now = Time.unscaledTime;
            try
            {
                if (AppDomain.CurrentDomain.GetData(SharedScanKey) is object[] box && box.Length == 2 && box[0] is float at
                    && box[1] is Dictionary<IntPtr, List<SkinnedMeshRenderer>> cached && now >= at && now - at < 3.5f)
                    return cached;
            }
            catch { }
            var map = new Dictionary<IntPtr, List<SkinnedMeshRenderer>>();
            foreach (var o in UnityEngine.Object.FindObjectsOfType(Il2CppType.Of<SkinnedMeshRenderer>()))
            {
                var smr = o != null ? o.TryCast<SkinnedMeshRenderer>() : null;
                if (smr == null) continue;
                var mesh = smr.sharedMesh;
                if (mesh == null) continue;
                if (!map.TryGetValue(mesh.Pointer, out var list)) map[mesh.Pointer] = list = new List<SkinnedMeshRenderer>();
                list.Add(smr);
            }
            try { AppDomain.CurrentDomain.SetData(SharedScanKey, new object[] { now, map }); } catch { }
            return map;
        }

        void FitColliders(GameObject go, Transform root, Bounds nb)
        {
            foreach (var c in go.GetComponentsInChildren<Collider>(true))
            {
                try
                {
                    var t = c.transform;
                    var box = c.TryCast<BoxCollider>();
                    if (box == null)
                    {
                        bool trig = c.isTrigger;
                        c.enabled = false;
                        box = c.gameObject.AddComponent<BoxCollider>();
                        box.isTrigger = trig;
                    }
                    var min = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue); var max = -min;
                    for (int i = 0; i < 8; i++)
                    {
                        var p = new Vector3((i & 1) == 0 ? nb.min.x : nb.max.x, (i & 2) == 0 ? nb.min.y : nb.max.y, (i & 4) == 0 ? nb.min.z : nb.max.z);
                        var lp = t.InverseTransformPoint(root.TransformPoint(p));
                        min = Vector3.Min(min, lp); max = Vector3.Max(max, lp);
                    }
                    box.center = (min + max) * 0.5f;
                    box.size = max - min;
                }
                catch { }
            }
        }

        static readonly Dictionary<string, Texture2D> _texCache = new();
        static Texture2D LoadTexture(string dir, string file)
        {
            if (string.IsNullOrEmpty(file)) return null;
            string p = Path.Combine(dir, file);
            if (_texCache.TryGetValue(p, out var t)) return t;
            // paketlemede BC7'ye cevrilmis doku (ayni ad, .bc7) varsa PNG cozulmeden yuklenir: ekran kartinda 4 kat az yer, acilis hizli
            t = Bc7Tex.Load(p);
            if (t != null) { t.name = Path.GetFileName(p); t.hideFlags = HideFlags.DontUnloadUnusedAsset; t.anisoLevel = 4; _texCache[p] = t; return t; }
            if (!File.Exists(p)) { _texCache[p] = null; return null; }
            t = new Texture2D(2, 2, TextureFormat.RGBA32, true);
            if (!ImageConversion.LoadImage(t, File.ReadAllBytes(p), true)) t = null;
            else { t.name = file; t.hideFlags = HideFlags.DontUnloadUnusedAsset; t.anisoLevel = 4; }
            _texCache[p] = t;
            return t;
        }

        Material MakeMaterial(Material baseMat, Stat2Part part, string dir)
        {
            Shader lit = Shader.Find("Universal Render Pipeline/Lit");
            Material m;
            if (baseMat != null && baseMat.shader != null && baseMat.shader.name == "Universal Render Pipeline/Lit") m = new Material(baseMat);
            else if (lit != null) m = new Material(lit);
            else m = new Material(baseMat);
            m.name = "RGS_" + part.Name;
            m.hideFlags = HideFlags.DontUnloadUnusedAsset;

            var tex = LoadTexture(dir, part.Texture);
            SetTex(m, "_BaseMap", tex); SetTex(m, "_MainTex", tex);
            var bc = new Color(part.BaseColor.x, part.BaseColor.y, part.BaseColor.z, 1f);
            SetColor(m, "_BaseColor", bc); SetColor(m, "_Color", bc);
            foreach (var p in new[] { "_BumpMap", "_MetallicGlossMap", "_OcclusionMap", "_SpecGlossMap", "_ParallaxMap", "_DetailAlbedoMap", "_DetailNormalMap" }) SetTex(m, p, null);
            foreach (var k in new[] { "_NORMALMAP", "_METALLICSPECGLOSSMAP", "_OCCLUSIONMAP", "_PARALLAXMAP", "_DETAIL_MULX2", "_SPECGLOSSMAP" }) m.DisableKeyword(k);
            SetFloat(m, "_Metallic", part.Metallic);
            SetFloat(m, "_Smoothness", part.Smoothness);
            SetFloat(m, "_Glossiness", part.Smoothness);

            // isik saçan parcalar (lav, buyu kristali...)
            bool emissive = part.Emissive.x + part.Emissive.y + part.Emissive.z > 0.01f;
            if (emissive)
            {
                var et = LoadTexture(dir, part.EmissiveTexture);
                SetTex(m, "_EmissionMap", et);
                SetColor(m, "_EmissionColor", new Color(part.Emissive.x, part.Emissive.y, part.Emissive.z, 1f));
                m.EnableKeyword("_EMISSION");
                m.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            }
            else
            {
                SetTex(m, "_EmissionMap", null);
                SetColor(m, "_EmissionColor", Color.black);
                m.DisableKeyword("_EMISSION");
            }

            SetFloat(m, "_Surface", 0f);
            m.DisableKeyword("_SURFACE_TYPE_TRANSPARENT");
            SetFloat(m, "_SrcBlend", 1f); SetFloat(m, "_DstBlend", 0f); SetFloat(m, "_ZWrite", 1f);
            if (part.AlphaMode == 2)
            {
                // yari saydam (isik efektleri)
                SetFloat(m, "_Surface", 1f); SetFloat(m, "_Blend", 0f);
                m.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
                SetFloat(m, "_SrcBlend", 5f); SetFloat(m, "_DstBlend", 10f); SetFloat(m, "_ZWrite", 0f);
                SetFloat(m, "_AlphaClip", 0f); m.DisableKeyword("_ALPHATEST_ON");
                m.SetOverrideTag("RenderType", "Transparent");
                m.renderQueue = 3000;
                var c0 = m.HasProperty("_BaseColor") ? m.GetColor("_BaseColor") : Color.white;
                SetColor(m, "_BaseColor", new Color(c0.r, c0.g, c0.b, part.BaseColor.w)); SetColor(m, "_Color", new Color(c0.r, c0.g, c0.b, part.BaseColor.w));
            }
            else if (part.AlphaMode == 1)
            {
                SetFloat(m, "_AlphaClip", 1f); SetFloat(m, "_Cutoff", 0.5f); m.EnableKeyword("_ALPHATEST_ON"); m.renderQueue = 2450;
            }
            else
            {
                SetFloat(m, "_AlphaClip", 0f); m.DisableKeyword("_ALPHATEST_ON"); m.renderQueue = 2000;
            }
            SetFloat(m, "_Cull", part.DoubleSided ? 0f : 2f);
            return m;
        }

        static void SetTex(Material m, string n, Texture t) { if (m.HasProperty(n)) m.SetTexture(n, t); }
        static void SetColor(Material m, string n, Color c) { if (m.HasProperty(n)) m.SetColor(n, c); }
        static void SetFloat(Material m, string n, float v) { if (m.HasProperty(n)) m.SetFloat(n, v); }
        static float Nz(float v) => Mathf.Abs(v) < 1e-5f ? 1f : v;

        static Bounds MeshBounds(GameObject go, Transform root, List<Renderer> only)
        {
            var list = only ?? go.GetComponentsInChildren<Renderer>(true).ToList();
            bool any = false; var min = Vector3.zero; var max = Vector3.zero;
            foreach (var r in list)
            {
                Mesh mesh = null;
                var smr = r.TryCast<SkinnedMeshRenderer>();
                if (smr != null) mesh = smr.sharedMesh;
                else { var mf = r.GetComponent<MeshFilter>(); if (mf != null) mesh = mf.sharedMesh; }
                if (mesh == null) continue;
                var b = mesh.bounds;
                for (int i = 0; i < 8; i++)
                {
                    var p = new Vector3((i & 1) == 0 ? b.min.x : b.max.x, (i & 2) == 0 ? b.min.y : b.max.y, (i & 4) == 0 ? b.min.z : b.max.z);
                    var lp = root.InverseTransformPoint(r.transform.TransformPoint(p));
                    if (!any) { min = max = lp; any = true; }
                    else { min = Vector3.Min(min, lp); max = Vector3.Max(max, lp); }
                }
            }
            var res = new Bounds(); res.SetMinMax(min, max); return res;
        }

        void ApplyIcon(Item it, string path)
        {
            try
            {
                if (!File.Exists(path)) return;
                var tex = new Texture2D(2, 2, TextureFormat.RGBA32, true);
                if (!ImageConversion.LoadImage(tex, File.ReadAllBytes(path), false)) return;
                tex.hideFlags = HideFlags.DontUnloadUnusedAsset;
                tex.wrapMode = TextureWrapMode.Clamp;
                tex.Apply(true, true);
                var sp = Sprite.Create(tex, new Rect(0, 0, tex.width, tex.height), new Vector2(0.5f, 0.5f), 100f);
                sp.name = "CST_" + it.Slug;
                sp.hideFlags = HideFlags.DontUnloadUnusedAsset;
                it.Def._icon = sp;
                if (it.Bd != null) it.Bd._icon = sp;
            }
            catch (Exception e) { Log.Warning("Icon: " + e.Message); }
        }

        // ------------------------------------------------------------------ keep registered

        static void EnsureRegistered(bool log = false)
        {
            if (_cfgCache == null || _cfgCache.WasCollected) _cfgCache = FindAll<ProductsConfig>().FirstOrDefault();
            var cfg = _cfgCache;
            bool changed = false;
            foreach (var it in Items)
            {
                if (it.Def == null) continue;
                if (cfg != null)
                {
                    foreach (var list in new[] { cfg._furnitureDefinitions, cfg._decor2FloorDefinitions })
                        if (list != null && _src != null && ContainsId(list, SafeId(_src)) && !ContainsId(list, it.PickupId)) { list.Add(it.Def); changed = true; }
                    try { var dict = cfg._pickupDict; if (dict != null && !dict.ContainsKey(it.PickupId)) dict.Add(it.PickupId, it.Def); } catch { }
                }
                try { var d = PickupDB.s_DefinitionsById; if (d != null && !d.ContainsKey(it.PickupId)) d.Add(it.PickupId, it.Def); }
                catch (Exception e) { if (log) MelonLogger.Warning("PickupDB: " + e.Message); }
                try { var d = BuildingDB.s_DefinitionsById; if (d != null && !d.ContainsKey(it.BuildingId)) d.Add(it.BuildingId, it.Bd); }
                catch (Exception e) { if (log) MelonLogger.Warning("BuildingDB: " + e.Message); }
            }
            if (changed && cfg != null) { try { cfg.RebuildDefinitions(); } catch { } }
        }

        void EnsureNetworkPrefabs()
        {
            var nm = InstanceFinder.NetworkManager;
            if (nm == null || nm.Pointer == _registeredNm) return;
            var objs = nm.SpawnablePrefabs;
            if (objs == null) return;
            foreach (var it in Items) if (it.Prefab != null) objs.AddObject(it.Prefab, true, true);
            _registeredNm = nm.Pointer;
            Log.Msg("Network prefabs registered.");
        }

        static void EnsureLocalization(bool log = false)
        {
            try
            {
                LanguageSourceData src = null;
                LocalizationManager.GetTermData(RefTermKey, out src);
                if (src == null) { var all = LocalizationManager.Sources; if (all != null && all.Count > 0) src = all[0]; }
                if (src == null) return;
                var langs = src.mLanguages;
                int n = langs != null ? langs.Count : 0;
                foreach (var it in Items)
                {
                    var term = src.GetTermData(it.TermKey, false) ?? src.AddTerm(it.TermKey);
                    if (term == null) continue;
                    if (term.Languages == null || term.Languages.Length < n) term.Languages = new Il2CppStringArray(n);
                    for (int i = 0; i < n; i++)
                    {
                        string code = langs[i].Code ?? "";
                        string want = code.StartsWith("tr", StringComparison.OrdinalIgnoreCase) ? it.NameTr : it.NameEn;
                        if (term.Languages[i] != want) term.Languages[i] = want;
                    }
                    var dict = src.mDictionary;
                    if (dict != null && !dict.ContainsKey(it.TermKey)) dict.Add(it.TermKey, term);
                }
                if (log) MelonLogger.Msg($"Names added ({n} languages).");
            }
            catch (Exception e) { if (log) MelonLogger.Warning("Localization: " + e.Message); }
        }

        // ------------------------------------------------------------------ helpers

        static bool Has(Il2CppReferenceArray<BuildingPieceDefinition> arr, BuildingPieceDefinition item)
        {
            if (arr == null || item == null) return false;
            int id = SafeId(item);
            for (int i = 0; i < arr.Length; i++) if (arr[i] != null && SafeId(arr[i]) == id) return true;
            return false;
        }

        static Il2CppReferenceArray<BuildingPieceDefinition> Append(Il2CppReferenceArray<BuildingPieceDefinition> arr, BuildingPieceDefinition item)
        {
            if (Has(arr, item)) return arr;
            int len = arr != null ? arr.Length : 0;
            var res = new Il2CppReferenceArray<BuildingPieceDefinition>(len + 1);
            for (int i = 0; i < len; i++) res[i] = arr[i];
            res[len] = item;
            return res;
        }

        // Bu kontrol her 15 sn'de bir calisiyor. Eskiden listedeki her urun icin oyuna birkac cagri yapiyordu
        // (yuzlerce urun x birkac liste = binlerce cagri) ve oyunda kisa bir takilma yapiyordu.
        // Artik liste degismediyse (ayni liste, ayni eleman sayisi) onceki sonuc kullaniliyor.
        static readonly Dictionary<IntPtr, (int count, HashSet<int> ids)> _idCache = new();
        static bool ContainsId(Il2CppSystem.Collections.Generic.List<PickupDefinition> list, int id)
        {
            int n = list.Count;
            var key = list.Pointer;
            if (!_idCache.TryGetValue(key, out var c) || c.count != n)
            {
                var ids = new HashSet<int>();
                for (int i = 0; i < n; i++) { var e = list[i]; if (e != null) ids.Add(SafeId(e)); }
                c = (n, ids);
                _idCache[key] = c;
            }
            return c.ids.Contains(id);
        }

        static int SafeId(DDef d) { try { return d._id; } catch { return 0; } }

        static IEnumerable<T> FindAll<T>() where T : Il2CppObjectBase
        {
            var arr = Resources.FindObjectsOfTypeAll(Il2CppType.Of<T>());
            foreach (var o in arr)
            {
                var t = o != null ? o.TryCast<T>() : null;
                if (t != null) yield return t;
            }
        }
    }

    // ---------------------------------------------------------------------- model file (STAT2)

    internal class Stat2Part
    {
        public string Name, Texture, EmissiveTexture;
        public int AlphaMode; public bool DoubleSided;
        public Vector4 BaseColor; public Vector3 Emissive;
        public float Metallic, Smoothness;
        public Vector3[] Pos, Nrm; public Vector2[] Uv; public int[] Idx;
    }

    internal class Stat2File
    {
        public List<Stat2Part> Parts = new();
        static string Str(BinaryReader br) => Encoding.UTF8.GetString(br.ReadBytes(br.ReadInt32()));

        public static Stat2File Load(string path)
        {
            using var br = new BinaryReader(File.OpenRead(path));
            if (Encoding.ASCII.GetString(br.ReadBytes(5)) != "STAT2") throw new Exception("Invalid model file");
            int n = br.ReadInt32();
            var f = new Stat2File();
            for (int k = 0; k < n; k++)
            {
                var p = new Stat2Part { Name = Str(br), Texture = Str(br) };
                p.AlphaMode = br.ReadByte(); p.DoubleSided = br.ReadByte() != 0;
                p.BaseColor = new Vector4(br.ReadSingle(), br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                p.EmissiveTexture = Str(br);
                p.Emissive = new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                p.Metallic = br.ReadSingle(); p.Smoothness = br.ReadSingle();
                int v = br.ReadInt32();
                p.Pos = new Vector3[v]; p.Nrm = new Vector3[v]; p.Uv = new Vector2[v];
                for (int i = 0; i < v; i++) p.Pos[i] = new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                for (int i = 0; i < v; i++) p.Nrm[i] = new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                for (int i = 0; i < v; i++) p.Uv[i] = new Vector2(br.ReadSingle(), br.ReadSingle());
                int ic = br.ReadInt32();
                p.Idx = new int[ic];
                for (int i = 0; i < ic; i++) p.Idx[i] = br.ReadInt32();
                f.Parts.Add(p);
            }
            return f;
        }

        public Mesh BuildMesh()
        {
            int total = Parts.Sum(p => p.Pos.Length);
            var pos = new Vector3[total]; var nrm = new Vector3[total]; var uv = new Vector2[total];
            int o = 0;
            foreach (var p in Parts)
            {
                Array.Copy(p.Pos, 0, pos, o, p.Pos.Length);
                Array.Copy(p.Nrm, 0, nrm, o, p.Nrm.Length);
                Array.Copy(p.Uv, 0, uv, o, p.Uv.Length);
                o += p.Pos.Length;
            }
            var mesh = new Mesh { name = "GSPS_Model" };
            mesh.indexFormat = IndexFormat.UInt32;
            mesh.vertices = pos; mesh.normals = nrm; mesh.uv = uv;
            mesh.subMeshCount = Parts.Count;
            o = 0;
            for (int s = 0; s < Parts.Count; s++)
            {
                var src = Parts[s].Idx;
                var idx = new int[src.Length];
                for (int i = 0; i < src.Length; i++) idx[i] = src[i] + o;
                mesh.SetTriangles(idx, s, false);
                o += Parts[s].Pos.Length;
            }
            mesh.RecalculateBounds();
            mesh.hideFlags = HideFlags.DontUnloadUnusedAsset;
            mesh.UploadMeshData(true);
            return mesh;
        }
    }

    // ---------------------------------------------------------------------- hareketli model dosyasi (SKIN2)

    internal class SkinNode { public string Name; public int Parent; public Vector3 T; public Quaternion R; public Vector3 S; }
    internal class SkinSkin { public int[] Joints; public Matrix4x4[] BindPoses; }
    internal class SkinChannel
    {
        public int Node; public int Path; public float[] Data;
        public bool Const;   // butun karelerde ayni deger: her karede yeniden yazmaya gerek yok

        public static bool IsConst(float[] d, int k)
        {
            for (int j = k; j < d.Length; j++) if (Mathf.Abs(d[j] - d[j % k]) > 1e-6f) return false;
            return true;
        }
    }

    internal class SkinMesh
    {
        public string Name, Texture, EmissiveTexture; public int Clip; public bool DoubleSided; public int Skin;
        public Vector4 BaseColor; public Vector3 Emissive; public float Metallic, Smoothness;
        public Vector3[] Pos, Nrm; public Vector2[] Uv; public int[] J; public float[] W; public int[] Idx;

        public Mesh BuildMesh(Matrix4x4[] bindPoses)
        {
            int n = Pos.Length;
            var mesh = new Mesh { name = Name };
            mesh.indexFormat = IndexFormat.UInt32;
            mesh.vertices = Pos; mesh.normals = Nrm; mesh.uv = Uv;
            mesh.SetTriangles(Idx, 0, false);
            var bw = new Il2CppStructArray<BoneWeight>(n);
            for (int i = 0; i < n; i++)
            {
                var b = new BoneWeight();
                b.boneIndex0 = J[i * 4]; b.weight0 = W[i * 4];
                b.boneIndex1 = J[i * 4 + 1]; b.weight1 = W[i * 4 + 1];
                b.boneIndex2 = J[i * 4 + 2]; b.weight2 = W[i * 4 + 2];
                b.boneIndex3 = J[i * 4 + 3]; b.weight3 = W[i * 4 + 3];
                bw[i] = b;
            }
            mesh.boneWeights = bw;
            var bp = new Il2CppStructArray<Matrix4x4>(bindPoses.Length);
            for (int i = 0; i < bindPoses.Length; i++) bp[i] = bindPoses[i];
            mesh.bindposes = bp;
            mesh.RecalculateBounds();
            mesh.hideFlags = HideFlags.DontUnloadUnusedAsset;
            mesh.UploadMeshData(true);
            return mesh;
        }
    }

    internal class SkinFile
    {
        public float Scale, CenterX, Floor, CenterZ, Fps;
        public Vector3 BoundsCenter, BoundsSize;
        public int Frames;
        public List<SkinNode> Nodes = new();
        public List<SkinSkin> Skins = new();
        public List<SkinMesh> Meshes = new();
        public List<SkinChannel> Channels = new();

        static string Str(BinaryReader br) => Encoding.UTF8.GetString(br.ReadBytes(br.ReadInt32()));
        static Vector3 V3(BinaryReader br) => new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());

        public static SkinFile Load(string path)
        {
            using var br = new BinaryReader(File.OpenRead(path));
            if (Encoding.ASCII.GetString(br.ReadBytes(5)) != "SKIN2") throw new Exception("Invalid animated model file");
            var f = new SkinFile();
            f.Scale = br.ReadSingle(); f.CenterX = br.ReadSingle(); f.Floor = br.ReadSingle(); f.CenterZ = br.ReadSingle();
            f.BoundsCenter = V3(br); f.BoundsSize = V3(br);
            int nn = br.ReadInt32();
            for (int i = 0; i < nn; i++)
            {
                var n = new SkinNode { Name = Str(br), Parent = br.ReadInt32() };
                n.T = V3(br);
                n.R = new Quaternion(br.ReadSingle(), br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                n.S = V3(br);
                f.Nodes.Add(n);
            }
            int ns = br.ReadInt32();
            for (int i = 0; i < ns; i++)
            {
                int jc = br.ReadInt32();
                var s = new SkinSkin { Joints = new int[jc], BindPoses = new Matrix4x4[jc] };
                for (int j = 0; j < jc; j++) s.Joints[j] = br.ReadInt32();
                for (int j = 0; j < jc; j++)
                {
                    var a = new float[16];
                    for (int k = 0; k < 16; k++) a[k] = br.ReadSingle(); // satir satir
                    s.BindPoses[j] = new Matrix4x4(
                        new Vector4(a[0], a[4], a[8], a[12]), new Vector4(a[1], a[5], a[9], a[13]),
                        new Vector4(a[2], a[6], a[10], a[14]), new Vector4(a[3], a[7], a[11], a[15]));
                }
                f.Skins.Add(s);
            }
            int nm = br.ReadInt32();
            for (int i = 0; i < nm; i++)
            {
                var m = new SkinMesh { Name = Str(br), Texture = Str(br) };
                m.Clip = br.ReadByte(); m.DoubleSided = br.ReadByte() != 0; m.Skin = br.ReadInt32();
                m.BaseColor = new Vector4(br.ReadSingle(), br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                m.EmissiveTexture = Str(br);
                m.Emissive = V3(br);
                m.Metallic = br.ReadSingle(); m.Smoothness = br.ReadSingle();
                int v = br.ReadInt32();
                m.Pos = new Vector3[v]; m.Nrm = new Vector3[v]; m.Uv = new Vector2[v]; m.J = new int[v * 4]; m.W = new float[v * 4];
                for (int k = 0; k < v; k++) m.Pos[k] = V3(br);
                for (int k = 0; k < v; k++) m.Nrm[k] = V3(br);
                for (int k = 0; k < v; k++) m.Uv[k] = new Vector2(br.ReadSingle(), br.ReadSingle());
                for (int k = 0; k < v * 4; k++) m.J[k] = br.ReadInt32();
                for (int k = 0; k < v * 4; k++) m.W[k] = br.ReadSingle();
                int ic = br.ReadInt32();
                m.Idx = new int[ic];
                for (int k = 0; k < ic; k++) m.Idx[k] = br.ReadInt32();
                f.Meshes.Add(m);
            }
            f.Fps = br.ReadSingle(); f.Frames = br.ReadInt32();
            int nc = br.ReadInt32();
            for (int i = 0; i < nc; i++)
            {
                var c = new SkinChannel { Node = br.ReadInt32(), Path = br.ReadByte() };
                int k = c.Path == 1 ? 4 : 3;
                c.Data = new float[f.Frames * k];
                for (int j = 0; j < c.Data.Length; j++) c.Data[j] = br.ReadSingle();
                c.Const = SkinChannel.IsConst(c.Data, k);
                f.Channels.Add(c);
            }
            return f;
        }

        // t (saniye) anindaki pozu uygula; full=false: sabit kanallar atlanir (onceden uygulandi)
        public void Apply(Transform[] nodes, float t, bool full = true)
        {
            float ft = t * Fps;
            int i0 = Mathf.Clamp((int)ft, 0, Frames - 1);
            int i1 = (i0 + 1) % Frames;
            float a = Mathf.Clamp01(ft - i0);
            foreach (var c in Channels)
            {
                if (c.Const && !full) continue;
                if (c.Node < 0 || c.Node >= nodes.Length) continue;
                var tr = nodes[c.Node];
                if (tr == null) continue;
                var d = c.Data;
                if (c.Path == 1)
                {
                    int p = i0 * 4, q = i1 * 4;
                    float qx = d[q], qy = d[q + 1], qz = d[q + 2], qw = d[q + 3];
                    if (d[p] * qx + d[p + 1] * qy + d[p + 2] * qz + d[p + 3] * qw < 0) { qx = -qx; qy = -qy; qz = -qz; qw = -qw; }
                    float x = d[p] + (qx - d[p]) * a, y = d[p + 1] + (qy - d[p + 1]) * a;
                    float z = d[p + 2] + (qz - d[p + 2]) * a, w = d[p + 3] + (qw - d[p + 3]) * a;
                    float len = Mathf.Sqrt(x * x + y * y + z * z + w * w);
                    if (len > 1e-6f) tr.localRotation = new Quaternion(x / len, y / len, z / len, w / len);
                }
                else
                {
                    int p = i0 * 3, q = i1 * 3;
                    var v = new Vector3(d[p] + (d[q] - d[p]) * a, d[p + 1] + (d[q + 1] - d[p + 1]) * a, d[p + 2] + (d[q + 2] - d[p + 2]) * a);
                    if (c.Path == 0) tr.localPosition = v; else tr.localScale = v;
                }
            }
        }
    }
}
