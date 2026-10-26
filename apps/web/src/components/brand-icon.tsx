export function BrandIcon() {
  return (
    <span aria-hidden className="relative size-8 shrink-0 overflow-hidden">
      {/* The supplied logo has generous transparent margins around the sprout. */}
      <img
        src="/brb-logo.webp"
        alt=""
        width={72}
        height={72}
        className="absolute top-1/2 left-1/2 size-18 max-w-none -translate-x-[51.4%] -translate-y-[54%]"
      />
    </span>
  );
}
