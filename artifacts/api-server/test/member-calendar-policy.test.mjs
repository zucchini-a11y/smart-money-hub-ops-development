import assert from "node:assert/strict";
import test from "node:test";
import { impactFor, parseBea, parseBls, parseCensus } from "../src/routes/member-calendar.ts";

const NOW = new Date("2026-11-06T12:00:00.000Z");
const BLS_SOURCE = {
  id: "bls",
  sourceName: "U.S. Bureau of Labor Statistics",
  url: "https://www.bls.gov/schedule/news_release/cpi.htm",
};

test("BLS events require recognized titles and retain explicit UTC times", () => {
  const events = parseBls([
    "BEGIN:VCALENDAR",
    "BEGIN:VEVENT",
    "SUMMARY:Consumer Price Index",
    "DTSTART:20261210T133000Z",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "SUMMARY:Unrelated announcement",
    "DTSTART:20261211T130000Z",
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n"), BLS_SOURCE, NOW);

  assert.equal(events.length, 1);
  assert.equal(events[0].eventDate, "2026-12-10");
  assert.equal(events[0].eventAt, "2026-12-10T13:30:00.000Z");
  assert.equal(events[0].timezoneStatus, "verified_source_timezone:UTC");
});

test("BLS does not invent a timezone for a floating event time", () => {
  const events = parseBls([
    "BEGIN:VEVENT",
    "SUMMARY:Employment Situation",
    "DTSTART:20261204T083000",
    "END:VEVENT",
  ].join("\n"), BLS_SOURCE, NOW);

  assert.equal(events.length, 1);
  assert.equal(events[0].eventAt, null);
  assert.equal(events[0].timezoneStatus, "unverified_missing_source_timezone");
});

test("BEA accepts explicit offsets and rejects timezone-free timestamps", () => {
  const events = parseBea(JSON.stringify({
    "Gross Domestic Product": {
      release_dates: [
        "2026-12-10T13:30:00Z",
        "2026-12-11T13:30:00-05:00",
        "2026-12-12T13:30:00",
      ],
    },
  }), { id: "bea", sourceName: "Bureau of Economic Analysis", url: "https://apps.bea.gov/news/schedule/" }, NOW);

  assert.equal(events.length, 2);
  assert.equal(events[0].eventAt, "2026-12-10T13:30:00.000Z");
  assert.equal(events[1].eventAt, "2026-12-11T18:30:00.000Z");
});

test("Census events show listed times without inventing a timezone", () => {
  const events = parseCensus(
    `<table id="calendar"><tr><td><a href="/news/2026/retail.html">Advance Monthly Sales for Retail and Food Services</a></td><td>December 15, 2026</td><td>8:30 AM</td></tr></table>`,
    { id: "census", sourceName: "U.S. Census Bureau", url: "https://www.census.gov/economic-indicators/" },
    NOW,
  );

  assert.equal(events.length, 1);
  assert.equal(events[0].eventAt, null);
  assert.equal(events[0].timezoneStatus, "unverified_no_timezone_in_source");
  assert.match(events[0].timeLabel, /source timezone unverified/);
  assert.equal(new URL(events[0].sourceUrl).hostname, "www.census.gov");
});

test("impact labels are explanatory, not source-provided economic values", () => {
  assert.equal(impactFor("Consumer Price Index (CPI)"), "high");
  assert.equal(impactFor("Producer Price Index (PPI)"), "medium");
  assert.equal(impactFor("A less common release"), "low");
});
