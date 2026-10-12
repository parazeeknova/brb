import "dotenv/config";
import { definePrismaConfig } from "@prisma/cli-engine";
import { defineConfig as ormConfig } from "@prisma/orm-postgres/config";

const connection = process.env["DATABASE_URL"];
if (!connection) {
  throw new Error("DATABASE_URL is not set");
}

export default definePrismaConfig({
  orm: ormConfig({
    contract: "./src/prisma/contract.prisma",
    db: {
      connection,
    },
  }),
});
