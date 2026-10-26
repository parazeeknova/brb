import { createFileRoute, Link, notFound } from "@tanstack/react-router";

import { BrandIcon } from "@/components/brand-icon";
import { ArrowIcon } from "@/components/pixel-icons";
import { pageSeo, SITE_URL, structuredData } from "@/lib/seo";
import { SOURCE_PAGES } from "@/lib/source-pages";
import type { SourcePage } from "@/lib/source-pages";

function getSource(slug: string): SourcePage {
  const source = SOURCE_PAGES.find((item) => item.slug === slug);
  if (!source) {
    throw notFound();
  }
  return source;
}

export const Route = createFileRoute("/sources/$source")({
  component: SourceGuide,
  head: ({ params }) => {
    const source = getSource(params.source);
    const path = `/sources/${source.slug}`;
    return {
      ...pageSeo(
        `${source.name} job search guide | BRB`,
        source.description,
        path
      ),
      scripts: [
        structuredData({
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", item: SITE_URL, name: "BRB", position: 1 },
            {
              "@type": "ListItem",
              item: `${SITE_URL}${path}`,
              name: `${source.name} job search guide`,
              position: 2,
            },
          ],
        }),
      ],
    };
  },
  loader: ({ params }) => getSource(params.source),
});

function SourceGuide() {
  const source = getSource(Route.useParams().source);
  return (
    <div className="min-h-dvh px-4 pb-12 sm:px-8">
      <header className="mx-auto flex max-w-5xl items-center justify-between gap-4 py-6">
        <Link to="/" className="flex items-center gap-2">
          <BrandIcon />
          <span className="font-pixel text-lg">BRB</span>
        </Link>
        <Link
          to="/app"
          className="btn-honey flex min-h-11 items-center gap-2 rounded-full px-5 text-sm font-bold"
        >
          Explore BRB <ArrowIcon size={12} />
        </Link>
      </header>
      <main className="mx-auto max-w-3xl pt-10 sm:pt-16">
        <Link
          to="/"
          className="text-muted-foreground text-sm underline underline-offset-4"
        >
          BRB / Job sources
        </Link>
        <div className="mt-8 flex items-center gap-4">
          <span className="grid size-14 shrink-0 place-items-center rounded-xl bg-white p-3">
            <img
              src={source.logo}
              alt=""
              width={36}
              height={36}
              className="max-h-9 object-contain"
            />
          </span>
          <p className="font-pixel text-moss text-sm">
            A FIELD GUIDE TO YOUR NEXT ROLE
          </p>
        </div>
        <h1 className="mt-6 text-3xl leading-tight sm:text-5xl">
          Finding jobs on {source.name}
        </h1>
        <p className="text-muted-foreground mt-6 text-lg leading-relaxed">
          {source.intro}
        </p>
        <div className="mt-10 space-y-8">
          {[
            { text: source.find, title: "Where to start" },
            { text: source.check, title: "What to check before applying" },
            { text: source.approach, title: "How BRB approaches this source" },
          ].map((section) => (
            <section
              key={section.title}
              className="glass rounded-3xl p-6 sm:p-8"
            >
              <h2 className="text-xl sm:text-2xl">{section.title}</h2>
              <p className="text-muted-foreground mt-4 leading-relaxed">
                {section.text}
              </p>
            </section>
          ))}
        </div>
        <div className="mt-8 flex flex-wrap items-center gap-4">
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="btn-honey inline-flex min-h-12 items-center gap-2 rounded-2xl px-6 font-bold"
          >
            Visit {source.name} <ArrowIcon size={14} />
          </a>
          <Link
            to="/app"
            className="text-moss inline-flex min-h-12 items-center underline underline-offset-4"
          >
            Explore the BRB assistant
          </Link>
        </div>
        <p className="text-muted-foreground mt-6 text-xs leading-relaxed">
          Independent source guide. BRB is not affiliated with or endorsed by{" "}
          {source.name}. Employer requirements and availability can change.
        </p>
        <nav
          aria-label="More job source guides"
          className="border-moss/25 mt-12 border-t-2 border-dashed pt-8"
        >
          <h2 className="font-pixel text-lg">Explore more sources</h2>
          <div className="mt-4 flex flex-wrap gap-3">
            {SOURCE_PAGES.filter((item) => item.slug !== source.slug).map(
              (item) => (
                <Link
                  key={item.slug}
                  to="/sources/$source"
                  params={{ source: item.slug }}
                  className="glass rounded-full px-4 py-2 text-sm hover:underline"
                >
                  {item.name}
                </Link>
              )
            )}
          </div>
        </nav>
      </main>
      <footer className="text-muted-foreground mx-auto mt-12 max-w-3xl text-xs">
        © {new Date().getUTCFullYear()} BRB. All rights reserved.
      </footer>
    </div>
  );
}
