# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML/CSS served by the existing FastAPI backend on Fly.io (`backend/app/site/`). No build step.

## Users

Footballers, mostly amateurs and youth players, who want to read the game better from their own position. The site also serves Google Play and App Store reviewers, who check that privacy, terms and account deletion pages exist and say the right things.

## Product Purpose

FootIQ is a mobile app (Flutter, Android and iOS) that trains football decision-making. The player picks a position, solves tactical scenes on a pitch, and earns a chess-style rating, overall and per position.

## Positioning

The server judges every move with the same geometry the app draws, so the rating cannot be farmed from the client. Scenes are built per position (10 roles), not generic quizzes.

## Operating Context

- Modes: «Тактический полигон» (place the pass/run on the pitch), «Реакция» (rush, 7 seconds per decision, 3 lives), video review with a typed explanation scored out of 10 (currently only for DM, scored by a keyword rubric, no LLM).
- Rating: Glicko-2, overall and per position, leaderboards, private leagues joined by code (`amplua.app/l/<code>`).
- Sign-in with Google or Apple only. No passwords.
- PRO subscription: $4.99/month or $29.99/year (shown in dollars on the site), removes daily limits (free: 2 rush runs, 1 video review per day), unlocks coach personas, lets the player change position without the 30-day wait.

## Capabilities and Constraints

- Data stored: Google/Apple account ID, email, display name, chosen position and region, attempts (scene, action, coordinates, outcome, rating change, time), ratings, league membership, typed video-review answers, subscription status, session tokens, time zone offset.
- Account deletion in the app removes all of it at once (`DELETE /v1/me`). Fly.io daily volume snapshots keep copies for up to 5 days.
- No analytics, no ads, no crash reporting SDKs in the client.
- Domain: `amplua.app` (not bought yet; `footiq.app` is taken). Until then the site lives on `footiq.fly.dev`. Store links do not exist yet.

## Brand Commitments

- Name: Amplua (renamed from FootIQ on 2026-10-06; Play package id stays `com.footiq.footiq`). Operator in legal pages: «Команда Amplua» (no legal entity yet).
- Contact email: placeholder Gmail, replace before publishing.
- Mark: `assets/mark.svg` (green pitch, gold penalty-box line). App theme: near-black base, green `#00855C`, gold for medals, Inter + JetBrains Mono.
- Voice: Russian, informal «ты», short and concrete, the way a coach talks.

## Evidence on Hand

No users, reviews, press or download numbers yet. Do not invent any.

## Product Principles

1. The rating means something because the server judges it.
2. Train from your own position.
3. Collect only what the game needs.
