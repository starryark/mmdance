#!/bin/bash
# Prepare a Linux GPU machine (tested on a RunPod L40S pod) for headless EEVEE renders: Blender 5.2.2
# and the GL/EGL/Vulkan client libraries that the NVIDIA driver's graphics libraries need. Start
# the container with NVIDIA_DRIVER_CAPABILITIES=all, or EEVEE finds no GPU; check with gpu_check.py.
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq libegl1 libgl1 libglvnd0 libgles2 libvulkan1 libxi6 libxxf86vm1 libxfixes3 libxrender1 \
    libxkbcommon0 libxkbcommon-x11-0 libsm6 libice6 libx11-6 libxext6 libxrandr2 libxinerama1 libxcursor1 \
    libwayland-client0 libwayland-egl1 libdbus-1-3 xz-utils ffmpeg rsync >/dev/null
mkdir -p /opt && cd /opt
if [ ! -x /opt/blender/blender ]; then
  for m in https://mirrors.ocf.berkeley.edu/blender https://mirror.clarkson.edu/blender https://ftp.halifax.rwth-aachen.de/blender; do
    if curl -sfL -o blender.tar.xz "$m/release/Blender5.2/blender-5.2.2-linux-x64.tar.xz"; then
      curl -sfL -o blender.sha256 "$m/release/Blender5.2/blender-5.2.2.sha256" || true
      break
    fi
  done
  if [ -s blender.sha256 ]; then
    want=$(grep linux-x64.tar.xz blender.sha256 | cut -d' ' -f1); got=$(sha256sum blender.tar.xz | cut -d' ' -f1)
    [ "$want" = "$got" ] && echo "blender sha256 OK" || { echo "blender sha256 MISMATCH $want $got"; exit 1; }
  fi
  tar -xf blender.tar.xz && mv blender-5.2.2-linux-x64 blender && rm blender.tar.xz
fi
/opt/blender/blender --version | head -1
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
ls /usr/lib/x86_64-linux-gnu/ | grep -E "libEGL_nvidia|libGLX_nvidia|libnvidia-glcore|libnvidia-eglcore" | head
ls /usr/share/glvnd/egl_vendor.d/ /etc/vulkan/icd.d/ /usr/share/vulkan/icd.d/ 2>/dev/null || true
