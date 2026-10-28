"""Which GPU does EEVEE get? Render the default scene once and report the GPU backend and renderer.
  blender -b --python gpu_check.py [-- out.png]      (default: gpu_check.png in the temp folder)"""
import os
import sys
import tempfile
import time

import bpy
import gpu

out = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else os.path.join(tempfile.gettempdir(), 'gpu_check.png')
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
sc.eevee.taa_render_samples = 64
sc.render.filepath = out
t = time.time()
bpy.ops.render.render(write_still=True)
print('RENDER_SECONDS', round(time.time() - t, 2), '|', out)
renderer = gpu.platform.renderer_get()
print('GPU_BACKEND', gpu.platform.backend_type_get(), '| VENDOR', gpu.platform.vendor_get(), '| RENDERER', renderer)
# llvmpipe: software OpenGL, the container lacks the driver's graphics libraries (NVIDIA_DRIVER_CAPABILITIES=all)
print('EEVEE_ON_GPU', not any(s in renderer.lower() for s in ('llvmpipe', 'softpipe', 'swrast')))
