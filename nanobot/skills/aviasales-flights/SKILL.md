---
name: aviasales-flights
description: "Search flight prices via the Aviasales (Travelpayouts) Data API and return an indicative price plus a live-search link to aviasales.ru. TRIGGER when: user asks about flight prices, wants to fly somewhere, asks 'how much from X to Y', mentions a budget for flights, asks when it's cheaper to fly, or wants to discover cheap directions from a city — even if Aviasales is not mentioned by name."
---

# Aviasales Flights Skill

Help the user explore flight prices and direct them to a live aviasales.ru search. The agent never sells tickets and never claims a price is final — every answer must include both an indicative price ("от X₽" / "около X₽") and the aviasales.ru link returned by the tool.

## What the data is

The Aviasales Data API serves a cache of real searches from the last 48 hours (kept up to 7 days). Popular routes have very fresh data; niche routes may have nothing or shifted dates. Always frame results as indicative and historical, never as bookable prices.

## Tools

- `aviasales_search_dates` — main search by route and dates. Default for any concrete query.
- `aviasales_grouped_prices` — when is it cheaper (group by day or month).
- `aviasales_week_matrix` — flexible dates ±3/4 days.
- `aviasales_price_range` — search within a budget.

All tools accept either a 3-letter IATA code (`MOW`, `DXB`) or a city name in Russian or English (`Москва`, `Dubai`). Dates are `YYYY-MM` or `YYYY-MM-DD`. Today's date is in your system context — convert any natural-language date ("в июле", "на следующих выходных", "послезавтра") into one of those two formats before calling.

## Method selection

### `aviasales_search_dates`
Call when the user:
- Names a concrete route ("from Moscow to Dubai")
- Names at least an approximate date or month
- Asks "how much does it cost to fly to X"
- Wants to find cheap directions from a city without a fixed destination → omit `destination`, set `unique=true`
- Wants direct flights only → set `direct=true`

This is your default. When in doubt, call this.

### `aviasales_grouped_prices`
Call when the user:
- Hasn't picked dates and wants to know when it's cheaper ("when is it cheapest to fly to Barcelona")
- Asks about a whole month or season → `group_by=month`
- Wants the price spread by day → `group_by=departure_at`
- Is flexible and wants the optimal moment

Don't call when a specific date is already given — `aviasales_search_dates` handles that.

### `aviasales_week_matrix`
Call when the user:
- Names an approximate date but is willing to shift by a few days ("around the 15th", "±a couple of days")
- Explicitly says dates are flexible and wants the cheapest within a ±3/4 day window
- Already has a price from `aviasales_search_dates` and asks "is it cheaper on neighboring days"

Pair with `aviasales_search_dates` (parallel calls in one response) whenever the user signals date flexibility.

### `aviasales_price_range`
Call when the user:
- States a budget ("up to 10000₽", "no more than 15k", "within 20k")
- Asks what's available for a given amount

If the user gave both a budget and a route, prefer this tool over `aviasales_search_dates` — the budget is the primary filter.

## Round-trip handling

For round trips (`return_at` provided, `one_way=false`) `aviasales_search_dates` automatically fires three parallel requests internally and returns `{round_trip, outbound, inbound}`. Show the user every variant that came back; do not hide options:

- Only `round_trip` populated → show that.
- Only `outbound` + `inbound` populated → show their sum and clearly say these are two separate bookings, with two separate links.
- Both populated → show both honestly: "Two options: round-trip from ~28 000₽ as one booking, or two separate flights summing to ~24 500₽ — would need to be booked separately." Let the user choose.

## Cities, names, and ambiguity

The tools resolve city names automatically. If a name has multiple equally-likely matches (e.g. "Springfield"), the tool returns an error listing the candidates. Ask the user which one they meant and pass the IATA code in your retry. If the tool resolved a name on its own (one clear match or one obvious dominant), accept the result — don't second-guess.

## Discovery queries ("somewhere in Europe", "to the sea")

When the user wants ideas without naming a destination, call `aviasales_search_dates` without `destination` and with `unique=true`. The tool returns cheap directions from the origin. Filter the result on your side by IATA codes that match what they asked for (European capitals, beach destinations, warm climate, etc.) using your own geographic knowledge.

## Mandatory phrasing rules

- **Indicative price only.** Always "от X₽" or "около X₽" — never call a price exact, current, or bookable.
- **Always include the link.** Every recommendation ends with the `link` field returned by the tool — it is the full `https://www.aviasales.ru/...` URL with route and dates pre-filled.
- **`is_expired` flag.** Each ticket comes with `is_expired`. If `true`, phrase as "the last known price was ~X₽, but the data is stale — see the link for live pricing." If `false`, "ticket from ~X₽."
- **Empty result is not 'no tickets'.** If the tool returns no tickets, say "I couldn't find cached data for this route on these dates" and offer the live aviasales.ru search link directly.

## Clarification policy

Ask only when the missing detail materially changes the search:
- No origin city
- No destination AND no "find me anything" framing
- Genuinely ambiguous city name (the tool returned a list of candidates)

Do not ask when:
- Dates are missing — pass without `departure_at` (the API will return what it has) or use `aviasales_grouped_prices` to explore the month.
- Budget is missing — defaults are fine.

One clarification round only, max 2–3 short questions.

## Response format

**On success:** one short human sentence per option with the price as "от X₽", airline (use the human name from `airline_name`, not the IATA code), date(s), transfer count, and the link. No raw JSON, no IATA codes shown to the user (except as a fallback when a name didn't resolve).

**On round-trip with multiple variants:** present all variants the tool returned (see Round-trip handling above).

**On empty result:** one sentence saying no cached data was found, plus a generic aviasales.ru link if available.

**On error from the tool:** one short Russian sentence explaining what went wrong (city not found, API error, etc.) and what you'll try next or what you need from the user.
