export interface BlockWipeGrid {
  blockSize: number;
  centerOffset: number;
  columns: number;
  height: number;
  jitter: number[];
  rows: number;
  width: number;
}

function noise(seed: number, column: number, row: number) {
  let value =
    seed ^ Math.imul(column + 1, 374_761_393) ^ Math.imul(row + 1, 668_265_263);
  value = Math.imul(value ^ (value >>> 13), 1_274_126_177);
  value ^= value >>> 16;
  return (value >>> 0) / 4_294_967_296;
}

export function smoothPixelStep(value: number) {
  const p = Math.min(1, Math.max(0, value));
  return p * p * (3 - 2 * p);
}

export function easePixelWipe(progress: number) {
  return progress * 0.4 + smoothPixelStep(progress) * 0.6;
}

export function createBlockWipeGrid(
  width: number,
  height: number,
  blockSize: number,
  seed: number
): BlockWipeGrid {
  const size = Math.min(
    32,
    Math.max(8, Math.round(Number.isFinite(blockSize) ? blockSize : 8))
  );
  const pixelWidth = Math.max(1, Math.ceil(Number.isFinite(width) ? width : 1));
  const pixelHeight = Math.max(
    1,
    Math.ceil(Number.isFinite(height) ? height : 1)
  );
  const columns = Math.ceil(pixelWidth / size);
  const rows = Math.ceil(pixelHeight / size);
  let randomState = seed >>> 0;
  const random = () => {
    randomState = (Math.imul(randomState, 1_664_525) + 1_013_904_223) >>> 0;
    return randomState / 4_294_967_296;
  };
  const centerOffset = (random() - 0.5) * 0.06;
  const jitter = Array.from({ length: rows * columns }, (_, index) => {
    // A shared contour keeps the seam connected; fine seeded texture adds steps.
    // Both remain stable when the card resizes.
    const column = index % columns;
    const row = Math.floor(index / columns);
    const group = Math.floor(column / 4);
    const blend = smoothPixelStep((column % 4) / 4);
    // eslint-disable-next-line unicorn/numeric-separators-style -- hex seed, not a decimal literal
    const left = noise(seed ^ 0x5f356495, group, 0);
    // eslint-disable-next-line unicorn/numeric-separators-style -- hex seed, not a decimal literal
    const right = noise(seed ^ 0x5f356495, group + 1, 0);
    const contour = left + (right - left) * blend;
    return size * (contour * 0.5 + noise(seed, column, row) * 0.18);
  });

  return {
    blockSize: size,
    centerOffset,
    columns,
    height: pixelHeight,
    jitter,
    rows,
    width: pixelWidth,
  };
}

function rectangle(x: number, y: number, width: number, height: number) {
  return height > 0 ? `M${x} ${y}h${width}v${height}h-${width}z` : "";
}

export function getBlockWipePaths(grid: BlockWipeGrid, progress: number) {
  const p = Math.min(1, Math.max(0, progress));
  const { blockSize, columns, height, rows, width } = grid;
  const bulgeHeight = Math.max(48, blockSize * 4);
  const radius = Math.max(20, blockSize * 1.5);
  const lead = bulgeHeight + blockSize * 3;
  // Carry the entire raised ridge out of view before releasing the final card.
  const base = -lead + p * (height + lead + radius + blockSize * 2);
  const center =
    width * (0.5 + grid.centerOffset + 0.07 * Math.sin(Math.PI * (p - 0.5)));
  const spread = Math.max(blockSize, width * 0.22);
  const fronts = Array.from({ length: columns }, (_, column) => {
    const distance = ((column + 0.5) * blockSize - center) / spread;
    return base + bulgeHeight * Math.exp(-0.5 * distance * distance);
  });
  const relief = { newPath: "", oldPath: "" };
  let newPath = "";
  let oldPath = "";

  if (p === 0 || p === 1) {
    const fullPath = rectangle(0, 0, width, height);
    return {
      center,
      fronts,
      newPath: p === 1 ? fullPath : "",
      oldPath: p === 0 ? fullPath : "",
      radius,
      relief,
    };
  }

  for (let column = 0; column < columns; column += 1) {
    const x = column * blockSize;
    const tileWidth = Math.min(blockSize, width - x);
    const front = fronts[column] ?? base;
    // Only rows immediately around the front need jitter checks. Settled areas are
    // single tall rectangles, so frame work scales with width, not card area.
    const settledRows =
      front >= height
        ? rows
        : Math.max(0, Math.min(rows, Math.floor(front / blockSize)));
    const edgeEnd = Math.max(
      settledRows,
      Math.min(rows, Math.ceil((front + blockSize * 2) / blockSize))
    );
    let startY = 0;
    let incoming = settledRows > 0;

    for (let row = settledRows; row < edgeEnd; row += 1) {
      const bottom = Math.min(height, (row + 1) * blockSize);
      const showsNew =
        bottom <= front + (grid.jitter[row * columns + column] ?? 0);
      if (showsNew !== incoming) {
        const y = row * blockSize;
        const run = rectangle(x, startY, tileWidth, y - startY);
        if (incoming) {
          newPath += run;
        } else {
          oldPath += run;
        }
        startY = y;
        incoming = showsNew;
      }
    }
    const endY = Math.min(height, edgeEnd * blockSize);
    const run = rectangle(x, startY, tileWidth, endY - startY);
    if (incoming) {
      newPath += run;
    } else {
      oldPath += run;
    }
    if (endY < height) {
      oldPath += rectangle(x, endY, tileWidth, height - endY);
    }

    const reliefStart = Math.max(0, Math.floor((front - radius) / blockSize));
    const reliefEnd = Math.min(
      rows,
      Math.ceil((front + blockSize * 2 + radius) / blockSize)
    );
    for (let row = reliefStart; row < reliefEnd; row += 1) {
      const y = row * blockSize;
      const localFront = front + (grid.jitter[row * columns + column] ?? 0);
      const distance = y + blockSize / 2 - localFront;
      if (Math.abs(distance) >= radius) {
        continue;
      }
      const tileHeight = Math.min(blockSize, height - y);
      const path = rectangle(x, y, tileWidth, tileHeight);
      if (y + tileHeight <= localFront) {
        relief.newPath += path;
      } else {
        relief.oldPath += path;
      }
    }
  }

  return {
    center,
    fronts,
    newPath,
    oldPath,
    radius,
    relief,
  };
}

export function paintPixelRelief(
  context: CanvasRenderingContext2D,
  grid: BlockWipeGrid,
  frame: ReturnType<typeof getBlockWipePaths>,
  strength: number
) {
  context.clearRect(0, 0, grid.columns, grid.rows);
  if (strength <= 0) {
    return;
  }
  const { blockSize, columns, rows } = grid;
  const { fronts, radius } = frame;
  for (let column = 0; column < columns; column += 1) {
    const front = fronts[column] ?? 0;
    const firstRow = Math.max(0, Math.floor((front - radius) / blockSize));
    const lastRow = Math.min(
      rows,
      Math.ceil((front + blockSize * 2 + radius) / blockSize)
    );
    for (let row = firstRow; row < lastRow; row += 1) {
      const localFront = front + (grid.jitter[row * columns + column] ?? 0);
      const distance = ((row + 0.5) * blockSize - localFront) / radius;
      if (Math.abs(distance) >= 1) {
        continue;
      }
      const curvature = 1 - distance * distance;
      const slope = Math.abs(distance) * curvature * 2.6;
      // Continuous material lighting, sampled once per tile. No image blending.
      context.fillStyle = distance < 0 ? "white" : "black";
      context.globalAlpha = strength * slope * (distance < 0 ? 0.05 : 0.075);
      context.fillRect(column, row, 1, 1);
    }
  }
  context.globalAlpha = 1;
}

export function getBlockWipeFrame(grid: BlockWipeGrid, progress: number) {
  const p = Math.min(1, Math.max(0, progress));
  const frame = getBlockWipePaths(grid, p);
  const newCells = Array.from(
    { length: grid.rows * grid.columns },
    (_, index) => {
      const row = Math.floor(index / grid.columns);
      const column = index % grid.columns;
      const bottom = Math.min(grid.height, (row + 1) * grid.blockSize);
      return (
        p === 1 ||
        (p > 0 &&
          bottom <= (frame.fronts[column] ?? 0) + (grid.jitter[index] ?? 0))
      );
    }
  );
  return { ...frame, newCells };
}
