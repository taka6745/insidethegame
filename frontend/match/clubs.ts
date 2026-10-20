import type { Team } from "./types.ts";

export interface ClubBrand {
  asset: string;
  theme: string;
}
/** Brand presentation only. Unknown recordings retain their own names and initials. */
const clubs = {
  chelsea: { asset: "chelsea", theme: "chelsea" },
  manutd: { asset: "manutd", theme: "manutd" },
  "manchester-united": { asset: "manutd", theme: "manutd" },
} satisfies Record<string, ClubBrand>;
const byId: Partial<Record<string, ClubBrand>> = clubs;
export function clubBrand(team: Team = {}): ClubBrand | null {
  return (
    byId[String(team.id)] || (team.name === "Manchester United" ? clubs.manutd : null)
  );
}
