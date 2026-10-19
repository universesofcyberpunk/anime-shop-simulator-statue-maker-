# Blender: FBX (ya da OBJ / BLEND) -> GLB (iskelet + animasyon + dokular gomulu)
import bpy, sys, os
argv = sys.argv[sys.argv.index('--') + 1:]
src, dst = argv[0], argv[1]
ext = os.path.splitext(src)[1].lower()
if ext == '.blend':
    bpy.ops.wm.open_mainfile(filepath=src)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=src, use_anim=True, automatic_bone_orientation=True)
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=src)
    else:
        raise SystemExit('unsupported: ' + ext)
# dokular: FBX yanindaki klasorlerde aranir
try: bpy.ops.file.find_missing_files(directory=os.path.dirname(src))
except Exception: pass
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_animations=True, export_skins=True,
                          export_yup=True, export_apply=False, export_image_format='AUTO', export_force_sampling=True)
print('FBX2GLB ok')
