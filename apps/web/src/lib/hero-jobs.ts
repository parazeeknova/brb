import type { Job } from "./jobs-data";

// Employer-owned job boards, checked 2026-10-26. Fit notes use an example profile.
export const HERO_JOBS: Job[] = [
  {
    advice:
      "Example fit: production experience with Kafka, Spark or Iceberg would be relevant. Check the full requirements before applying.",
    company: "OpenAI",
    description:
      "Build data platforms and streaming systems that support AI research, products and analytics.",
    fit: true,
    hue: 145,
    id: "openai-data-infrastructure",
    illustrative: true,
    location: "San Francisco · Hybrid",
    logo: "/company-logos/openai.svg",
    logoDark: "/company-logos/openai-dark.svg",
    posted: "Checked Oct 26",
    source: "Ashby",
    tags: ["Full-time", "Backend", "AI/ML"],
    title: "Software Engineer, Data Infrastructure",
    type: "Full-time",
    url: "https://jobs.ashbyhq.com/openai/f763c6b3-5167-4a67-b691-4c3fa2c44156",
  },
  {
    advice:
      "Example fit: a senior full-stack portfolio could align. Review the team's product ownership and experience expectations.",
    company: "Anthropic",
    description:
      "Own product experiences across Claude, developer tools and enterprise applications, working across the stack.",
    fit: true,
    hue: 35,
    id: "anthropic-fullstack",
    illustrative: true,
    location: "San Francisco · NYC · Seattle",
    logo: "/company-logos/anthropic.svg",
    logoDark: "/company-logos/anthropic-dark.svg",
    posted: "Checked Oct 26",
    source: "Greenhouse",
    tags: ["Full-time", "Frontend", "Backend", "AI/ML"],
    title: "Senior Software Engineer, Full-stack",
    type: "Full-time",
    url: "https://job-boards.greenhouse.io/anthropic/jobs/5174743008",
  },
  {
    advice:
      "Example fit: operating logging, metrics or tracing systems could translate well. Read the role's systems requirements first.",
    company: "OpenAI",
    description:
      "Develop observability infrastructure and tools that help engineers investigate and improve production systems.",
    fit: true,
    hue: 145,
    id: "openai-observability",
    illustrative: true,
    location: "San Francisco",
    logo: "/company-logos/openai.svg",
    logoDark: "/company-logos/openai-dark.svg",
    posted: "Checked Oct 26",
    source: "Ashby",
    tags: ["Full-time", "Backend", "AI/ML"],
    title: "Software Engineer, Observability",
    type: "Full-time",
    url: "https://jobs.ashbyhq.com/openai/d4dcd344-40cf-44d6-a7dd-172118eb0842",
  },
  {
    advice:
      "Example review: this is a senior technical leadership role. An early-career profile would need substantially more experience.",
    company: "Anthropic",
    description:
      "Lead evaluation frameworks, research infrastructure and engineering tools for the Claude Code team.",
    fit: false,
    hue: 35,
    id: "anthropic-model-performance",
    illustrative: true,
    location: "San Francisco · New York City",
    logo: "/company-logos/anthropic.svg",
    logoDark: "/company-logos/anthropic-dark.svg",
    posted: "Checked Oct 26",
    source: "Greenhouse",
    tags: ["Full-time", "AI/ML", "Backend"],
    title: "Model Performance Software Engineer, Claude Code",
    type: "Full-time",
    url: "https://job-boards.greenhouse.io/anthropic/jobs/5098025008",
  },
];
