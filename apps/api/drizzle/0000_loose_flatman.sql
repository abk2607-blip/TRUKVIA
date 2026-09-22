CREATE SCHEMA "trukvia";
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "trukvia"."payment_correction" (
	"id" text PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"company_id" text NOT NULL,
	"payment_type" text NOT NULL,
	"payment_id" text NOT NULL,
	"correction_index" integer NOT NULL,
	"kind" text DEFAULT '' NOT NULL,
	"correction_reason" text DEFAULT '' NOT NULL,
	"before" jsonb,
	"after" jsonb,
	"diff" jsonb,
	"linked_reversal_id" text,
	"linked_new_id" text,
	"force_reconciled_override" boolean,
	"corrected_by" text DEFAULT '' NOT NULL,
	"corrected_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "trukvia"."vendor" (
	"id" text PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"company_id" text NOT NULL,
	"name" text NOT NULL,
	"contact_person" text DEFAULT '' NOT NULL,
	"mobile" text DEFAULT '' NOT NULL,
	"alt_mobile" text DEFAULT '' NOT NULL,
	"address" text DEFAULT '' NOT NULL,
	"state" text DEFAULT '' NOT NULL,
	"city" text DEFAULT '' NOT NULL,
	"gst_in" text DEFAULT '' NOT NULL,
	"pan" text DEFAULT '' NOT NULL,
	"msme_number" text DEFAULT '' NOT NULL,
	"bank_name" text DEFAULT '' NOT NULL,
	"account_number" text DEFAULT '' NOT NULL,
	"ifsc" text DEFAULT '' NOT NULL,
	"branch" text DEFAULT '' NOT NULL,
	"payment_terms" text DEFAULT '' NOT NULL,
	"opening_balance" numeric(14, 2) DEFAULT '0' NOT NULL,
	"opening_balance_type" text DEFAULT 'payable' NOT NULL,
	"remarks" text DEFAULT '' NOT NULL,
	"is_active" boolean DEFAULT true NOT NULL,
	"is_historical" boolean DEFAULT false NOT NULL,
	"imported_from" text DEFAULT '' NOT NULL,
	"imported_ref" text DEFAULT '' NOT NULL,
	"imported_batch" text DEFAULT '' NOT NULL,
	"created_by" text DEFAULT '' NOT NULL,
	"created_at" timestamp with time zone,
	"modified_by" text DEFAULT '' NOT NULL,
	"modified_at" timestamp with time zone,
	"deactivated_by" text DEFAULT '' NOT NULL,
	"deactivated_at" timestamp with time zone,
	"deactivation_reason" text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "trukvia"."vendor_bill" (
	"id" text PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"company_id" text NOT NULL,
	"vendor_id" text NOT NULL,
	"vendor_name" text DEFAULT '' NOT NULL,
	"bill_number" text DEFAULT '' NOT NULL,
	"bill_date" date,
	"bill_amount" numeric(14, 2) DEFAULT '0' NOT NULL,
	"vehicle_id" text DEFAULT '' NOT NULL,
	"vehicle_number" text DEFAULT '' NOT NULL,
	"trip_id" text DEFAULT '' NOT NULL,
	"repair_event_id" text DEFAULT '' NOT NULL,
	"narration" text DEFAULT '' NOT NULL,
	"remarks" text DEFAULT '' NOT NULL,
	"file_ids" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"is_deleted" boolean DEFAULT false NOT NULL,
	"deleted_by" text DEFAULT '' NOT NULL,
	"deleted_at" timestamp with time zone,
	"deletion_reason" text DEFAULT '' NOT NULL,
	"created_by" text DEFAULT '' NOT NULL,
	"created_at" timestamp with time zone,
	"modified_by" text DEFAULT '' NOT NULL,
	"modified_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "trukvia"."vendor_payment" (
	"id" text PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"company_id" text NOT NULL,
	"vendor_id" text NOT NULL,
	"vendor_bill_id" text DEFAULT '' NOT NULL,
	"payment_date" date,
	"amount" numeric(14, 2) DEFAULT '0' NOT NULL,
	"type" text DEFAULT '' NOT NULL,
	"mode" text DEFAULT '' NOT NULL,
	"account_id" text DEFAULT '' NOT NULL,
	"ref_no" text DEFAULT '' NOT NULL,
	"against" text DEFAULT '' NOT NULL,
	"remarks" text DEFAULT '' NOT NULL,
	"file_ids" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"corrected_by" text,
	"corrected_at" timestamp with time zone,
	"correction_count" integer,
	"latest_correction_id" text,
	"is_reversed" boolean,
	"reversed_by" text,
	"reversed_at" timestamp with time zone,
	"reversal_reason" text,
	"reversal_of" text,
	"reconciled_at" date,
	"reconciled_ref" text,
	"bank_account_id" text,
	"bank_snapshot" jsonb,
	"company_bank_account_id" text,
	"source_bank_snapshot" jsonb,
	"is_deleted" boolean DEFAULT false NOT NULL,
	"deleted_by" text DEFAULT '' NOT NULL,
	"deleted_at" timestamp with time zone,
	"deletion_reason" text DEFAULT '' NOT NULL,
	"created_by" text DEFAULT '' NOT NULL,
	"created_at" timestamp with time zone,
	"modified_by" text DEFAULT '' NOT NULL,
	"modified_at" timestamp with time zone
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "pcr_scope_payment_index" ON "trukvia"."payment_correction" USING btree ("user_id","company_id","payment_type","payment_id","correction_index");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_scope_name" ON "trukvia"."vendor" USING btree ("user_id","company_id","name");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_bill_scope_date" ON "trukvia"."vendor_bill" USING btree ("user_id","company_id","bill_date");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_bill_vendor" ON "trukvia"."vendor_bill" USING btree ("vendor_id");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_bill_vehicle" ON "trukvia"."vendor_bill" USING btree ("vehicle_id");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_bill_repair" ON "trukvia"."vendor_bill" USING btree ("repair_event_id");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_payment_scope_date" ON "trukvia"."vendor_payment" USING btree ("user_id","company_id","payment_date");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_payment_vendor" ON "trukvia"."vendor_payment" USING btree ("vendor_id");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_payment_bill" ON "trukvia"."vendor_payment" USING btree ("vendor_bill_id");--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "vendor_payment_reversal_of" ON "trukvia"."vendor_payment" USING btree ("reversal_of");