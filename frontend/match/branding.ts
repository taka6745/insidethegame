import type { Team, TeamBranding } from "./types.ts";

export interface ClubBrand {
  /** Crest file under /assets/league/clubs/, keyed by the MA1 crestAssetId. */
  crest: string | null;
  primary: string | null;
  secondary: string | null;
}
const COLOUR = /^#[0-9a-f]{6}$/i;
const ASSET = /^[a-z0-9][a-z0-9-]{0,63}$/;

/** Club presentation from the match data; nothing is keyed by club in the client. */
export function clubBrand(branding?: TeamBranding | null): ClubBrand | null {
  if (!branding) return null;
  const colour = (value: unknown) => typeof value === "string" && COLOUR.test(value) ? value : null;
  const asset = branding.crest_asset_id;
  const brand = {
    crest: typeof asset === "string" && ASSET.test(asset) ? `/assets/league/clubs/${asset}.svg` : null,
    primary: colour(branding.primary_colour),
    secondary: colour(branding.secondary_colour),
  };
  return brand.crest || brand.primary ? brand : null;
}

/** Snapshot teams may omit branding; the match listing carries it per team id. */
export function teamBranding(team: Team, known: readonly Team[] = []): TeamBranding | null {
  return team.branding ?? known.find((other) => other.id && other.id === team.id)?.branding ?? null;
}

/** Three-letter mark: the MA1 code, else the name's first letters. */
export function monogram(team: Team, fallback: string): string {
  return (team.code || team.short_name || team.name || fallback).slice(0, 3).toUpperCase();
}

/** Banner colours go through CSS custom properties (CSSOM, allowed by the strict CSP). */
export function applyBrand(element: HTMLElement, brand: ClubBrand | null) {
  element.dataset.club = brand?.primary ? "branded" : "unknown";
  for (const [name, value] of [["--club-primary", brand?.primary], ["--club-secondary", brand?.secondary ?? brand?.primary]] as const)
    if (value) element.style.setProperty(name, value);
    else element.style.removeProperty(name);
}
