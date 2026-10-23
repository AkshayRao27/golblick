// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Stitches one frame of a clip, steadied, straight into NV12, for ffmpeg's
// program_opencl (golblick-worker.sh). program_opencl runs this once for the
// luma plane and once for the interleaved chroma plane, handing it the same
// plane of every input, so each table is P016 laid out for that by
// lib/Render/GpuTables.php: plane 0 holds one table at full size, plane 1 two
// at half size.
//
// The geometry is the CPU stitch's (lib/Service/VideoRenderer.php): the output
// sample's direction, turned by the frame's steadying (steady.cl's
// convention), looked up in the app's tables, which are made for the levelled
// clip. So the picture is resampled once, where stitching and then baking
// resampled it twice. The lenses hand over in two bands, as in the desktop
// player: the narrow band's blend, plus (mask - wide) times the difference of
// the lenses blurred, which are the lenses scaled down to a pixel about 3
// degrees across and sampled bilinearly (the player's mip level). Blending is
// linear, so it works on Y, U and V as it would on R, G and B.
//
// #defines from the job: WIDTH (output width), MARK (1 to set the frame
// code's baked bit: the copy is steadied and the player mustn't steady it
// again), SAMPLES (how many turns across each frame's readout the shutter
// input holds; 0, no such input and the rolling shutter is left in).

__constant sampler_t pick = CLK_NORMALIZED_COORDS_FALSE | CLK_ADDRESS_CLAMP_TO_EDGE | CLK_FILTER_NEAREST;
__constant sampler_t smooth = CLK_NORMALIZED_COORDS_FALSE | CLK_ADDRESS_CLAMP_TO_EDGE | CLK_FILTER_LINEAR;
__constant sampler_t wrap = CLK_NORMALIZED_COORDS_TRUE | CLK_ADDRESS_REPEAT | CLK_FILTER_LINEAR;

#define CODE_ROWS 16
#define CODE_CELLS 40
#define BAKED (1u << 19)

float3 turn(float4 q, float3 v) {
    float3 u = (float3)(q.y, q.z, q.w);
    return v + 2.0f * cross(u, cross(u, v) + q.x * v);
}

// Bilinear round the circle, clamped at the poles; both channels, as 16-bit integers.
float2 table(__read_only image2d_t t, float2 uv) {
    int2 size = get_image_dim(t);
    uv.y = clamp(uv.y, 0.5f / size.y, 1.0f - 0.5f / size.y);
    return read_imagef(t, wrap, uv).xy * 65535.0f;
}

// Quaternion k of a track (w, x, y, z): plane 0 as steady.cl reads it, plane 1 as two pixels a frame.
float4 stored(__read_only image2d_t t, int k, bool chroma) {
    int2 rows = get_image_dim(t);
    float4 q;
    if (!chroma) {
        k = min(k, rows.x * (rows.y / 8) - 1);
        int col = k % rows.x, row = 4 * (k / rows.x);
        q = (float4)(read_imagef(t, pick, (int2)(col, row)).x, read_imagef(t, pick, (int2)(col, row + 1)).x,
                     read_imagef(t, pick, (int2)(col, row + 2)).x, read_imagef(t, pick, (int2)(col, row + 3)).x);
    } else {
        k = min(k, rows.x * (rows.y / 2) - 1);
        int col = k % rows.x, row = 2 * (k / rows.x);
        float2 a = read_imagef(t, pick, (int2)(col, row)).xy, b = read_imagef(t, pick, (int2)(col, row + 1)).xy;
        q = (float4)(a.x, a.y, b.x, b.y);
    }
    return q * 2.0f - 1.0f;
}

// golblick's equirectangular convention (render._rays), as texture coordinates.
float2 around(float3 s) {
    return (float2)((atan2(s.x, s.z) + 3.141592654f) / 6.283185307f,
                    (1.570796327f - asin(clamp(s.y, -1.0f, 1.0f))) / 3.141592654f);
}

// Where each lens sees a direction, in full-size lens pixels, from this pass's tables.
float2 lens0_at(float2 uv, bool chroma, __read_only image2d_t ta, __read_only image2d_t tb) {
    return chroma ? table(ta, uv) : (float2)(table(ta, uv).x, table(tb, uv).x);
}

float2 lens1_at(float2 uv, bool chroma, __read_only image2d_t tb, __read_only image2d_t tc, __read_only image2d_t td) {
    return chroma ? table(tb, uv) : (float2)(table(tc, uv).x, table(td, uv).x);
}

#if SAMPLES > 1
// render._project_read: a lens row was read (row / height) of the way through
// the frame, so the direction is turned by the camera's turn to that moment,
// between the two nearest of the frame's SAMPLES (in the tables' frame,
// Stabilise::shutterFor).
float3 when_read(float3 s, float row, __read_only image2d_t shutter, unsigned int index, bool chroma) {
    float at = clamp(row, 0.0f, 1.0f) * (SAMPLES - 1);
    int j = min((int)floor(at), SAMPLES - 2);
    int k = SAMPLES * (int)index + j;
    float3 mixed = mix(turn(stored(shutter, k, chroma), s), turn(stored(shutter, k + 1, chroma), s), at - j);
    return normalize(mixed);
}
#endif

// A lens at a position in full-size lens pixels (centres at +0.5), in this pass's plane.
float2 lens(__read_only image2d_t img, float2 at, float scale) {
    int2 size = get_image_dim(img);
    float2 c = clamp(at * scale, (float2)(0.5f, 0.5f), (float2)(size.x - 0.5f, size.y - 0.5f));
    return read_imagef(img, smooth, c).xy;
}

__kernel void stitch(__write_only image2d_t dst, unsigned int index,
                     __read_only image2d_t lens0, __read_only image2d_t lens1,
                     __read_only image2d_t blur0, __read_only image2d_t blur1,
                     __read_only image2d_t ta, __read_only image2d_t tb, __read_only image2d_t tc,
                     __read_only image2d_t td, __read_only image2d_t te, __read_only image2d_t tf,
                     __read_only image2d_t track
#if SAMPLES > 1
                     , __read_only image2d_t shutter
#endif
                     ) {
    int2 p = (int2)(get_global_id(0), get_global_id(1));
    int2 size = get_image_dim(dst);
    bool chroma = size.x < WIDTH;
    float scale = chroma ? 0.5f : 1.0f;     // chroma planes are half size, lenses and tables alike

    int code_rows = chroma ? CODE_ROWS / 2 : CODE_ROWS;
    if (p.y >= size.y - code_rows) {
        uint code = (index & (BAKED - 1u)) | (MARK ? BAKED : 0u);
        int cell = p.x * CODE_CELLS / size.x;
        bool set = ((code >> (cell / 2)) & 1u) != 0u;
        float shade = (cell % 2 == 0) == set ? 1.0f : 0.0f;
        write_imagef(dst, p, chroma ? (float4)(0.5f, 0.5f, 0.0f, 1.0f) : (float4)(shade, 0.0f, 0.0f, 1.0f));
        return;
    }

    // The frame's steadying; the player turns the sphere by q, so the picture is sampled by the inverse.
    float4 q = stored(track, (int)index, chroma);
    q.yzw = -q.yzw;

    float lon = (p.x + 0.5f) / size.x * 6.283185307f - 3.141592654f;
    float lat = 1.570796327f - (p.y + 0.5f) / size.y * 3.141592654f;
    float3 s = turn(q, (float3)(cos(lat) * sin(lon), sin(lat), cos(lat) * cos(lon)));
    float2 uv = around(s);

    float2 at0 = lens0_at(uv, chroma, ta, tb);
    float2 at1 = lens1_at(uv, chroma, tb, tc, td);
    float share = (chroma ? table(tc, uv).x : table(te, uv).x) / 65535.0f;
#if SAMPLES > 1
    // Twice, because the turn moves the row a direction lands on.
    float height = get_image_dim(lens0).y / scale;
    for (int n = 0; n < 2; n++) {
        at0 = lens0_at(around(when_read(s, at0.y / height, shutter, index, chroma)), chroma, ta, tb);
        at1 = lens1_at(around(when_read(s, at1.y / height, shutter, index, chroma)), chroma, tb, tc, td);
    }
#endif
    float2 v;
    if (share <= 0.0f) {
        v = lens(lens0, at0 + 0.5f, scale);
    } else if (share >= 1.0f) {
        v = lens(lens1, at1 + 0.5f, scale);
    } else {
        v = mix(lens(lens0, at0 + 0.5f, scale), lens(lens1, at1 + 0.5f, scale), share);
    }

    // The wide band: the tables fold wide back to share wherever it mustn't apply.
    float wide = table(tf, uv).x / 65535.0f;
    if (wide != share) {
        float small = scale * get_image_dim(blur0).x / get_image_dim(lens0).x;
        v = clamp(v + (share - wide) * (lens(blur0, at0 + 0.5f, small) - lens(blur1, at1 + 0.5f, small)), 0.0f, 1.0f);
    }
    write_imagef(dst, p, (float4)(v.x, chroma ? v.y : 0.0f, 0.0f, 1.0f));
}
