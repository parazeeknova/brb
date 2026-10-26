import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import { PixelJobCard } from "@/components/hero-job-card";
import { JOBS } from "@/lib/jobs-data";
import type { Job } from "@/lib/jobs-data";

let host: HTMLDivElement;
let root: Root;
let mounted: boolean;
let now: number;
let nextFrameId: number;
let frames: Map<number, FrameRequestCallback>;
let reducedMotion: boolean;
let observers: MockResizeObserver[];
let measure: ReturnType<typeof vi.spyOn>;
let cancelFrame: ReturnType<typeof vi.fn>;
let removeMotionListener: Mock<MediaQueryList["removeEventListener"]>;

class MockResizeObserver implements ResizeObserver {
  readonly callback: ResizeObserverCallback;
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    observers.push(this);
  }

  resize(target: Element, width: number, height: number) {
    const box = { blockSize: height, inlineSize: width };
    this.callback(
      [
        {
          borderBoxSize: [box],
          contentBoxSize: [box],
          contentRect: new DOMRect(0, 0, width, height),
          devicePixelContentBoxSize: [box],
          target,
        },
      ],
      this
    );
  }
}

function makeJob(company: string): Job {
  const [base] = JOBS;
  if (!base) {
    throw new Error("The hero card tests need a sample job");
  }
  return {
    ...base,
    company,
    tags: [company],
    title: `${company} developer`,
    url: `https://example.test/${company.toLowerCase()}`,
  };
}

function wipe() {
  const element = host.querySelector<HTMLDivElement>(".pixel-job-wipe");
  if (!element) {
    throw new Error("Expected a rendered pixel job card");
  }
  return element;
}

function layers() {
  return [...host.querySelectorAll<HTMLDivElement>(".pixel-job-layer")];
}

function maskPaths() {
  return [...host.querySelectorAll<SVGPathElement>("clipPath path")];
}

async function renderJob(job: Job, strict = false) {
  await act(async () => {
    const card = <PixelJobCard duration={600} job={job} />;
    root.render(strict ? <StrictMode>{card}</StrictMode> : card);
  });
}

async function advanceFrame(timestamp: number) {
  now = timestamp;
  const scheduledFrames = [...frames.values()];
  frames.clear();
  await act(async () => {
    for (const renderFrame of scheduledFrames) {
      renderFrame(timestamp);
    }
  });
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mounted = true;
  now = 0;
  nextFrameId = 1;
  frames = new Map();
  reducedMotion = false;
  observers = [];
  removeMotionListener = vi.fn<MediaQueryList["removeEventListener"]>();
  cancelFrame = vi.fn((id: number) => frames.delete(id));

  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("ResizeObserver", MockResizeObserver);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const id = nextFrameId;
    nextFrameId += 1;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", cancelFrame);
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  measure = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(() => new DOMRect(0, 0, 400, 360));
  vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
    addEventListener: vi.fn(),
    addListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
    get matches() {
      return reducedMotion;
    },
    media: query,
    onchange: null,
    removeEventListener: removeMotionListener,
    removeListener: vi.fn(),
  }));
});

afterEach(async () => {
  if (mounted) {
    await act(async () => root.unmount());
  }
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("PixelJobCard", () => {
  it("transitions when fields or tags change without changing the job ID", async () => {
    const oldJob = makeJob("Alpha");
    const newJob = makeJob("Beta");
    expect(oldJob.id).toBe(newJob.id);

    await renderJob(oldJob);
    expect(wipe()).toHaveAttribute("data-transitioning", "false");
    await renderJob(newJob);

    expect(wipe()).toHaveAttribute("data-transitioning", "true");
    expect(layers()[0]).toHaveTextContent("Alpha developer");
    expect(layers()[1]).toHaveTextContent("Beta developer");
    await advanceFrame(600);

    await renderJob({ ...newJob, tags: ["Remote", "Backend"] });
    expect(wipe()).toHaveAttribute("data-transitioning", "true");
    expect(layers()).toHaveLength(2);
    await advanceFrame(1200);
    expect(layers()).toHaveLength(1);
  });

  it("updates complementary pixel masks on animation frames and restores one interactive card", async () => {
    await renderJob(makeJob("Alpha"));
    expect(layers()[0]).not.toHaveAttribute("inert");
    await renderJob(makeJob("Beta"));

    const [oldLayer, newLayer] = layers();
    const [oldPath, newPath] = maskPaths();
    if (!oldLayer || !newLayer || !oldPath || !newPath) {
      throw new Error("Expected old and new masked card layers");
    }
    expect(wipe()).toHaveAttribute("data-mode", "blocks");
    expect(oldLayer).toHaveAttribute("aria-hidden", "true");
    expect(oldLayer).toHaveAttribute("inert");
    expect(newLayer).toHaveAttribute("inert");
    expect(oldLayer.style.clipPath).toContain(oldPath.parentElement?.id);
    expect(newLayer.style.clipPath).toContain(newPath.parentElement?.id);
    expect(oldPath.getAttribute("d")).not.toBe("");
    expect(newPath.getAttribute("d")).toBe("");
    expect(oldLayer.style.opacity).toBe("1");
    expect(newLayer.style.opacity).toBe("1");

    const initialPath = oldPath.getAttribute("d");
    await advanceFrame(50);
    expect(oldPath.getAttribute("d")).not.toBe(initialPath);
    await advanceFrame(300);
    expect(oldPath.getAttribute("d")).not.toBe("");
    expect(newPath.getAttribute("d")).not.toBe("");

    await advanceFrame(600);
    expect(wipe()).toHaveAttribute("data-transitioning", "false");
    expect(layers()).toHaveLength(1);
    expect(layers()[0]).not.toHaveAttribute("inert");
    expect(layers()[0]).not.toHaveAttribute("aria-hidden");
    expect(host.querySelectorAll("article")).toHaveLength(1);
    expect(host.querySelector("a")).toHaveAttribute(
      "href",
      "https://example.test/beta"
    );
    expect(frames.size).toBe(0);
  });

  it("cancels an interrupted swap and prevents stale frames from replacing the latest job", async () => {
    await renderJob(makeJob("Alpha"));
    await renderJob(makeJob("Beta"));
    const [staleFrame] = [...frames.values()];
    if (!staleFrame) {
      throw new Error("Expected a scheduled transition frame");
    }
    await advanceFrame(200);
    const [interruptedFrameId] = [...frames.keys()];
    await renderJob(makeJob("Gamma"));

    expect(cancelFrame).toHaveBeenCalledWith(interruptedFrameId);
    expect(frames.size).toBe(1);
    expect(layers()[0]).toHaveTextContent("Beta developer");
    expect(layers()[1]).toHaveTextContent("Gamma developer");
    await advanceFrame(800);
    await act(async () => staleFrame(1000));

    expect(layers()).toHaveLength(1);
    expect(layers()[0]).toHaveTextContent("Gamma developer");
    expect(host).not.toHaveTextContent("Beta developer");
    expect(host.querySelector("a")).toHaveAttribute(
      "href",
      "https://example.test/gamma"
    );
    expect(frames.size).toBe(0);
  });

  it("rebuilds the grid on resize without measuring layout inside animation frames", async () => {
    await renderJob(makeJob("Alpha"));
    await renderJob(makeJob("Beta"));
    expect(measure).toHaveBeenCalledTimes(1);
    measure.mockClear();
    await advanceFrame(200);
    const observer = observers.at(-1);
    if (!observer) {
      throw new Error("Expected a transition ResizeObserver");
    }

    await act(async () => observer.resize(wipe(), 317, 293));
    let rightEdge = 0;
    let bottomEdge = 0;
    for (const path of maskPaths()) {
      for (const rectangle of (path.getAttribute("d") ?? "").matchAll(
        /M(\d+) (\d+)h(\d+)v(\d+)h-\d+z/g
      )) {
        rightEdge = Math.max(
          rightEdge,
          Number(rectangle[1]) + Number(rectangle[3])
        );
        bottomEdge = Math.max(
          bottomEdge,
          Number(rectangle[2]) + Number(rectangle[4])
        );
      }
    }
    expect({ bottomEdge, rightEdge }).toEqual({
      bottomEdge: 293,
      rightEdge: 317,
    });
    await advanceFrame(300);
    await advanceFrame(600);

    expect(measure).not.toHaveBeenCalled();
    expect(observer.disconnect).toHaveBeenCalled();
    expect(layers()).toHaveLength(1);
    expect(layers()[0]).not.toHaveAttribute("inert");
  });

  it("uses a plain crossfade when reduced motion is preferred", async () => {
    reducedMotion = true;
    await renderJob(makeJob("Alpha"));
    await renderJob(makeJob("Beta"));
    const [oldLayer, newLayer] = layers();
    if (!oldLayer || !newLayer) {
      throw new Error("Expected crossfade layers");
    }

    expect(wipe()).toHaveAttribute("data-mode", "crossfade");
    expect(oldLayer.style.clipPath).toBe("none");
    expect(newLayer.style.clipPath).toBe("none");
    expect(oldLayer.style.opacity).toBe("1");
    expect(newLayer.style.opacity).toBe("0");
    expect(maskPaths().every((path) => !path.getAttribute("d"))).toBe(true);
    await advanceFrame(100);
    expect(oldLayer.style.opacity).toBe("0.5");
    expect(newLayer.style.opacity).toBe("0.5");
    await advanceFrame(200);

    expect(wipe()).toHaveAttribute("data-transitioning", "false");
    expect(layers()).toHaveLength(1);
    expect(layers()[0]).not.toHaveAttribute("inert");
    expect(frames.size).toBe(0);
  });

  it("cleans up pending frames and observers on unmount under StrictMode", async () => {
    await renderJob(makeJob("Alpha"), true);
    await renderJob(makeJob("Beta"), true);
    const [pendingId, staleFrame] = [...frames.entries()][0] ?? [];
    const observer = observers.at(-1);
    if (pendingId === undefined || !staleFrame || !observer) {
      throw new Error("Expected an active transition to clean up");
    }
    await act(async () => root.unmount());
    mounted = false;
    expect(cancelFrame).toHaveBeenCalledWith(pendingId);
    expect(observer.disconnect).toHaveBeenCalled();
    expect(removeMotionListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function)
    );
    expect(frames.size).toBe(0);
    await act(async () => staleFrame(600));
    expect(host).toBeEmptyDOMElement();
    expect(frames.size).toBe(0);
  });
});
