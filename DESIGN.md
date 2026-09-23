# Tennisd design guide

## Product idea

Tennisd is a **courtside diary**: a place to remember professional tennis matches you watched. The central object is a *match*, not a player news article or live score. A member can log one viewing of a match, rate it in half-star steps, write a review, mark it as a favorite, choose public/private visibility and discuss public reviews. Player pages provide context for the match archive.

## Navigation and information hierarchy

| Page | Primary question | Main action |
| --- | --- | --- |
| Discover | What should I explore? | Open a match |
| Matches | Can I find a particular match? | Search/filter |
| Match | What happened, and what did people think? | Log the match |
| Players | Who played, and what is their record here? | Open/follow player |
| My diary | What tennis have I watched? | Review entries |
| Settings | How do I appear to others? | Edit profile |
| About | Where do these numbers come from? | Inspect sources |

The header stays short: brand, Discover, Matches, Players, and account access. No extra menus until there is a real user need. Search is on the directory pages where filters make sense.

## Visual direction

Think **old grass courts, scoreboards and editorial sports print**, expressed in a clean current web interface. It should feel like tennis without using racket clip art or stock photos. The pages are dense enough to reward exploration, but the match outcome remains legible at a glance.

- Deep court green `#0b1916` for the canvas; a warmer green `#162b25` for cards.
- Warm paper white `#f4f2e8` for primary text and a muted sage `#a4b8a9` for secondary text.
- Tennis-ball lime `#d6ed80` appears on selected navigation, winning markers, links, ratings and the main action. It is an accent, not a full-page gradient.
- ATP and WTA use small differently colored badges. These are labels, not the sole way to identify tours.
- Oswald gives compact scoreboard and magazine-style headings; DM Sans keeps forms and body copy comfortable. System fallbacks remain usable if font loading fails.
- Dividers and rectangular cards recall a court's lines and a printed score sheet. Rounded corners are restrained.

## Component rules

- **Match card:** tour, year, surface, event, round, winner, opponent, score and a clear link target. The winner gets a lime marker. Full card is clickable.
- **Scoreboard:** both player names have profile links; score, event and tournament-week date are prominent. The match date is intentionally not fabricated.
- **Stats:** raw counts and percentages are labeled. A dash means the source did not include a value. Bars support comparison but numerical values are always shown too.
- **Review:** author, viewing date, rating and text. Spoilers are collapsed by default. Comments appear directly below the review.
- **Diary entry:** the watched-on date is distinct from tournament week. Private entries appear only to the owner.
- **Watchlist:** an owner-only shelf for matches to watch or revisit; logging one removes it from the shelf.
- **Player page:** imported win/loss record, surfaces, seasons, opponents, titles and prize money each state the scope or source of their number.
- **Empty state:** tells the visitor what is missing and where to go next. No fake activity or ratings are seeded.

## Accessibility and small screens

All actions are links or real buttons; fields have labels; focus indicators are visible. Contrast is high in dark mode. The skip link jumps over navigation. At tablet widths the archive moves below its filters; at phone widths match and player cards become one column, match names stack, and scoreboard comparisons remain readable. Spoiler content requires deliberate disclosure.

## Trust rules

The visual design must never imply live scores. Historical coverage and the provenance of prize money are stated where the figures appear. Reviews are member opinions; match results come from the attributed data source. A user can keep a diary entry private. Forms use CSRF protection and passwords are hashed.

## Later iterations

The next release could add custom lists, follow other members, notification preferences and player comparison. Public launch should wait for verified email, account recovery, moderation, backups and persistent abuse limits. These features are left out of the first release so the core diary stays coherent and maintainable.
