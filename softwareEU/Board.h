#pragma once
#include <stdint.h>

// PCB_EU only: ESP32-WROOM-32E-N4 (4 MB). Source: hardware/PCB_EU/DESIGN.md.
constexpr uint8_t LED_PWM_PIN = 25; // Common active-high nDIM of both LM3429 drivers.
constexpr uint8_t FAN1_PWM_PIN = 26;
constexpr uint8_t FAN2_PWM_PIN = 27;
constexpr uint8_t FAN1_TACH_PIN = 34; // Input-only GPIOs, external pull-ups on the PCB.
constexpr uint8_t FAN2_TACH_PIN = 35;
constexpr uint8_t HEATER_PIN = 32; // 100 W PTC: OUTPUT only, LOW = off. Never pull up/hold.
constexpr uint8_t PUMP_PIN = 33;
constexpr uint8_t WATER_LEVEL_PIN = 14; // External 10k pull-up; closed to GND = water available.
constexpr uint8_t SD_CS_PIN = 13;
constexpr uint8_t SD_SCK_PIN = 18;
constexpr uint8_t SD_MOSI_PIN = 23;
constexpr uint8_t SD_MISO_PIN = 19;
constexpr uint8_t I2C_SDA_PIN = 21;
constexpr uint8_t I2C_SCL_PIN = 22;

constexpr uint32_t LED_PWM_FREQ = 1000;
constexpr uint32_t FAN_PWM_FREQ = 25000;
constexpr uint8_t PWM_RES = 8;
constexpr uint8_t LED_PWM_CHANNEL = 0;  // Timer 0: nDIM, 1 kHz.
constexpr uint8_t FAN1_PWM_CHANNEL = 2; // Timer 1: fans, 25 kHz; never share the LED timer.
constexpr uint8_t FAN2_PWM_CHANNEL = 3;
constexpr uint32_t LED_MIN_PULSE_US = 10;
constexpr uint32_t PWM_COUNTS = 1UL << PWM_RES;
constexpr int PWM_MAX = PWM_COUNTS - 1;
constexpr int LED_MIN_DUTY = (LED_MIN_PULSE_US * LED_PWM_FREQ * PWM_COUNTS + 999999UL) / 1000000UL;
constexpr uint32_t FAN_TACH_PULSES_PER_REV = 2; // Typical four-wire fans; verify on the bench.

constexpr int clampPwm(int duty) { return duty < 0 ? 0 : (duty > PWM_MAX ? PWM_MAX : duty); }

// At 1 kHz / 8 bits, 1-2 counts are too short. Keep zero truly off; round up to
// 3 counts (11.71875 us). 255 is continuous HIGH with Arduino-ESP32 ledcWrite().
constexpr int ledDutyForRequest(int duty) {
  return duty <= 0 ? 0 : (duty < LED_MIN_DUTY ? LED_MIN_DUTY : clampPwm(duty));
}

// AO3422 inverts the fan's PWM wire. Keep speed/status/CSV in logical 0..255;
// only the GPIO duty is complemented. GPIO LOW (duty 0) = full airflow, including boot.
constexpr int fanGpioDuty(int speed) { return PWM_MAX - clampPwm(speed); }
