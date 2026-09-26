#pragma once
#include <stdint.h>

// Shared by firmware and host regression tests. All durations use modulo-2^32 ms.
constexpr uint32_t elapsedMs(uint32_t now, uint32_t start) { return now - start; }

constexpr void advanceBackupClock(uint32_t now, uint32_t &anchor, uint32_t &unixTime) {
  const uint32_t seconds = elapsedMs(now, anchor) / 1000;
  unixTime += seconds;
  anchor += seconds * 1000;
}

constexpr bool validCalendar(int year, int month, int day, int hour, int minute, int second) {
  if (year < 2024 || year > 2099 || month < 1 || month > 12 ||
      hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) return false;
  int maximum = month == 2 ? 28 : (month == 4 || month == 6 || month == 9 || month == 11 ? 30 : 31);
  if (month == 2 && year % 4 == 0) ++maximum;
  return day >= 1 && day <= maximum;
}

constexpr bool wateringDayAllowed(bool clockTrusted, uint32_t today, uint32_t lastDay) {
  // Also suppress duplicate watering after moving the date backwards.
  return clockTrusted && today > lastDay;
}

struct RtcFields { int year, month, day, hour, minute, second; };

// DS3231 register format. Reject OSF, malformed BCD and impossible calendar dates.
constexpr bool decodeRtc(const uint8_t (&raw)[7], uint8_t status, RtcFields &out) {
  if (status & 0x80) return false;
  if ((raw[0] & 0x80) || (raw[1] & 0x80) || (raw[2] & 0x80) ||
      (raw[4] & 0xc0) || (raw[5] & 0xe0)) return false;
  const bool twelveHour = raw[2] & 0x40;
  int value[7] = {};
  for (int i = 0; i < 7; ++i) {
    uint8_t bcd = i == 2 ? raw[i] & (twelveHour ? 0x1f : 0x3f) : raw[i];
    if ((bcd & 15) > 9 || (bcd >> 4) > 9) return false;
    value[i] = (bcd >> 4) * 10 + (bcd & 15);
  }
  if (twelveHour) {
    if (value[2] < 1 || value[2] > 12) return false;
    value[2] = value[2] % 12 + ((raw[2] & 0x20) ? 12 : 0);
  }
  if (!validCalendar(2000 + value[6], value[5], value[4], value[2], value[1], value[0])) return false;
  out = {2000 + value[6], value[5], value[4], value[2], value[1], value[0]};
  return true;
}
