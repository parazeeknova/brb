export interface SourcePage {
  slug: string;
  name: string;
  logo: string;
  url: string;
  description: string;
  intro: string;
  find: string;
  check: string;
  approach: string;
}

export const SOURCE_PAGES: SourcePage[] = [
  {
    approach:
      "BRB's discovery pipeline distinguishes a public employer posting from a social post or search-result page. A LinkedIn mention can be a starting point, while the employer's own application page supplies the evidence. Login requirements and restricted pages can limit verification; BRB does not promise access to private listings.",
    check:
      "Follow the company name to its official website and look for the same role on its careers page. Compare the location, seniority, job description and application destination. Be cautious when an application asks for payment or sends you to a domain unrelated to the employer.",
    description:
      "Find jobs through LinkedIn, confirm the employer's original posting, and compare role requirements before applying. A practical BRB source guide.",
    find: "Start with a role family, then narrow by location and workplace type. Use the company filter when you already know where you want to work. Search results, reposts and recruiter updates can point to the same opening, so save the employer's direct link rather than treating every mention as a new job.",
    intro:
      "LinkedIn combines job listings with company pages, recruiter activity and professional networks. That makes it useful for discovering an opportunity and learning who is hiring, but the social context is different from an employer's canonical job description.",
    logo: "/source-logos/linkedin.svg",
    name: "LinkedIn",
    slug: "linkedin",
    url: "https://www.linkedin.com/jobs/",
  },
  {
    approach:
      "BRB separates company discovery from job verification. Finding a YC company is not proof that it is hiring for your role. The ingest pipeline follows public job evidence, keeps the original application destination and treats duplicate references as one opportunity where possible.",
    check:
      "Read the company's product description and stage alongside the role. Check whether compensation includes equity, whether the location requires relocation, and what the team expects you to own. A small team may use a broad title for responsibilities that would span several roles elsewhere.",
    description:
      "Explore startup roles through Y Combinator and evaluate company stage, ownership, location and application requirements with BRB's source guide.",
    find: "Use YC's job directory to explore startups by role and location. Read the company profile before the vacancy: team size, product and hiring priorities help explain why the position exists. Search by the work you want to do as well as by a familiar job title.",
    intro:
      "Y Combinator's job directory is a useful starting point for startup careers. Company context matters here: a role at an early team can involve wider ownership, a different pace and different tradeoffs from the same title at an established employer.",
    logo: "/source-logos/y-combinator.svg",
    name: "Y Combinator",
    slug: "y-combinator",
    url: "https://www.ycombinator.com/jobs",
  },
  {
    approach:
      "BRB's ingest service includes Workday discovery and structured posting acquisition. Employer tenant and requisition information help connect the job to its original source. The public web app is currently separate from this corpus, so this guide does not represent a live feed of Workday results.",
    check:
      "Check the requisition number, country, workplace expectations and closing information on the employer's page. Similar titles can belong to different countries or business units. An application account may be specific to that employer rather than transferable across all Workday career sites.",
    description:
      "Navigate employer Workday career sites, understand requisition IDs and location filters, and keep track of original application links with BRB.",
    find: "Begin on the employer's official careers page and follow its Workday link. Search within that employer's tenant, using location and job-family filters. Keep the requisition ID when saving a role: it is often a more useful reference than a title that may appear on several different openings.",
    intro:
      "Workday powers career sites for individual employers. It is not a single universal job board: each employer has its own tenant, filters and application flow. Knowing which employer and requisition you are looking at makes research much easier.",
    logo: "/source-logos/workday.svg",
    name: "Workday",
    slug: "workday",
    url: "https://www.workday.com/en-us/products/talent-management/talent-acquisition.html",
  },
  {
    approach:
      "BRB's ingest pipeline reads public Greenhouse board data and preserves the employer's posting URL. Structured source data can establish that a posting exists, while personal suitability still requires comparison with your experience. BRB's landing examples link directly to the employer's application page.",
    check:
      "Compare the role's responsibilities with the requirements rather than relying on the title alone. Check whether several offices are alternatives or whether the position requires a specific local presence. Return to the original listing before applying because responsibilities and availability can change.",
    description:
      "Find employer openings on Greenhouse, read location and experience requirements, and verify the original application page with BRB's source guide.",
    find: "Follow the jobs link from the employer's website to its Greenhouse board. Filter by department or office when the board supports it, then open individual roles for the full description. Save the job ID and direct URL so that a repost on another website does not become a duplicate application.",
    intro:
      "Greenhouse hosts job boards and application forms for employers. Public boards usually group opportunities by department and location, giving you a direct route from a company's careers site to its own requirements and application form.",
    logo: "/source-logos/greenhouse.svg",
    name: "Greenhouse",
    slug: "greenhouse",
    url: "https://www.greenhouse.com/",
  },
  {
    approach:
      "BRB has a source-specific Lever connector in its ingest pipeline. It uses public posting data rather than inventing role details from a company name. Keeping the source URL and employer identity attached to the record makes it possible to revisit the original evidence.",
    check:
      "Read the workplace classification, location and employment type together. Remote availability may still be limited to particular countries or time zones. Confirm the application link belongs to the employer's Lever page and review the original description before sharing personal information.",
    description:
      "Explore employer jobs hosted on Lever, check workplace and employment details, and preserve the direct application link with BRB's source guide.",
    find: "Start on the company's careers page or its public Lever board. Department, team, location and commitment filters can narrow a large list. Open the full role instead of deciding from a search snippet; the description may clarify responsibilities or regional restrictions that are absent from the title.",
    intro:
      "Lever hosts employer-specific job pages and application forms. It is useful for researching a company's openings in one place, especially when a role has been shared across several outside job boards with slightly different summaries.",
    logo: "/source-logos/lever.png",
    name: "Lever",
    slug: "lever",
    url: "https://www.lever.co/",
  },
  {
    approach:
      "BRB's ingest service supports public Ashby board data and keeps the original employer URL. The landing page includes real OpenAI roles hosted on Ashby as examples. Their fit notes are illustrative, and a dated example should always be checked against the current posting.",
    check:
      "Check location, remote eligibility and required experience in the original description. When compensation information is present, read the region and role-level context rather than assuming every candidate receives the same range. Confirm that the role is still accepting applications.",
    description:
      "Find public employer openings on Ashby, review location and role requirements, and use original posting links with BRB's job-search guide.",
    find: "Use the employer's careers website to reach its Ashby board, then narrow the list by team, location or employment type. Keep the direct posting URL when you save a role. A role mentioned in a newsletter or social post may refer to this same canonical page.",
    intro:
      "Ashby provides public job boards and application workflows for employers. A board brings a company's roles together, while each individual posting contains the detailed responsibilities and application path you need to assess an opportunity.",
    logo: "/source-logos/ashby.png",
    name: "Ashby",
    slug: "ashby",
    url: "https://www.ashbyhq.com/",
  },
];
