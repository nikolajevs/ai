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

// Sensirion CRC-8 (SHT4x datasheet: polynomial 0x31, init 0xFF).
constexpr uint8_t sensirionCrc8(const uint8_t *data, int len) {
  uint8_t crc = 0xFF;
  for (int i = 0; i < len; ++i) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; ++bit) crc = (crc & 0x80) ? uint8_t((crc << 1) ^ 0x31) : uint8_t(crc << 1);
  }
  return crc;
}

struct RtcFields { int year, month, day, hour, minute, second; };

// DS3231 register format. Reject OSF, malformed BCD and impossible calendar dates.
constexpr bool decodeDs3231(const uint8_t (&raw)[7], uint8_t status, RtcFields &out) {
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

// PCF8563 registers 02h..08h (board v0.20). VL (bit 7 of 02h) means clock integrity is not
// guaranteed after a supply loss. Unused bits are undefined and masked; the century bit is
// ignored because the calendar is limited to 2024..2099 anyway.
constexpr bool decodePcf8563(const uint8_t (&raw)[7], RtcFields &out) {
  if (raw[0] & 0x80) return false;
  const uint8_t mask[7] = {0x7f, 0x7f, 0x3f, 0x3f, 0x07, 0x1f, 0xff};
  int value[7] = {};
  for (int i = 0; i < 7; ++i) {
    const uint8_t bcd = raw[i] & mask[i];
    if ((bcd & 15) > 9 || (bcd >> 4) > 9) return false;
    value[i] = (bcd >> 4) * 10 + (bcd & 15);
  }
  if (!validCalendar(2000 + value[6], value[5], value[3], value[2], value[1], value[0])) return false;
  out = {2000 + value[6], value[5], value[3], value[2], value[1], value[0]};
  return true;
}
