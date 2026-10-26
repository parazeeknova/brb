#!/usr/bin/env -S node
import {
  Migration,
  MigrationCLI,
  col,
  fn,
  lit,
  primaryKey,
  sql,
} from "@prisma/orm-postgres/migration";

import type { Contract as End } from "../../snapshots/1ba3e5834e775bb666a1de762bae893e79a8c59f65aea2310bd291c4d3e626d3/contract";
import endContract from "../../snapshots/1ba3e5834e775bb666a1de762bae893e79a8c59f65aea2310bd291c4d3e626d3/contract.json" with { type: "json" };

export default class M extends Migration<never, End> {
  override readonly endContractJson = endContract;

  override get operations() {
    return [
      this.createSchema({ schema: "public" }),
      this.createTable({
        columns: [
          col("created_at", "timestamp", {
            codecRef: { codecId: "pg/timestamp-string@1" },
            default: fn(sql`now()`),
          }),
          col("direct_posting_verified", "bool", {
            codecRef: { codecId: "pg/bool@1" },
            default: lit(false),
          }),
          col("first_seen", "float8", {
            codecRef: { codecId: "pg/float8@1" },
            default: lit(0),
          }),
          col("freshness_lane", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("review"),
          }),
          col("last_seen", "float8", {
            codecRef: { codecId: "pg/float8@1" },
            default: lit(0),
          }),
          col("raw_json", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit({}),
          }),
          col("snippet", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("source", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
            notNull: true,
          }),
          col("title", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("url", "text", {
            codecRef: { codecId: "pg/text@1" },
            notNull: true,
          }),
          col("url_hash", "text", {
            codecRef: { codecId: "pg/text@1" },
            notNull: true,
          }),
          col("verification_method", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("verified", "bool", {
            codecRef: { codecId: "pg/bool@1" },
            default: lit(false),
          }),
        ],
        constraints: [
          primaryKey(["url_hash"], { name: "job_observations_pkey" }),
        ],
        schema: "public",
        table: "job_observations",
      }),
      this.createTable({
        columns: [
          col("company", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
            notNull: true,
          }),
          col("content_hash", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
            notNull: true,
          }),
          col("embedded_at", "timestamp", {
            codecRef: { codecId: "pg/timestamp-string@1" },
            default: fn(sql`now()`),
          }),
          col("title", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
            notNull: true,
          }),
          col("url_hash", "text", {
            codecRef: { codecId: "pg/text@1" },
            notNull: true,
          }),
        ],
        constraints: [
          primaryKey(["url_hash"], { name: "obs_embeddings_pkey" }),
        ],
        schema: "public",
        table: "obs_embeddings",
      }),
      this.createTable({
        columns: [
          col("canonical_id", "text", {
            codecRef: { codecId: "pg/text@1" },
            notNull: true,
          }),
          col("company_description", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("company_news", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("created_at", "timestamp", {
            codecRef: { codecId: "pg/timestamp-string@1" },
            default: fn(sql`now()`),
          }),
          col("direct_apply_url", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("eligibility", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("pending"),
          }),
          col("extra", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit({}),
          }),
          col("first_seen", "float8", {
            codecRef: { codecId: "pg/float8@1" },
            default: lit(0),
          }),
          col("founder_socials", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit([]),
          }),
          col("founders", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit([]),
          }),
          col("freshness_lane", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("review"),
          }),
          col("funding_info", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit({}),
          }),
          col("funding_stage", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("is_remote", "bool", {
            codecRef: { codecId: "pg/bool@1" },
            default: lit(false),
          }),
          col("jd_summary", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("last_seen", "float8", {
            codecRef: { codecId: "pg/float8@1" },
            default: lit(0),
          }),
          col("match_percent", "int4", {
            codecRef: { codecId: "pg/int4@1" },
            default: lit(0),
          }),
          col("matching_skills", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit([]),
          }),
          col("missing_skills", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit([]),
          }),
          col("normalized_company", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("normalized_location", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("Remote"),
          }),
          col("normalized_role", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("osint_signals", "jsonb", {
            codecRef: { codecId: "pg/jsonb@1" },
            default: lit([]),
          }),
          col("posted_date", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("rejection_detail", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("rejection_reason", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("role_family", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("unknown"),
          }),
          col("role_summary", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("salary_amount", "float4", {
            codecRef: { codecId: "pg/float4@1" },
          }),
          col("salary_currency", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("salary_period", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("salary_raw", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("shortlist_probability", "int4", {
            codecRef: { codecId: "pg/int4@1" },
            default: lit(0),
          }),
          col("source", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
            notNull: true,
          }),
          col("source_confidence", "float4", {
            codecRef: { codecId: "pg/float4@1" },
            default: lit(0.5),
          }),
          col("updated_at", "timestamp", {
            codecRef: { codecId: "pg/timestamp-string@1" },
            default: fn(sql`now()`),
          }),
          col("verdict", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("NO_MATCH"),
          }),
          col("verified", "bool", {
            codecRef: { codecId: "pg/bool@1" },
            default: lit(false),
          }),
        ],
        constraints: [
          primaryKey(["canonical_id"], { name: "radar_candidates_pkey" }),
        ],
        schema: "public",
        table: "radar_candidates",
      }),
      this.createTable({
        columns: [
          col("active", "bool", {
            codecRef: { codecId: "pg/bool@1" },
            default: lit(true),
          }),
          col("backoff_until", "float8", {
            codecRef: { codecId: "pg/float8@1" },
            default: lit(0),
          }),
          col("board_url", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("company_name", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("consecutive_empty", "int4", {
            codecRef: { codecId: "pg/int4@1" },
            default: lit(0),
          }),
          col("consecutive_failures", "int4", {
            codecRef: { codecId: "pg/int4@1" },
            default: lit(0),
          }),
          col("discovery_origin", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("last_change_at", "float8", {
            codecRef: { codecId: "pg/float8@1" },
            default: lit(0),
            notNull: true,
          }),
          col("last_polled", "float8", {
            codecRef: { codecId: "pg/float8@1" },
            default: lit(0),
          }),
          col("last_snapshot_count", "int4", {
            codecRef: { codecId: "pg/int4@1" },
            default: lit(0),
          }),
          col("last_snapshot_hash", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit(""),
          }),
          col("poll_lane", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("high"),
            notNull: true,
          }),
          col("quality_score", "float4", {
            codecRef: { codecId: "pg/float4@1" },
            default: lit(0.5),
          }),
          col("source_id", "text", {
            codecRef: { codecId: "pg/text@1" },
            notNull: true,
          }),
          col("source_type", "text", {
            codecRef: { codecId: "pg/text@1" },
            default: lit("unknown"),
            notNull: true,
          }),
          col("total_direct_url_rate", "float4", {
            codecRef: { codecId: "pg/float4@1" },
            default: lit(0),
          }),
          col("total_jobs_produced", "int4", {
            codecRef: { codecId: "pg/int4@1" },
            default: lit(0),
          }),
          col("updated_at", "timestamp", {
            codecRef: { codecId: "pg/timestamp-string@1" },
            default: fn(sql`now()`),
          }),
          col("yield_per_poll", "float4", {
            codecRef: { codecId: "pg/float4@1" },
            default: lit(0),
            notNull: true,
          }),
        ],
        constraints: [
          primaryKey(["source_id"], { name: "source_checkpoints_pkey" }),
        ],
        schema: "public",
        table: "source_checkpoints",
      }),
    ];
  }
}

MigrationCLI.run(import.meta.url, M);
