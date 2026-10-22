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
// Core 3.3.x assigns LEDC timers by frequency/resolution, not by channel number:
// the LED gets its own timer only because LED_PWM_FREQ != FAN_PWM_FREQ (see SafetyTests.h).
constexpr uint8_t LED_PWM_CHANNEL = 0;  // nDIM, 1 kHz, attached first.
constexpr uint8_t FAN1_PWM_CHANNEL = 2; // Fans, 25 kHz, share one timer.
constexpr uint8_t FAN2_PWM_CHANNEL = 3;
constexpr uint32_t LED_MIN_PULSE_US = 10;
constexpr uint32_t PWM_COUNTS = 1UL << PWM_RES;
constexpr int PWM_MAX = PWM_COUNTS - 1;
constexpr int LED_MIN_DUTY = (LED_MIN_PULSE_US * LED_PWM_FREQ * PWM_COUNTS + 999999UL) / 1000000UL;
constexpr uint32_t FAN_TACH_PULSES_PER_REV = 2; // Typical four-wire fans; verify on the bench.
constexpr uint32_t FAN_TACH_GLITCH_NS = 10000;  // PCNT filter; ESP32 maximum is ~12.7 us.
constexpr int32_t FAN_RPM_PLAUSIBLE_MAX = 15000; // Above this the reading is noise: reported as invalid.

// Software ceiling for the 100 W PTC, independent of every setting. The external thermal
// cutoff stays mandatory; this only adds a second, settings-proof limit.
constexpr float HEATER_HARD_LIMIT_C = 60.0f;

// INA226 on the 24 V input (values from the PCB_EU board revision with the power meter):
// 5 mOhm low-side shunt (2x 0R01 2512 in parallel), IN+ on the board-GND side, so current
// drawn from the PSU reads positive. VBUS comes from +24V_FUSED through 1 kOhm (R113) and is
// clamped by a 33 V zener; the 1 k / 830 k input divider reads ~0.12 % low.
constexpr uint8_t INA226_ADDR = 0x40;            // A0 = A1 = GND. Not 0x44/0x45: SHT4x.
constexpr uint16_t INA226_MANUFACTURER_ID = 0x5449;
constexpr uint16_t INA226_CONFIG = 0x4727;       // AVG 64, VBUS/VSH 1.1 ms, continuous.
constexpr uint16_t INA226_CALIBRATION = 2048;    // 0.00512 / (0.5 mA * 5 mOhm).
constexpr float INA226_SHUNT_LSB_V = 2.5e-6f;    // Shunt voltage register, V per count.
constexpr float INA226_BUS_LSB_V = 1.25e-3f;     // Bus voltage register, V per count.
constexpr float INA226_SHUNT_OHM = 0.005f;
constexpr float INA226_BUS_CORRECTION = 1.0012f; // R113 1 k in series with the ~830 k VBUS input.
constexpr float PSU_LOW_VOLTAGE_V = 21.6f;       // Lower end of the design input range (UI warning only).

constexpr int clampPwm(int duty) { return duty < 0 ? 0 : (duty > PWM_MAX ? PWM_MAX : duty); }

// At 1 kHz / 8 bits, 1-2 counts are too short. Keep zero truly off; round up to
// 3 counts (11.71875 us). 255 is continuous HIGH with Arduino-ESP32 ledcWrite().
// The same limit applies to the LOW gap near full brightness: 254 would leave a 2-count
// (7.8 us) gap, so it snaps to continuous HIGH.
constexpr int ledDutyForRequest(int duty) {
  return duty <= 0 ? 0
       : duty < LED_MIN_DUTY ? LED_MIN_DUTY
       : duty >= PWM_MAX ? PWM_MAX
       : int(PWM_COUNTS) - duty < LED_MIN_DUTY ? PWM_MAX
       : duty;
}

// AO3422 inverts the fan's PWM wire. Keep speed/status/CSV in logical 0..255;
// only the GPIO duty is complemented. GPIO LOW (duty 0) = full airflow, including boot.
constexpr int fanGpioDuty(int speed) { return PWM_MAX - clampPwm(speed); }

// INA226 register values to physical units. correction is the user's current calibration
// factor (1.0 = none); the bus voltage correction for R113 is fixed by the hardware.
constexpr float ina226Amps(int16_t shuntRaw, float correction) {
  return float(shuntRaw) * (INA226_SHUNT_LSB_V / INA226_SHUNT_OHM) * correction;
}
constexpr float ina226Volts(uint16_t busRaw) { return float(busRaw & 0x7fff) * INA226_BUS_LSB_V * INA226_BUS_CORRECTION; }

// Falling-edge count over elapsedMs to RPM; -1 when it cannot be a real fan (noise).
constexpr int32_t tachRpm(int pulses, uint32_t elapsedMs) {
  return pulses < 0 || elapsedMs == 0 ? -1
       : uint64_t(pulses) * 60000 / (uint64_t(elapsedMs) * FAN_TACH_PULSES_PER_REV) > uint64_t(FAN_RPM_PLAUSIBLE_MAX) ? -1
       : int32_t(uint64_t(pulses) * 60000 / (uint64_t(elapsedMs) * FAN_TACH_PULSES_PER_REV));
}
