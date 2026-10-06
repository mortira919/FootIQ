---
version: 1
slug: "backend-app-site-index-html"
primary_target: "backend/app/site/index.html"
related_targets: ["backend/app/site/privacy.html","backend/app/site/terms.html","backend/app/site/delete.html","backend/app/site/league.html"]
---

# Surface: FootIQ site (landing + legal)

Scope: `/` landing (Persuade), `/privacy`, `/terms`, `/delete`, `/l/<code>` (Read). Audience: footballers deciding to install; store reviewers checking legal pages. Action: install from Google Play (`com.footiq.footiq`); App Store not live. Proof: the app's own 10 role scenes, lessons and rendered clips. No invented users, reviews or numbers.

## Direction contract

THESIS: The page is a team sheet. The 10-role formation on a pitch is the interface: pick your position, see your scene. Refuses the split hero with a phone mockup over three feature cards.

OWN-WORLD: Near-black #060A08 ground, a mown pitch in deep green with chalk-white 1.5px markings, player markers as round discs with mono codes (GK, CB, RB). Green #00855C for action, #30D158 for live text, gold #FFD60A only for «Золото» and PRO. Inter for words, JetBrains Mono for codes, ratings, seconds, prices. Radius 14px surfaces, round markers, pill buttons.

STORY: Visitor finds their position, watches its scene and reads the lesson, learns the server judges with the same geometry the app draws, sees modes, rank ladder, leagues, PRO, installs.

FIRST VIEWPORT: Desktop: left 5/12 wordmark, two-line H1, one sentence, Google Play button. Right 7/12 vertical pitch with all markers, selected marker ringed; scene card (role, scene title, looping clip, lesson) docked under the headline column. Mobile: H1, pitch full width, scene card below, button sticky in reach.

FORM: team sheet, position 2 of 7 on my list, seed 4ebd79ab. Signature interaction: tapping a marker moves the ring and swaps the clip with a 200ms blur cross-fade.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
