/** Proposed launch allowances. Billing and credit enforcement are not live yet. */
export const BILLING_PROVIDER = "Dodo Payments";
export const AUTOFILL_MINUTES_PER_CREDIT = 5;
export const AUTOFILL_TOP_UP = { credits: 10, priceUsd: 5 };

export const SEARCH_PLAN = {
  autofillCredits: 30,
  chatMessages: 300,
  description: "For a focused, active job search.",
  documentPacks: 60,
  id: "search",
  matchFrequency: "Daily job matches",
  name: "Search",
  priceUsd: 19,
  recommended: true,
} as const;

export const PRICING_PLANS = [
  {
    autofillCredits: 0,
    chatMessages: 10,
    description: "Get your bearings and apply at your own pace.",
    documentPacks: 2,
    id: "explore",
    matchFrequency: "Daily job matches",
    name: "Explore",
    priceUsd: 0,
    recommended: false,
  },
  {
    autofillCredits: 10,
    chatMessages: 100,
    description: "For internships, first jobs and smaller budgets.",
    documentPacks: 20,
    id: "starter",
    matchFrequency: "Daily job matches",
    name: "Starter",
    priceUsd: 7,
    recommended: false,
  },
  SEARCH_PLAN,
  {
    autofillCredits: 60,
    chatMessages: 750,
    description: "More room for an ambitious career move.",
    documentPacks: 150,
    id: "career",
    matchFrequency: "Daily job matches",
    name: "Career",
    priceUsd: 39,
    recommended: false,
  },
] as const;
