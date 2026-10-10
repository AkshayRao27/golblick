/**
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * A drag-to-look sphere for one equirectangular image, rendered with three.js.
 *
 * Ported from the panorama viewer this project wrote for Nextcloud Memories
 * (PsPanorama.ts on the feat/panorama-viewer branch), where its geometry was
 * scored in a headless harness. Cut down to complete spheres: a .insp render
 * always covers the whole sphere, so the crop handling is gone.
 *
 * This module is imported dynamically, so three.js lands in its own chunk and
 * costs nothing on a page where nobody opens a sphere.
 */
import {
  MathUtils,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  SRGBColorSpace,
  Scene,
  SphereGeometry,
  TextureLoader,
  VideoTexture,
  WebGLRenderer,
} from 'three';

/**
 * The rotation that steadies each frame of a video (lib/Service/MotionStore):
 * one quaternion (w, x, y, z) per frame, scaled by 32767, `period` seconds apart.
 */
export type Motion = { period: number; frames: number; q: Int16Array };

export class SphereView {
  private disposers: (() => void)[] = [];
  private destroyed = false;
  private swapTexture: ((src: string) => Promise<void>) | null = null;
  private swapVideo: ((video: HTMLVideoElement) => void) | null = null;
  /** While a video plays, every animation frame draws; otherwise only changes do. */
  private video: HTMLVideoElement | null = null;
  private invalidate: (() => void) | null = null;

  /** Steadying for the video, if the server had a track, and whether it is on. */
  private motion: Motion | null = null;
  private steady = true;
  /** Media time of the frame on screen, from requestVideoFrameCallback where the browser has it. */
  private frameTime: number | null = null;

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

    // 🔴 MIRROR. Rendering a sphere's back faces from inside shows the texture
    // through the surface, flipped left to right: invisible on scenery and
    // obvious the moment a sign is in shot. Scaling x by -1 turns the sphere
    // inside out instead, and the -90° phi start puts the middle column of the
    // image at longitude 0, which the inversion would otherwise move.
    const geometry = new SphereGeometry(100, 64, 48, -Math.PI / 2);
    geometry.scale(-1, 1, 1);
    const material = new MeshBasicMaterial({ map: texture });
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
      needsRender = true;
      // Steadying has to turn the sphere for the frame actually on screen,
      // which the playback clock runs slightly ahead of.
      if ('requestVideoFrameCallback' in video) {
        const onFrame = (_now: number, frame: VideoFrameCallbackMetadata) => {
          if (this.destroyed || this.video !== video) return;
          this.frameTime = frame.mediaTime;
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

      // The track is in golblick's frame, whose x is this sphere's -x (see
      // the geometry): conjugating by that reflection keeps w and x and
      // negates y and z.
      const motion = this.motion;
      if (motion && this.steady && this.video) {
        const time = this.frameTime ?? this.video.currentTime;
        const k = Math.min(motion.frames - 1, Math.max(0, Math.round(time / motion.period)));
        const q = motion.q;
        mesh.quaternion.set(q[4 * k + 1], -q[4 * k + 2], -q[4 * k + 3], q[4 * k]).normalize();
      } else {
        mesh.quaternion.identity();
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
     * under the pointer stays under it. three's fov is the vertical one, so
     * the focal length in pixels depends on the height alone. A constant here
     * measured 0.34x the finger in a 400 px viewer and 0.77x at 900 px.
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
    this.motion = motion;
    this.invalidate?.();
  }

  public setSteady(on: boolean) {
    this.steady = on;
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
