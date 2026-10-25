import { describe, expect, it } from "vitest";

import { createBlockWipeGrid, getBlockWipeFrame } from "@/lib/pixel-wipe";

type BlockWipeGrid = ReturnType<typeof createBlockWipeGrid>;

function rasterizeMask(path: string, grid: BlockWipeGrid) {
  const rectangles = /M(\d+) (\d+)h(\d+)v(\d+)h-(\d+)z/g;
  const coverage = new Uint8Array(grid.width * grid.height);

  expect(path.replace(rectangles, "").trim()).toBe("");

  for (const match of path.matchAll(rectangles)) {
    const x = Number(match[1]);
    const y = Number(match[2]);
    const width = Number(match[3]);
    const height = Number(match[4]);

    expect(Number(match[5])).toBe(width);
    expect(width).toBeGreaterThan(0);
    expect(height).toBeGreaterThan(0);
    expect(x % grid.blockSize).toBe(0);
    expect(y % grid.blockSize).toBe(0);
    expect(x + width).toBeLessThanOrEqual(grid.width);
    expect(y + height).toBeLessThanOrEqual(grid.height);
    expect(height % grid.blockSize === 0 || y + height === grid.height).toBe(
      true
    );
    expect(width % grid.blockSize === 0 || x + width === grid.width).toBe(true);

    for (let pixelY = y; pixelY < y + height; pixelY += 1) {
      for (let pixelX = x; pixelX < x + width; pixelX += 1) {
        const index = pixelY * grid.width + pixelX;
        coverage[index] = (coverage[index] ?? 0) + 1;
      }
    }
  }

  return coverage;
}

describe("Block wipe geometry", () => {
  it("gives every pixel exactly one card, including partial edge blocks", () => {
    for (const blockSize of [16, 24, 32]) {
      const grid = createBlockWipeGrid(137, 109, blockSize, 481);

      for (const progress of [0, 0.17, 0.34, 0.5, 0.73, 0.91, 1]) {
        const frame = getBlockWipeFrame(grid, progress);
        const oldCoverage = rasterizeMask(frame.oldPath, grid);
        const newCoverage = rasterizeMask(frame.newPath, grid);
        let holes = 0;
        let overlaps = 0;
        let mismatches = 0;

        expect(frame.newCells).toHaveLength(grid.columns * grid.rows);

        for (let y = 0; y < grid.height; y += 1) {
          for (let x = 0; x < grid.width; x += 1) {
            const pixel = y * grid.width + x;
            const oldCount = oldCoverage[pixel] ?? 0;
            const newCount = newCoverage[pixel] ?? 0;
            const cell =
              Math.floor(y / grid.blockSize) * grid.columns +
              Math.floor(x / grid.blockSize);

            if (oldCount + newCount === 0) {
              holes += 1;
            }
            if (oldCount + newCount > 1) {
              overlaps += 1;
            }
            if (newCount !== Number(frame.newCells[cell])) {
              mismatches += 1;
            }
          }
        }

        expect({ holes, mismatches, overlaps }).toEqual({
          holes: 0,
          mismatches: 0,
          overlaps: 0,
        });
      }
    }
  });

  it("starts entirely old and finishes entirely new for different sizes and seeds", () => {
    const dimensions = [
      { height: 1, width: 1 },
      { height: 73, width: 49 },
      { height: 417, width: 448 },
    ];

    for (const { width, height } of dimensions) {
      for (const seed of [0, 1, 42, 7_654_321]) {
        const grid = createBlockWipeGrid(width, height, 24, seed);
        const first = getBlockWipeFrame(grid, 0);
        const last = getBlockWipeFrame(grid, 1);

        expect(first.newCells.every((cell) => !cell)).toBe(true);
        expect(first.newPath).toBe("");
        expect(last.newCells.every(Boolean)).toBe(true);
        expect(last.oldPath).toBe("");
        expect(
          rasterizeMask(first.oldPath, grid).every((count) => count === 1)
        ).toBe(true);
        expect(
          rasterizeMask(last.newPath, grid).every((count) => count === 1)
        ).toBe(true);
      }
    }
  });

  it("uses stable seeded jitter within zero to two block heights", () => {
    const first = createBlockWipeGrid(448, 417, 24, 481);
    const repeat = createBlockWipeGrid(448, 417, 24, 481);
    const different = createBlockWipeGrid(448, 417, 24, 482);

    expect(first).toEqual(repeat);
    expect(first.jitter).not.toEqual(different.jitter);
    expect(first.jitter).toHaveLength(first.columns * first.rows);
    expect(new Set(first.jitter).size).toBeGreaterThan(1);

    for (const jitter of first.jitter) {
      expect(jitter).toBeGreaterThanOrEqual(0);
      expect(jitter).toBeLessThanOrEqual(2 * first.blockSize);
    }

    const middle = getBlockWipeFrame(first, 0.5);
    expect(middle).toEqual(getBlockWipeFrame(repeat, 0.5));
    getBlockWipeFrame(first, 0.75);
    expect(getBlockWipeFrame(first, 0.5)).toEqual(middle);
  });

  it("bounds block sizes and covers fractional card dimensions with positive pixel bounds", () => {
    expect(createBlockWipeGrid(86.7, 98.2, 8, 1)).toMatchObject({
      blockSize: 8,
      columns: 11,
      height: 99,
      rows: 13,
      width: 87,
    });
    expect(createBlockWipeGrid(86.7, 98.2, 64, 1)).toMatchObject({
      blockSize: 32,
      columns: 3,
      height: 99,
      rows: 4,
      width: 87,
    });
    expect(createBlockWipeGrid(-12, 0, 24, 1)).toMatchObject({
      columns: 1,
      height: 1,
      rows: 1,
      width: 1,
    });

    const fractional = createBlockWipeGrid(100, 100, 23.7, 1);
    expect(Number.isInteger(fractional.blockSize)).toBe(true);
    expect(fractional.blockSize).toBeGreaterThanOrEqual(8);
    expect(fractional.blockSize).toBeLessThanOrEqual(32);
  });

  it("bows the front downward around a drifting interior center", () => {
    const grid = createBlockWipeGrid(768, 600, 24, 481);
    const middle = getBlockWipeFrame(grid, 0.5);
    const peak = Math.max(...middle.fronts);
    const peakColumn = middle.fronts.indexOf(peak);

    expect(middle.fronts).toHaveLength(grid.columns);
    expect(peakColumn).toBeGreaterThan(0);
    expect(peakColumn).toBeLessThan(grid.columns - 1);
    expect(peak).toBeGreaterThan(middle.fronts[0] ?? peak);
    expect(peak).toBeGreaterThan(middle.fronts.at(-1) ?? peak);

    for (let column = 1; column <= peakColumn; column += 1) {
      expect(middle.fronts[column]).toBeGreaterThanOrEqual(
        middle.fronts[column - 1] ?? 0
      );
    }
    for (let column = peakColumn + 1; column < grid.columns; column += 1) {
      expect(middle.fronts[column]).toBeLessThanOrEqual(
        middle.fronts[column - 1] ?? 0
      );
    }

    const early = getBlockWipeFrame(grid, 0.25).fronts;
    const late = getBlockWipeFrame(grid, 0.75).fronts;
    const earlyMinimum = Math.min(...early);
    const lateMinimum = Math.min(...late);
    let profileChanged = false;

    for (let column = 0; column < grid.columns; column += 1) {
      const earlyBulge = (early[column] ?? 0) - earlyMinimum;
      const lateBulge = (late[column] ?? 0) - lateMinimum;
      if (Math.abs(earlyBulge - lateBulge) > 0.01) {
        profileChanged = true;
      }
    }

    expect(profileChanged).toBe(true);
  });
});
