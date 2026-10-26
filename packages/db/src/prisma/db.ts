import "dotenv/config";
import postgres from "@prisma/orm-postgres/runtime";
import { contractFromJson } from "@prisma/orm-postgres/static";

import type { Contract } from "./contract.d";
import contractJson from "./contract.json" with { type: "json" };

const url = process.env["DATABASE_URL"];
if (!url) {
  throw new Error("DATABASE_URL is not set");
}

export const db = postgres<Contract>({
  contract: contractFromJson<Contract>(contractJson),
  url,
});
