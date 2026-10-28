/** Words that name a kind of place or a title, not the person or center ("Dr.", "مركز"). */
const GENERIC = new Set([
  "dr",
  "prof",
  "the",
  "center",
  "centre",
  "medical",
  "clinic",
  "clinics",
  "hospital",
  "د",
  "دكتور",
  "الدكتور",
  "دكتورة",
  "الدكتورة",
  "بروف",
  "مركز",
  "المركز",
  "عيادة",
  "عيادات",
  "مستشفى",
  "الطبي",
  "الطبية",
]);

const ZWNJ = "‌";

function bare(word: string): string {
  return word.replace(/[.,،()"'«»]/gu, "");
}

/**
 * One or two letters standing for a name, for avatars and the center monogram: the first letters
 * of the first two meaningful words ("Dr. Amal Hassan" is "AH", "مركز النور الطبي" is "ن").
 * Titles and generic place words are skipped; Arabic letters are kept apart (a ZWNJ between
 * them) so they never join into a stray word. An empty name gives "".
 */
export function initialsOf(name: string, max = 2): string {
  const words = name
    .trim()
    .split(/\s+/u)
    .map(bare)
    .filter((w) => w.length > 0);
  const meaningful = words.filter((w) => !GENERIC.has(w.toLowerCase()));
  const pool = meaningful.length > 0 ? meaningful : words;
  const letters = pool
    .slice(0, max)
    .map((w) => {
      // Arabic definite article: "النور" stands for "ن".
      const stem = /^ال.{2,}/u.test(w) ? w.slice(2) : w;
      const first = stem.codePointAt(0);
      return first === undefined ? "" : String.fromCodePoint(first).toLocaleUpperCase();
    })
    .filter(Boolean);
  return letters.join(ZWNJ);
}
