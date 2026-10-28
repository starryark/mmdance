#!/bin/bash
# Render a packed scene (python -m mmdance pack) on a GPU machine with N Blender processes sharing
# the GPU. The scene writes no-overwrite + placeholders, so the processes split the frames and a
# rerun resumes. Motion blur makes EEVEE CPU-bound by the scene evaluation, so more processes than
# usual pay off (nine shared one L40S for DreamWings).
#   render_job.sh <scene.blend> <first> <last> [processes]       ($BLENDER, default /opt/blender/blender)
set -u
blend=$1; first=$2; last=$3; jobs=${4:-2}
exe=${BLENDER:-/opt/blender/blender}
dir=$(dirname "$blend"); name=$(basename "$blend" .blend)
mkdir -p "$dir/logs"
for j in $(seq 1 "$jobs"); do
  "$exe" -b "$blend" --enable-autoexec -s "$first" -e "$last" -a > "$dir/logs/${name}_$j.log" 2>&1 &
  sleep 20                               # stagger: the first process compiles the shaders
done
wait
n=$(find "$dir/frames" -name '*.png' -size +1k 2>/dev/null | wc -l)
echo "DONE $name: $n frames over 1 KB (placeholders are smaller)"
