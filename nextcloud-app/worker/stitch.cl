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
// resampled it twice. Blending and the balance offset are linear, so they work
// on Y, U and V as they would on R, G and B.
//
// #defines from the job: WIDTH (output width), MARK (1 to set the frame
// code's baked bit: the copy is steadied and the player mustn't steady it
// again).

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

float2 entry(__read_only image2d_t t, int2 p) {
    return read_imagef(t, pick, p).xy * 65535.0f;
}

// A lens at a position in full-size lens pixels (centres at +0.5), in this pass's plane.
float2 lens(__read_only image2d_t img, float2 at, float scale) {
    int2 size = get_image_dim(img);
    float2 c = clamp(at * scale, (float2)(0.5f, 0.5f), (float2)(size.x - 0.5f, size.y - 0.5f));
    return read_imagef(img, smooth, c).xy;
}

__kernel void stitch(__write_only image2d_t dst, unsigned int index,
                     __read_only image2d_t lens0, __read_only image2d_t lens1,
                     __read_only image2d_t ta, __read_only image2d_t tb, __read_only image2d_t tc,
                     __read_only image2d_t td, __read_only image2d_t te,
                     __read_only image2d_t fa, __read_only image2d_t fb,
                     __read_only image2d_t ladder, __read_only image2d_t track) {
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

    // The frame's quaternion: plane 0 as steady.cl reads it, plane 1 as two pixels a frame.
    int2 rows = get_image_dim(track);
    float4 q;
    if (!chroma) {
        int k = min((int)index, rows.x * (rows.y / 8) - 1);
        int col = k % rows.x, row = 4 * (k / rows.x);
        q = (float4)(read_imagef(track, pick, (int2)(col, row)).x, read_imagef(track, pick, (int2)(col, row + 1)).x,
                     read_imagef(track, pick, (int2)(col, row + 2)).x, read_imagef(track, pick, (int2)(col, row + 3)).x);
    } else {
        int k = min((int)index, rows.x * (rows.y / 2) - 1);
        int col = k % rows.x, row = 2 * (k / rows.x);
        float2 a = read_imagef(track, pick, (int2)(col, row)).xy, b = read_imagef(track, pick, (int2)(col, row + 1)).xy;
        q = (float4)(a.x, a.y, b.x, b.y);
    }
    q = q * 2.0f - 1.0f;
    q.yzw = -q.yzw;

    float lon = (p.x + 0.5f) / size.x * 6.283185307f - 3.141592654f;
    float lat = 1.570796327f - (p.y + 0.5f) / size.y * 3.141592654f;
    float3 s = turn(q, (float3)(cos(lat) * sin(lon), sin(lat), cos(lat) * cos(lon)));
    float2 uv = (float2)((atan2(s.x, s.z) + 3.141592654f) / 6.283185307f,
                         (1.570796327f - asin(clamp(s.y, -1.0f, 1.0f))) / 3.141592654f);

    float2 at0, at1;
    float share;
    if (!chroma) {
        at0 = (float2)(table(ta, uv).x, table(tb, uv).x);
        at1 = (float2)(table(tc, uv).x, table(td, uv).x);
        share = table(te, uv).x / 65535.0f;
    } else {
        at0 = table(ta, uv);
        at1 = table(tb, uv);
        share = table(tc, uv).x / 65535.0f;
    }
    float2 v;
    if (share <= 0.0f) {
        v = lens(lens0, at0 + 0.5f, scale);
    } else if (share >= 1.0f) {
        v = lens(lens1, at1 + 0.5f, scale);
    } else {
        v = mix(lens(lens0, at0 + 0.5f, scale), lens(lens1, at1 + 0.5f, scale), share);
    }

    // The balance: the ladder looked up through the field, nearest at the
    // field's resolution, spread bilinearly between field pixels (as the CPU graph).
    int2 fsize = get_image_dim(fa);
    float2 c = uv * (float2)(fsize.x, fsize.y) - 0.5f;
    float2 f = floor(c);
    float2 w = c - f;
    float2 corr[4];
    for (int k = 0; k < 4; k++) {
        int i = ((int)f.x + (k & 1)) % fsize.x;
        if (i < 0) i += fsize.x;
        int j = clamp((int)f.y + (k >> 1), 0, fsize.y - 1);
        float2 cr = chroma ? entry(fa, (int2)(i, j)) : (float2)(entry(fa, (int2)(i, j)).x, entry(fb, (int2)(i, j)).x);
        cr = chroma ? cr * 0.5f : cr;   // ladder chroma is half size too
        corr[k] = read_imagef(ladder, pick, (int2)((int)cr.x, (int)cr.y)).xy;
    }
    float2 off = mix(mix(corr[0], corr[1], w.x), mix(corr[2], corr[3], w.x), w.y) - 0.5f;
    v = clamp(v + off, 0.0f, 1.0f);
    write_imagef(dst, p, (float4)(v.x, chroma ? v.y : 0.0f, 0.0f, 1.0f));
}
