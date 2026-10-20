/** Brand presentation only. Unknown recordings retain their own names and initials. */
const clubs = {
  chelsea: { asset: "chelsea", theme: "chelsea" },
  manutd: { asset: "manutd", theme: "manutd" },
  "manchester-united": { asset: "manutd", theme: "manutd" },
};
export function clubBrand(team = {}) {
  return (
    clubs[team.id] || (team.name === "Manchester United" ? clubs.manutd : null)
  );
}
