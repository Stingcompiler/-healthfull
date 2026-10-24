/*
 * One family (Design Reference 2.2 section 2, docs/DECISIONS.md D-0008): IBM Plex Sans Arabic
 * draws Arabic and IBM Plex Sans draws Latin letters and digits. Bundled from @fontsource
 * packages: no CDN, no Google Fonts. Only the arabic subset of the Arabic family is loaded so
 * Latin text always comes from IBM Plex Sans, and each @font-face carries a unicode-range, so
 * the browser only downloads the files a page actually uses. The stack is --font-ui in
 * tokens.css (generated from tokens/base.tokens.json).
 */
import "@fontsource/ibm-plex-sans-arabic/arabic-400.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-500.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-600.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-700.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/latin-700.css";
import "@fontsource/ibm-plex-sans/latin-ext-400.css";
import "@fontsource/ibm-plex-sans/latin-ext-500.css";
import "@fontsource/ibm-plex-sans/latin-ext-600.css";
import "@fontsource/ibm-plex-sans/latin-ext-700.css";
