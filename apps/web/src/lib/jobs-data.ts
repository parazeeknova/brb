import { HERO_JOBS } from "./hero-jobs";

export interface Job {
  id: string;
  company: string;
  hue: number;
  illustrative?: boolean;
  logo?: string;
  logoDark?: string;
  title: string;
  posted: string;
  location: string;
  type: string;
  description: string;
  source: string;
  fit: boolean;
  advice: string;
  url: string;
  tags: string[];
}

export const CATEGORIES = [
  "All",
  "Remote",
  "Internships",
  "Full-time",
  "AI/ML",
  "Frontend",
  "Backend",
  "Startups",
  "Design",
];

export const JOBS: Job[] = HERO_JOBS;
