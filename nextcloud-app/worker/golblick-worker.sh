#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# golblick's GPU worker: stitches the Nextcloud app's videos on the GPU, and
# bakes the steadying into copies the app stitched itself, so they play
# steady anywhere.
#
# Usage: golblick-worker.sh JOBS_DIR [DATA_DIR]
#
# JOBS_DIR is the app's video folder (<datadirectory>/appdata_<instanceid>/golblick/videos),
# the only thing the worker writes to. DATA_DIR, /data by default, is
# Nextcloud's data directory, mounted read-only, where the clips are; without
# it the worker only bakes. Run it as the web server's user, in a container
# that has ffmpeg with CUDA, OpenCL and the GPU; the app's settings page has a
# compose file.
#
# The app asks for a stitch by leaving <name>.stitch/ holding the tables
# (lib/Render/GpuTables.php), `job` and `inputs` (lib/Service/StitchQueue.php),
# and for a bake by leaving <name>.bake/ next to <name>.mp4, holding
# `track.raw` (lib/Service/BakeQueue.php) and `job`; either way it creates
# `ready` last. The worker writes `stitched.mp4` or `baked.mp4`, `log` and
# finally `status` (ffmpeg's exit code) into the folder; the app's render job
# takes it from there. `worker.json` is a heartbeat the app reads to know a
# worker is there and what it can do.

set -u
VERSION=3
JOBS=${1:?usage: golblick-worker.sh JOBS_DIR [DATA_DIR]}
DATA=${2:-/data}
KERNEL="$(cd "$(dirname "$0")" && pwd)/steady.cl"
STITCH_KERNEL="$(dirname "$KERNEL")/stitch.cl"
cd "$JOBS" || exit 1

device=$(ffmpeg -hide_banner -v verbose -init_hw_device opencl=ocl -f lavfi -i nullsrc=s=16x16 -frames:v 1 -f null - 2>&1 \
	| sed -n 's/^\[OpenCL @ [^]]*\] 0\.0: //p' | head -n 1)
if [ -z "$device" ]; then
	echo "golblick-worker: ffmpeg found no OpenCL device; retrying in a minute" >&2
	sleep 60
	exit 1
fi
# NVENC takes the encode off the CPU where the GPU has it.
if ffmpeg -hide_banner -v error -f lavfi -i nullsrc=s=256x128 -frames:v 1 -c:v h264_nvenc -f null - 2>/dev/null; then
	encoder=(-c:v h264_nvenc -preset p5)
else
	encoder=(-c:v libx264 -preset veryfast -threads 2)
fi
# Stitching decodes on the GPU (CUDA), so it needs an NVIDIA card as well as
# the data directory; anything else still bakes.
stitch=false
if [ -d "$DATA" ] && [ -r "$DATA" ] && ffmpeg -hide_banner -v error -init_hw_device cuda=cu -init_hw_device opencl=ocl -filter_hw_device ocl \
	-f lavfi -i nullsrc=s=64x64 -frames:v 1 -vf format=nv12,hwupload_cuda,scale_cuda=32:32,hwdownload,format=nv12,hwupload -f null - 2>/dev/null; then
	stitch=true
fi
echo "golblick-worker $VERSION: $device, ${encoder[1]}, watching $JOBS, stitching: $stitch" >&2

heartbeat() {
	printf '{"version":%d,"seen":%d,"device":"%s","encoder":"%s","stitch":%s}\n' \
		"$VERSION" "$(date +%s)" "${device//[\"\\]/}" "${encoder[1]}" "$stitch" > worker.json.part && mv -f worker.json.part worker.json
}

# A job that was running when the worker stopped is tried again.
for running in *.bake/running *.stitch/running; do
	[ -e "$running" ] && rm -f "$running"
done

value() {   # value FILE KEY: a whole-number setting from a job file, or nothing
	sed -n "s/^$2=\([0-9][0-9]*\)\$/\1/p" "$1" | head -n 1
}

probe() {   # probe FILE: the video's frame count, frame rate (as a fraction) and duration
	ffprobe -v error -count_packets -select_streams v:0 -show_entries stream=nb_read_packets,r_frame_rate:format=duration \
		-of default=noprint_wrappers=1 "$1"
}

text() {    # text FILE KEY PATTERN: a setting from a job file that matches PATTERN in full, or nothing
	sed -n "s#^$2=\($3\)\$#\1#p" "$1" | head -n 1
}

field() {   # field PROBE KEY [PATTERN]
	sed -n "s|^$2=\(${3:-[0-9][0-9]*}\)\$|\1|p" <<< "$1" | head -n 1
}

bake() {
	local dir=$1 name=${1%.bake}
	local rows bitrate source frames rate
	rows=$(value "$dir/job" rows)
	bitrate=$(value "$dir/job" bitrate)
	source=$(probe "$name.mp4")
	frames=$(field "$source" nb_read_packets)
	rate=$(field "$source" r_frame_rate '[0-9][0-9]*/[0-9][0-9]*')
	if [ -z "$rows" ] || [ -z "$bitrate" ] || [ -z "$frames" ] || [ -z "$rate" ]; then
		echo "golblick-worker: $dir/job or $name.mp4 is unreadable" > "$dir/log"
		echo 1 > "$dir/status"
		return
	fi
	touch "$dir/running"
	nice -n 19 ffmpeg -nostdin -v error -y -init_hw_device opencl=ocl -filter_hw_device ocl \
		-threads 2 -i "$name.mp4" \
		-f rawvideo -pixel_format gray16le -video_size "4096x$((4 * rows))" -framerate "$rate" -stream_loop -1 -i "$dir/track.raw" \
		-filter_complex "[0:v]format=rgba,hwupload[v];[1:v]hwupload[t];[v][t]program_opencl=source=$KERNEL:kernel=steady:inputs=2,hwdownload,format=rgba,format=yuv420p[out]" \
		-map '[out]' -map '0:a:0?' -frames:v "$frames" "${encoder[@]}" \
		-b:v "$bitrate" -maxrate "$((bitrate * 3 / 2))" -bufsize "$((bitrate * 2))" \
		-c:a copy -map_metadata 0 -movflags +faststart -f mp4 "$dir/baked.mp4" > "$dir/log" 2>&1
	local code=$?
	# The track has to run at the copy's frame rate, or the two inputs fall out
	# of step and the output's timing comes apart: a 25 fps copy once came out
	# 39 times its length. Refuse anything that isn't frame for frame the copy.
	if [ "$code" = 0 ]; then
		local baked
		baked=$(probe "$dir/baked.mp4")
		if [ "$(field "$baked" nb_read_packets)" != "$frames" ] || ! awk -v a="$(field "$baked" duration '[0-9.]*')" \
			-v b="$(field "$source" duration '[0-9.]*')" 'BEGIN { exit !(a != "" && b != "" && a - b < 0.5 && b - a < 0.5) }'; then
			echo "golblick-worker: the baked copy doesn't match the copy frame for frame" >> "$dir/log"
			code=3
		fi
	fi
	finish "$dir" "$code"
}

finish() {  # finish DIR CODE: hand the result back to the app
	echo "$2" > "$1/status.part"
	mv -f "$1/status.part" "$1/status"
	rm -f "$1/running"
}

# One pass on the GPU from the camera's files to a finished copy: both lenses
# decoded and scaled with CUDA, stitched and steadied by stitch.cl, encoded
# with NVENC. ffmpeg can't hand CUDA frames to OpenCL directly, so each lens
# goes through memory once; on the way it is also scaled down to `blur` on the
# CPU, the blurred copy stitch.cl's wide band samples.
stitch() {
	local dir=$1
	local width lens blur bitrate mark matrix range rate created duration track shutter samples
	width=$(value "$dir/job" width); lens=$(value "$dir/job" lens); blur=$(value "$dir/job" blur)
	bitrate=$(value "$dir/job" bitrate)
	mark=$(text "$dir/job" mark '[01]')
	matrix=$(text "$dir/job" matrix 'bt709\|smpte170m\|bt470bg')
	range=$(text "$dir/job" range 'pc\|tv')
	rate=$(text "$dir/job" rate '[0-9][0-9]*/[0-9][0-9]*')
	created=$(text "$dir/job" created '[0-9T:.Z-]*')
	duration=$(text "$dir/job" duration '[0-9][0-9.]*')
	track=$(text "$dir/job" track '[0-9][0-9]*x[0-9][0-9]*')
	# Optional: each frame's turns across its readout, to undo rolling shutter.
	shutter=$(text "$dir/job" shutter '[0-9][0-9]*x[0-9][0-9]*'); samples=$(value "$dir/job" samples)
	[ -n "$shutter" ] && [ -n "$samples" ] && [ -r "$dir/shutter.p016" ] || { shutter=; samples=0; }
	local inputs=()
	while IFS= read -r path; do
		# Only files under the data directory, named the way the app names them.
		case "$path" in "$DATA"/*/../* | "$DATA"/../*) ;; "$DATA"/*) [ -r "$path" ] && inputs+=("$path") ;; esac
	done < "$dir/inputs"
	if [ "$stitch" != true ] || [ -z "$width" ] || [ -z "$lens" ] || [ -z "$blur" ] \
		|| [ -z "$bitrate" ] || [ -z "$mark" ] || [ -z "$matrix" ] || [ -z "$range" ] || [ -z "$rate" ] || [ -z "$duration" ] \
		|| [ -z "$track" ] || [ "${#inputs[@]}" = 0 ] || [ "${#inputs[@]}" != "$(grep -c . "$dir/inputs")" ]; then
		echo "golblick-worker: $dir/job is unreadable, or a clip in $dir/inputs can't be read under $DATA" > "$dir/log"
		finish "$dir" 1
		return
	fi
	touch "$dir/running"
	printf '#define WIDTH %d\n#define MARK %d\n#define SAMPLES %d\n' "$width" "$mark" "$samples" | cat - "$STITCH_KERNEL" > "$dir/stitch.cl"

	# ffmpeg negotiates colour range and space across a filter's inputs and
	# can't convert frames on the GPU, so every input to the kernel carries
	# the lenses' own tags.
	local tag="setparams=range=$range:colorspace=$matrix:color_primaries=$matrix:color_trc=$matrix"
	local decode=(-threads 1 -hwaccel cuda -hwaccel_device cu -hwaccel_output_format cuda)
	local args=() a b
	if [ "${#inputs[@]}" = 2 ]; then
		args=("${decode[@]}" -i "${inputs[0]}" "${decode[@]}" -i "${inputs[1]}"); a='[0:v:0]'; b='[1:v:0]'
	else
		args=("${decode[@]}" -i "${inputs[0]}"); a='[0:v:0]'; b='[0:v:1]'
	fi
	local n=${#inputs[@]} t size f
	declare -A at
	local static=(ta tb tc td te tf track)
	[ -n "$shutter" ] && static+=(shutter)
	for t in "${static[@]}"; do
		case $t in track) size=$track ;; shutter) size=$shutter ;; *) size="${width}x$((width / 2))" ;; esac
		args+=(-threads 1 -f rawvideo -pixel_format p016le -video_size "$size" -i "$dir/$t.p016"); at[$t]=$n; n=$((n + 1))
	done
	f="${a}scale_cuda=$lens:$lens:interp_algo=lanczos,hwdownload,format=nv12,split[m0][q0];"
	f+="${b}scale_cuda=$lens:$lens:interp_algo=lanczos,hwdownload,format=nv12,split[m1][q1];"
	f+="[m0]hwupload[l0];[m1]hwupload[l1];"
	f+="[q0]scale=$blur:$blur:flags=area,hwupload[s0];[q1]scale=$blur:$blur:flags=area,hwupload[s1];"
	local kernel="[l0][l1][s0][s1][ta][tb][tc][td][te][tf][track]"
	[ -n "$shutter" ] && kernel+="[shutter]"
	for t in "${static[@]}"; do f+="[${at[$t]}:v]$tag,hwupload[$t];"; done
	f+="${kernel}program_opencl=source=$dir/stitch.cl:kernel=stitch:inputs=$((${#static[@]} + 4)):size=${width}x$((width / 2)),"
	f+="hwdownload,format=nv12,settb=AVTB,setpts=N*${rate#*/}/${rate%/*}/TB[out]"

	local meta=()
	[ -n "$created" ] && meta=(-metadata "creation_time=$created")
	# No frame limit: the static inputs repeat, so the graph ends with the lenses.
	nice -n 19 ffmpeg -nostdin -v error -y -filter_threads 1 -init_hw_device cuda=cu -init_hw_device opencl=ocl -filter_hw_device ocl \
		"${args[@]}" -filter_complex "$f" -map '[out]' -map '0:a:0?' -r "$rate" \
		"${encoder[@]}" -b:v "$bitrate" -maxrate "$((bitrate * 3 / 2))" -bufsize "$((bitrate * 2))" \
		-color_range "$range" -colorspace "$matrix" -color_primaries "$matrix" -color_trc "$matrix" \
		-c:a copy "${meta[@]}" -movflags +faststart -progress "$dir/progress" -stats_period 5 -f mp4 "$dir/stitched.mp4" > "$dir/log" 2>&1
	local code=$?
	if [ "$code" = 0 ] && ! awk -v a="$(field "$(probe "$dir/stitched.mp4")" duration '[0-9.]*')" -v b="$duration" \
		'BEGIN { exit !(a != "" && a - b < 1 && b - a < 1) }'; then
		echo "golblick-worker: the stitched copy isn't as long as the clip" >> "$dir/log"
		code=3
	fi
	finish "$dir" "$code"
}

# The heartbeat keeps going through a long bake.
(while true; do heartbeat; sleep 10; done) &
trap 'kill $! 2>/dev/null' EXIT

while true; do
	# Upgrading the app replaces its folder, and this container's mount of it
	# then points at the deleted one, so every bake would fail. Exiting lets
	# Docker's restart policy start it again on the new folder.
	if [ ! -f "$KERNEL" ] || [ ! -f "$STITCH_KERNEL" ]; then
		echo "golblick-worker: $KERNEL is gone (the app was upgraded?); exiting so the container restarts" >&2
		exit 1
	fi
	for ready in *.bake/ready; do
		[ -e "$ready" ] || continue
		dir=${ready%/ready}
		[ -e "$dir/status" ] || [ -e "$dir/running" ] || bake "$dir"
	done
	for ready in *.stitch/ready; do
		[ -e "$ready" ] || continue
		dir=${ready%/ready}
		[ -e "$dir/status" ] || [ -e "$dir/running" ] || stitch "$dir"
	done
	sleep 10
done
