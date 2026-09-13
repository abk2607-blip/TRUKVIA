/**
 * TRUKVIA · SchedulerPort — cron + delayed job execution.
 * Providers: `.emergent/crons.yml` (preferred, platform-durable),
 * BullMQ + Redis (in-cluster), APScheduler (current Python-only).
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result } from "./common";

export interface CronScheduleRequest {
  readonly name: string;                    // unique per tenant
  readonly cron_expr: string;               // "0 18 * * *" IST etc.
  readonly handler_ref: string;             // stable handler id resolved in-process
  readonly enabled: boolean;
}
export interface CronScheduleResult {
  readonly job_ref: string;
}

export interface EnqueueRequest {
  readonly name: string;
  readonly run_at?: string;                 // ISO-8601 UTC; if absent → run ASAP
  readonly payload: Readonly<Record<string, unknown>>;
  readonly idempotency_key: string;
}
export interface EnqueueResult {
  readonly job_ref: string;
  readonly scheduled_at: string;
}

export interface SchedulerPort {
  schedule(req: CronScheduleRequest, ctx: IntegrationContext): Promise<Result<CronScheduleResult>>;
  enqueue(req: EnqueueRequest, ctx: IntegrationContext): Promise<Result<EnqueueResult>>;
  cancel(job_ref: string, ctx: IntegrationContext): Promise<Result<{ cancelled: true }>>;
}

/**
 * Distributed-lock guarantee: no cron handler runs twice concurrently
 * across replicas. APScheduler (in-process only) does NOT satisfy this;
 * .emergent/crons.yml or BullMQ+Redis MUST be used before scaling beyond
 * one Node worker.
 */
