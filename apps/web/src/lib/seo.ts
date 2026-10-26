export const SITE_URL = "https://jobs.amemorymachine.cc";
export const SHARE_IMAGE = "https://img.przknv.cc/t/brb_github_banner.png";

export function pageSeo(title: string, description: string, path = "/") {
  const url = `${SITE_URL}${path}`;
  return {
    links: [{ href: url, rel: "canonical" }],
    meta: [
      { title },
      { content: description, name: "description" },
      { content: "index,follow,max-image-preview:large", name: "robots" },
      { content: "BRB", property: "og:site_name" },
      { content: "website", property: "og:type" },
      { content: "en_US", property: "og:locale" },
      { content: title, property: "og:title" },
      { content: description, property: "og:description" },
      { content: url, property: "og:url" },
      { content: SHARE_IMAGE, property: "og:image" },
      { content: "BRB — a job search that learns", property: "og:image:alt" },
      { content: "1852", property: "og:image:width" },
      { content: "849", property: "og:image:height" },
      { content: "summary_large_image", name: "twitter:card" },
      { content: title, name: "twitter:title" },
      { content: description, name: "twitter:description" },
      { content: SHARE_IMAGE, name: "twitter:image" },
      { content: "BRB — a job search that learns", name: "twitter:image:alt" },
    ],
  };
}

export function structuredData(value: unknown) {
  return {
    children: JSON.stringify(value).replaceAll("<", "\\u003c"),
    type: "application/ld+json",
  };
}
