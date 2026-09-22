CREATE TABLE IF NOT EXISTS "trukvia"."fin_account" (
	"id" text PRIMARY KEY NOT NULL,
	"mongo_id" text,
	"user_id" text NOT NULL,
	"company_id" text NOT NULL,
	"code" text NOT NULL,
	"name" text,
	"type" text,
	"is_system" boolean,
	"is_active" boolean,
	"remarks" text,
	"created_at" text
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "trukvia"."fin_day_closure" (
	"id" text PRIMARY KEY NOT NULL,
	"mongo_id" text,
	"user_id" text NOT NULL,
	"company_id" text NOT NULL,
	"close_date" text NOT NULL,
	"status" text,
	"closed_at" text,
	"closed_by" text,
	"close_notes" text,
	"snapshot" json,
	"snapshot_source_count" integer,
	"reopened_at" text,
	"reopened_by" text,
	"reopen_reason" text,
	"history" json,
	"created_at" text,
	"modified_at" text
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "trukvia"."fin_txn" (
	"id" text PRIMARY KEY NOT NULL,
	"mongo_id" text,
	"user_id" text NOT NULL,
	"company_id" text NOT NULL,
	"ref_source_key" text,
	"account_code" text,
	"account_id" text,
	"adjustment_group_id" text,
	"amount" numeric(14, 2),
	"category" text,
	"counter_account_code" text,
	"counter_account_id" text,
	"created_at" text,
	"direction" text,
	"is_reversal" boolean,
	"is_supplier_settlement_recovery" boolean,
	"narration" text,
	"party_id" text,
	"party_name" text,
	"party_type" text,
	"projected_at" text,
	"reconciled_at" text,
	"reconciled_ref" text,
	"reversal_of" text,
	"source_id" text,
	"source_key" text,
	"source_type" text,
	"status" text,
	"transfer_group_id" text,
	"trip_id" text,
	"txn_date" text,
	"txn_type" text,
	"vehicle_id" text,
	"source_shape" jsonb
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "fin_account_scope_code" ON "trukvia"."fin_account" USING btree ("user_id","company_id","code");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "fin_day_closure_scope_date" ON "trukvia"."fin_day_closure" USING btree ("user_id","company_id","close_date");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "fin_txn_scope_date" ON "trukvia"."fin_txn" USING btree ("user_id","company_id","txn_date");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "fin_txn_account_code" ON "trukvia"."fin_txn" USING btree ("account_code");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "fin_txn_source" ON "trukvia"."fin_txn" USING btree ("source_type","source_id");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "fin_txn_ref_source_key" ON "trukvia"."fin_txn" USING btree ("ref_source_key");