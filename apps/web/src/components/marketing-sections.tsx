import { Link } from "@tanstack/react-router";

import { JOBS } from "@/lib/jobs-data";
import {
  AUTOFILL_MINUTES_PER_CREDIT,
  AUTOFILL_TOP_UP,
  BILLING_PROVIDER,
  PRICING_PLANS,
} from "@/lib/pricing";
import { SOURCE_PAGES } from "@/lib/source-pages";

import { JobCard } from "./jobs-tab";
import { LearningCurve } from "./pixel-diagrams";
import {
  ArrowIcon,
  LeafIcon,
  SearchIcon,
  SendIcon,
  SparkleIcon,
} from "./pixel-icons";

const STEPS = [
  {
    d: "Drop in your resume and a few real projects. That's the only form you'll fill.",
    t: "Tell BRB who you are",
  },
  {
    d: "BRB sweeps career sites and boards, dedupes everything and ranks each role against you.",
    t: "It goes hunting",
  },
  {
    d: "Every match says apply or skip, with one honest line on why.",
    t: "You get a short list",
  },
  {
    d: "A tailored resume and cover letter, then autofill for the repetitive fields. You check the details and submit.",
    t: "You review and apply",
  },
  {
    d: "Replies, rejections and silence all feed back, so next week's picks are sharper.",
    t: "It learns",
  },
];

export function MarketingSections() {
  return (
    <>
      {/* Sources */}
      <section className="mx-auto max-w-6xl pb-20">
        <div className="glass rounded-[1.8rem] p-6 sm:p-10">
          <p className="text-muted-foreground text-center text-sm">
            Jobs from company career sites and job boards, including
          </p>
          <div className="mx-auto mt-6 grid max-w-3xl grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center sm:justify-center sm:gap-3">
            {SOURCE_PAGES.map((s) => (
              <Link
                key={s.slug}
                to="/sources/$source"
                params={{ source: s.slug }}
                className="engraved flex min-h-12 min-w-0 items-center gap-2 rounded-full py-1.5 pr-2 pl-1.5 hover:underline sm:gap-2.5 sm:pr-4"
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-white p-1.5 sm:size-9">
                  <img
                    src={s.logo}
                    alt=""
                    width={28}
                    height={28}
                    loading="lazy"
                    className="max-h-5 w-5 object-contain sm:max-h-7 sm:w-7"
                  />
                </span>
                <span className="font-pixel min-w-0 text-xs sm:text-sm">
                  {s.name}
                </span>
              </Link>
            ))}
            <span className="font-pixel text-moss col-span-2 mt-2 text-center text-xs sm:mt-0 sm:text-sm">
              + employer career pages
            </span>
          </div>
        </div>
      </section>

      {/* Statement */}
      <section className="mx-auto max-w-6xl pb-20 text-center">
        <h2 className="mx-auto max-w-3xl text-3xl leading-tight sm:text-5xl">
          Your evenings deserve better than copy‑pasting cover letters.
        </h2>
        <p className="text-muted-foreground mx-auto mt-5 max-w-lg text-lg">
          Hand BRB the next hundred applications. Keep your energy for the
          conversations that matter.
        </p>
      </section>

      {/* Pricing */}
      <section
        id="pricing"
        className="mx-auto max-w-6xl pb-20"
        aria-labelledby="pricing-title"
      >
        <div className="mx-auto max-w-2xl text-center">
          <p className="font-pixel text-moss text-sm">
            ROOM FOR YOUR NEXT CHAPTER
          </p>
          <h2 id="pricing-title" className="mt-3 text-3xl sm:text-4xl">
            Start small. Step up when you need to.
          </h2>
          <p className="text-muted-foreground mt-4 leading-relaxed">
            A free starting point, a student-friendly plan, and more room for an
            active search. Monthly pricing. No annual commitment.
          </p>
          <p className="text-muted-foreground mt-3 text-xs leading-relaxed">
            Proposed launch plans, in USD. Personalized matching, tailoring,
            autofill and {BILLING_PROVIDER} checkout are coming. The current
            preview does not charge you.
          </p>
        </div>
        <div className="mt-8 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {PRICING_PLANS.map((plan) => (
            <div
              key={plan.id}
              className={`pixel-frame flex ${plan.recommended ? "is-pop" : ""}`}
            >
              <div className="pixel-inner relative flex w-full flex-col p-5 sm:p-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-xl">{plan.name}</h3>
                  {plan.recommended && (
                    <span className="gem gem-fit font-pixel px-2 py-1 text-[10px]">
                      Active search
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground mt-3 min-h-10 text-sm leading-relaxed">
                  {plan.description}
                </p>
                <p className="mt-5">
                  <span className="font-pixel text-4xl">${plan.priceUsd}</span>
                  <span className="text-muted-foreground text-sm">
                    {" "}
                    / month
                  </span>
                </p>
                <ul className="mt-6 flex flex-1 flex-col gap-3 text-sm">
                  {[
                    "Your reusable career profile",
                    plan.matchFrequency,
                    `${plan.chatMessages} AI chat messages / month`,
                    `${plan.documentPacks} tailored application packs / month`,
                    plan.autofillCredits
                      ? `${plan.autofillCredits} autofill credits / month`
                      : "Apply manually on employer sites",
                  ].map((item) => (
                    <li key={item} className="flex gap-2">
                      <SparkleIcon
                        size={12}
                        className="text-moss mt-1 shrink-0"
                      />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-muted-foreground mt-4 text-xs">
                  {plan.autofillCredits
                    ? `Up to ${plan.autofillCredits * AUTOFILL_MINUTES_PER_CREDIT} minutes of active autofill.`
                    : "No browser automation included."}
                </p>
                <Link
                  to="/app"
                  className={`group mt-6 flex min-h-11 items-center justify-center gap-2 rounded-[0.9rem] text-sm font-bold ${plan.recommended ? "btn-honey" : "engraved"}`}
                >
                  Explore the preview <ArrowIcon size={12} />
                </Link>
              </div>
            </div>
          ))}
        </div>
        <div className="glass mt-6 grid gap-6 rounded-3xl p-6 text-sm sm:grid-cols-3 sm:p-8">
          <div>
            <h3 className="font-pixel text-sm">One pack, one role.</h3>
            <p className="text-muted-foreground mt-3 leading-relaxed">
              A tailored resume and cover letter for one job, grounded in your
              profile. Use them even when you apply manually.
            </p>
          </div>
          <div>
            <h3 className="font-pixel text-sm">Autofill you control.</h3>
            <p className="text-muted-foreground mt-3 leading-relaxed">
              One credit covers up to {AUTOFILL_MINUTES_PER_CREDIT} active
              browser minutes. Longer forms ask before using another credit. You
              review and submit.
            </p>
          </div>
          <div>
            <h3 className="font-pixel text-sm">A little extra, if needed.</h3>
            <p className="text-muted-foreground mt-3 leading-relaxed">
              Planned top-up: {AUTOFILL_TOP_UP.credits} autofill credits for $
              {AUTOFILL_TOP_UP.priceUsd}. No automatic top-ups. Monthly
              allowances reset each billing cycle.
            </p>
          </div>
        </div>
        <p className="text-muted-foreground mx-auto mt-5 max-w-3xl text-center text-xs leading-relaxed">
          No interview or offer guarantees. An autofill credit covers browser
          work, not a guaranteed completed application. Applicable taxes will be
          shown before payment when billing launches.
        </p>
      </section>
    </>
  );
}

export function HowItWorks() {
  return (
    <section id="how" className="mx-auto max-w-6xl pb-20">
      <h2 className="text-2xl sm:text-4xl">How it works</h2>
      <p className="text-muted-foreground mt-3 max-w-md">
        Five minutes of setup. Then it just keeps going.
      </p>
      <div className="mt-10 flex flex-col gap-6">
        {STEPS.map((s, i) => (
          <div
            key={s.t}
            className="glass grid items-center gap-6 rounded-[1.8rem] p-5 sm:p-8 lg:grid-cols-2 lg:gap-12"
          >
            <div className={i % 2 ? "lg:order-2" : ""}>
              <span className="font-pixel text-honey text-3xl">0{i + 1}</span>
              <h3 className="mt-3 text-xl sm:text-2xl">{s.t}</h3>
              <p className="text-muted-foreground mt-3 max-w-sm leading-relaxed">
                {s.d}
              </p>
            </div>
            <div className="engraved rounded-[1.4rem] p-4 sm:p-6">
              <StepDemo i={i} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Bot({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-end gap-2.5">
      <LeafIcon size={16} className="text-moss mb-3 shrink-0" />
      <div className="bubble-bot rounded-[1.25rem] rounded-bl-md px-4 py-3 text-sm leading-relaxed">
        {children}
      </div>
    </div>
  );
}
function Me({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex justify-end">
      <div className="bubble-user rounded-[1.25rem] rounded-br-md px-4 py-3 text-sm leading-relaxed">
        {children}
      </div>
    </div>
  );
}

function StepDemo({ i }: { i: number }) {
  if (i === 0) {
    return (
      <div className="space-y-3">
        <Me>
          Here's my resume. I built a log processor that handles 2M events a
          minute.
        </Me>
        <Bot>Nice. I'll use that as proof for backend and data roles.</Bot>
        <div className="glass flex items-center gap-2 rounded-[1.2rem] p-2">
          <span className="engraved text-muted-foreground flex h-10 flex-1 items-center rounded-[0.8rem] px-3 text-sm">
            Add a project link
          </span>
          <span className="btn-honey grid size-10 place-items-center rounded-[0.8rem]">
            <SendIcon size={14} />
          </span>
        </div>
      </div>
    );
  }
  if (i === 1) {
    return (
      <div className="space-y-3">
        <div className="glass flex items-center gap-3 rounded-[1.2rem] p-2">
          <span className="engraved text-muted-foreground flex h-10 flex-1 items-center gap-2 rounded-[0.8rem] px-3 text-sm">
            <SearchIcon size={14} /> backend · remote · seed to series B
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {["Greenhouse 412", "Lever 188", "Ashby 96", "Career pages 731"].map(
            (c) => (
              <span
                key={c}
                className="glass rounded-full px-3 py-1.5 text-xs font-semibold"
              >
                {c}
              </span>
            )
          )}
        </div>
        <p className="font-pixel text-muted-foreground text-xs">
          1,427 found · 1,102 after dedup · 38 ranked fits
        </p>
      </div>
    );
  }
  if (i === 2) {
    const [job] = JOBS;
    if (job === undefined) {
      return null;
    }
    return <JobCard job={job} i={0} />;
  }
  if (i === 3) {
    return (
      <div className="space-y-3">
        <Bot>
          Your application draft is ready. The examples come from the projects
          and experience in your profile.
        </Bot>
        <Me>Let me review the answers first.</Me>
        <Bot>
          Of course. Check the answers and documents, then submit when ready.
        </Bot>
      </div>
    );
  }
  return (
    <div>
      <LearningCurve />
      <p className="text-muted-foreground mt-3 text-xs">
        Each run, BRB keeps what got replies and drops what didn't.
      </p>
    </div>
  );
}
