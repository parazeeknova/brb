import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { HERO_JOBS as JOBS } from "@/lib/hero-jobs";
import type { Job } from "@/lib/jobs-data";
import {
  createBlockWipeGrid,
  easePixelWipe,
  getBlockWipePaths,
  paintPixelRelief,
  smoothPixelStep,
} from "@/lib/pixel-wipe";

import { JobCard } from "./jobs-tab";

const HOLD_MS = 5000;
const WIPE_MS = 1800;

interface WipeOptions {
  /** Square tile size in CSS pixels, clamped to 8–32. */
  blockSize?: number;
  /** Full swap duration in milliseconds. */
  duration?: number;
}

function snapshot(job: Job): Job {
  return { ...job, tags: [...job.tags] };
}

export function PixelJobCard({
  blockSize = 8,
  duration = WIPE_MS,
  job,
}: WipeOptions & { job: Job }) {
  const id = useId().replaceAll(":", "");
  const oldClipId = `${id}-old`;
  const newClipId = `${id}-new`;
  const containerRef = useRef<HTMLDivElement>(null);
  const oldLayerRef = useRef<HTMLDivElement>(null);
  const newLayerRef = useRef<HTMLDivElement>(null);
  const oldPathRef = useRef<SVGPathElement>(null);
  const newPathRef = useRef<SVGPathElement>(null);
  const reliefOldLayerRef = useRef<HTMLDivElement>(null);
  const reliefNewLayerRef = useRef<HTMLDivElement>(null);
  const reliefOldPathRef = useRef<SVGPathElement>(null);
  const reliefNewPathRef = useRef<SVGPathElement>(null);
  const reliefCanvasRef = useRef<HTMLCanvasElement>(null);
  const reliefSurfaceRef = useRef<HTMLDivElement>(null);
  const incomingRef = useRef(snapshot(job));
  const signature = JSON.stringify(job);
  const signatureRef = useRef(signature);
  const generationRef = useRef(0);
  const seedRef = useRef(0);
  const [previousJob, setPreviousJob] = useState<Job | null>(null);

  // Keep a snapshot so even edits to an existing job ID trigger a real old/new swap.
  useLayoutEffect(() => {
    if (signatureRef.current === signature) {
      return;
    }
    const previous = incomingRef.current;
    incomingRef.current = snapshot(job);
    signatureRef.current = signature;
    setPreviousJob(previous);
  }, [job, signature]);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const oldLayer = oldLayerRef.current;
    const newLayer = newLayerRef.current;
    const oldPath = oldPathRef.current;
    const newPath = newPathRef.current;
    if (
      !previousJob ||
      !container ||
      !oldLayer ||
      !newLayer ||
      !oldPath ||
      !newPath
    ) {
      return;
    }

    const generation = ++generationRef.current;
    const seed = Math.imul(++seedRef.current, 2_654_435_761) >>> 0;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const fullDuration = Number.isFinite(duration)
      ? Math.max(0, duration)
      : WIPE_MS;
    const bounds = container.getBoundingClientRect();
    let grid = createBlockWipeGrid(
      bounds.width,
      bounds.height,
      blockSize,
      seed
    );
    let frameId = 0;
    let lastProgress = 0;
    let finished = false;
    let lastTransform = "";
    const pathNodes = [
      oldPath,
      newPath,
      reliefOldPathRef.current,
      reliefNewPathRef.current,
    ];
    const lastPaths: string[] = [];
    const reliefLayers = [
      reliefOldLayerRef.current,
      reliefNewLayerRef.current,
      reliefSurfaceRef.current,
    ];
    const canvas = reliefCanvasRef.current;
    const lighting = canvas?.getContext("2d") ?? null;
    const startedAt = performance.now();

    const sizeLighting = () => {
      if (canvas && lighting) {
        canvas.width = grid.columns;
        canvas.height = grid.rows;
        canvas.style.width = `${grid.columns * grid.blockSize}px`;
        canvas.style.height = `${grid.rows * grid.blockSize}px`;
        lighting.imageSmoothingEnabled = false;
      }
    };

    const configureMode = () => {
      container.dataset["mode"] = motion.matches ? "crossfade" : "blocks";
      oldLayer.style.clipPath = motion.matches
        ? "none"
        : `url("#${oldClipId}")`;
      newLayer.style.clipPath = motion.matches
        ? "none"
        : `url("#${newClipId}")`;
      oldLayer.style.opacity = "1";
      newLayer.style.opacity = motion.matches ? "0" : "1";
      const oldRelief = reliefOldLayerRef.current;
      const newRelief = reliefNewLayerRef.current;
      if (oldRelief && newRelief) {
        oldRelief.style.clipPath = `url("#${id}-relief-old")`;
        newRelief.style.clipPath = `url("#${id}-relief-new")`;
      }
      sizeLighting();
    };

    const paint = (progress: number) => {
      lastProgress = progress;
      if (motion.matches) {
        oldLayer.style.opacity = String(1 - progress);
        newLayer.style.opacity = String(progress);
      } else {
        const frame = getBlockWipePaths(grid, easePixelWipe(progress));
        const paths = [
          frame.oldPath,
          frame.newPath,
          frame.relief.oldPath,
          frame.relief.newPath,
        ];
        // Skip unchanged masks, and keep React and layout reads out of the loop.
        for (let index = 0; index < paths.length; index += 1) {
          const path = paths[index];
          if (path !== undefined && path !== lastPaths[index]) {
            pathNodes[index]?.setAttribute("d", path);
            lastPaths[index] = path;
          }
        }
        const crest = Math.max(...frame.fronts);
        const tail = Math.min(...frame.fronts);
        container.style.perspectiveOrigin = `${frame.center.toFixed(3)}px ${crest.toFixed(3)}px`;
        // Rise as the ridge enters the card and release after its trailing edge.
        const entry = smoothPixelStep(
          (crest + frame.radius) / (frame.radius * 2)
        );
        const exit = smoothPixelStep(
          (grid.height - tail + frame.radius) / (frame.radius * 2)
        );
        const envelope = entry * exit;
        const lift = 20 * envelope;
        const transform = `translate3d(0, ${(-envelope).toFixed(3)}px, ${lift.toFixed(3)}px)`;
        if (lastTransform !== transform) {
          for (const layer of reliefLayers) {
            if (layer) {
              layer.style.transform = transform;
            }
          }
          lastTransform = transform;
        }
        if (lighting) {
          paintPixelRelief(
            lighting,
            grid,
            frame,
            progress === 1 ? 0 : envelope
          );
        }
      }
    };

    const finish = () => {
      if (finished || generation !== generationRef.current) {
        return;
      }
      finished = true;
      newLayer.style.clipPath = "none";
      newLayer.style.opacity = "1";
      oldLayer.style.opacity = "0";
      setPreviousJob(null);
    };

    const tick = (now: number) => {
      if (finished || generation !== generationRef.current) {
        return;
      }
      const elapsed = Math.max(0, now - startedAt);
      const ms = motion.matches ? Math.min(fullDuration, 200) : fullDuration;
      if (elapsed >= ms) {
        paint(1);
        finish();
        return;
      }
      paint(elapsed / ms);
      frameId = window.requestAnimationFrame(tick);
    };

    const resizeObserver = new ResizeObserver(([entry]) => {
      if (!entry || finished || generation !== generationRef.current) {
        return;
      }
      const { width, height } = entry.contentRect;
      if (
        width <= 0 ||
        height <= 0 ||
        (Math.ceil(width) === grid.width && Math.ceil(height) === grid.height)
      ) {
        return;
      }
      // The seed and progress survive resize; no layout reads happen in RAF.
      grid = createBlockWipeGrid(width, height, blockSize, seed);
      sizeLighting();
      paint(lastProgress);
    });

    const handleMotionChange = () => {
      if (finished || generation !== generationRef.current) {
        return;
      }
      window.cancelAnimationFrame(frameId);
      configureMode();
      tick(performance.now());
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        window.cancelAnimationFrame(frameId);
        finish();
      }
    };

    const visibilityObserver =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver(([entry]) => {
            if (entry && !entry.isIntersecting) {
              window.cancelAnimationFrame(frameId);
              finish();
            }
          });

    configureMode();
    paint(0);
    resizeObserver.observe(container);
    visibilityObserver?.observe(container);
    motion.addEventListener("change", handleMotionChange);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    if (
      fullDuration === 0 ||
      document.hidden ||
      bounds.width <= 0 ||
      bounds.height <= 0
    ) {
      finish();
    } else {
      frameId = window.requestAnimationFrame(tick);
    }

    return () => {
      generationRef.current += 1;
      window.cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      visibilityObserver?.disconnect();
      motion.removeEventListener("change", handleMotionChange);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      delete container.dataset["mode"];
      container.style.perspectiveOrigin = "";
      newLayer.style.clipPath = "none";
      newLayer.style.opacity = "1";
    };
  }, [blockSize, duration, id, newClipId, oldClipId, previousJob, signature]);

  return (
    <div
      aria-label="Featured job"
      className="pixel-job-wipe card-lift"
      data-transitioning={previousJob !== null}
      ref={containerRef}
      role="group"
    >
      {previousJob && (
        <div
          aria-hidden="true"
          className="pixel-job-layer"
          inert
          ref={oldLayerRef}
        >
          <JobCard job={previousJob} i={0} />
        </div>
      )}
      <div
        className="pixel-job-layer"
        inert={previousJob !== null}
        ref={newLayerRef}
      >
        <JobCard job={job} i={0} />
      </div>
      {previousJob && (
        <>
          <div
            aria-hidden="true"
            className="pixel-job-relief-layer"
            inert
            ref={reliefOldLayerRef}
          >
            <JobCard job={previousJob} i={0} />
          </div>
          <div
            aria-hidden="true"
            className="pixel-job-relief-layer"
            inert
            ref={reliefNewLayerRef}
          >
            <JobCard job={job} i={0} />
          </div>
          <div
            aria-hidden="true"
            className="pixel-job-relief-shading"
            ref={reliefSurfaceRef}
          >
            <canvas ref={reliefCanvasRef} />
          </div>
        </>
      )}
      <svg
        aria-hidden="true"
        className="pixel-job-clips"
        focusable="false"
        height={0}
        width={0}
      >
        <defs>
          <clipPath clipPathUnits="userSpaceOnUse" id={oldClipId}>
            <path ref={oldPathRef} shapeRendering="crispEdges" />
          </clipPath>
          <clipPath clipPathUnits="userSpaceOnUse" id={newClipId}>
            <path ref={newPathRef} shapeRendering="crispEdges" />
          </clipPath>
          <clipPath clipPathUnits="userSpaceOnUse" id={`${id}-relief-old`}>
            <path ref={reliefOldPathRef} shapeRendering="crispEdges" />
          </clipPath>
          <clipPath clipPathUnits="userSpaceOnUse" id={`${id}-relief-new`}>
            <path ref={reliefNewPathRef} shapeRendering="crispEdges" />
          </clipPath>
        </defs>
      </svg>
    </div>
  );
}

export function HeroJobCard(options: WipeOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || JOBS.length < 2) {
      return;
    }
    let visible = true;
    const observer = new IntersectionObserver(([entry]) => {
      visible = Boolean(entry?.isIntersecting);
    });
    observer.observe(container);
    const timer = window.setInterval(() => {
      if (
        !document.hidden &&
        visible &&
        !container.contains(document.activeElement)
      ) {
        setIndex((current) => (current + 1) % JOBS.length);
      }
    }, HOLD_MS);

    return () => {
      window.clearInterval(timer);
      observer.disconnect();
    };
  }, []);

  const job = JOBS[index];
  return (
    <div ref={containerRef}>
      {job && <PixelJobCard {...options} job={job} />}
    </div>
  );
}
