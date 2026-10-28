"""Which GPU does EEVEE get? Render the default scene once and report the GPU backend and renderer.
  blender -b --python gpu_check.py      (writes /workspace/gpu_check.png)"""
import time

import bpy
import gpu

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
sc.eevee.taa_render_samples = 64
sc.render.filepath = '/workspace/gpu_check.png'
t = time.time()
bpy.ops.render.render(write_still=True)
print('RENDER_SECONDS', round(time.time() - t, 2))
print('GPU_BACKEND', gpu.platform.backend_type_get(), '| VENDOR', gpu.platform.vendor_get(), '| RENDERER', gpu.platform.renderer_get())
