ALTER TABLE "trukvia"."payment_correction" ADD COLUMN "source_id" text;--> statement-breakpoint
ALTER TABLE "trukvia"."vendor" ADD COLUMN "source_id" text;--> statement-breakpoint
ALTER TABLE "trukvia"."vendor_bill" ADD COLUMN "source_id" text;--> statement-breakpoint
ALTER TABLE "trukvia"."vendor_payment" ADD COLUMN "source_id" text;