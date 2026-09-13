/**
 * TRUKVIA · TelematicsPort — GPS / geofence / trip trail.
 * Providers: Loconav, TrackoBit, Fleetx, OEM-native.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result, ExternalRef } from "./common";

export interface LiveLocation {
  readonly vehicle_id: string;
  readonly lat: number;
  readonly lon: number;
  readonly speed_kmh?: number;
  readonly heading_deg?: number;
  readonly ignition?: boolean;
  readonly captured_at: string;              // ISO-8601
  readonly external_ref?: ExternalRef;
}

export interface TripTrailPoint {
  readonly lat: number;
  readonly lon: number;
  readonly speed_kmh?: number;
  readonly captured_at: string;
}

export interface GeofenceEvent {
  readonly vehicle_id: string;
  readonly geofence_id: string;
  readonly kind: "enter" | "exit";
  readonly at: string;
}

export interface TelematicsPort {
  currentLocation(vehicle_id: string, ctx: IntegrationContext): Promise<Result<LiveLocation>>;
  tripTrail(
    vehicle_id: string,
    from: string,
    to: string,
    ctx: IntegrationContext,
  ): Promise<Result<{ points: readonly TripTrailPoint[] }>>;
  geofenceEvents(
    vehicle_id: string,
    geofence_id: string,
    from: string,
    to: string,
    ctx: IntegrationContext,
  ): Promise<Result<{ events: readonly GeofenceEvent[] }>>;
}

/** Push-mode: provider webhooks land at a normalised endpoint; the hub
 *  translates provider payloads into `GeofenceEvent` / `LiveLocation`
 *  shapes above before invoking any downstream domain listener. */
