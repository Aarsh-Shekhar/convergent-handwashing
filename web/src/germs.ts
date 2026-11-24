// What each germ character stands for. They are game characters tied to a part of the hand; the camera
// recognizes scrubbing motions, it does not see real germs. Facts are kept general and checkable.
import type { Zone } from "./api";

export const GERM_NAMES: Record<string, string> = {
  gunky: "Gunky", sneezel: "Sneezel", prickle: "Prickle", smudge: "Smudge", king_sneeze: "King Sneeze", king_gunk: "King Gunk",
  rainbow_sneezel: "Rainbow Sneezel", king_prickle: "King Prickle",
};
export const HIDES: Record<Zone, string> = {
  palms: "on palms", between_fingers: "between fingers", thumbs: "on thumbs", nails: "under nails and on fingertips", backs: "on the backs of hands", wrists: "on wrists",
};
export const WHY: Record<Zone, string> = {
  palms: "Palms touch almost everything we pick up, so they need soap first.",
  between_fingers: "The gaps between fingers stay dry and unwashed unless the fingers are laced together.",
  thumbs: "Thumbs are one of the most often missed parts in handwashing studies.",
  nails: "Dirt collects under and around fingernails, where a quick rinse does not reach.",
  backs: "We look at our palms when we wash, so the backs of the hands get forgotten.",
  wrists: "Wrists get wet and soapy last, and are easy to skip.",
};
export const RARITY: Record<string, string> = { common: "Common", rare: "Rare", legendary: "Legendary", boss: "Boss" };
