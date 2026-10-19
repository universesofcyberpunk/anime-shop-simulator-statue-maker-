# Statue Maker - StatueShop gercek boy heykel uretici (Fabianens). Figure Maker'dan catallandi.
# glTF / GLB / Sketchfab zip / FBX / OBJ / BLEND  ->  <Ad>\ klasoru: model.statue (+ model.skin) + dokular (.bc7) + statue.json + icon.png + license.txt
# Klasor UserData\StatueShop\ icine konunca oyunda Mod Market'in MODLAR ekraninda (Heykeller) satilir.
# Sabit heykel: secilen animasyon karesinde (ya da dinlenme pozunda) donmus model. Animasyonlu heykel: butun model
# secilen animasyonu dongude oynar (model.statue bos bir yer tutucu, model.skin hareketli model).
#
# Kullanim:  python statuemaker.py                      (toplu pencere: surukle-birak / coklu secim, sirayla cevirir)
#            python statuemaker.py <model.glb|.gltf|.zip> [--name Ad] [--en "English name"] [--tr "Türkçe ad"]
#                                  [--pose AnimasyonAdi] [--pose-time 0] [--animated] [--height 1.8] [--price 15000] [--install]
import sys, os, re, math, json, shutil, struct, zipfile, glob, subprocess, argparse, traceback
FROZEN = getattr(sys, 'frozen', False)
HERE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))          # betikler / sablonlar
BASE = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))   # out\, work\
sys.path.insert(0, os.path.join(HERE, 'tools'))
import numpy as np
from PIL import Image
import conv, gl, standalone, bc7

def _find_game():
    d = BASE
    for _ in range(6):
        if os.path.exists(os.path.join(d, 'Anime Shop Simulator.exe')): return d
        d = os.path.dirname(d)
    for d in (r"C:\Program Files (x86)\Steam\steamapps\common\Anime Shop Simulator", r"D:\SteamLibrary\steamapps\common\Anime Shop Simulator"):
        if os.path.exists(os.path.join(d, 'Anime Shop Simulator.exe')): return d
    return None
GAME = _find_game() or BASE
USERDATA = os.path.join(GAME, 'UserData', 'StatueShop')
BLENDERS = [r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"] + sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
BLENDER = next((b for b in BLENDERS if os.path.exists(b)), None)


LOG_SINK = None   # kuyruk penceresi acikken satirlari oraya da gonderir (is parcacigindan guvenli: queue.Queue.put)
def log(*a):
    print('[StatueMaker]', *a, flush=True)
    if LOG_SINK: LOG_SINK(' '.join(str(x) for x in a))


def folder_name(s):
    s = re.sub(r'[^A-Za-z0-9_\- ]+', '', s).strip()
    s = re.sub(r'[\s\-]+', '_', s)
    return s[:40] or 'Statue'


def pretty(s):
    s = re.sub(r'[_\-]+', ' ', s).strip()
    return ' '.join(w[:1].upper() + w[1:] for w in s.split())


def find_source(path, work):
    """zip ise ac; FBX / OBJ / BLEND ise Blender ile GLB'ye cevir; glb/gltf yolunu dondur"""
    if os.path.splitext(path)[1].lower() in ('.fbx', '.obj', '.blend'):
        if not BLENDER: raise FMError('err_blender')
        out = os.path.join(work, 'src.glb')
        r = subprocess.run([BLENDER, '-b', '--factory-startup', '-P', os.path.join(HERE, 'tools', 'fbx2glb.py'), '--', path, out],
                           capture_output=True, text=True, encoding='utf-8', errors='ignore')
        if 'FBX2GLB ok' not in r.stdout or not os.path.exists(out): raise FMError('err_fbx', r.stdout[-1200:] + r.stderr[-800:])
        lp = os.path.join(os.path.dirname(path), 'license.txt')
        if os.path.exists(lp): shutil.copy(lp, os.path.join(work, 'license.txt'))
        log('FBX/OBJ/BLEND -> GLB:', out)
        return out
    if path.lower().endswith('.zip'):
        d = os.path.join(work, 'src'); shutil.rmtree(d, True); os.makedirs(d)
        zipfile.ZipFile(path).extractall(d)
        c = glob.glob(d + '/**/*.gltf', recursive=True) + glob.glob(d + '/**/*.glb', recursive=True)
        if not c: raise FMError('err_zip')
        return c[0]
    return path


def tri_count(g):
    t = 0
    for i in gl.scene_nodes(g.j):
        n = g.j['nodes'][i]
        if 'mesh' in n:
            for pr in g.j['meshes'][n['mesh']]['primitives']:
                if pr.get('mode', 4) != 4: continue
                a = g.j['accessors'][pr['indices']]['count'] if 'indices' in pr else g.j['accessors'][pr['attributes']['POSITION']]['count']
                t += a // 3
    return t


def render_icon(modeldir, yaw, front=None, frame=0):
    """posed model.skin -> <modeldir>\\icon.png (256, seffaf), yerlesik cizici (Blender gerekmez)"""
    try:
        return standalone.render_icon(modeldir, os.path.join(modeldir, 'icon.png'), yaw, front=front, frame=frame)
    except Exception as e:
        log('ikon cizilemedi:', e); return False


def credits(g, src):
    """yazar / kaynak / lisans: glb asset.extras (Sketchfab) ya da license.txt"""
    ex = (g.j.get('asset') or {}).get('extras') or {}
    lic = getattr(g, 'license', '') or ''
    if not lic:
        lp = os.path.join(os.path.dirname(src), 'license.txt')
        if os.path.exists(lp): lic = open(lp, encoding='utf-8', errors='ignore').read()
    info = dict(title=str(ex.get('title') or ''), author=str(ex.get('author') or ''), source=str(ex.get('source') or ''), license=str(ex.get('license') or ''))
    if lic:
        m = re.search(r'model[^"]*"([^"]+)"', lic, re.I)
        if m and not info['title']: info['title'] = m.group(1)
        m = re.search(r'\(https?://sketchfab\.com/3d-models/[^)]+\)', lic)
        if m and not info['source']: info['source'] = m.group(0)[1:-1]
        m = re.search(r'by\s+(.+?)\s*\(https?://sketchfab\.com/(?!3d-models)', lic)
        if m and not info['author']: info['author'] = m.group(1).strip()
        m = re.search(r'(CC-BY[-A-Z0-9.]*|CC0[-0-9.]*|Standard license|Free Standard|Editorial)', lic, re.I)
        if m and not info['license']: info['license'] = m.group(1)
    if not lic and any(info.values()):
        lic = f'Model: "{info["title"]}" ({info["source"]}) by {info["author"]}, {info["license"]}'
    return info, lic


# ---------------- dil dosyalari / language files ----------------
# exe'nin yanindaki lang\<kod>.json; ilk calismada en.json ve tr.json yazilir, sonra hep oradan okunur.
# Yeni dil: lang\de.json gibi bir dosya ekle ("_name": "Deutsch"); dil listesi her acilista klasoru yeniden tarar.
LANG_DIR = os.path.join(BASE, 'lang')
SETTINGS = os.path.join(BASE, 'settings.json')
STRINGS = {
    'en': {
        '_name': 'English',
        'language': 'Language',
        'app_sub': 'Turns 3D models into life-size statues for Statue Shop',
        'hint': 'Drop 3D models or folders onto this window, or use Add files. Press Start and they are converted one after another.',
        'drop_here': 'Drop models here\n.glb  .gltf  .zip  .fbx  .obj  .blend',
        'col_model': 'Model', 'col_folder': 'Output folder', 'col_status': 'Status',
        'st_wait': 'Waiting', 'st_edit': 'Editing', 'st_run': 'Converting…', 'st_done': 'Done', 'st_err': 'Error',
        'btn_add': 'Add files…', 'btn_add_folder': 'Add folder…', 'btn_edit': 'Edit…', 'btn_remove': 'Remove',
        'btn_retry': 'Retry', 'btn_clear': 'Clear finished', 'btn_out': 'Open output folder', 'btn_start': 'Start',
        'btn_running': 'Converting…', 'btn_details_show': 'Show details', 'btn_details_hide': 'Hide details',
        'install': 'Also install into the game (UserData\\StatueShop)',
        'stat_empty': 'Add models to begin.',
        'stat_ready': '{total} in the queue. Press Start.',
        'stat_running': 'Converting {name} ({done} of {total} finished)',
        'stat_finished': 'Finished: {ok} done, {bad} failed. Copy the folders into UserData\\StatueShop and restart the game.',
        'msg_no_models': 'No supported model was found.\nSupported: {types}',
        'msg_nothing_waiting': 'Nothing is waiting in the queue.',
        'msg_select_one': 'Select one waiting model.',
        'msg_close_running': 'Conversion is still running. Close anyway?',
        'dlg_models': 'Choose models', 'dlg_folder': 'Choose a folder with models',
        'form_title': 'Statue settings',
        'sec_statue': 'Statue', 'f_folder': 'Folder name', 'f_en': 'Name in English', 'f_tr': 'Name in Turkish',
        'f_pose': 'Pose (animation)', 'f_price': 'Price', 'f_height': 'Height in metres',
        'f_animated': 'Animated: the statue plays this animation in a loop',
        'f_up': 'Up axis of the model', 'up_auto': 'Automatic',
        'sec_preview': 'Preview', 'pv_loading': 'Loading preview…',
        'pv_hint': 'Drag left / right to turn, up / down to tip it over. Drag with the right button to tip it sideways. The side you see faces the customers.',
        'pv_tip': 'Tip over 90°', 'pv_side': 'Tip sideways 90°', 'pv_turn': 'Turn 180°', 'pv_auto': 'Automatic',
        'pv_autostate': 'Orientation: automatic', 'pv_manual': 'Orientation: set by hand',
        'pv_frame': 'Frame {n} / {total} ({sec} s) – the statue is made in this frame', 'pv_frame_rest': 'No animation: rest pose',
        'sec_parts': 'Parts', 'col_part': 'Part', 'col_tris': 'Triangles', 'col_note': 'Note',
        'parts_hint': 'Click a part to leave it out of the statue (or take it back). Left-out parts are not drawn and do not count for the height.',
        'pt_auto': 'invisible / effect', 'pt_far': 'far from the body', 'pt_off': 'left out', 'btn_parts_auto': 'Automatic',
        'req_note': 'Needs Fabianens Statue Shop and Fabianens Mod Market in the game. Statues are sold on the MODS screen under Statues.',
        'btn_create': 'Create', 'btn_save': 'Save', 'btn_cancel': 'Cancel',
        'busy_read': 'Reading {name}…', 'busy_convert': 'Converting {name}…', 'busy_note': 'This can take up to a minute for large models.',
        'done_title': 'Done',
        'done_text': 'The statue is ready: {folder}\n\nCopy the folder into the game\'s UserData\\StatueShop folder and restart the game.',
        'err_title': 'Error',
        'err_read': 'The model cannot be read (broken or unsupported file).',
        'err_no_mesh': 'The model has no visible mesh (only a skeleton or animation?). Use a model that contains a mesh.',
        'err_zip': 'The zip file contains no .gltf or .glb model.',
        'err_blender': 'FBX, OBJ and BLEND files need Blender 4.x. Install Blender or save the model as GLB.',
        'err_fbx': 'Blender could not convert the model to GLB.',
        'err_no_anim': 'Animated statue: the model has no animation. Turn off "Animated" or use a model with an animation.',
    },
    'tr': {
        '_name': 'Türkçe',
        'language': 'Dil',
        'app_sub': '3D modelleri Statue Shop için gerçek boy heykele çevirir',
        'hint': '3D modelleri ya da klasörleri bu pencereye sürükle-bırak veya Dosya ekle\'yi kullan. Başlat\'a basınca sırayla çevrilir.',
        'drop_here': 'Modelleri buraya bırak\n.glb  .gltf  .zip  .fbx  .obj  .blend',
        'col_model': 'Model', 'col_folder': 'Çıktı klasörü', 'col_status': 'Durum',
        'st_wait': 'Bekliyor', 'st_edit': 'Düzenleniyor', 'st_run': 'Çevriliyor…', 'st_done': 'Tamam', 'st_err': 'Hata',
        'btn_add': 'Dosya ekle…', 'btn_add_folder': 'Klasör ekle…', 'btn_edit': 'Düzenle…', 'btn_remove': 'Çıkar',
        'btn_retry': 'Tekrar dene', 'btn_clear': 'Bitenleri temizle', 'btn_out': 'Çıktı klasörünü aç', 'btn_start': 'Başlat',
        'btn_running': 'Çevriliyor…', 'btn_details_show': 'Ayrıntıları göster', 'btn_details_hide': 'Ayrıntıları gizle',
        'install': 'Oyuna da kur (UserData\\StatueShop)',
        'stat_empty': 'Başlamak için model ekle.',
        'stat_ready': 'Kuyrukta {total} model var. Başlat\'a bas.',
        'stat_running': '{name} çevriliyor ({total} modelden {done} tanesi bitti)',
        'stat_finished': 'Bitti: {ok} tamam, {bad} hata. Klasörleri UserData\\StatueShop içine kopyala ve oyunu yeniden başlat.',
        'msg_no_models': 'Desteklenen bir model bulunamadı.\nDesteklenenler: {types}',
        'msg_nothing_waiting': 'Kuyrukta bekleyen model yok.',
        'msg_select_one': 'Bekleyen tek bir model seç.',
        'msg_close_running': 'Çevirme sürüyor. Yine de kapatılsın mı?',
        'dlg_models': 'Modelleri seç', 'dlg_folder': 'Modellerin olduğu klasörü seç',
        'form_title': 'Heykel ayarları',
        'sec_statue': 'Heykel', 'f_folder': 'Klasör adı', 'f_en': 'İngilizce adı', 'f_tr': 'Türkçe adı',
        'f_pose': 'Poz (animasyon)', 'f_price': 'Fiyat', 'f_height': 'Boyu (metre)',
        'f_animated': 'Animasyonlu: heykel bu animasyonu döngüde oynatır',
        'f_up': 'Modelin yukarı ekseni', 'up_auto': 'Otomatik',
        'sec_preview': 'Önizleme', 'pv_loading': 'Önizleme hazırlanıyor…',
        'pv_hint': 'Sola / sağa sürükle: döndür, yukarı / aşağı: öne / arkaya yatır. Sağ tuşla sürükle: yana yatır. Gördüğün yüz müşteriye bakar.',
        'pv_tip': 'Öne yatır 90°', 'pv_side': 'Yana yatır 90°', 'pv_turn': '180° çevir', 'pv_auto': 'Otomatik',
        'pv_autostate': 'Yön: otomatik', 'pv_manual': 'Yön: elle ayarlandı',
        'pv_frame': 'Kare {n} / {total} ({sec} sn) – heykel bu karede yapılır', 'pv_frame_rest': 'Animasyon yok: dinlenme pozu',
        'sec_parts': 'Parçalar', 'col_part': 'Parça', 'col_tris': 'Üçgen', 'col_note': 'Not',
        'parts_hint': 'Bir parçaya tıklayınca heykelden çıkarılır (tekrar tıklayınca geri gelir). Çıkarılan parça çizilmez ve boya katılmaz.',
        'pt_auto': 'görünmez / efekt', 'pt_far': 'gövdeden uzak', 'pt_off': 'çıkarıldı', 'btn_parts_auto': 'Otomatik',
        'req_note': 'Oyunda Fabianens Statue Shop ve Fabianens Mod Market gerekir. Heykeller MODLAR ekranında, Heykeller altında satılır.',
        'btn_create': 'Oluştur', 'btn_save': 'Kaydet', 'btn_cancel': 'İptal',
        'busy_read': '{name} okunuyor…', 'busy_convert': '{name} çevriliyor…', 'busy_note': 'Büyük modellerde bir dakikayı bulabilir.',
        'done_title': 'Tamam',
        'done_text': 'Heykel hazır: {folder}\n\nKlasörü oyunun UserData\\StatueShop klasörüne kopyala ve oyunu yeniden başlat.',
        'err_title': 'Hata',
        'err_read': 'Model okunamadı (bozuk ya da desteklenmeyen dosya).',
        'err_no_mesh': 'Modelde görünen bir mesh yok (sadece iskelet ya da animasyon mu?). Mesh içeren bir model kullan.',
        'err_zip': 'Zip dosyasında .gltf ya da .glb model yok.',
        'err_blender': 'FBX, OBJ ve BLEND dosyaları için Blender 4.x gerekir. Blender kur ya da modeli GLB olarak kaydet.',
        'err_fbx': 'Blender modeli GLB\'ye çeviremedi.',
        'err_no_anim': 'Animasyonlu heykel: modelde animasyon yok. "Animasyonlu"yu kapat ya da animasyonlu bir model kullan.',
    },
}


class FMError(RuntimeError):
    """kullaniciya gosterilen hata: metni dil dosyasindan gelir, teknik ayrinti konsola / ayrintilara"""
    def __init__(self, key, detail=''):
        self.key, self.detail = key, str(detail or '')
        super().__init__(STRINGS['en'].get(key, key) + (f' ({self.detail[:300]})' if self.detail else ''))


class I18n:
    def __init__(self):
        self.subs = []
        self.ensure_files()
        self.scan()
        code = self.setting('lang') or self.system_lang()
        self.code = code if code in self.langs else 'en'

    def ensure_files(self):
        """en.json / tr.json yoksa yaz; varsa elle yapilan ceviriye dokunma, sadece yeni anahtarlari ekle"""
        try: os.makedirs(LANG_DIR, exist_ok=True)
        except Exception as e: log('lang klasoru olusturulamadi:', e); return
        for code, d in STRINGS.items():
            p = os.path.join(LANG_DIR, code + '.json')
            try:
                cur = json.load(open(p, encoding='utf-8-sig')) if os.path.exists(p) else {}
                miss = {k: v for k, v in d.items() if k not in cur}
                if miss:
                    cur.update(miss)
                    with open(p, 'w', encoding='utf-8') as f: json.dump(cur, f, ensure_ascii=False, indent=2)
            except Exception as e: log('dil dosyasi yazilamadi:', p, e)

    def scan(self):
        """lang klasorunu oku; degisen bir sey varsa acik pencereleri yenile"""
        langs = {c: dict(d) for c, d in STRINGS.items()}
        for p in sorted(glob.glob(os.path.join(LANG_DIR, '*.json'))):
            c = os.path.splitext(os.path.basename(p))[0].lower()
            try: d = json.load(open(p, encoding='utf-8-sig'))
            except Exception as e: log('dil dosyasi okunamadi:', p, e); continue
            if isinstance(d, dict): langs[c] = {**langs.get(c, {}), **{k: str(v) for k, v in d.items()}}
        changed = getattr(self, 'langs', None) not in (None, langs)
        self.langs = langs
        if changed: self.notify()
        return langs

    def names(self):
        return sorted(((c, d.get('_name') or c) for c, d in self.langs.items()), key=lambda x: x[1].lower())

    def t(self, key, **kw):
        s = self.langs.get(self.code, {}).get(key) or STRINGS['en'].get(key) or key
        try: return s.format(**kw) if kw else s
        except Exception: return s

    def set(self, code):
        if code == self.code or code not in self.langs: return
        self.code = code
        self.save_setting('lang', code)
        self.notify()

    def notify(self):
        for f in list(self.subs):
            try: f()
            except Exception:        # pencere kapanmis
                if f in self.subs: self.subs.remove(f)

    def watch(self, f): self.subs.append(f); f(); return f
    def unwatch(self, f):
        if f in self.subs: self.subs.remove(f)

    def setting(self, k):
        try: return json.load(open(SETTINGS, encoding='utf-8')).get(k)
        except Exception: return None

    def save_setting(self, k, v):
        try:
            d = json.load(open(SETTINGS, encoding='utf-8')) if os.path.exists(SETTINGS) else {}
            d[k] = v
            with open(SETTINGS, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception as e: log('ayar yazilamadi:', e)

    def system_lang(self):
        try:
            import ctypes, locale
            return (locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage()) or 'en').split('_')[0].lower()
        except Exception:
            return 'en'


_I18N = None
def L():
    global _I18N
    if _I18N is None: _I18N = I18n()
    return _I18N
def T(key, **kw): return L().t(key, **kw)


def err_text(e):
    """hatanin secili dildeki metni (FMError) ya da ham metni"""
    if isinstance(e, FMError):
        return T(e.key) + ('\n\n' + e.detail[:600] if e.detail and e.key in ('err_fbx', 'err_read') else '')
    return str(e)[:1500] or type(e).__name__


# ---------------- pencereler / windows ----------------
_TK = None
def tkroot():
    """tek, gizli Tk koku (dosya secimi, form ve mesajlar hep bunu kullanir)"""
    global _TK
    if _TK is None:
        import tkinter as tk
        from tkinter import ttk, font
        try:
            import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)   # keskin yazi
        except Exception: pass
        _TK = tk.Tk(); _TK.withdraw()
        st = ttk.Style(_TK)
        if 'vista' in st.theme_names(): st.theme_use('vista')
        for n in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            try: font.nametofont(n).configure(family='Segoe UI', size=10)
            except Exception: pass
        st.configure('Treeview', rowheight=int(26 * ui_scale()))
        st.configure('Treeview.Heading', font=('Segoe UI Semibold', 10))
        st.configure('Title.TLabel', font=('Segoe UI Semibold', 15))
        st.configure('Sub.TLabel', foreground='#5f6368')
        st.configure('Drop.TLabel', foreground='#8a8f98', background='white', font=('Segoe UI', 12), justify='center')
        st.configure('Accent.TButton', font=('Segoe UI Semibold', 10), padding=(18, 6))
        st.configure('Section.TLabelframe.Label', font=('Segoe UI Semibold', 10))
    return _TK


def ui_scale():
    try: return max(1.0, tkroot().winfo_fpixels('1i') / 96.0)
    except Exception: return 1.0


def hide_console():
    """exe'ye cift tik / surukle-birak: arkadaki siyah konsolu gizle (komut satirindan calisinca gizleme)"""
    if os.name != 'nt': return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        arr = (ctypes.c_uint * 8)()
        if k.GetConsoleProcessList(arr, 8) <= (2 if FROZEN else 1):
            h = k.GetConsoleWindow()
            if h: ctypes.windll.user32.ShowWindow(h, 0)
    except Exception: pass


def message(title, text, error=False):
    if _TK is None: return
    from tkinter import messagebox
    (messagebox.showerror if error else messagebox.showinfo)(title, text, parent=_TK)


def bring_front(win):
    win.lift(); win.attributes('-topmost', True); win.after(300, lambda: win.attributes('-topmost', False)); win.focus_force()


def center(win, parent=None):
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    if parent is not None and parent.winfo_viewable():
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2; y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    else:
        x = (win.winfo_screenwidth() - w) // 2; y = (win.winfo_screenheight() - h) // 3
    win.geometry(f'+{max(0, x)}+{max(0, y)}')


def lang_picker(parent):
    """sag ustteki dil secici: secince butun acik pencereler aninda o dile gecer; liste her acilista lang klasorunu yeniden tarar"""
    from tkinter import ttk
    i = L()
    fr = ttk.Frame(parent)
    lbl = ttk.Label(fr); lbl.pack(side='left', padx=(0, 6))
    box = ttk.Combobox(fr, state='readonly', width=14); box.pack(side='left')
    codes = []
    def fill():
        names = i.names(); codes[:] = [c for c, _ in names]
        box['values'] = [n for _, n in names]
        if i.code in codes: box.current(codes.index(i.code))
        lbl.config(text=T('language'))
    box.configure(postcommand=lambda: (i.scan(), fill()))
    box.bind('<<ComboboxSelected>>', lambda e: i.set(codes[box.current()]))
    i.watch(fill)
    return fr


def fmt_num(x):
    try:
        f = float(x); return str(int(f)) if f == int(f) else str(f)
    except Exception: return str(x)


def form(d, anims, title_name='', save=False, parent=None, prep=None):
    """Heykel bilgileri formu (tkinter). prep verilirse sagda on izleme: fare ile cevrilen yon res['orient'] (3x3) olarak doner.
    Iptal -> None"""
    import tkinter as tk
    from tkinter import ttk
    i = L(); res = {}
    master = tkroot()
    root = tk.Toplevel(parent or master); root.resizable(False, False)
    if parent is not None: root.transient(parent)
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    fr = ttk.Frame(root, padding=(18, 14, 18, 16)); fr.grid(sticky='nsew'); fr.columnconfigure(0, weight=1)
    texts = []                       # (widget, anahtar) -> dil degisince yenilenir

    head = ttk.Frame(fr); head.grid(row=0, column=0, columnspan=2, sticky='we'); head.columnconfigure(0, weight=1)
    title = ttk.Label(head, style='Title.TLabel'); title.grid(row=0, column=0, sticky='w')
    lang_picker(head).grid(row=0, column=1, sticky='ne', padx=(16, 0))
    if title_name: ttk.Label(head, text=title_name, style='Sub.TLabel').grid(row=1, column=0, columnspan=2, sticky='w')

    v = {k: tk.StringVar(root, value=fmt_num(d.get(k, '')) if k in ('price', 'height') else str(d.get(k, '') or ''))
         for k in ('folder', 'en', 'tr', 'pose', 'price', 'height')}
    animated = tk.BooleanVar(root, value=bool(d.get('animated')))

    def row(box, r, key, w):
        lbl = ttk.Label(box); lbl.grid(row=r, column=0, sticky='w', padx=(0, 14), pady=4); w.grid(row=r, column=1, sticky='we', pady=4)
        texts.append((lbl, key)); return w

    sec = ttk.LabelFrame(fr, padding=(12, 8), style='Section.TLabelframe'); sec.columnconfigure(1, weight=1)
    sec.grid(row=1, column=0, sticky='we', pady=(12, 0))
    first = row(sec, 0, 'f_folder', ttk.Entry(sec, textvariable=v['folder'], width=44))
    row(sec, 1, 'f_en', ttk.Entry(sec, textvariable=v['en']))
    row(sec, 2, 'f_tr', ttk.Entry(sec, textvariable=v['tr']))
    row(sec, 3, 'f_pose', ttk.Combobox(sec, textvariable=v['pose'], values=(anims or []) + ['-'], state='readonly' if anims else 'disabled'))
    anim_cb = ttk.Checkbutton(sec, variable=animated); anim_cb.grid(row=4, column=1, sticky='w', pady=(0, 4)); texts.append((anim_cb, 'f_animated'))
    row(sec, 5, 'f_height', ttk.Entry(sec, textvariable=v['height'], width=12)).grid(sticky='w')
    row(sec, 6, 'f_price', ttk.Entry(sec, textvariable=v['price'], width=12)).grid(sticky='w')
    UPS = ['Y', 'Z', '-Z', 'X', '-X', '-Y']        # modelin yukari ekseni; ilk secenek "otomatik"
    up0 = str(d.get('up') or 'auto').upper().replace('+', '')
    upv = tk.StringVar(root, value=up0 if up0 in UPS else T('up_auto'))
    upbox = row(sec, 7, 'f_up', ttk.Combobox(sec, textvariable=upv, state='readonly', width=16)); upbox.grid(sticky='w')

    def sync_anim(*_):
        """animasyon secili degilse 'Animasyonlu' secilemez"""
        ok = bool(anims) and v['pose'].get() not in ('', '-')
        anim_cb.state(['!disabled'] if ok else ['disabled'])
        if not ok: animated.set(False)
    v['pose'].trace_add('write', sync_anim); sync_anim()

    note = ttk.Label(fr, style='Sub.TLabel', wraplength=int(470 * ui_scale())); note.grid(row=3, column=0, sticky='nw', pady=(10, 0))
    texts.append((note, 'req_note'))

    pv = preview_panel(fr, root, prep, anims, v['pose'], upv, UPS, texts, d.get('pose_frame', 0)) if prep is not None else None
    if pv: pv['frame'].grid(row=1, column=1, rowspan=3, sticky='n', padx=(16, 0), pady=(12, 0))
    parts = parts_panel(fr, prep, d, texts, pv) if prep is not None and prep.get('parts') else None
    if parts: parts['frame'].grid(row=2, column=0, sticky='we', pady=(12, 0))

    def ok(_e=None):
        res.update({k: x.get().strip() for k, x in v.items()}); res['animated'] = animated.get()
        res['up'] = upv.get() if upv.get() in UPS else 'auto'
        if pv and pv['state']['manual']: res['orient'] = [float(x) for x in pv['state']['R'].ravel()]
        if pv: res['pose_frame'] = pv['frame_of'](res['pose'])
        if parts: res['exclude'] = sorted(parts['off'])
        root.destroy()
    bf = ttk.Frame(fr); bf.grid(row=4, column=0, columnspan=2, sticky='e', pady=(14, 0))
    cb = ttk.Button(bf, command=root.destroy); cb.pack(side='right')
    okb = ttk.Button(bf, command=ok, style='Accent.TButton'); okb.pack(side='right', padx=(0, 8))
    texts += [(cb, 'btn_cancel'), (okb, 'btn_save' if save else 'btn_create')]
    root.bind('<Return>', ok); root.bind('<Escape>', lambda e: root.destroy())

    def retext():
        root.title('Statue Maker – ' + T('form_title')); title.config(text=T('form_title'))
        sec.config(text=T('sec_statue'))
        for w, k in texts: w.config(text=T(k))
        if upv.get() not in UPS: upv.set(T('up_auto'))
        upbox['values'] = [T('up_auto')] + UPS
        if pv: pv['retext']()
        if parts: parts['retext']()
    i.watch(retext)
    center(root, parent); bring_front(root); first.focus_set()
    if parent is not None: root.grab_set()
    master.wait_window(root)
    i.unwatch(retext)
    return res or None


def parts_panel(fr, prep, d, texts, pv):
    """modelin parcalari (materyal basina): tikla -> heykele alinmaz / geri alinir. Otomatik kapatilanlar (gorunmez / efekt) ve
    govdeden uzak parcalar notta yazar. Degisince on izleme yeniden cizilir."""
    import tkinter as tk
    from tkinter import ttk
    g = prep['g']; info = prep['parts']
    off = set(int(k) for k in (d.get('exclude') if d.get('exclude') is not None else g.auto_exclude))
    box = ttk.LabelFrame(fr, padding=(12, 8), style='Section.TLabelframe'); box.columnconfigure(0, weight=1)
    hint = ttk.Label(box, style='Sub.TLabel', wraplength=int(450 * ui_scale()), justify='left'); hint.grid(row=0, column=0, columnspan=2, sticky='w')
    tv = ttk.Treeview(box, columns=('on', 'name', 'tris', 'note'), show='headings', height=min(7, max(3, len(info))), selectmode='none')
    sc = ui_scale()
    for c, w, anc in (('on', 30, 'center'), ('name', 230, 'w'), ('tris', 70, 'e'), ('note', 120, 'w')):
        tv.column(c, width=int(w * sc), anchor=anc, stretch=c == 'name')
    sb = ttk.Scrollbar(box, orient='vertical', command=tv.yview); tv.configure(yscrollcommand=sb.set)
    tv.grid(row=1, column=0, sticky='we', pady=(6, 0)); sb.grid(row=1, column=1, sticky='ns', pady=(6, 0))
    tv.tag_configure('off', foreground='#9aa0a8')
    bauto = ttk.Button(box); bauto.grid(row=2, column=0, columnspan=2, sticky='e', pady=(6, 0)); texts.append((bauto, 'btn_parts_auto'))
    texts.append((hint, 'parts_hint'))

    def fill():
        tv.delete(*tv.get_children())
        for k, name, tris, auto, far in info:
            notes = [T('pt_auto')] if auto else []
            if far: notes.append(T('pt_far'))
            if k in off and not auto: notes.append(T('pt_off'))
            tv.insert('', 'end', iid=str(k), values=('—' if k in off else '✔', name, fmt_num(tris), ', '.join(notes)),
                      tags=('off',) if k in off else ())
        for c, key in (('on', ''), ('name', 'col_part'), ('tris', 'col_tris'), ('note', 'col_note')):
            tv.heading(c, text=T(key) if key else '')

    def apply():
        if len(off) >= len(info): return False                 # en az bir parca kalsin
        g.set_exclude(off); fill()
        if pv: pv['reload']()
        return True

    def click(e):
        row = tv.identify_row(e.y)
        if not row or tv.identify_region(e.x, e.y) not in ('cell', 'tree'): return
        k = int(row)
        if k in off: off.discard(k); apply()
        else:
            off.add(k)
            if not apply(): off.discard(k)
    tv.bind('<ButtonRelease-1>', click)

    def auto():
        off.clear(); off.update(g.auto_exclude); apply()
    bauto.config(command=auto)

    def retext():
        box.config(text=T('sec_parts')); fill()
    g.set_exclude(off)
    return dict(frame=box, off=off, retext=retext)


def preview_panel(fr, root, prep, anims, posevar, upv, UPS, texts, frame0=0):
    """formun sagindaki on izleme: fare ile surukle (sola/saga: dondur, yukari/asagi: one/arkaya yatir, sag tus: yana yatir),
    birakinca 90 / 5 dereceye oturur. Gorulen yuz oyunda musteriye bakar. state['manual'] -> elle ayarlandi.
    Altta kare kaydiricisi: secili animasyonun hangi karesinde heykel yapilacak (statue.json maker.poseFrame)"""
    import tkinter as tk, threading
    from tkinter import ttk
    from PIL import ImageTk
    import orient
    sc = ui_scale(); W, H = int(300 * sc), int(380 * sc)
    box = ttk.LabelFrame(fr, padding=(10, 8), style='Section.TLabelframe')
    img = tk.Label(box, background='#eef0f4', cursor='fleur', anchor='center', compound='center')
    img.pack(); blank = tk.PhotoImage(width=W, height=H); img.config(image=blank)
    stat = ttk.Label(box, style='Sub.TLabel'); stat.pack(anchor='w', pady=(6, 0))
    fv = tk.DoubleVar(root, value=0)
    scale = ttk.Scale(box, from_=0, to=1, orient='horizontal', variable=fv, length=W); scale.pack(fill='x', pady=(6, 0))
    flab = ttk.Label(box, style='Sub.TLabel'); flab.pack(anchor='w')
    hint = ttk.Label(box, style='Sub.TLabel', wraplength=W, justify='left'); hint.pack(anchor='w', pady=(2, 6))
    bts = ttk.Frame(box); bts.pack(fill='x')
    g = prep['g']
    st = dict(R=np.eye(3), manual=False, pts=None, drag=None, live=None, photo=None, busy=False, want=None, pending=False,
              tex={}, timer=None, ver=0)
    def cur_up(): return upv.get() if upv.get() in UPS else 'auto'

    def frames_of(k):                                       # model.skin ile ayni kare sayisi (30 fps)
        return conv.clip_frames(g, g.j['animations'][k])[1] if k is not None else 1

    def frame_of(name):
        k = next((q for q, a in enumerate(anims or []) if a == name), None)
        return min(int(round(fv.get())), frames_of(k) - 1) if k is not None else 0

    def frame_text():
        k = pose_index(); n = frames_of(k); f = min(int(round(fv.get())), n - 1)
        flab.config(text=T('pv_frame_rest') if k is None else T('pv_frame', n=f + 1, total=n, sec='%.2f' % (f / 30.0)))

    def setup_scale(f=0):
        """poz degisince kaydiricinin araligi o klibin karelerine gore; tek kareli / animasyonsuz -> kapali"""
        k = pose_index(); n = frames_of(k)
        scale.config(to=max(n - 1, 1)); fv.set(min(max(int(f), 0), n - 1))
        scale.state(['!disabled'] if k is not None and n > 1 else ['disabled'])
        frame_text()

    def draw():
        if st['pts'] is None: return
        R = st['live'] if st['live'] is not None else st['R']
        st['photo'] = ImageTk.PhotoImage(orient.render(*st['pts'], R, W, H))
        img.config(image=st['photo'], text='')

    def status():
        stat.config(text=T('pv_manual' if st['manual'] else 'pv_autostate'))

    def pose_index():
        n = posevar.get()
        return next((k for k, a in enumerate(anims or []) if a == n), None)

    def load():
        """noktalari arka planda hazirla (buyuk dokularda bir iki saniye surer), sonra ciz"""
        k = pose_index(); f = frame_of(posevar.get()); key = (k, f, st['ver'])
        if st['busy']: st['want'] = key; return
        st['busy'] = True; st['want'] = None
        if st['pts'] is None: img.config(image=blank, text=T('pv_loading'))   # kare degisirken eski resim kalsin
        out = {}; up = cur_up()                              # tk degiskeni is parcacigindan okunmaz
        def job():
            try:
                out['pts'] = orient.load(g, k, frame=f, cache=st['tex'])
                out['R'] = orient.initial(g, up)
            except Exception as e: out['e'] = e; traceback.print_exc()
        th = threading.Thread(target=job, daemon=True); th.start()
        def poll():
            if th.is_alive(): root.after(80, poll); return
            st['busy'] = False
            if 'e' in out: img.config(text=str(out['e'])[:200]); return
            st['pts'] = out['pts']
            if not st['manual']: st['R'] = out['R']
            draw(); status()
            if st['want'] is not None and st['want'] != key: load()
        root.after(80, poll)

    def set_R(R, manual=True):
        st['R'] = orient.snap(R); st['manual'] = manual; st['live'] = None; draw(); status()

    def auto():
        st['manual'] = False
        if st['pts'] is not None: set_R(orient.initial(g, cur_up()), False)
        else: status()

    def press(e, btn):
        if st['pts'] is not None: st['drag'] = (e.x, e.y, btn, st['R'])

    def angles(e):
        x0, y0, btn, R0 = st['drag']; dx, dy = e.x - x0, e.y - y0
        if btn == 3: return 0.0, 0.0, dx * 0.6                      # sag tus: yana yatir (kamera ekseni)
        return dx * 0.6, dy * 0.6, 0.0

    def rot(yaw, tip, roll, R0):
        return orient.rz(-roll) @ orient.rx(tip) @ orient.ry(yaw) @ R0

    def move(e):
        if not st['drag'] or st['pts'] is None: return
        st['live'] = rot(*angles(e), st['drag'][3])
        if not st['pending']:
            st['pending'] = True
            def later(): st['pending'] = False; draw()
            root.after(16, later)

    def release(e):
        if not st['drag'] or st['pts'] is None: st['drag'] = None; return
        yaw, tip, roll = angles(e); R0 = st['drag'][3]; st['drag'] = None
        if abs(yaw) < 1 and abs(tip) < 1 and abs(roll) < 1: st['live'] = None; draw(); return
        set_R(rot(round(yaw / 5) * 5, round(tip / 90) * 90, round(roll / 90) * 90, R0))

    for b in (1, 3):
        img.bind(f'<ButtonPress-{b}>', lambda e, b=b: press(e, b))
        img.bind(f'<B{b}-Motion>', move)
        img.bind(f'<ButtonRelease-{b}>', release)
    def turn(M):
        if st['pts'] is not None: set_R(M @ st['R'])
    buttons = [('pv_tip', lambda: turn(orient.rx(90))), ('pv_side', lambda: turn(orient.rz(-90))),
               ('pv_turn', lambda: turn(orient.ry(180))), ('pv_auto', auto)]
    for k, (key, cmd) in enumerate(buttons):
        b = ttk.Button(bts, command=cmd); b.grid(row=k // 2, column=k % 2, sticky='we', padx=(0, 4) if k % 2 == 0 else 0, pady=2)
        texts.append((b, key))
    bts.columnconfigure(0, weight=1); bts.columnconfigure(1, weight=1)
    texts.append((hint, 'pv_hint'))
    def pose_changed(*_): setup_scale(0); load()
    posevar.trace_add('write', pose_changed)
    def frame_moved():                                       # surukerken yazi hemen, resim kisa bir duraklamadan sonra
        fv.set(round(fv.get())); frame_text()
        if st['timer']: root.after_cancel(st['timer'])
        def later(): st['timer'] = None; load()
        st['timer'] = root.after(120, later)
    scale.config(command=lambda *_: frame_moved())
    last = [cur_up()]
    def up_changed(*_):                                      # eksen secilince elle ayar biter, o eksenden baslar (dil degisimi sayilmaz)
        if cur_up() != last[0]: last[0] = cur_up(); auto()
    upv.trace_add('write', up_changed)

    def retext():
        box.config(text=T('sec_preview')); status(); frame_text()
        if st['pts'] is None: img.config(text=T('pv_loading'))
    setup_scale(frame0)
    root.after(50, load)
    def reload():                                            # parca acilip kapaninca: yeni nokta bulutu, otomatik yon yeniden
        st['ver'] += 1; load()
    return dict(frame=box, state=st, retext=retext, frame_of=frame_of, reload=reload)


def run_busy(fn, text_key, name, parent=None):
    """fn'i arka planda calistir, bu sirada 'okunuyor / cevriliyor' penceresi goster; sonucu ya da hatasi dondur"""
    import tkinter as tk, threading
    from tkinter import ttk
    master = tkroot()
    w = tk.Toplevel(parent or master); w.resizable(False, False); w.protocol('WM_DELETE_WINDOW', lambda: None)
    f = ttk.Frame(w, padding=22); f.pack(fill='both')
    lab = ttk.Label(f, font=('Segoe UI Semibold', 11)); lab.pack(anchor='w')
    pb = ttk.Progressbar(f, mode='indeterminate', length=int(380 * ui_scale())); pb.pack(pady=(12, 6)); pb.start(12)
    sub = ttk.Label(f, style='Sub.TLabel'); sub.pack(anchor='w')
    def retext():
        w.title('Statue Maker'); lab.config(text=T(text_key, name=name)); sub.config(text=T('busy_note'))
    L().watch(retext)
    res = {}
    def job():
        try: res['v'] = fn()
        except BaseException as e: res['e'] = e; traceback.print_exc()
    th = threading.Thread(target=job, daemon=True); th.start()
    def poll():
        if th.is_alive(): w.after(120, poll)
        else: w.destroy()
    center(w, parent); bring_front(w); w.after(120, poll)   # pencere wait_window'dan once kapanmasin
    master.wait_window(w)
    L().unwatch(retext)
    if 'e' in res: raise res['e']
    return res.get('v')


def num(s, d):
    try: return float(str(s).replace(',', '.'))
    except Exception: return d


VERSION = '1.1.0'
MODEL_TYPES = ('.glb', '.gltf', '.fbx', '.obj', '.blend', '.zip')
WARN_TRIS = 300000          # bundan buyuk heykeller oyunu yavaslatabilir (azaltilmaz: ayrinti kaybolmasin, sadece uyari)


def default_pose(anims):
    """varsayilan poz: bekleme animasyonu (idle / stand / wait); oyun modellerinin ilk animasyonu cogu zaman giris
    hareketidir ("Come": silah havada ucar)"""
    if not anims: return '-'
    return next((n for n in anims if re.search(r'idle|stand|wait|breath', n, re.I)), anims[0])


def prepare(model, a, work_key=None):
    """modeli oku: kaynak, animasyonlar, emegi gecenler ve varsayilan form degerleri"""
    model = os.path.abspath(model)
    stem = os.path.splitext(os.path.basename(model))[0]
    if stem.lower() in ('scene', 'model', 'source'): stem = os.path.basename(os.path.dirname(model)) or stem
    work = os.path.join(BASE, 'work', work_key or folder_name(stem)); os.makedirs(work, exist_ok=True)
    log('kaynak:', model)

    src = find_source(model, work)
    try: g = conv.Src(src)
    except Exception as e: raise FMError('err_read', e)
    anims = [an.get('name') or 'Anim%d' % k for k, an in enumerate(g.j.get('animations', []))]
    info, lic = credits(g, src)
    if not lic and os.path.exists(os.path.join(work, 'license.txt')): lic = open(os.path.join(work, 'license.txt'), encoding='utf-8', errors='ignore').read()

    base = pretty(info['title']) if info['title'] else pretty(stem)
    opt = dict(folder=folder_name(a.name or base), en=a.en or base, tr=a.tr or a.en or base, pose=a.pose or default_pose(anims),
               price=a.price, height=a.height, animated=bool(a.animated and anims), up=getattr(a, 'up', None) or 'auto',
               pose_frame=int(round(max(a.pose_time or 0.0, 0.0) * 30.0)))
    parts = conv.parts_info(g)
    excl = set(g.exclude)
    def match(spec):                                    # --hide / --show: virgulle ayrilmis materyal adlari (parcasi da olur)
        ws = [w.strip().lower() for w in (spec or '').split(',') if w.strip()]
        return {pt[0] for pt in parts if any(w in pt[1].lower() for w in ws)}
    excl = (excl | match(getattr(a, 'hide', None))) - match(getattr(a, 'show', None))
    opt['exclude'] = sorted(excl)
    return dict(parts=parts, model=model, stem=stem, work=work, src=src, g=g, anims=anims, info=info, lic=lic, base=base, opt=opt)


def _ry(deg):
    t = math.radians(deg); c, s = math.cos(t), math.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], float)


def build(p, opt, a, folder=None):
    """hazirlanan modelden out\\<klasor> heykel klasorunu uret; klasor adini dondurur"""
    g, src, anims, info, lic, work = p['g'], p['src'], p['anims'], p['info'], p['lic'], p['work']
    folder = folder or folder_name(opt['folder'] or p['base'])
    out = os.path.join(BASE, 'out', folder)
    shutil.rmtree(out, True); os.makedirs(out)

    excl = set(int(k) for k in (opt.get('exclude') if opt.get('exclude') is not None else g.auto_exclude))
    g.set_exclude(excl)                                 # formda kapatilan / otomatik kapatilan parcalar
    clips = []
    if anims and opt['pose'] != '-':
        idx = next((k for k, n in enumerate(anims) if n == opt['pose']), next((k for k, n in enumerate(anims) if opt['pose'].lower() in n.lower()), 0))
        clips = [(idx, anims[idx])]
    if opt.get('animated') and not clips: raise FMError('err_no_anim')
    animated = bool(opt.get('animated'))
    # pozun karesi (on izlemedeki kaydirici / --pose-time); 30 fps
    start, nfr = conv.clip_frames(g, g.j['animations'][clips[0][0]]) if clips else (0.0, 1)
    frame = min(max(int(opt.get('pose_frame') or 0), 0), nfr - 1) if clips else 0
    tris = tri_count(g)
    if tris == 0: raise FMError('err_no_mesh')
    height = num(opt.get('height'), 1.8)
    if height <= 0: height = 1.8
    log(f'{tris} ucgen, animasyonlar: {anims[:10] or "-"}; ' +
        (f'animasyonlu: {clips[0][1]} ({nfr} kare)' if animated else f'poz: {clips[0][1] + f" (kare {frame})" if clips else "dinlenme pozu"}') +
        f'; boy {height:g} m')
    if g.dropped: log(f'heykele alinmayan parcalar ({len(g.dropped)}): {", ".join(g.dropped[:6])}' + (' ...' if len(g.dropped) > 6 else ''))
    if getattr(g, 'merged', None): log(f'parcali animasyonlar birlestirildi: {", ".join(g.merged[:6])}')
    if tris > WARN_TRIS: log(f'UYARI: {tris} ucgen cok fazla - dukkanda cok sayida olursa oyun yavaslayabilir')

    orient_m = np.array(opt['orient'], float).reshape(3, 3) if opt.get('orient') else None   # on izlemede elle cevrildi
    up = str(opt.get('up') or 'auto').upper().replace('+', '')
    if orient_m is not None: up, how = 'custom', 'preview'
    elif up not in conv.UP_ROT: up, how = conv.detect_up(g)
    else: how = 'manual'
    log(f'yukari ekseni: {up} ({how})' + ('' if up == 'Y' else ' -> ayaga kaldirildi'))
    R_up = orient_m if orient_m is not None else conv.UP_ROT[up]

    # 1) deneme cevirisi (figur bicimi): yuzun nereye baktigi ve ikon bundan
    probe = os.path.join(work, 'probe'); shutil.rmtree(probe, True); os.makedirs(probe)
    conv.convert_anim(src, probe, clips, height=height, maxtex=512, up=R_up, exclude=excl)
    if orient_m is not None: front, how_front = (0.0, 1.0), 'preview'   # on izlemede gorulen yuz musteriye bakar
    else: front, how_front = standalone.detect_front(probe, frame)
    yaw = float(round(math.degrees(math.atan2(front[0], front[1])) / 5.0) * 5.0)   # heykelin on yuzu oyunda +Z
    log(f'heykelin yonu: {how_front} -> {yaw:g} derece cevrildi')
    if render_icon(probe, a.yaw, front, frame): log('icon.png hazir')
    M = _ry(yaw) @ R_up

    # 2) heykel: sabit (model.statue) ya da butun model hareketli (bos model.statue + model.skin)
    if animated:
        r = conv.convert_anim(src, out, clips, height=height, up=M, part_fmt=True, exclude=excl)
        conv.write_stub_stat2(os.path.join(out, 'model.statue'))
    else:
        r = conv.convert_static(src, out, height=height, clip=clips[0][0] if clips else None,
                                clip_time=start + frame / 30.0, up=M, exclude=excl)
    log(f'{"model.skin" if animated else "model.statue"}: {r["tris"]} ucgen, {r["parts"]} parca, olcu {r["dims"]}')
    shutil.copy(os.path.join(probe, 'icon.png'), os.path.join(out, 'icon.png')) if os.path.exists(os.path.join(probe, 'icon.png')) else None

    if a.bc7 and bc7.available():
        n, total = bc7.convert_folder(out, log)
        if total: log(f'dokular BC7: {n}/{total}')
    elif a.bc7: log('Not: BC7 sikistirma yok (etcpak) - dokular PNG/JPG kaldi, oyun bunlari da okur')

    if lic: open(os.path.join(out, 'license.txt'), 'w', encoding='utf-8').write(lic.strip() + '\n')
    else: log('UYARI: lisans bilgisi bulunamadi - paylasmadan once license.txt ekle (modelin dagitim izni olmali)')

    sj = {
        'nameEnglish': opt['en'],
        'nameTurkish': opt['tr'] or opt['en'],
        'price': num(opt.get('price'), 15000.0),
        'enabled': True,
        'requires': {'StatueShop': '1.0.0', 'ModMarket': '1.4.0'},
        'credits': info,
        'maker': {'tool': 'Statue Maker ' + VERSION, 'tris': r['tris'], 'parts': r['parts'], 'height': height, 'up': up,
                  'facing': how_front, 'yaw': yaw, 'animated': animated,
                  'pose': clips[0][1] if clips else '-', 'poseFrame': frame, 'hiddenParts': g.dropped},
    }
    json.dump(sj, open(os.path.join(out, 'statue.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    if a.install:
        if not os.path.exists(os.path.join(GAME, 'Mods', 'StatueShop.dll')): log('UYARI: Mods\\StatueShop.dll yok - heykeller Statue Shop olmadan oyuna gelmez')
        if not os.path.exists(os.path.join(GAME, 'Mods', 'ModMarket.dll')): log('UYARI: Mods\\ModMarket.dll yok - Fabianens Mod Market zorunlu')
        dst = os.path.join(USERDATA, folder)
        shutil.rmtree(dst, True); shutil.copytree(out, dst)
        log('kuruldu:', dst)
    log('TAMAM:', out)
    return folder, out


def enable_drop(win, callback):
    """Windows Gezgini'nden pencereye dosya surukle-birak (WM_DROPFILES, ek kutuphane yok)"""
    if os.name != 'nt': return False
    try:
        import ctypes
        from ctypes import wintypes
        u32, sh = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u32.SetWindowLongPtrW.restype = ctypes.c_void_p
        u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        u32.CallWindowProcW.restype = LRESULT
        u32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        sh.DragQueryFileW.restype = wintypes.UINT
        sh.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
        sh.DragFinish.argtypes = [ctypes.c_void_p]
        sh.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        win.update_idletasks()
        hwnd = int(win.wm_frame(), 16)
        # yonetici olarak calisirsa Gezgin'in birakmasina izin ver
        try:
            for m in (0x0233, 0x004A, 0x0049): u32.ChangeWindowMessageFilterEx(hwnd, m, 1, None)
        except Exception: pass
        state = {}
        def proc(h, msg, wp, lp):
            if msg == 0x0233:   # WM_DROPFILES
                files = []
                for k in range(sh.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)):
                    n = sh.DragQueryFileW(wp, k, None, 0)
                    buf = ctypes.create_unicode_buffer(n + 1); sh.DragQueryFileW(wp, k, buf, n + 1); files.append(buf.value)
                sh.DragFinish(wp)
                win.after(0, callback, files)
                return 0
            return u32.CallWindowProcW(state['old'], h, msg, wp, lp)
        state['proc'] = WNDPROC(proc)
        state['old'] = u32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(state['proc'], ctypes.c_void_p))   # GWLP_WNDPROC
        sh.DragAcceptFiles(hwnd, True)
        win._fm_drop = state    # geri cagirma silinmesin
        return True
    except Exception as e:
        log('surukle-birak acilamadi:', e)
        return False


def expand_models(paths):
    """birakilan / secilen yollar: klasorse icindeki modeller, degilse desteklenen uzantilar"""
    res = []
    for p in paths:
        p = os.path.abspath(p.strip('"'))
        if os.path.isdir(p):
            for f in sorted(glob.glob(os.path.join(p, '**', '*'), recursive=True)):
                if os.path.splitext(f)[1].lower() in MODEL_TYPES and os.path.isfile(f): res.append(f)
        elif os.path.splitext(p)[1].lower() in MODEL_TYPES and os.path.isfile(p):
            res.append(p)
    return res


ST_ICON = {'wait': '•', 'edit': '✎', 'run': '⟳', 'done': '✓', 'err': '✗'}


def queue_window(a, files):
    """Toplu cevirme: modelleri listeye at (surukle-birak ya da coklu secim), Baslat'a bas, sirayla cevrilsin"""
    import tkinter as tk, threading, queue as qmod
    from tkinter import ttk, filedialog, messagebox
    global LOG_SINK
    i = L()
    master = tkroot(); sc = ui_scale()
    win = tk.Toplevel(master); win.geometry(f'{int(900 * sc)}x{int(600 * sc)}'); win.minsize(int(700 * sc), int(440 * sc))
    events = qmod.Queue()
    lock = threading.Lock()
    items = []          # dict(id, path, status, opt, prep, folder, out, err, err_key)
    st = dict(running=False, next_id=1, install=bool(a.install), current='', finished=None)
    used_work, used_folder = {}, {}   # bu oturumda verilen work / out klasorleri -> oge id (ayni adli iki model birbirini ezmesin)
    ba = argparse.Namespace(**vars(a)); ba.name = ba.en = ba.tr = None   # ad her modelin kendisinden
    LOG_SINK = lambda line: events.put(('log', line))
    texts = []          # (widget, anahtar)

    fr = ttk.Frame(win, padding=(16, 12, 16, 12)); fr.pack(fill='both', expand=True)
    fr.columnconfigure(0, weight=1); fr.rowconfigure(3, weight=1)

    # baslik + sag ustte dil secici
    head = ttk.Frame(fr); head.grid(row=0, column=0, sticky='we'); head.columnconfigure(0, weight=1)
    ttk.Label(head, text='Statue Maker', style='Title.TLabel').grid(row=0, column=0, sticky='w')
    lang_picker(head).grid(row=0, column=1, sticky='ne')
    sub = ttk.Label(head, style='Sub.TLabel'); sub.grid(row=1, column=0, columnspan=2, sticky='w'); texts.append((sub, 'app_sub'))
    hint = ttk.Label(fr, wraplength=int(860 * sc)); hint.grid(row=1, column=0, sticky='we', pady=(10, 6)); texts.append((hint, 'hint'))

    # arac cubugu
    tb = ttk.Frame(fr); tb.grid(row=2, column=0, sticky='we', pady=(0, 6))
    def tbtn(key, cmd, side='left', **kw):
        b = ttk.Button(tb, command=cmd, **kw); b.pack(side=side, padx=(0, 6)); texts.append((b, key)); return b

    # liste
    tf = ttk.Frame(fr); tf.grid(row=3, column=0, sticky='nsew')
    tree = ttk.Treeview(tf, columns=('file', 'folder', 'status'), show='headings', selectmode='extended')
    for c, w in (('file', 280), ('folder', 240), ('status', 330)): tree.column(c, width=int(w * sc), anchor='w')
    ysb = ttk.Scrollbar(tf, orient='vertical', command=tree.yview); tree.configure(yscrollcommand=ysb.set)
    tree.pack(side='left', fill='both', expand=True); ysb.pack(side='right', fill='y')
    tree.tag_configure('done', foreground='#1a7f37'); tree.tag_configure('err', foreground='#c62828'); tree.tag_configure('run', foreground='#1565c0')
    drop = ttk.Label(tf, style='Drop.TLabel'); texts.append((drop, 'drop_here'))

    # alt: ilerleme, kur secenegi, Baslat
    bot = ttk.Frame(fr); bot.grid(row=4, column=0, sticky='we', pady=(10, 0)); bot.columnconfigure(0, weight=1)
    pbar = ttk.Progressbar(bot, mode='determinate'); pbar.grid(row=0, column=0, columnspan=4, sticky='we')
    status = ttk.Label(bot); status.grid(row=1, column=0, columnspan=4, sticky='w', pady=(6, 0))
    install = tk.BooleanVar(win, value=st['install'])
    install.trace_add('write', lambda *_: st.__setitem__('install', install.get()))
    opts = ttk.Frame(bot); opts.grid(row=2, column=0, sticky='w', pady=(6, 0))
    inst = ttk.Checkbutton(opts, variable=install); inst.pack(side='left'); texts.append((inst, 'install'))
    out_btn = ttk.Button(bot); out_btn.grid(row=2, column=1, sticky='e', padx=(0, 6), pady=(6, 0))
    det_btn = ttk.Button(bot); det_btn.grid(row=2, column=2, sticky='e', padx=(0, 6), pady=(6, 0))
    start_btn = ttk.Button(bot, style='Accent.TButton'); start_btn.grid(row=2, column=3, sticky='e', pady=(6, 0))
    logf = ttk.Frame(fr)
    logbox = tk.Text(logf, height=8, wrap='none', state='disabled', font=('Consolas', 9), relief='flat', background='#f6f8fa')
    lsb = ttk.Scrollbar(logf, orient='vertical', command=logbox.yview); logbox.configure(yscrollcommand=lsb.set)
    logbox.pack(side='left', fill='both', expand=True); lsb.pack(side='right', fill='y')
    show_log = tk.BooleanVar(win, value=False)

    def find(iid): return next((x for x in items if x['id'] == iid), None)

    def shown(path):
        b = os.path.basename(path)
        if os.path.splitext(b)[0].lower() in ('scene', 'model', 'source'): b = os.path.join(os.path.basename(os.path.dirname(path)), b)
        return b

    def status_text(x):
        s = f"{ST_ICON[x['status']]}  {T('st_' + x['status'])}"
        if x['status'] == 'err': s += ': ' + (T(x['err_key']) if x.get('err_key') else x.get('err') or '')
        return s

    def refresh(x):
        folder = x.get('folder') or (x['opt'] or {}).get('folder') or ''
        vals = (shown(x['path']), folder, status_text(x))
        if tree.exists(str(x['id'])): tree.item(str(x['id']), values=vals, tags=(x['status'],))
        else: tree.insert('', 'end', iid=str(x['id']), values=vals, tags=(x['status'],))
        overall()

    def overall():
        """ilerleme cubugu, durum satiri, bos liste yazisi ve dugmeler"""
        total = len(items); done = sum(1 for y in items if y['status'] in ('done', 'err'))
        pbar.configure(maximum=max(1, total), value=done)
        if st['running']: txt = T('stat_running', name=st['current'] or '…', done=done, total=total)
        elif st['finished'] and total: txt = T('stat_finished', ok=st['finished'][0], bad=st['finished'][1])
        elif total: txt = T('stat_ready', total=total)
        else: txt = T('stat_empty')
        status.config(text=txt)
        if total: drop.place_forget()
        else: drop.place(relx=0.5, rely=0.5, anchor='center')
        start_btn.config(text=T('btn_running') if st['running'] else T('btn_start'))
        start_btn.state(['disabled'] if st['running'] or not any(y['status'] == 'wait' for y in items) else ['!disabled'])
        sel = selected()
        edit_b.state(['!disabled'] if len(sel) == 1 and sel[0]['status'] == 'wait' else ['disabled'])
        rem_b.state(['!disabled'] if any(x['status'] not in ('run', 'edit') for x in sel) else ['disabled'])
        retry_b.state(['!disabled'] if any(x['status'] == 'err' for x in sel) else ['disabled'])
        clear_b.state(['!disabled'] if done else ['disabled'])

    def add(paths):
        models = expand_models(paths)
        if paths and not models:
            messagebox.showwarning('Statue Maker', T('msg_no_models', types=', '.join(MODEL_TYPES)), parent=win)
        with lock:
            have = {x['path'].lower() for x in items if x['status'] in ('wait', 'edit', 'run')}
            new = []
            for m in models:
                if m.lower() in have: continue
                have.add(m.lower())
                x = dict(id=st['next_id'], path=m, status='wait', opt=None, prep=None, folder='', out='', err='', err_key='')
                st['next_id'] += 1; items.append(x); new.append(x)
            if new and not st['running']: st['finished'] = None
        for x in new: refresh(x)
        if new and st['running']: log(f'{len(new)} model kuyruga eklendi')

    def pick():
        fs = filedialog.askopenfilenames(parent=win, title=T('dlg_models'),
                                         filetypes=[('3D model', ' '.join('*' + e for e in MODEL_TYPES)), ('*.*', '*.*')])
        if fs: add(list(fs))

    def pick_folder():
        d = filedialog.askdirectory(parent=win, title=T('dlg_folder'))
        if d: add([d])

    def unique(table, key, iid):
        """ayni ad bu oturumda baska bir ogeye verildiyse _2, _3 ... ekle"""
        k, n = key, 2
        while table.get(k.lower(), iid) != iid: k = f'{key}_{n}'; n += 1
        table[k.lower()] = iid
        return k

    def work_key(x):
        stem = os.path.splitext(os.path.basename(x['path']))[0]
        if stem.lower() in ('scene', 'model', 'source'): stem = os.path.basename(os.path.dirname(x['path'])) or stem
        with lock: return unique(used_work, folder_name(stem), x['id'])

    def worker():
        ok = bad = 0
        while True:
            with lock:
                x = next((y for y in items if y['status'] == 'wait'), None)
                if x is None:
                    st['running'] = False; st['finished'] = (ok, bad); events.put(('idle', None)); return
                x['status'] = 'run'; st['current'] = shown(x['path'])
            events.put(('item', x))
            try:
                log(f'===== {os.path.basename(x["path"])} =====')
                p = x['prep'] or prepare(x['path'], ba, work_key(x))
                opt = dict(p['opt'])
                if x['opt']: opt.update(x['opt'])
                with lock: folder = unique(used_folder, folder_name(opt['folder'] or p['base']), x['id'])
                aa = argparse.Namespace(**vars(ba)); aa.install = st['install']   # tk degiskeni is parcacigindan okunmaz
                x['folder'], x['out'] = build(p, opt, aa, folder)
                x['status'] = 'done'; ok += 1
            except Exception as e:
                log('HATA:', e); log(traceback.format_exc().strip().splitlines()[-1])
                x['status'] = 'err'; bad += 1
                x['err_key'] = e.key if isinstance(e, FMError) else ''
                x['err'] = (str(e).splitlines() or [type(e).__name__])[0][:200]
            x['prep'] = None   # bellegi birak
            events.put(('item', x))

    def start():
        with lock:
            if st['running']: return
            if not any(x['status'] == 'wait' for x in items):
                messagebox.showinfo('Statue Maker', T('msg_nothing_waiting'), parent=win); return
        with lock:
            if st['running']: return
            st['running'] = True; st['finished'] = None
        threading.Thread(target=worker, daemon=True).start()
        overall()

    def selected(): return [x for x in (find(int(i)) for i in tree.selection()) if x]

    def drop_item(x):
        items.remove(x); tree.delete(str(x['id']))
        for t in (used_work, used_folder):
            for k in [k for k, v in t.items() if v == x['id']]: del t[k]

    def remove():
        with lock:
            for x in selected():
                if x['status'] not in ('run', 'edit'): drop_item(x)
        overall()

    def clear_done():
        with lock:
            for x in [y for y in items if y['status'] in ('done', 'err')]: drop_item(x)
            st['finished'] = None
        overall()

    def retry():
        for x in selected():
            if x['status'] == 'err': x['status'] = 'wait'; x['err'] = x['err_key'] = ''; refresh(x)

    def edit():
        sel = selected()
        if len(sel) != 1 or sel[0]['status'] != 'wait':
            messagebox.showinfo('Statue Maker', T('msg_select_one'), parent=win); return
        x = sel[0]
        with lock:
            if x['status'] != 'wait': return
            x['status'] = 'edit'
        refresh(x)
        try:
            if not x['prep']: x['prep'] = run_busy(lambda: prepare(x['path'], ba, work_key(x)), 'busy_read', shown(x['path']), win)
            d = dict(x['prep']['opt']); d.update(x['opt'] or {})
            r = form(d, x['prep']['anims'], shown(x['path']), save=True, parent=win, prep=x['prep'])
            if r is not None: x['opt'] = r
        except Exception as e:
            log('HATA:', e); messagebox.showerror(T('err_title'), err_text(e), parent=win)
            x['prep'] = None
        finally:
            x['status'] = 'wait'; refresh(x)

    def open_item(_e=None):
        sel = selected()
        if not sel: return
        x = sel[0]
        if x['status'] == 'done' and x['out']:
            try: os.startfile(x['out'])
            except Exception: pass
        elif x['status'] == 'err':
            messagebox.showerror(T('err_title'), (T(x['err_key']) + '\n\n' if x['err_key'] else '') + (x['err'] or ''), parent=win)
        elif x['status'] == 'wait': edit()

    def open_out():
        d = os.path.join(BASE, 'out'); os.makedirs(d, exist_ok=True)
        try: os.startfile(d)
        except Exception: pass

    def toggle_log():
        show_log.set(not show_log.get())
        if show_log.get(): logf.grid(row=5, column=0, sticky='we', pady=(8, 0))
        else: logf.grid_forget()
        det_btn.config(text=T('btn_details_hide' if show_log.get() else 'btn_details_show'))

    tbtn('btn_add', pick); tbtn('btn_add_folder', pick_folder)
    ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=(4, 10), pady=2)
    edit_b = tbtn('btn_edit', edit); rem_b = tbtn('btn_remove', remove); retry_b = tbtn('btn_retry', retry); clear_b = tbtn('btn_clear', clear_done)
    out_btn.config(command=open_out); texts.append((out_btn, 'btn_out'))
    start_btn.config(command=start); det_btn.config(command=toggle_log)
    tree.bind('<Double-1>', open_item); tree.bind('<Delete>', lambda e: remove())
    tree.bind('<<TreeviewSelect>>', lambda e: overall())

    def retext():
        win.title(f'Statue Maker {VERSION}')
        for w, k in texts: w.config(text=T(k))
        for c in ('file', 'folder', 'status'): tree.heading(c, text=T({'file': 'col_model', 'folder': 'col_folder', 'status': 'col_status'}[c]))
        det_btn.config(text=T('btn_details_hide' if show_log.get() else 'btn_details_show'))
        for x in items: refresh(x)
        overall()
    i.watch(retext)

    def pump():
        try:
            while True:
                k, v = events.get_nowait()
                if k == 'log':
                    logbox.config(state='normal'); logbox.insert('end', v + '\n')
                    if int(logbox.index('end-1c').split('.')[0]) > 2000: logbox.delete('1.0', '500.0')
                    logbox.see('end'); logbox.config(state='disabled')
                elif k == 'item': refresh(v)
                elif k == 'idle':
                    overall()
                    log(f'Kuyruk bitti: {st["finished"][0]} tamam, {st["finished"][1]} hata.')
        except qmod.Empty: pass
        if win.winfo_exists(): win.after(150, pump)

    def close():
        if st['running'] and not messagebox.askyesno('Statue Maker', T('msg_close_running'), parent=win):
            return
        win.destroy()
    win.protocol('WM_DELETE_WINDOW', close)

    win._fm_add = add   # disaridan (test) ekleme
    if not enable_drop(win, add): log('Not: surukle-birak calismiyor, "Dosya ekle" kullan')
    add(files)
    pump()
    center(win); bring_front(win)
    master.wait_window(win)
    i.unwatch(retext)
    LOG_SINK = None


def main():
    ap = argparse.ArgumentParser(description='StatueShop heykel uretici')
    ap.add_argument('model', nargs='*'); ap.add_argument('--name'); ap.add_argument('--en'); ap.add_argument('--tr')
    ap.add_argument('--pose'); ap.add_argument('--pose-time', type=float, default=0.0)
    ap.add_argument('--animated', action='store_true', help='heykel secilen animasyonu dongude oynatsin')
    ap.add_argument('--height', type=float, default=1.8, help='heykelin boyu (metre)')
    ap.add_argument('--price', type=float, default=15000.0)
    ap.add_argument('--yaw', type=float, default=25.0, help='ikon kamerasinin yan acisi')
    ap.add_argument('--up', default='auto', help='modelin yukari ekseni: auto (bul), Y (oldugu gibi), Z, -Z, X, -X, -Y')
    ap.add_argument('--hide', help='heykele alinmayacak parcalar: virgulle ayrilmis materyal adlari (adin bir kismi da olur)')
    ap.add_argument('--show', help='otomatik kapatilan parcalardan geri alinacaklar (ayni bicim)')
    ap.add_argument('--no-bc7', dest='bc7', action='store_false', help='dokulari BC7\'ye cevirme (PNG/JPG kalsin)')
    ap.add_argument('--install', action='store_true', help='UserData/StatueShop icine de kopyala')
    ap.add_argument('--form', action='store_true', help='heykel formunu ac')
    ap.add_argument('--no-form', action='store_true', help='formu acma (komut satiri)')
    ap.add_argument('--batch', action='store_true', help='toplu cevirme penceresini ac')
    a = ap.parse_args()
    models = a.model

    # cift tik (model yok) ya da birden cok model / klasor surukle-birak: toplu pencere
    if not a.no_form and (a.batch or not models or len(models) > 1 or any(os.path.isdir(m) for m in models)):
        hide_console()
        queue_window(a, models)
        return
    if a.no_form and (len(models) > 1 or any(os.path.isdir(m) for m in models)):
        ok = bad = 0
        for m in expand_models(models):
            try:
                b = argparse.Namespace(**vars(a)); b.name = b.en = b.tr = None
                p = prepare(m, b); build(p, p['opt'], b); ok += 1
            except Exception as e:
                traceback.print_exc(); log('HATA:', m, e); bad += 1
        log(f'Toplu: {ok} tamam, {bad} hata')
        if bad: sys.exit(1)
        return
    if not models: ap.error('model gerekli')

    a.model = models[0]
    if len(sys.argv) <= 2 and not a.no_form: a.form = True   # surukle-birak / cift tik: form
    if not a.form:
        p = prepare(a.model, a); build(p, p['opt'], a)
        log('Gerekli: Fabianens Statue Shop ve Fabianens Mod Market. Klasoru UserData\\StatueShop\\ icine kopyala, oyunu yeniden baslat.')
        return
    hide_console()
    name = os.path.basename(a.model)
    p = run_busy(lambda: prepare(a.model, a), 'busy_read', name)
    opt = p['opt']
    r = form(opt, p['anims'], name, prep=p)
    if r is None: log('iptal edildi'); return
    opt.update(r)
    folder, out = run_busy(lambda: build(p, opt, a), 'busy_convert', name)
    message('Statue Maker – ' + T('done_title'), T('done_text', folder=folder))
    try: os.startfile(out)
    except Exception: pass

if __name__ == '__main__':
    try: main()
    except Exception as e:
        traceback.print_exc()
        if _TK is not None: message('Statue Maker – ' + T('err_title'), err_text(e), True)
        sys.exit(1)
