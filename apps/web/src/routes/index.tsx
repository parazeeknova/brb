import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

import { BrandIcon } from "@/components/brand-icon";
import { FaqIllustration } from "@/components/faq-illustration";
import { HeroJobCard } from "@/components/hero-job-card";
import { JobCard } from "@/components/jobs-tab";
import { HowItWorks, MarketingSections } from "@/components/marketing-sections";
import {
  GateDiagram,
  LearningCurve,
  PipelineDiagram,
  PixelLoop,
  ThroughputChart,
} from "@/components/pixel-diagrams";
import { ArrowIcon, LeafIcon, MoonIcon } from "@/components/pixel-icons";
import { JOBS } from "@/lib/jobs-data";
import { pageSeo, SITE_URL, structuredData } from "@/lib/seo";

const TITLE = "BRB — AI job search & career discovery";
const DESC =
  "Explore BRB, an open-source AI job search project. Discover employer career sites, learn how to assess roles, and preview experience-based job matching.";

export const Route = createFileRoute("/")({
  component: Landing,
  head: () => ({
    ...pageSeo(TITLE, DESC),
    scripts: [
      structuredData({
        "@context": "https://schema.org",
        "@graph": [
          {
            "@id": `${SITE_URL}/#organization`,
            "@type": "Organization",
            logo: `${SITE_URL}/favicon.svg`,
            name: "BRB",
            sameAs: ["https://github.com/parazeeknova/brb"],
            url: SITE_URL,
          },
          {
            "@id": `${SITE_URL}/#website`,
            "@type": "WebSite",
            description: DESC,
            inLanguage: "en",
            name: "BRB",
            publisher: { "@id": `${SITE_URL}/#organization` },
            url: SITE_URL,
          },
          {
            "@id": `${SITE_URL}/#webpage`,
            "@type": "WebPage",
            description: DESC,
            isPartOf: { "@id": `${SITE_URL}/#website` },
            name: TITLE,
            url: SITE_URL,
          },
        ],
      }),
    ],
  }),
});

const BENEFITS = [
  {
    d: "BRB watches ATS boards, career pages and startup lists around the clock, so you see jobs hours after they go live.",
    n: "24/7",
    t: "Never miss a fresh role",
  },
  {
    d: "Every match comes with a plain apply or skip, and the reason why. No more guessing if you're qualified.",
    n: "1 line",
    t: "Honest advice, not noise",
  },
  {
    d: "Applications are written from your real projects and results, then checked before anything is sent.",
    n: "0",
    t: "Generic cover letters",
  },
];

const FOOTER: { h: string; links: { t: string; href: string }[] }[] = [
  {
    h: "Product",
    links: [
      { href: "/app", t: "Open assistant" },
      { href: "#how", t: "How it works" },
      { href: "#pricing", t: "Pricing" },
    ],
  },
  {
    h: "Open source",
    links: [
      { href: "https://github.com/parazeeknova/brb", t: "GitHub" },
      {
        href: "https://github.com/parazeeknova/brb/issues",
        t: "Report an issue",
      },
    ],
  },
  {
    h: "People",
    links: [
      { href: "https://przknv.cc", t: "Author · pzk" },
      { href: "https://itssingularity.com", t: "Singularity Works" },
    ],
  },
];

const HIRING_COMPANIES: {
  name: string;
  file: string;
  darkFile?: string;
  width: number;
  lightenInDark?: boolean;
}[] = [
  { file: "google", name: "Google", width: 44 },
  { file: "microsoft", name: "Microsoft", width: 44 },
  { file: "meta", name: "Meta", width: 64 },
  { file: "amazon", lightenInDark: true, name: "Amazon", width: 112 },
  { darkFile: "apple-dark", file: "apple", name: "Apple", width: 38 },
  { darkFile: "nvidia-dark", file: "nvidia", name: "NVIDIA", width: 60 },
  { darkFile: "openai-dark", file: "openai", name: "OpenAI", width: 44 },
  {
    darkFile: "anthropic-dark",
    file: "anthropic",
    name: "Anthropic",
    width: 44,
  },
  { file: "adobe", name: "Adobe", width: 50 },
  { file: "netflix", name: "Netflix", width: 44 },
  { file: "tesla", name: "Tesla", width: 44 },
  { file: "spotify", name: "Spotify", width: 44 },
  { file: "oracle", name: "Oracle", width: 150 },
  { file: "salesforce", name: "Salesforce", width: 64 },
  { file: "intel", name: "Intel", width: 44 },
  { file: "ibm", name: "IBM", width: 104 },
  { darkFile: "cisco-dark", file: "cisco", name: "Cisco", width: 78 },
  { darkFile: "uber-dark", file: "uber", name: "Uber", width: 102 },
  { file: "airbnb", name: "Airbnb", width: 42 },
  { file: "atlassian", name: "Atlassian", width: 44 },
];

// eslint-disable-next-line no-unused-vars
function HeroJobCarousel() {
  const renderCards = (jobs: typeof JOBS, duplicate = false) => (
    <div
      aria-hidden={duplicate || undefined}
      className={`hero-carousel-group ${duplicate ? "hero-carousel-group--duplicate" : ""}`}
      inert={duplicate}
    >
      {jobs.map((job, i) => (
        <div className="hero-carousel-slide" key={job.id}>
          <JobCard job={job} i={i} />
        </div>
      ))}
    </div>
  );

  return (
    <div
      aria-label="Job matches"
      className="hero-carousel focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2"
      role="region"
      tabIndex={0}
    >
      <div className="hero-carousel-track">
        {renderCards(JOBS)}
        {renderCards(JOBS, true)}
      </div>
    </div>
  );
}

function CompaniesHiringCarousel({ dark }: { dark: boolean }) {
  const renderLogos = (duplicate = false) => (
    <div
      aria-hidden={duplicate || undefined}
      className="logo-marquee-set"
      inert={duplicate}
    >
      {HIRING_COMPANIES.map((company) => (
        <img
          alt={duplicate ? "" : `${company.name} logo`}
          className={`logo-marquee-image ${company.lightenInDark ? "logo-marquee-image--lighten-in-dark" : ""}`}
          decoding="async"
          height={44}
          key={company.file}
          src={`/company-logos/${dark && company.darkFile ? company.darkFile : company.file}.svg`}
          width={company.width}
          style={
            { "--company-logo-width": `${company.width}px` } as CSSProperties
          }
        />
      ))}
    </div>
  );

  return (
    <section
      aria-labelledby="companies-hiring-title"
      className="mx-auto max-w-6xl pb-24"
    >
      <h2
        className="font-pixel text-muted-foreground text-center text-sm tracking-wide"
        id="companies-hiring-title"
      >
        Companies Hiring
      </h2>
      <div
        aria-label="Companies hiring"
        className="logo-marquee mt-6"
        role="region"
      >
        <div className="logo-marquee-track">
          {renderLogos()}
          {renderLogos(true)}
        </div>
      </div>
    </section>
  );
}

function Landing() {
  const [dusk, setDusk] = useState(false);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dusk);
  }, [dusk]);

  return (
    <div className="min-h-dvh px-4 sm:px-8">
      <div className="hero-stage relative isolate -mx-4 overflow-hidden px-4 sm:-mx-8 sm:px-8">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
        >
          {Array.from({ length: 14 }, (_, i) => (
            <LeafIcon
              key={i}
              size={12 + (i % 3) * 4}
              className={`hero-leaf absolute top-0 ${i % 4 === 0 ? "text-honey" : "text-moss"}`}
              style={{
                animationDelay: `${-(i * 1.1)}s`,
                animationDuration: `${10 + (i % 5) * 2}s`,
                left: `${((i + 0.5) / 14) * 100}%`,
              }}
            />
          ))}
        </div>
        <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between py-5 sm:py-6">
          <Link to="/" className="flex items-center gap-2">
            <BrandIcon />
            <span className="font-pixel text-lg">BRB</span>
          </Link>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setDusk((d) => !d)}
              aria-label={dusk ? "Switch to light" : "Switch to dark"}
              className={`glass grid size-10 place-items-center rounded-full transition-colors ${dusk ? "text-honey" : "text-muted-foreground hover:text-foreground"}`}
            >
              <MoonIcon size={16} />
            </button>
            <Link
              to="/app"
              className="btn-honey group flex h-10 items-center gap-2 rounded-full px-5 text-sm font-bold"
            >
              Open assistant
              <ArrowIcon
                size={12}
                className="transition-transform duration-200 group-hover:translate-x-1"
              />
            </Link>
          </div>
        </header>

        {/* Hero */}
        <section className="relative z-10 mx-auto grid max-w-6xl items-center gap-10 pt-8 pb-12 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] sm:gap-8 sm:pt-10 lg:gap-16 lg:pt-16 lg:pb-24">
          <div className="text-center sm:text-left">
            <h1 className="text-4xl leading-[1.15] sm:text-[clamp(2rem,4.5vw,3.75rem)]">
              A job search
              <br />
              that learns.
            </h1>
            <p className="text-muted-foreground mx-auto mt-6 max-w-md text-lg leading-relaxed sm:mx-0 sm:text-base lg:text-lg">
              BRB scans the web for fresh roles, ranks them against your real
              experience and tells you plainly what to apply for.
            </p>
            <div className="mt-9 flex flex-wrap items-center justify-center gap-5 sm:justify-start">
              <Link
                to="/app"
                className="btn-honey group flex h-12 items-center gap-2 rounded-2xl px-6 font-bold"
              >
                Meet your assistant
                <ArrowIcon
                  size={14}
                  className="transition-transform duration-200 group-hover:translate-x-1"
                />
              </Link>
            </div>
          </div>
          <div className="relative mx-auto w-full max-w-md min-w-0">
            {/* <HeroJobCarousel /> */}
            <HeroJobCard blockSize={8} duration={1800} />
            <p className="text-muted-foreground mt-4 text-center text-xs leading-relaxed">
              Real employer listings checked October 26, 2026. Fit notes
              illustrate an example profile. Availability may change.
            </p>
          </div>
        </section>
      </div>

      <CompaniesHiringCarousel dark={dusk} />

      {/* Why */}
      <section className="mx-auto max-w-6xl pb-24">
        <h2 className="max-w-xl text-2xl leading-snug sm:text-4xl">
          Stop scrolling job boards. Start getting replies.
        </h2>
        <div className="mt-10 grid gap-x-10 gap-y-8 sm:grid-cols-3">
          {BENEFITS.map((b) => (
            <div key={b.t}>
              <p className="font-pixel text-moss text-3xl">{b.n}</p>
              <h3 className="mt-3 text-lg">{b.t}</h3>
              <p className="text-muted-foreground mt-2 leading-relaxed">
                {b.d}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Loop */}
      <section className="mx-auto grid max-w-6xl items-center gap-10 pb-20 lg:grid-cols-[0.8fr_1.2fr]">
        <div>
          <h2 className="text-2xl sm:text-4xl">One loop, always running</h2>
          <p className="text-muted-foreground mt-4 max-w-sm leading-relaxed">
            Most tools search and stop. BRB treats every application as an
            experiment, watches what happens, and quietly gets better at picking
            the next one.
          </p>
        </div>
        <div className="glass rounded-[1.8rem] p-4 sm:p-8">
          <PixelLoop />
        </div>
      </section>

      {/* Pipeline */}
      <section className="mx-auto max-w-6xl pb-20">
        <div className="glass rounded-[1.8rem] p-5 sm:p-8">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="text-xl sm:text-2xl">Discovery to decision</h2>
            <span className="text-muted-foreground text-sm">
              Ranking is kept apart from discovery, so new sources earn trust.
            </span>
          </div>
          <div className="engraved mt-6 rounded-[1.2rem] p-4 sm:p-6">
            <PipelineDiagram />
          </div>
        </div>
      </section>

      <HowItWorks />

      {/* Charts */}
      <section className="mx-auto max-w-6xl pb-8">
        <h2 className="max-w-2xl text-2xl leading-snug sm:text-4xl">
          Fast where it should be. Careful where it counts.
        </h2>
        <p className="text-muted-foreground mt-4 max-w-xl leading-relaxed">
          BRB reads thousands of postings a minute so you don't have to, then
          slows right down before anything goes out with your name on it.
        </p>
      </section>
      <section className="mx-auto grid max-w-6xl gap-5 pb-20 lg:grid-cols-[1.25fr_1fr]">
        <div className="glass rounded-[1.8rem] p-5 sm:p-8">
          <h2 className="text-xl sm:text-2xl">Peak throughput / min</h2>
          <p className="text-muted-foreground mt-2 text-sm">
            Log scale. Fast at finding, deliberately slow at applying.
          </p>
          <div className="mt-6">
            <ThroughputChart />
          </div>
          <p className="mt-5 font-bold">
            Fresh roles land in your list while other applicants are still
            refreshing.
          </p>
          <p className="text-muted-foreground mt-2 text-xs">
            i7 12th Gen · 32 GB DDR5 · RTX 3060 · 700 Mbps
          </p>
          <div className="pixel-frame mt-6">
            <div className="pixel-inner p-4 sm:p-5">
              <p className="font-bold">
                Run the whole pipeline locally, with your own agents.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {["Claude Code", "pi", "Codex"].map((a) => (
                  <span
                    key={a}
                    className="glass font-pixel rounded-full px-3 py-1 text-[11px]"
                  >
                    {a} <span className="text-honey">· soon</span>
                  </span>
                ))}
              </div>
              <p className="text-muted-foreground mt-3 text-xs">
                Support for all local agents is coming soon!!
              </p>
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-5">
          <div className="glass rounded-[1.8rem] p-5 sm:p-8">
            <h2 className="text-xl sm:text-2xl">It gets sharper</h2>
            <p className="text-muted-foreground mt-2 text-sm">
              Qualified applications per run.{" "}
              <span className="text-honey">■</span> new policy promoted.
            </p>
            <div className="mt-5">
              <LearningCurve />
            </div>
            <p className="mt-4 text-sm font-bold">
              Week four picks beat week one. Every outcome teaches it.
            </p>
          </div>
          <div className="glass rounded-[1.8rem] p-5 sm:p-8">
            <h2 className="text-xl sm:text-2xl">Fails closed</h2>
            <div className="mt-4">
              <GateDiagram />
            </div>
            <p className="mt-4 text-sm font-bold">
              If a claim can't be backed by your real work, it never gets sent.
              No embarrassing applications.
            </p>
          </div>
        </div>
      </section>

      <MarketingSections />

      <section
        aria-labelledby="faq-title"
        className="mx-auto grid max-w-6xl items-start gap-8 pb-20 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-12"
      >
        <div className="text-center lg:sticky lg:top-24 lg:text-left">
          <p className="font-pixel text-moss text-sm">
            BEFORE YOUR NEXT CHAPTER
          </p>
          <h2 id="faq-title" className="mt-3 text-3xl sm:text-4xl">
            A few good questions.
          </h2>
          <div className="mt-6 lg:mt-10">
            <FaqIllustration />
          </div>
        </div>
        <div className="space-y-3">
          {[
            {
              a: "Start with your resume, a few projects or examples of your work, and the kind of role you want. In chat, BRB turns those details into a reusable career profile, including your skills, experience, location and preferences. You can refine it as your search changes.",
              q: "What do I need to get started?",
            },
            {
              a: "BRB compares your career profile with requirements in the continuously updated job corpus. Each recommendation explains relevant experience, gaps and practical constraints such as location or seniority, so you can decide whether the role deserves your time. A match is guidance, not an interview guarantee.",
              q: "How does BRB decide which jobs fit me?",
            },
            {
              a: "Yes. Autofill prepares repetitive fields and your selected documents. You check the answers, provide anything that needs your judgment and make the final submission yourself. You choose the roles; BRB helps with the repetitive work.",
              q: "Can I check an application before it is submitted?",
            },
            {
              a: "Tailoring uses the experience, projects and achievements in your profile to emphasize what matters for a particular role. It should not invent employers, qualifications or results. Review and edit the resume and cover letter before you use them; missing facts need to come from you.",
              q: "Will tailoring add skills or experience I do not have?",
            },
            {
              a: "One pack is a tailored resume and cover letter for one role. Packs and autofill have separate allowances, so you can use the documents to apply manually without spending an autofill credit.",
              q: "What do I get in an application pack?",
            },
            {
              a: "One autofill credit covers up to five minutes of active browser work. Longer forms ask before using another credit. Logins, verification checks and questions requiring your judgment are handed back to you. If a BRB-side error interrupts the run, the affected credit is restored. A credit covers browser work rather than a guaranteed completed application.",
              q: "What happens with long forms, logins or verification checks?",
            },
            {
              a: "Your profile and saved jobs stay available, and you can still use the employer's application link. Choose a $5 top-up for 10 autofill credits or a larger monthly plan if you need more. There are no automatic top-ups or annual commitments. Monthly allowances reset each billing cycle.",
              q: "What happens when I use all my credits?",
            },
            {
              a: "Your career profile is used for matching and tailoring. When you autofill a role, the relevant answers and documents are prepared for that employer's application form. You review what is being shared before submission. Dodo Payments handles checkout separately from your application documents.",
              q: "Who receives my resume and application details?",
            },
          ].map((faq) => (
            <details key={faq.q} className="glass rounded-2xl px-5 py-4">
              <summary className="cursor-pointer font-bold">{faq.q}</summary>
              <p className="text-muted-foreground mt-3 leading-relaxed">
                {faq.a}
              </p>
            </details>
          ))}
        </div>
      </section>

      <footer className="mx-auto max-w-6xl pt-4 pb-10">
        <div className="pixel-footer relative overflow-hidden">
          <div aria-hidden className="pixel-footer-checks h-3" />
          <div className="border-moss/25 grid items-center gap-6 border-b-2 border-dashed px-6 py-10 text-center sm:px-8 sm:text-left lg:grid-cols-[1fr_auto] lg:px-10">
            <div>
              <p className="font-pixel text-moss text-xs tracking-widest">
                NEXT LEVEL: YOUR NEXT ROLE
              </p>
              <h2 className="mx-auto mt-4 max-w-xl text-3xl leading-tight sm:mx-0 sm:text-4xl">
                A little less searching.
                <br />A lot more possibility.
              </h2>
              <p className="text-muted-foreground mx-auto mt-4 max-w-lg leading-relaxed sm:mx-0">
                Let BRB find the roles that fit. Save your energy for what comes
                next.
              </p>
            </div>
            <Link
              to="/app"
              className="btn-honey group mx-auto inline-flex min-h-12 w-fit items-center gap-3 rounded-2xl px-6 py-3 font-bold sm:mx-0"
            >
              Start your next chapter
              <ArrowIcon size={14} />
            </Link>
          </div>
          <div className="grid gap-8 px-6 py-8 sm:grid-cols-2 sm:px-8 lg:grid-cols-[1.4fr_1fr_1fr_1fr] lg:px-10">
            <div>
              <Link to="/" className="inline-flex items-center gap-2">
                <BrandIcon />
                <span className="font-pixel text-xl">BRB</span>
              </Link>
              <p className="text-muted-foreground mt-3 max-w-xs text-sm leading-relaxed">
                A job search that learns.
                <br />
                Built with care. Shared in the open.
              </p>
              <div aria-hidden className="mt-5 flex gap-1.5">
                {Array.from({ length: 8 }, (_, i) => (
                  <span
                    key={i}
                    className={`size-2 ${i % 3 === 0 ? "bg-honey" : "bg-moss/50"}`}
                  />
                ))}
              </div>
            </div>
            {FOOTER.map((col) => (
              <nav key={col.h} aria-label={col.h}>
                <p className="font-pixel text-sm">{col.h}</p>
                <ul className="text-muted-foreground mt-3 space-y-1 text-sm">
                  {col.links.map((l) => (
                    <li key={l.t}>
                      {l.href === "/app" ? (
                        <Link
                          to="/app"
                          className="pixel-footer-link hover:text-foreground inline-flex min-h-9 items-center gap-2"
                        >
                          <span aria-hidden className="font-pixel text-moss">
                            +
                          </span>
                          {l.t}
                        </Link>
                      ) : (
                        <a
                          href={l.href}
                          {...(l.href.startsWith("http")
                            ? { rel: "noreferrer", target: "_blank" }
                            : {})}
                          className="pixel-footer-link hover:text-foreground inline-flex min-h-9 items-center gap-2"
                        >
                          <span aria-hidden className="font-pixel text-moss">
                            +
                          </span>
                          {l.t}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
          <div className="border-moss/25 text-muted-foreground mx-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t-2 border-dashed py-5 text-xs sm:mx-8 lg:mx-10">
            <p>© {new Date().getUTCFullYear()} BRB. All rights reserved.</p>
            <p className="font-pixel inline-flex items-center gap-2">
              <span aria-hidden className="bg-moss size-2" />
              Made by{" "}
              <a
                className="underline underline-offset-4"
                href="https://przknv.cc"
                target="_blank"
                rel="noreferrer"
              >
                pzk
              </a>
            </p>
          </div>
          <div aria-hidden className="pixel-footer-ground h-4" />
        </div>
      </footer>
    </div>
  );
}
