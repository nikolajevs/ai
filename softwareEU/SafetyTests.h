#pragma once
#include "Safety.h"
#include "Board.h"

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

static_assert(reconcileWateringMark(true, 20000, 20365) == 20000, "a mark from a future clock is pulled back to today");
static_assert(!wateringDayAllowed(true, 20000, reconcileWateringMark(true, 20000, 20365)), "no repeat on the day of the correction");
static_assert(wateringDayAllowed(true, 20001, reconcileWateringMark(true, 20000, 20365)), "watering resumes the next day");
static_assert(reconcileWateringMark(true, 20000, 19999) == 19999, "a normal mark is left alone");
static_assert(reconcileWateringMark(false, 20000, 20365) == 20365, "an untrusted clock must not rewrite the mark");

// Schedule 08:00 = second 28800 of the day, catch-up window 4 h.
static_assert(wateringDue(28800, 28800, 0, 14400), "starts at the scheduled second");
static_assert(wateringDue(28859, 28800, 0, 14400), "still starts at the end of the scheduled minute");
static_assert(!wateringDue(28799, 28800, 0, 14400), "never starts early");
static_assert(wateringDue(36000, 28800, 0, 14400), "catches up after a two-hour outage");
static_assert(!wateringDue(43201, 28800, 0, 14400), "gives up once the window has passed");
static_assert(!wateringDue(36000, 28800, 36000, 14400), "saving settings two hours later must not start the pump");
static_assert(wateringDue(28800, 28800, 28700, 14400), "a schedule saved shortly before its time still runs");

constexpr bool debounceRegression() {
  Debounce level{true, true, 0};
  debounceUpdate(level, false, 100, 2000);          // The float dips for the first time.
  if (!level.stable) return false;
  debounceUpdate(level, false, 1500, 2000);
  if (!level.stable) return false;                  // Not long enough yet.
  debounceUpdate(level, true, 1600, 2000);          // It bobs back: a slosh, not an empty tank.
  debounceUpdate(level, false, 1700, 2000);
  debounceUpdate(level, false, 3600, 2000);
  if (!level.stable) return false;                  // The hold restarted at 1700.
  debounceUpdate(level, false, 3700, 2000);
  if (level.stable) return false;                   // Held low for 2 s: the tank is empty.
  debounceUpdate(level, true, 0xfffffff0, 2000);    // Refilled just before millis() wraps.
  debounceUpdate(level, true, 2000, 2000);
  return level.stable;
}
static_assert(debounceRegression(), "float switch debounce must ignore sloshing and survive millis wrap");

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

constexpr bool mcp7940nRegression() {
  // 2026-10-21 23:59:59, ST=1, OSCRUN=1, VBATEN=1, weekday=4.
  uint8_t raw[7] = {0xd9, 0x59, 0x23, 0x2c, 0x21, 0x10, 0x26};
  RtcFields result{};
  if (!decodeMcp7940n(raw, result) || result.year != 2026 || result.month != 10 || result.day != 21 ||
      result.hour != 23 || result.minute != 59 || result.second != 59) return false;
  raw[0] &= ~MCP7940N_ST;
  if (decodeMcp7940n(raw, result)) return false; // Plausible date but oscillator disabled.
  raw[0] |= MCP7940N_ST;
  raw[3] &= ~MCP7940N_OSCRUN;
  if (decodeMcp7940n(raw, result)) return false; // ST alone does not prove the crystal runs.
  raw[3] |= MCP7940N_OSCRUN;
  raw[3] &= ~MCP7940N_VBATEN;
  if (decodeMcp7940n(raw, result)) return false;
  raw[3] |= MCP7940N_VBATEN | 0x10;
  if (!decodeMcp7940n(raw, result)) return false; // PWRFAIL after good battery backup is OK.
  raw[2] = 0x63;
  if (decodeMcp7940n(raw, result)) return false; // Do not silently accept 12-hour mode.
  raw[2] = 0x23;
  for (int i = 0; i < 7; ++i) {
    const uint8_t saved = raw[i];
    raw[i] = (raw[i] & 0xf0) | (i == 3 ? 0x08 : 0x0a);
    if (decodeMcp7940n(raw, result)) return false; // Bad BCD in each field, or weekday zero.
    raw[i] = saved;
  }
  raw[0] = 0xe0;
  if (decodeMcp7940n(raw, result)) return false; // Seconds 60.
  raw[0] = 0xd9; raw[1] = 0x60;
  if (decodeMcp7940n(raw, result)) return false;
  raw[1] = 0x59; raw[2] = 0x24;
  if (decodeMcp7940n(raw, result)) return false;
  raw[2] = 0x23; raw[4] = 0x31; raw[5] = 0x04;
  if (decodeMcp7940n(raw, result)) return false; // 31 April.
  raw[4] = 0x29; raw[5] = 0x22; raw[6] = 0x24;
  if (!decodeMcp7940n(raw, result) || result.month != 2) return false; // LPYR is not month BCD.
  raw[6] = 0x25;
  if (decodeMcp7940n(raw, result)) return false; // Non-leap year.
  raw[4] = 0x01; raw[5] = 0x01; raw[6] = 0x00;
  return !decodeMcp7940n(raw, result); // Factory reset year is not trusted.
}
static_assert(mcp7940nRegression(), "validate MCP7940N ST/OSCRUN/VBATEN, BCD, 24h and calendar");

constexpr bool mcp7940nWriteRegression() {
  const RtcFields dates[] = {{2024, 2, 29, 0, 0, 0}, {2026, 10, 21, 12, 34, 56}, {2099, 12, 31, 23, 59, 59}};
  for (const RtcFields &date : dates) {
    for (uint8_t weekday = 1; weekday <= 7; ++weekday) {
      uint8_t raw[7]{};
      if (!encodeMcp7940n(date, weekday, raw) || !(raw[0] & MCP7940N_ST) ||
          raw[3] != (weekday | MCP7940N_VBATEN) || (raw[2] & 0xc0)) return false;
      raw[3] |= MCP7940N_OSCRUN; // Read-only flag set by the chip after starting.
      RtcFields read{};
      if (!decodeMcp7940n(raw, read) || read.year != date.year || read.month != date.month ||
          read.day != date.day || read.hour != date.hour || read.minute != date.minute || read.second != date.second) return false;
    }
  }
  uint8_t raw[7]{};
  return !encodeMcp7940n(dates[0], 0, raw) && !encodeMcp7940n(dates[0], 8, raw) &&
         !encodeMcp7940n({2025, 2, 29, 0, 0, 0}, 1, raw);
}
static_assert(mcp7940nWriteRegression(), "MCP7940N writes set ST/VBATEN and round-trip all calendar fields");

constexpr bool ledPulseRegression() {
  for (int request = -5; request <= 260; ++request) {
    const int duty = ledDutyForRequest(request);
    if (duty < 0 || duty > PWM_MAX || (request <= 0 && duty != 0)) return false;
    if (request > 0 && uint64_t(duty) * 1000000 < uint64_t(LED_MIN_PULSE_US) * LED_PWM_FREQ * PWM_COUNTS) return false;
    if (request >= LED_MIN_DUTY && duty != clampPwm(request)) return false;
  }
  return ledDutyForRequest(255) == 255;
}
static_assert(LED_PWM_FREQ >= 500 && LED_PWM_FREQ <= 1000 && ledPulseRegression(), "every nonzero LED pulse must be at least 10 us");
static_assert(FAN_PWM_FREQ == 25000 && fanGpioDuty(255) == 0 && fanGpioDuty(0) == 255 &&
              fanGpioDuty(128) == 127 && fanGpioDuty(-1) == 255 && fanGpioDuty(256) == 0,
              "fan GPIO duty must invert logical airflow, including endpoint saturation");
static_assert(LED_PWM_CHANNEL / 2 != FAN1_PWM_CHANNEL / 2 && LED_PWM_CHANNEL / 2 != FAN2_PWM_CHANNEL / 2,
              "ESP32 LED and fans must use separate LEDC timers");
