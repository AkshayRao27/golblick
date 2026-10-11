// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Bakes the steadying into a stitched copy, for ffmpeg's program_opencl
// (golblick-worker.sh). Inputs: the copy, as one RGBA plane, and the track the
// app wrote (lib/Service/BakeQueue.php): 16-bit grey, 4096 frames a row, each
// frame's quaternion (w, x, y, z) on four rows as (c + 1) / 2.
//
// The output is the frame as the player would show it steadied, and its frame
// code (lib/Render/FrameCode.php) redrawn with bit 19 set, which tells the
// player the copy is already steady.

__constant sampler_t pick = CLK_NORMALIZED_COORDS_FALSE | CLK_ADDRESS_CLAMP_TO_EDGE | CLK_FILTER_NEAREST;
__constant sampler_t blend = CLK_NORMALIZED_COORDS_TRUE | CLK_ADDRESS_REPEAT | CLK_FILTER_LINEAR;

#define CODE_ROWS 16
#define CODE_CELLS 40
#define BAKED (1u << 19)

float3 turn(float4 q, float3 v) {
    float3 u = (float3)(q.y, q.z, q.w);
    return v + 2.0f * cross(u, cross(u, v) + q.x * v);
}

// index is the frame's number in the filter graph, which is ffmpeg's n when
// the copy was rendered: the copy is decoded in order and nothing is dropped.
__kernel void steady(__write_only image2d_t dst, unsigned int index, __read_only image2d_t src, __read_only image2d_t track) {
    int2 p = (int2)(get_global_id(0), get_global_id(1));
    int2 size = get_image_dim(dst);

    if (p.y >= size.y - CODE_ROWS) {
        uint code = (index & (BAKED - 1u)) | BAKED;
        int cell = p.x * CODE_CELLS / size.x;
        bool set = ((code >> (cell / 2)) & 1u) != 0u;
        // The even cell is white when the bit is set, the odd one when it isn't.
        float shade = (cell % 2 == 0) == set ? 1.0f : 0.0f;
        write_imagef(dst, p, (float4)(shade, shade, shade, 1.0f));
        return;
    }

    int2 rows = get_image_dim(track);
    int k = min((int)index, rows.x * (rows.y / 4) - 1);
    int col = k % rows.x, row = 4 * (k / rows.x);
    float4 q = (float4)(read_imagef(track, pick, (int2)(col, row)).x, read_imagef(track, pick, (int2)(col, row + 1)).x,
                        read_imagef(track, pick, (int2)(col, row + 2)).x, read_imagef(track, pick, (int2)(col, row + 3)).x)
               * 2.0f - 1.0f;
    // The player turns the sphere by q; turning the picture the same way
    // means sampling it by the inverse.
    q.yzw = -q.yzw;

    // golblick's equirectangular convention (render._rays).
    float lon = (p.x + 0.5f) / size.x * 6.283185307f - 3.141592654f;
    float lat = 1.570796327f - (p.y + 0.5f) / size.y * 3.141592654f;
    float3 s = turn(q, (float3)(cos(lat) * sin(lon), sin(lat), cos(lat) * cos(lon)));
    float2 at = (float2)((atan2(s.x, s.z) + 3.141592654f) / 6.283185307f,
                         (1.570796327f - asin(clamp(s.y, -1.0f, 1.0f))) / 3.141592654f);
    // Never the old code strip: the row above it stands in, as in the player.
    at.y = min(at.y, 1.0f - (CODE_ROWS + 0.5f) / size.y);
    write_imagef(dst, p, read_imagef(src, blend, at));
}
