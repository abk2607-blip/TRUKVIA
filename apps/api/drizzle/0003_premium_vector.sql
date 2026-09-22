ALTER TABLE "trukvia"."payment_correction" ALTER COLUMN "before" SET DATA TYPE json;--> statement-breakpoint
ALTER TABLE "trukvia"."payment_correction" ALTER COLUMN "after" SET DATA TYPE json;--> statement-breakpoint
ALTER TABLE "trukvia"."payment_correction" ALTER COLUMN "diff" SET DATA TYPE json;--> statement-breakpoint
ALTER TABLE "trukvia"."vendor_payment" ALTER COLUMN "bank_snapshot" SET DATA TYPE json;--> statement-breakpoint
ALTER TABLE "trukvia"."vendor_payment" ALTER COLUMN "source_bank_snapshot" SET DATA TYPE json;