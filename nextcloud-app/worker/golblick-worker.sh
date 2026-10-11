#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# golblick's GPU worker: bakes the steadying into the stitched copies the
# Nextcloud app leaves in its video folder, so they play steady anywhere.
#
# Usage: golblick-worker.sh JOBS_DIR
#
# JOBS_DIR is the app's video folder (<datadirectory>/appdata_<instanceid>/golblick/videos),
# the only thing the worker writes to. Run it as the web server's user, in a
# container that has ffmpeg with OpenCL and the GPU; README.md has a compose file.
#
# The app asks for a bake by leaving <name>.bake/ next to <name>.mp4, holding
# `track.raw` (lib/Service/BakeQueue.php) and `job`, and creating `ready` last.
# The worker writes `baked.mp4`, `log` and finally `status` (ffmpeg's exit code)
# into it; the app's render job takes it from there. `worker.json` is a heartbeat
# the app reads to know a worker is there.

set -u
VERSION=1
JOBS=${1:?usage: golblick-worker.sh JOBS_DIR}
KERNEL="$(cd "$(dirname "$0")" && pwd)/steady.cl"
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
echo "golblick-worker $VERSION: $device, ${encoder[1]}, watching $JOBS" >&2

heartbeat() {
	printf '{"version":%d,"seen":%d,"device":"%s","encoder":"%s"}\n' \
		"$VERSION" "$(date +%s)" "${device//[\"\\]/}" "${encoder[1]}" > worker.json.part && mv -f worker.json.part worker.json
}

# A bake that was running when the worker stopped is tried again.
for running in *.bake/running; do
	[ -e "$running" ] && rm -f "$running"
done

value() {   # value FILE KEY: a whole-number setting from a job file, or nothing
	sed -n "s/^$2=\([0-9][0-9]*\)\$/\1/p" "$1" | head -n 1
}

probe() {   # probe FILE: the video's frame count, frame rate (as a fraction) and duration
	ffprobe -v error -count_packets -select_streams v:0 -show_entries stream=nb_read_packets,r_frame_rate:format=duration \
		-of default=noprint_wrappers=1 "$1"
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
	echo "$code" > "$dir/status.part"
	mv -f "$dir/status.part" "$dir/status"
	rm -f "$dir/running"
}

# The heartbeat keeps going through a long bake.
(while true; do heartbeat; sleep 10; done) &
trap 'kill $! 2>/dev/null' EXIT

while true; do
	for ready in *.bake/ready; do
		[ -e "$ready" ] || continue
		dir=${ready%/ready}
		[ -e "$dir/status" ] || [ -e "$dir/running" ] || bake "$dir"
	done
	sleep 10
done
