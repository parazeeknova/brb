// A small pixel desk: a career profile, a considered match and the final say.
export function FaqIllustration() {
  return (
    <svg
      aria-label="Your profile leads to clearer matches, with you in control of each application"
      className="mx-auto w-full max-w-sm"
      role="img"
      shapeRendering="crispEdges"
      viewBox="0 0 320 260"
    >
      <g
        className="text-foreground"
        fill="none"
        opacity="0.12"
        stroke="currentColor"
      >
        <path d="M24 40h272M24 80h272M24 120h272M24 160h272M24 200h272M40 24v208M80 24v208M120 24v208M160 24v208M200 24v208M240 24v208M280 24v208" />
      </g>
      <path
        className="text-moss"
        d="M92 90h44v48h40m16 32v44h-68"
        fill="none"
        stroke="currentColor"
        strokeDasharray="4 6"
        strokeWidth="3"
      />
      <g
        className="text-foreground"
        fill="var(--background)"
        stroke="currentColor"
        strokeWidth="2"
      >
        <path d="M32 38h84v8h8v104h-8v8H32v-8h-8V46h8Z" />
        <path d="M174 96h114v8h8v88h-8v8h-62l-20 20v-20h-32v-8h-8v-88h8Z" />
      </g>
      <g className="text-honey" fill="currentColor">
        <path d="M48 58h24v24H48zM42 88h36v12H42z" />
        <path d="M188 114h16v8h-8v8h-8zM212 114h62v6h-62zM212 126h46v6h-46z" />
        <path d="M252 36h12v12h12v12h-12v12h-12V60h-12V48h12z" />
      </g>
      <g className="text-foreground" fill="currentColor" opacity="0.35">
        <path d="M40 112h68v4H40zM40 124h52v4H40zM40 136h60v4H40zM188 148h86v4h-86zM188 160h62v4h-62z" />
      </g>
      <path
        className="text-moss"
        d="m254 176 6 6 14-14"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
      />
      <g
        className="font-pixel text-muted-foreground"
        fill="currentColor"
        fontSize="10"
      >
        <text x="28" y="26">
          YOUR PROFILE
        </text>
        <text x="168" y="84">
          CLEARER MATCHES
        </text>
        <text x="34" y="218">
          YOUR NEXT CHAPTER.
        </text>
        <text x="34" y="234">
          YOUR CALL.
        </text>
      </g>
      <g className="text-moss" fill="currentColor">
        <path d="M40 174h6v6h-6zM48 182h6v6h-6zM32 182h6v6h-6zM40 190h6v6h-6z" />
      </g>
    </svg>
  );
}
