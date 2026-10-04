#pragma once
#include "Safety.h"

// Compile-time regressions: every firmware build checks these, with no runtime cost.
static_assert(validCalendar(2024, 2, 29, 23, 59, 59), "leap day must work");
static_assert(!validCalendar(2025, 2, 29, 12, 0, 0), "reject nonexistent leap day");
static_assert(!validCalendar(2026, 4, 31, 12, 0, 0), "reject day overflow");
static_assert(!validCalendar(2026, 0, 1, 12, 0, 0), "reject month zero");
static_assert(!validCalendar(2026, 13, 1, 12, 0, 0), "reject month overflow");
static_assert(!validCalendar(2026, 1, 0, 12, 0, 0), "reject day zero");
static_assert(!validCalendar(2026, 1, 1, 45, 0, 0), "reject old RTC hour bug");
static_assert(!validCalendar(2026, 1, 1, 24, 0, 0), "reject hour 24");
static_assert(!validCalendar(2026, 1, 1, 12, 60, 0), "reject minute 60");
static_assert(!validCalendar(2026, 1, 1, 12, 0, 60), "reject second 60");
static_assert(!validCalendar(2000, 1, 1, 0, 0, 0), "reject factory reset date");
static_assert(!wateringDayAllowed(false, 20000, 0), "no watering with untrusted boot clock");
static_assert(!wateringDayAllowed(true, 20000, 20000), "no repeat after restoring persisted mark");
static_assert(!wateringDayAllowed(true, 19999, 20000), "no repeat after backwards date adjustment");
static_assert(wateringDayAllowed(true, 20001, 20000), "next day may water");
static_assert(elapsedMs(29999, 0) < 30000, "pump must run for requested duration");
static_assert(elapsedMs(30000, 0) >= 30000, "pump must stop at deadline");
static_assert(elapsedMs(0x20, 0xfffffff0) == 48, "millis wrap must be safe");

constexpr uint8_t kSensirionCrcExample[2] = {0xBE, 0xEF};
static_assert(sensirionCrc8(kSensirionCrcExample, 2) == 0x92, "SHT4x CRC must match the datasheet example");

constexpr bool backupRegression() {
  uint32_t anchor = 21600000, timestamp = 1775000000;
  advanceBackupClock(21601500, anchor, timestamp);
  if (timestamp != 1775000001 || anchor != 21601000) return false;
  advanceBackupClock(21602000, anchor, timestamp);
  return timestamp == 1775000002 && anchor == 21602000;
}
static_assert(backupRegression(), "fallback must retain fractional seconds without adding uptime");
constexpr bool backupWrapRegression() {
  uint32_t anchor = 0xffffff00, timestamp = 1775000000;
  advanceBackupClock(744, anchor, timestamp);
  return timestamp == 1775000001 && anchor == 744;
}
static_assert(backupWrapRegression(), "fallback clock must survive millis wrap");

constexpr bool rtcRegression() {
  uint8_t raw[7] = {0x59, 0x59, 0x23, 6, 0x26, 0x09, 0x26};
  RtcFields result{};
  if (!decodeDs3231(raw, 0, result) || result.year != 2026 || result.hour != 23 || result.day != 26) return false;
  if (decodeDs3231(raw, 0x80, result)) return false; // Valid date but oscillator stopped.
  raw[2] = 0x52; // 12 AM.
  if (!decodeDs3231(raw, 0, result) || result.hour != 0) return false;
  raw[2] = 0x72; // 12 PM.
  if (!decodeDs3231(raw, 0, result) || result.hour != 12) return false;
  raw[2] = 0x61; // 1 PM.
  if (!decodeDs3231(raw, 0, result) || result.hour != 13) return false;
  raw[2] = 0x24;
  if (decodeDs3231(raw, 0, result)) return false;
  raw[2] = 0x12; raw[0] = 0x2a;
  if (decodeDs3231(raw, 0, result)) return false; // Invalid BCD.
  raw[0] = 0; raw[4] = 0x30; raw[5] = 0x02;
  return !decodeDs3231(raw, 0, result);
}
static_assert(rtcRegression(), "validate DS3231 OSF, BCD, calendar, 12h and 24h registers");

constexpr bool pcf8563Regression() {
  // VL_seconds, minutes, hours, days, weekdays, century_months, years: 2026-09-26 23:59:59.
  uint8_t raw[7] = {0x59, 0x59, 0x23, 0x26, 6, 0x89, 0x26};
  RtcFields result{};
  if (!decodePcf8563(raw, result) || result.year != 2026 || result.month != 9 || result.day != 26 ||
      result.hour != 23 || result.minute != 59 || result.second != 59) return false; // Century bit ignored.
  raw[0] = 0xd9;
  if (decodePcf8563(raw, result)) return false; // VL: integrity lost after a supply dropout.
  raw[0] = 0x59; raw[1] = 0xd9; raw[2] = 0xe3; raw[4] = 0xfe;
  if (!decodePcf8563(raw, result) || result.minute != 59 || result.hour != 23) return false; // Unused bits masked.
  raw[3] = 0x2a;
  if (decodePcf8563(raw, result)) return false; // Invalid BCD.
  raw[3] = 0x31; raw[5] = 0x04;
  if (decodePcf8563(raw, result)) return false; // 31 April.
  raw[3] = 0x01; raw[5] = 0x01; raw[6] = 0x00;
  return !decodePcf8563(raw, result); // Factory date 2000-01-01.
}
static_assert(pcf8563Regression(), "validate PCF8563 VL flag, register masks, BCD and calendar");
