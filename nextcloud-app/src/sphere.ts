/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * A drag-to-look sphere for one equirectangular image, rendered with three.js.
 *
 * A cut-down port of the panorama viewer this project wrote for Nextcloud
 * Memories (PsPanorama.ts on the feat/panorama-viewer branch): a .insp render
 * always covers the whole sphere, so the crop handling is gone.
 *
 * This module is imported dynamically, so three.js lands in its own chunk and
 * costs nothing on a page where nobody opens a sphere.
 */
import {
  DataTexture,
  FloatType,
  MathUtils,
  Mesh,
  MeshBasicMaterial,
  NearestFilter,
  PerspectiveCamera,
  RGBAFormat,
  SRGBColorSpace,
  Scene,
  ShaderChunk,
  SphereGeometry,
  type Texture,
  TextureLoader,
  VideoTexture,
  WebGLRenderer,
} from 'three';

/**
 * The rotation that steadies each frame of a video (lib/Service/MotionStore):
 * one quaternion (w, x, y, z) per frame, scaled by 32767, `period` seconds apart.
 * `turn` is how far that view's heading has turned since frame 0 (radians,
 * scaled by 32767 / pi); turning back by it locks the direction.
 */
export type Motion = { period: number; frames: number; q: Int16Array; turn: Int16Array };

/** Rows of the track texture: 4096 frames a row. WebGL2 only promises 2048, though desktop GPUs allow 4096 or more. */
const TRACK_WIDTH = 4096;

/**
 * The copies carry each frame's number in their bottom 16 rows
 * (lib/Render/FrameCode.php): 19 bits and a flag for a copy whose steadying is
 * already baked in (worker/steady.cl), each cell next to its complement. The
 * vertex shader reads it from the same texture the fragment shader draws, so
 * the sphere turns for the frame on screen. A frame whose pairs don't read as
 * complements carries no code (an older copy, someone else's MP4) and isn't
 * turned.
 *
 * Never steady by the browser's clock (currentTime, requestVideoFrameCallback):
 * Firefox runs it ahead of the drawn frame, and the sphere flickers.
 * AGENT-NOTES.md, "Video spheres", has the measurements.
 */
const CODE_VERTEX_HEAD = `
uniform sampler2D uCode;
uniform bool uCoded;
uniform float uCodeRow;
uniform float uStripTop;
uniform highp sampler2D uTrack;
uniform highp sampler2D uBakedTrack;
varying float vStripTop;
vec3 turnBy(vec4 q, vec3 v) {
  return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v);
}
`;
const CODE_VERTEX_BODY = `
vStripTop = 0.0;
vec4 steadyTurn = vec4(0.0, 0.0, 0.0, 1.0);
if (uCoded) {
  float frameNumber = 0.0;
  bool valid = true;
  bool baked = false;
  for (int i = 0; i < 20; i++) {
    float set = textureLod(uCode, vec2((float(2 * i) + 0.5) / 40.0, uCodeRow), 0.0).g;
    float clear = textureLod(uCode, vec2((float(2 * i) + 1.5) / 40.0, uCodeRow), 0.0).g;
    if (abs(set - clear) < 0.4) valid = false;
    if (set > clear) {
      if (i == 19) baked = true;
      else frameNumber += exp2(float(i));
    }
  }
  if (valid) {
    vStripTop = uStripTop;
    ivec2 size = baked ? textureSize(uBakedTrack, 0) : textureSize(uTrack, 0);
    int k = min(int(frameNumber), size.x * size.y - 1);
    ivec2 at = ivec2(k % size.x, k / size.x);
    steadyTurn = baked ? texelFetch(uBakedTrack, at, 0) : texelFetch(uTrack, at, 0);
  }
}
transformed = turnBy(steadyTurn, transformed);
`;

export class SphereView {
  private disposers: (() => void)[] = [];
  private destroyed = false;
  private swapTexture: ((src: string) => Promise<void>) | null = null;
  private swapVideo: ((video: HTMLVideoElement) => void) | null = null;
  /** While a video plays, every animation frame draws; otherwise only changes do. */
  private video: HTMLVideoElement | null = null;
  private invalidate: (() => void) | null = null;

  /** Whether steadying is on and locked; the track itself is in `tracks`. */
  private steady = true;
  private locked = false;
  /**
   * The turn for each frame, as quaternions in this sphere's frame, one texel
   * a frame: for a copy as rendered, following or locked; for a baked one,
   * which is steady already, the lock's turn about the vertical, or the
   * inverse that undoes the steadying.
   */
  private tracks: { follow: DataTexture; locked: DataTexture; yaw: DataTexture; undo: DataTexture } | null = null;
  private static readonly unturned = SphereView.trackTexture(new Float32Array([0, 0, 0, 1]), 1);
  private readonly steadying = {
    uCode: { value: null as Texture | null },
    uCoded: { value: false },
    uCodeRow: { value: 0 },
    uStripTop: { value: 0 },
    uTrack: { value: SphereView.unturned },
    uBakedTrack: { value: SphereView.unturned },
  };

  /** Current view direction and vertical field of view, degrees. */
  private longitude = 0;
  private latitude = 0;
  private fov = 75;

  private constructor(public readonly element: HTMLElement, private canvas: HTMLCanvasElement) {}

  public static async create(container: HTMLElement, src: string): Promise<SphereView> {
    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'display:block;width:100%;height:100%;touch-action:none;cursor:grab';
    container.appendChild(canvas);

    const view = new SphereView(container, canvas);
    await view.mount(src);

    return view;
  }

  private async mount(src: string) {
    const texture = await new TextureLoader().loadAsync(src);
    if (this.destroyed) {
      texture.dispose();
      return;
    }
    texture.colorSpace = SRGBColorSpace;

    const renderer = new WebGLRenderer({ canvas: this.canvas, antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);

    const scene = new Scene();
    const camera = new PerspectiveCamera(this.fov, 1, 0.1, 1000);

    // Don't render back faces from inside instead: that shows the texture
    // mirrored, which is only obvious on text. Scaling x by -1 turns the sphere
    // inside out, and the -90° phi start puts the middle column of the image at
    // longitude 0, which the inversion would otherwise move.
    const geometry = new SphereGeometry(100, 64, 48, -Math.PI / 2);
    geometry.scale(-1, 1, 1);
    const material = new MeshBasicMaterial({ map: texture });
    const steadying = this.steadying;
    material.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, steadying);
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `#include <common>\n${CODE_VERTEX_HEAD}`)
        .replace('#include <begin_vertex>', `#include <begin_vertex>\n${CODE_VERTEX_BODY}`);
      // The code is never shown: the strip's rows sample the row above instead,
      // which smears a cap 2 degrees across under the camera.
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\nvarying float vStripTop;')
        .replace('#include <map_fragment>', ShaderChunk.map_fragment.replace(
          'texture2D( map, vMapUv )', 'texture2D( map, vec2( vMapUv.x, max( vMapUv.y, vStripTop ) ) )'));
    };
    const mesh = new Mesh(geometry, material);
    scene.add(mesh);

    let needsRender = true;

    // Progressive detail: the sphere opens on the screen-sized preview, which
    // is thin spread over 360 degrees, and a sharper texture replaces it once
    // the server has rendered one. That can take many seconds the first time.
    this.swapTexture = async (next: string) => {
      const loaded = await new TextureLoader().loadAsync(next);
      if (this.destroyed) {
        loaded.dispose();
        return;
      }
      loaded.colorSpace = SRGBColorSpace;
      const previous = material.map;
      material.map = loaded;
      material.needsUpdate = true;
      previous?.dispose();
      needsRender = true;
    };

    // A stitched video replaces the still once it can play. Same sphere, same
    // view; the texture just updates itself each frame.
    this.swapVideo = (video: HTMLVideoElement) => {
      const texture = new VideoTexture(video);
      texture.colorSpace = SRGBColorSpace;
      const previous = material.map;
      material.map = texture;
      material.needsUpdate = true;
      previous?.dispose();
      this.video = video;
      // The strip is the bottom 16 rows; three flips video textures, so v runs up from them.
      const height = video.videoHeight || video.videoWidth / 2 || 1440;
      this.steadying.uCode.value = texture;
      this.steadying.uCoded.value = true;
      this.steadying.uCodeRow.value = 8 / height;
      this.steadying.uStripTop.value = 16.5 / height;
      needsRender = true;
      // Draw whenever a new frame arrives, so a seek while paused shows up.
      if ('requestVideoFrameCallback' in video) {
        const onFrame = () => {
          if (this.destroyed || this.video !== video) return;
          needsRender = true;
          video.requestVideoFrameCallback(onFrame);
        };
        video.requestVideoFrameCallback(onFrame);
      }
    };

    const resize = () => {
      const width = this.element.clientWidth || 1;
      const height = this.element.clientHeight || 1;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      needsRender = true;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(this.element);
    resize();

    let frame = 0;
    const tick = () => {
      if (this.destroyed) return;
      frame = requestAnimationFrame(tick);
      const playing = this.video !== null && !this.video.paused && !this.video.ended;
      if (!needsRender && !playing) return;
      needsRender = false;

      camera.fov = this.fov;
      camera.updateProjectionMatrix();

      // The shader turns the sphere, by the frame code (CODE_VERTEX_BODY).
      const tracks = this.tracks;
      const unturned = SphereView.unturned;
      if (tracks && this.steady) {
        this.steadying.uTrack.value = this.locked ? tracks.locked : tracks.follow;
        this.steadying.uBakedTrack.value = this.locked ? tracks.yaw : unturned;
      } else {
        this.steadying.uTrack.value = unturned;
        this.steadying.uBakedTrack.value = tracks ? tracks.undo : unturned;
      }

      // Same convention as the geometry: x negated, longitude from the middle
      // column of the image.
      const phi = MathUtils.degToRad(90 - this.latitude);
      const theta = MathUtils.degToRad(this.longitude);
      camera.lookAt(
        -100 * Math.sin(phi) * Math.sin(theta),
        100 * Math.cos(phi),
        100 * Math.sin(phi) * Math.cos(theta),
      );
      renderer.render(scene, camera);
    };
    tick();

    this.invalidate = () => {
      needsRender = true;
    };
    this.attachControls(this.invalidate);

    this.disposers.push(() => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      geometry.dispose();
      material.map?.dispose();
      material.dispose();
      this.disposeTracks();
      renderer.dispose();
    });
  }

  private clampView() {
    this.fov = Math.max(30, Math.min(100, this.fov));
    this.latitude = Math.max(-85, Math.min(85, this.latitude));
  }

  /**
   * Drag to look around, wheel or pinch to zoom.
   *
   * Events stop here: the viewer underneath (Nextcloud's Viewer, or Memories'
   * PhotoSwipe) listens for the same gestures and would page or pan as well.
   */
  private attachControls(invalidate: () => void) {
    const el = this.canvas;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let pinch = 0;

    /**
     * Degrees per pixel of drag at the centre of the view, so whatever is
     * under the pointer stays under it; a constant can't do that at every
     * viewer size. three's fov is the vertical one, so the focal length in
     * pixels depends on the height alone.
     */
    const degreesPerPixel = () => {
      const focal = (el.clientHeight || 1) / 2 / Math.tan((this.fov * Math.PI) / 360);
      return 180 / Math.PI / focal;
    };

    const down = (x: number, y: number) => {
      dragging = true;
      lastX = x;
      lastY = y;
      el.style.cursor = 'grabbing';
    };
    const move = (x: number, y: number) => {
      if (!dragging) return;
      const scale = degreesPerPixel();
      this.longitude -= (x - lastX) * scale;
      this.latitude += (y - lastY) * scale;
      this.clampView();
      lastX = x;
      lastY = y;
      invalidate();
    };
    const up = (e?: Event) => {
      dragging = false;
      el.style.cursor = 'grab';
      if (e && 'pointerId' in e) {
        const id = (e as PointerEvent).pointerId;
        if (el.hasPointerCapture?.(id)) el.releasePointerCapture(id);
      }
    };
    const zoom = (delta: number) => {
      this.fov += delta;
      this.clampView();
      invalidate();
    };

    const onPointerDown = (e: PointerEvent) => {
      e.stopPropagation();
      // Capture, so a drag that runs past the edge keeps turning.
      try {
        el.setPointerCapture(e.pointerId);
      } catch {
        // Some pointer types cannot be captured; the drag still works.
      }
      down(e.clientX, e.clientY);
    };
    const onPointerMove = (e: PointerEvent) => {
      if (dragging) e.stopPropagation();
      move(e.clientX, e.clientY);
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      zoom(Math.sign(e.deltaY) * 3);
    };
    const onTouchStart = (e: TouchEvent) => {
      e.stopPropagation();
      if (e.touches.length === 1) {
        down(e.touches[0].clientX, e.touches[0].clientY);
      } else if (e.touches.length === 2) {
        dragging = false;
        pinch = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY,
        );
      }
    };
    const onTouchMove = (e: TouchEvent) => {
      e.stopPropagation();
      if (e.touches.length === 1) {
        move(e.touches[0].clientX, e.touches[0].clientY);
      } else if (e.touches.length === 2 && pinch > 0) {
        const distance = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY,
        );
        zoom((pinch - distance) * 0.1);
        pinch = distance;
      }
    };

    el.addEventListener('pointerdown', onPointerDown);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: true });
    el.addEventListener('touchend', up);

    this.disposers.push(() => {
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', up);
    });
  }

  /**
   * Swap in a sharper texture. A failure leaves the sphere on the one it
   * already has rather than blanking it.
   */
  public async upgrade(src: string): Promise<boolean> {
    try {
      await this.swapTexture?.(src);
      return true;
    } catch {
      return false;
    }
  }

  /** Show a video on the sphere instead of the still it opened with. */
  public attachVideo(video: HTMLVideoElement) {
    this.swapVideo?.(video);
  }

  /** Steady the video with this track; null to stop. */
  public setMotion(motion: Motion | null) {
    this.disposeTracks();
    if (motion !== null) {
      const follow = new Float32Array(4 * motion.frames);
      const locked = new Float32Array(4 * motion.frames);
      const yaw = new Float32Array(4 * motion.frames);
      const undo = new Float32Array(4 * motion.frames);
      const q = motion.q;
      for (let k = 0; k < motion.frames; k++) {
        const [w, x, y, z] = [q[4 * k] / 32767, q[4 * k + 1] / 32767, q[4 * k + 2] / 32767, q[4 * k + 3] / 32767];
        // Turn back about the vertical by how far the heading has turned:
        // (cos h, 0, sin h, 0) times q, with h half the turn. A baked copy
        // already shows q, so it takes that turn alone.
        const half = (motion.turn[k] / 32767) * Math.PI / 2;
        const c = Math.cos(half);
        const s = Math.sin(half);
        SphereView.toSphere(follow, k, w, x, y, z);
        SphereView.toSphere(locked, k, c * w - s * y, c * x + s * z, c * y + s * w, c * z - s * x);
        SphereView.toSphere(yaw, k, c, 0, s, 0);
        SphereView.toSphere(undo, k, w, -x, -y, -z);
      }
      this.tracks = {
        follow: SphereView.trackTexture(follow, motion.frames),
        locked: SphereView.trackTexture(locked, motion.frames),
        yaw: SphereView.trackTexture(yaw, motion.frames),
        undo: SphereView.trackTexture(undo, motion.frames),
      };
    }
    this.invalidate?.();
  }

  /**
   * The track is in golblick's frame, whose x is this sphere's -x (see the
   * geometry): conjugating by that reflection keeps w and x and negates y
   * and z. Stored x, y, z, w, as three and the shader take a quaternion.
   */
  private static toSphere(out: Float32Array, k: number, w: number, x: number, y: number, z: number) {
    const n = Math.hypot(w, x, y, z) || 1;
    out.set([x / n, -y / n, -z / n, w / n], 4 * k);
  }

  private static trackTexture(data: Float32Array, frames: number): DataTexture {
    const width = Math.min(frames, TRACK_WIDTH);
    const rows = Math.ceil(frames / width);
    // Past the last frame, no turn: the shader clamps to the texture, not the track.
    const padded = new Float32Array(4 * width * rows);
    for (let i = 3; i < padded.length; i += 4) padded[i] = 1;
    padded.set(data);
    const texture = new DataTexture(padded, width, rows, RGBAFormat, FloatType);
    texture.minFilter = texture.magFilter = NearestFilter;
    texture.needsUpdate = true;
    return texture;
  }

  private disposeTracks() {
    for (const texture of Object.values(this.tracks ?? {})) texture.dispose();
    this.tracks = null;
  }

  public setSteady(on: boolean) {
    this.steady = on;
    this.invalidate?.();
  }

  /** Keep the direction the video opens in, instead of following the camera's turns. */
  public setLocked(on: boolean) {
    this.locked = on;
    this.invalidate?.();
  }

  /**
   * Where the view looks, in the panorama's own terms, degrees: longitude from
   * the middle column, rising to the right, latitude up from the horizon, and
   * the vertical field of view. What the server keeps as an opening view.
   */
  public get direction(): { longitude: number; latitude: number; fov: number } {
    const longitude = ((this.longitude + 180) % 360 + 360) % 360 - 180;
    return { longitude, latitude: this.latitude, fov: this.fov };
  }

  /** Look that way; a missing field of view keeps the current one. */
  public look(longitude: number, latitude: number, fov?: number | null) {
    this.longitude = longitude;
    this.latitude = latitude;
    if (fov) this.fov = fov;
    this.clampView();
    this.invalidate?.();
  }

  /** Draw once more, e.g. when a paused video has shown a new frame after a seek. */
  public redraw() {
    this.invalidate?.();
  }

  public destroy() {
    this.destroyed = true;
    for (const dispose of this.disposers) dispose();
    this.disposers = [];
    this.canvas.remove();
  }
}
