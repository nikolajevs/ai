#include <esp_task_wdt.h>
#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <SPIFFS.h>
#include <RTClib.h>
#include <Adafruit_SHT4x.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <Preferences.h>
#include <HTTPClient.h>

// --- Настройки подключения к домашнему роутеру и Ubidots ---
// Значения по умолчанию используются только при первой прошивке / если NVS пуст.
// Реальные значения хранятся в Preferences и редактируются на вкладке "WiFi / Ubidots".
#define DEFAULT_WIFI_SSID     "B535_90A3-ext"
#define DEFAULT_WIFI_PASS     "d92Te5L78H3"
#define DEFAULT_UBIDOTS_TOKEN "BBUS-SjTUV0ChXNMezQpTFz1fOeZvHKTvjU"
#define DEFAULT_DEVICE_LABEL  "kireal"
#define DEFAULT_AP_SSID       "KiReal"
#define DEFAULT_AP_PASS       "420420420"

String wifi_ssid;
String wifi_pass;
String ubidots_token;
String device_label;
String ap_ssid;   // Имя локальной точки доступа (Wi-Fi, к которой подключается телефон/ноутбук)
String ap_pass;   // Пароль локальной точки доступа (пусто = открытая сеть, иначе >= 8 символов)

// --- Распиновка периферии ---
#define SD_CS_PIN     5
#define LED_PWM_PIN   4
#define FAN1_PWM_PIN  13
#define FAN2_PWM_PIN  33
#define PUMP_PIN      25 // реле/мосфет насоса полива — при необходимости смени на свободный GPIO
#define HEATER_PIN    27 // реле обогревателя — при необходимости смени на свободный GPIO

#define PWM_FREQ      5000
#define PWM_RES       8

// --- Переменные параметров климата и автоматизации ---
float temp_target = 25.0; 
float temp_delta = 2.0;   
float temp_target_night = 20.0; // Целевая температура для обогревателя ночью (гистерезис temp_delta общий)
float max_hum_night = 60.0; 

int led_on_hour = 6;        
int led_off_hour = 23;      
int led_on_minute = 0;
int led_off_minute = 0;
int fan1_min_limit = 30;    
int fan1_max_limit = 80;    
int fan2_min_limit = 30;    
int fan2_max_limit = 80;    
int led_min_limit = 30;     
int led_max_limit = 80;    
int fan_night_min_limit = 30;   // Ночной минимум скорости обоих вентиляторов, % (при низкой влажности)
int fan_night_max_limit = 100;  // Ночной максимум скорости обоих вентиляторов, % (при высокой влажности)
float min_hum_night = 40.0;     // Влажность, ниже которой ночью вентиляторы держат минимум (верхняя граница — max_hum_night)
uint32_t start_timestamp = 0; 

// --- Настройки автополива ---
uint8_t watering_days = 0;        // битовая маска: бит0=Пн, бит1=Вт, ... бит6=Вс
int watering_hour = 8;
int watering_minute = 0;
int watering_duration_sec = 30;

// --- Состояние насоса ---
bool pump_active = false;
uint32_t pump_start_time = 0;
uint32_t last_watering_day = 0;   // защита от повторного срабатывания в ту же минуту

// --- Настройки обогрева ---
// heater_mode: 0 = только день, 1 = только ночь, 2 = всегда, 3 = никогда
int heater_mode = 3;
bool heater_active = false;

// --- Глобальные переменные состояния системы ---
float current_temp = 0.0;
float current_hum = 0.0;
int current_led_pwm = 255;
int current_fan1_pwm = 51; 
int current_fan2_pwm = 51; 
bool is_day = true;

// --- Статус здоровья периферии (Самодиагностика) ---
bool sht_online = true;
unsigned long last_sht_retry = 0;               // Когда последний раз пытались восстановить датчик
const unsigned long SHT_RETRY_INTERVAL_MS = 30000; // Пауза между попытками восстановления, мс
int sht_recovery_streak = 0;                     // Счётчик подряд успешных попыток восстановления
const int SHT_RECOVERY_STREAK_NEEDED = 3;        // Сколько подряд удачных попыток нужно, чтобы снова доверять датчику
bool rtc_online = true;
unsigned long last_rtc_retry = 0;                // Когда последний раз пытались восстановить RTC
const unsigned long RTC_RETRY_INTERVAL_MS = 30000; // Пауза между попытками восстановления, мс
int rtc_recovery_streak = 0;                     // Счётчик подряд успешных попыток восстановления
const int RTC_RECOVERY_STREAK_NEEDED = 3;        // Сколько подряд удачных попыток нужно, чтобы снова доверять RTC

// Переменные для программного дублирования времени (на случай отказа RTC)
uint32_t backup_unixtime = 1774838400; // Дефолтный 2026 год, если RTC умер сразу при старте
unsigned long last_rtc_check_ms = 0;

// --- Хендлы FreeRTOS для многоядерности ---
TaskHandle_t UbidotsTaskHandle = NULL;
SemaphoreHandle_t xMutex = NULL; 

// --- Инициализация объектов ---
Adafruit_SHT4x sht40 = Adafruit_SHT4x();
RTC_DS3231 rtc;
AsyncWebServer server(80);
Preferences preferences;

// --- Хелперы валидации входных данных (защита от некорректных значений из веб-формы) ---
int clampInt(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

float clampFloat(float v, float lo, float hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

// SSID точки доступа: 1-32 символа (ограничение стандарта 802.11)
bool isValidApSsid(const String &s) {
  return s.length() >= 1 && s.length() <= 32;
}

// Пароль точки доступа: пусто (открытая сеть) или 8-63 символа (требование WPA2)
bool isValidApPass(const String &p) {
  return p.length() == 0 || (p.length() >= 8 && p.length() <= 63);
}

// SSID роутера (STA): можно оставить пустым (означает "не подключаться"), максимум 32 символа
bool isValidStaSsid(const String &s) {
  return s.length() <= 32;
}

// Пароль роутера (STA): пусто (открытая сеть) или 8-63 символа (требование WPA2)
bool isValidStaPass(const String &p) {
  return p.length() == 0 || (p.length() >= 8 && p.length() <= 63);
}

// Подстраховка на случай, если пришли "перевёрнутые" границы (min > max) —
// меняем местами, чтобы устройство не осталось с невозможным диапазоном.
void clampPairInt(Preferences &prefs, const char *keyMin, const char *keyMax, int a, int b, int lo, int hi) {
  int vMin = clampInt(a, lo, hi);
  int vMax = clampInt(b, lo, hi);
  if (vMin > vMax) { int t = vMin; vMin = vMax; vMax = t; }
  prefs.putInt(keyMin, vMin);
  prefs.putInt(keyMax, vMax);
}

void clampPairFloat(Preferences &prefs, const char *keyMin, const char *keyMax, float a, float b, float lo, float hi) {
  float vMin = clampFloat(a, lo, hi);
  float vMax = clampFloat(b, lo, hi);
  if (vMin > vMax) { float t = vMin; vMin = vMax; vMax = t; }
  prefs.putFloat(keyMin, vMin);
  prefs.putFloat(keyMax, vMax);
}

struct ClimateData {
  float temp;
  float hum;
  int led;
  int fan1;
  int fan2;
  bool sht_ok;
};

// Фоновая задача на Core 0 для работы с облаком Ubidots
void vUbidotsTask(void *pvParameters) {
  esp_task_wdt_add(NULL); // Регистрируем эту задачу (Core 0) в watchdog — раньше следили только за loop()
  ClimateData localData;

  for (;;) {
    // 2 минуты сна короткими интервалами по 500мс с "подкормкой" watchdog на каждом шаге —
    // иначе один долгий vTaskDelay(120000) сам по себе превысит 15-секундный таймаут TWDT
    for (int i = 0; i < 240; i++) {
      vTaskDelay(pdMS_TO_TICKS(500));
      esp_task_wdt_reset();
    }

    Serial.println("[Core 0] Пробуждение задачи Ubidots...");

    if (xSemaphoreTake(xMutex, pdMS_TO_TICKS(1000)) == pdTRUE) {
      localData.temp = current_temp;
      localData.hum = current_hum;
      localData.led = current_led_pwm;
      localData.fan1 = current_fan1_pwm;
      localData.fan2 = current_fan2_pwm;
      localData.sht_ok = sht_online;
      xSemaphoreGive(xMutex); 
    } else {
      continue; 
    }

    WiFi.mode(WIFI_AP_STA);
    WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
      vTaskDelay(pdMS_TO_TICKS(500)); 
      esp_task_wdt_reset();
      attempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      String url = "http://industrial.api.ubidots.com/api/v1.6/devices/" + device_label;
      
      http.begin(url);
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Auth-Token", ubidots_token);
      
      String payload = "{";
      if (localData.sht_ok) {
        payload += "\"temperature\":" + String(localData.temp, 2) + ",";
        payload += "\"humidity\":" + String(localData.hum, 2) + ",";
      }
      payload += "\"led-power\":" + String(round(localData.led / 2.55)) + ",";
      payload += "\"fan1-power\":" + String(round(localData.fan1 / 2.55)) + ",";
      payload += "\"fan2-power\":" + String(round(localData.fan2 / 2.55)) + ",";
      payload += "\"sensor-status\":" + String(localData.sht_ok ? 1 : 0); // Отсылаем статус датчика в облако
      payload += "}";
      
      int httpResponseCode = http.POST(payload);
      esp_task_wdt_reset(); // HTTPClient блокирует до ~5с по таймауту — подстраховываемся после запроса
      http.end();
    }
    
    WiFi.disconnect(true);
    WiFi.mode(WIFI_AP);
    esp_task_wdt_reset();
  }
}

// Функция получения безопасного времени (из RTC или программного бэкапа)
DateTime getSafeDateTime() {
  if (rtc_online) {
    DateTime now = rtc.now();
    // Проверяем, не выдает ли RTC нулевой или ошибочный год (признак сбоя чтения)
    if (now.minute() <= 60 && now.hour() <= 60) {
      backup_unixtime = now.unixtime(); // Синхронизируем бэкап
      return now;
    } else {
      Serial.println("[КРИТИКА] RTC вернул некорректную дату! Переход на программный таймер.");
      rtc_online = false;
    }
  }
  
  // Если RTC сломан, рассчитываем время программно на основе millis()
  unsigned long ms = millis();
  uint32_t elapsed_seconds = (ms - last_rtc_check_ms) / 1000;
  if (elapsed_seconds > 0) {
    backup_unixtime += elapsed_seconds;
    last_rtc_check_ms += elapsed_seconds * 1000;
  }
  return DateTime(backup_unixtime);
}

// Периодически пробует восстановить RTC после сбоя, без перезагрузки платы —
// та же схема, что и для датчика SHT4x. Нужно несколько подряд успешных
// попыток чтения вменяемой даты, прежде чем снова начать доверять RTC.
void tryRecoverRTC(unsigned long currentMillis) {
  if (rtc_online) return;
  if (currentMillis - last_rtc_retry < RTC_RETRY_INTERVAL_MS) return;
  last_rtc_retry = currentMillis;

  bool retry_ok = false;
  if (rtc.begin()) {
    DateTime now = rtc.now();
    // 2024..2099 — грубая защита от "проснувшегося после разряда батарейки" RTC,
    // который обычно сбрасывается на заводскую дату (например, 2000 или 2021 год)
    if (now.minute() <= 60 && now.hour() <= 60 && now.year() >= 2024 && now.year() <= 2099) {
      retry_ok = true;
      rtc_recovery_streak++;
      Serial.printf("[RTC] Попытка восстановления %d/%d успешна\n", rtc_recovery_streak, RTC_RECOVERY_STREAK_NEEDED);
      if (rtc_recovery_streak >= RTC_RECOVERY_STREAK_NEEDED) {
        rtc_online = true;
        backup_unixtime = now.unixtime();
        last_rtc_check_ms = millis();
        rtc_recovery_streak = 0;
        Serial.println("[RTC] DS3231 восстановлен, выходим из программного таймера.");
      }
    }
  }
  if (!retry_ok) {
    rtc_recovery_streak = 0; // Сбрасываем счётчик серии при любой неудачной попытке
  }
}

void setup() {
  Serial.begin(115200);
  // Внутри setup() после инициализации Serial
  #ifdef ESP_IDF_VERSION_VAL
    // Инициализация WDT на 15 секунды
    esp_task_wdt_config_t wdt_config = {
        .timeout_ms = 15000,
        .idle_core_mask = (1 << 0) | (1 << 1), // Мониторим оба ядра
        .trigger_panic = true
    };
    esp_task_wdt_reconfigure(&wdt_config);
    esp_task_wdt_add(NULL); // Добавляем текущую задачу (loop)
  #else
    // Старый метод для более старых версий (2.x)
    esp_task_wdt_init(4, true);
    esp_task_wdt_add(NULL);
  #endif
  Wire.begin(); 
  
  xMutex = xSemaphoreCreateMutex();

  preferences.begin("grow-box", false);
  temp_target = preferences.getFloat("temp_target", 25.0);
  temp_delta = preferences.getFloat("temp_delta", 2.0);
  temp_target_night = preferences.getFloat("temp_night", 20.0);
  max_hum_night = preferences.getFloat("max_hum_night", 60.0);
  led_on_hour = preferences.getInt("led_on_hour", 6);
  led_off_hour = preferences.getInt("led_off_hour", 18);
  led_on_minute = preferences.getInt("led_on_minute", 0);
  led_off_minute = preferences.getInt("led_off_minute", 0);
  fan1_min_limit = preferences.getInt("fan1_min_limit", 20);
  fan1_max_limit = preferences.getInt("fan1_max_limit", 100);
  fan2_min_limit = preferences.getInt("fan2_min_limit", 20);
  fan2_max_limit = preferences.getInt("fan2_max_limit", 100);
  led_min_limit = preferences.getInt("led_min_limit", 10); 
  led_max_limit = preferences.getInt("led_max_limit", 100);
  fan_night_min_limit = preferences.getInt("fan_night_min", 30);
  fan_night_max_limit = preferences.getInt("fan_night_max", 100);
  min_hum_night = preferences.getFloat("min_hum_night", 40.0);
  start_timestamp = preferences.getUInt("start_time", 0);

  watering_days = preferences.getUChar("watering_days", 0);
  watering_hour = preferences.getInt("watering_hour", 8);
  watering_minute = preferences.getInt("watering_minute", 0);
  watering_duration_sec = preferences.getInt("watering_dur", 30);
  heater_mode = preferences.getInt("heater_mode", 2);

  wifi_ssid = preferences.getString("wifi_ssid", DEFAULT_WIFI_SSID);
  wifi_pass = preferences.getString("wifi_pass", DEFAULT_WIFI_PASS);
  ubidots_token = preferences.getString("ubidots_token", DEFAULT_UBIDOTS_TOKEN);
  device_label = preferences.getString("device_label", DEFAULT_DEVICE_LABEL);
  ap_ssid = preferences.getString("ap_ssid", DEFAULT_AP_SSID);
  ap_pass = preferences.getString("ap_pass", DEFAULT_AP_PASS);
  // На случай испорченных/некорректных значений в NVS откатываемся на дефолт, чтобы не остаться без доступа к плате
  if (!isValidApSsid(ap_ssid)) ap_ssid = DEFAULT_AP_SSID;
  if (!isValidApPass(ap_pass)) ap_pass = DEFAULT_AP_PASS;

  // Безопасная инициализация датчиков с проверкой работоспособности
  if (!sht40.begin()) {
    Serial.println("ОШИБКА: SHT4x не найден!");
    sht_online = false;
  }
  
  if (!rtc.begin()) {
    Serial.println("ОШИБКА: RTC DS3231 не найден!");
    rtc_online = false;
    last_rtc_check_ms = millis();
  }

  if (!SD.begin(SD_CS_PIN)) Serial.println("SD-карта не обнаружена.");
  if (!SPIFFS.begin(true)) Serial.println("Ошибка SPIFFS!");

  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW); // насос выключен при старте

  pinMode(HEATER_PIN, OUTPUT);
  digitalWrite(HEATER_PIN, LOW); // обогреватель выключен при старте

  WiFi.mode(WIFI_AP);
  WiFi.softAP(ap_ssid.c_str(), ap_pass.length() > 0 ? ap_pass.c_str() : NULL);

  xTaskCreatePinnedToCore(vUbidotsTask, "UbidotsTask", 8192, NULL, 1, &UbidotsTaskHandle, 0);

  // --- МАРШРУТИЗАЦИЯ ВЕБ-СЕРВЕРА ---
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/index.html", "text/html"); });
  server.on("/settings", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/settings.html", "text/html"); });
  server.on("/style.css", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/style.css", "text/css"); });
  server.on("/script.js", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/script.js", "application/javascript"); });
  server.on("/settings.js", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/settings.js", "application/javascript"); });

  server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest *request){
    DateTime now = getSafeDateTime();
    int grow_day = (start_timestamp > 0 && now.unixtime() >= start_timestamp) ? ((now.unixtime() - start_timestamp) / 86400) + 1 : 0;
    
    float t, h; int l, f1, f2; bool s_ok, r_ok;
    if (xSemaphoreTake(xMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
      t = current_temp; h = current_hum; l = current_led_pwm; f1 = current_fan1_pwm; f2 = current_fan2_pwm;
      s_ok = sht_online; r_ok = rtc_online;
      xSemaphoreGive(xMutex);
    }

    String json = "{";
    json += "\"temp\":" + String(t, 2) + ",";
    json += "\"hum\":" + String(h, 2) + ",";
    json += "\"led\":" + String(l) + ",";
    json += "\"fan1\":" + String(f1) + ",";
    json += "\"fan2\":" + String(f2) + ",";
    json += "\"time\":\"" + now.timestamp(DateTime::TIMESTAMP_TIME) + "\",";
    json += "\"date\":\"" + now.timestamp(DateTime::TIMESTAMP_DATE) + "\",";
    json += "\"is_day\":" + String(is_day ? "true" : "false") + ",";
    json += "\"grow_day\":" + String(grow_day) + ",";
    json += "\"sht_online\":" + String(s_ok ? "true" : "false") + ","; // Передаем статус в UI
    json += "\"rtc_online\":" + String(r_ok ? "true" : "false") + ",";
    json += "\"pump_active\":" + String(pump_active ? "true" : "false") + ",";
    json += "\"heater_active\":" + String(heater_active ? "true" : "false");
    json += "}";
    request->send(200, "application/json", json);
  });

  server.on("/api/settings", HTTP_GET, [](AsyncWebServerRequest *request){
    DateTime now = getSafeDateTime();
    char buf[24]; snprintf(buf, sizeof(buf), "%02d.%02d.%04d %02d:%02d:%02d", now.day(), now.month(), now.year(), now.hour(), now.minute(), now.second());
    String json = "{";
    json += "\"temp_target\":" + String(temp_target, 1) + ",";
    json += "\"temp_delta\":" + String(temp_delta, 1) + ",";
    json += "\"temp_target_night\":" + String(temp_target_night, 1) + ",";
    json += "\"max_hum_night\":" + String(max_hum_night, 1) + ",";
    json += "\"led_on_hour\":" + String(led_on_hour) + ",";
    json += "\"led_off_hour\":" + String(led_off_hour) + ",";
    json += "\"led_on_minute\":" + String(led_on_minute) + ",";
    json += "\"led_off_minute\":" + String(led_off_minute) + ",";
    json += "\"fan1_min_limit\":" + String(fan1_min_limit) + ",";
    json += "\"fan1_max_limit\":" + String(fan1_max_limit) + ",";
    json += "\"fan2_min_limit\":" + String(fan2_min_limit) + ",";
    json += "\"fan2_max_limit\":" + String(fan2_max_limit) + ",";
    json += "\"led_min_limit\":" + String(led_min_limit) + ",";
    json += "\"led_max_limit\":" + String(led_max_limit) + ","; 
    json += "\"fan_night_min_limit\":" + String(fan_night_min_limit) + ",";
    json += "\"fan_night_max_limit\":" + String(fan_night_max_limit) + ",";
    json += "\"min_hum_night\":" + String(min_hum_night, 1) + ",";
    json += "\"start_time\":" + String(start_timestamp) + ",";
    json += "\"watering_days\":" + String(watering_days) + ",";
    json += "\"watering_hour\":" + String(watering_hour) + ",";
    json += "\"watering_minute\":" + String(watering_minute) + ",";
    json += "\"watering_duration\":" + String(watering_duration_sec) + ",";
    json += "\"heater_mode\":" + String(heater_mode) + ",";
    json += "\"wifi_ssid\":\"" + wifi_ssid + "\",";
    json += "\"wifi_pass\":\"" + wifi_pass + "\",";
    json += "\"ubidots_token\":\"" + ubidots_token + "\",";
    json += "\"device_label\":\"" + device_label + "\",";
    json += "\"ap_ssid\":\"" + ap_ssid + "\",";
    json += "\"ap_pass\":\"" + ap_pass + "\",";
    json += "\"rtc_time\":\"" + String(buf) + "\"";
    json += "}";
    request->send(200, "application/json", json);
  });

  server.on("/save-settings", HTTP_POST, [](AsyncWebServerRequest *request){
    // --- Валидация и сохранение (значения клэмпятся в разумные пределы, даже если запрос пришёл в обход веб-формы) ---
    if (request->hasParam("temp_target", true))  preferences.putFloat("temp_target", clampFloat(request->getParam("temp_target", true)->value().toFloat(), 0.0, 50.0));
    if (request->hasParam("temp_delta", true))   preferences.putFloat("temp_delta", clampFloat(request->getParam("temp_delta", true)->value().toFloat(), 0.1, 20.0));
    if (request->hasParam("led_on_hour", true))   preferences.putInt("led_on_hour", clampInt(request->getParam("led_on_hour", true)->value().toInt(), 0, 23));
    if (request->hasParam("led_off_hour", true))  preferences.putInt("led_off_hour", clampInt(request->getParam("led_off_hour", true)->value().toInt(), 0, 23));
    if (request->hasParam("led_on_minute", true))  preferences.putInt("led_on_minute", clampInt(request->getParam("led_on_minute", true)->value().toInt(), 0, 59));
    if (request->hasParam("led_off_minute", true)) preferences.putInt("led_off_minute", clampInt(request->getParam("led_off_minute", true)->value().toInt(), 0, 59));

    // Пары мин/макс: клэмпим в диапазон 0-100 и, если границы перепутаны местами, меняем их местами
    if (request->hasParam("fan1_min_limit", true) && request->hasParam("fan1_max_limit", true)) {
      clampPairInt(preferences, "fan1_min_limit", "fan1_max_limit",
        request->getParam("fan1_min_limit", true)->value().toInt(),
        request->getParam("fan1_max_limit", true)->value().toInt(), 0, 100);
    }
    if (request->hasParam("fan2_min_limit", true) && request->hasParam("fan2_max_limit", true)) {
      clampPairInt(preferences, "fan2_min_limit", "fan2_max_limit",
        request->getParam("fan2_min_limit", true)->value().toInt(),
        request->getParam("fan2_max_limit", true)->value().toInt(), 0, 100);
    }
    if (request->hasParam("led_min_limit", true) && request->hasParam("led_max_limit", true)) {
      clampPairInt(preferences, "led_min_limit", "led_max_limit",
        request->getParam("led_min_limit", true)->value().toInt(),
        request->getParam("led_max_limit", true)->value().toInt(), 0, 100);
    }
    if (request->hasParam("fan_night_min_limit", true) && request->hasParam("fan_night_max_limit", true)) {
      clampPairInt(preferences, "fan_night_min", "fan_night_max",
        request->getParam("fan_night_min_limit", true)->value().toInt(),
        request->getParam("fan_night_max_limit", true)->value().toInt(), 0, 100);
    }
    if (request->hasParam("min_hum_night", true) && request->hasParam("max_hum_night", true)) {
      clampPairFloat(preferences, "min_hum_night", "max_hum_night",
        request->getParam("min_hum_night", true)->value().toFloat(),
        request->getParam("max_hum_night", true)->value().toFloat(), 0.0, 100.0);
    }

    if (request->hasParam("watering_days", true)) preferences.putUChar("watering_days", (uint8_t)clampInt(request->getParam("watering_days", true)->value().toInt(), 0, 127));
    if (request->hasParam("watering_hour", true)) preferences.putInt("watering_hour", clampInt(request->getParam("watering_hour", true)->value().toInt(), 0, 23));
    if (request->hasParam("watering_minute", true)) preferences.putInt("watering_minute", clampInt(request->getParam("watering_minute", true)->value().toInt(), 0, 59));
    if (request->hasParam("watering_duration", true)) preferences.putInt("watering_dur", clampInt(request->getParam("watering_duration", true)->value().toInt(), 1, 3600));
    if (request->hasParam("heater_mode", true)) preferences.putInt("heater_mode", clampInt(request->getParam("heater_mode", true)->value().toInt(), 0, 3));
    if (request->hasParam("temp_target_night", true)) preferences.putFloat("temp_night", clampFloat(request->getParam("temp_target_night", true)->value().toFloat(), 0.0, 50.0));

    // WiFi роутера: сохраняем, только если длины корректны (SSID <= 32, пароль пусто либо 8-63 — требование WPA2)
    bool wifi_rejected = false;
    if (request->hasParam("wifi_ssid", true)) {
      String newSsid = request->getParam("wifi_ssid", true)->value();
      newSsid.trim();
      if (isValidStaSsid(newSsid)) preferences.putString("wifi_ssid", newSsid);
      else wifi_rejected = true;
    }
    if (request->hasParam("wifi_pass", true)) {
      String newPass = request->getParam("wifi_pass", true)->value();
      if (isValidStaPass(newPass)) preferences.putString("wifi_pass", newPass);
      else wifi_rejected = true;
    }
    if (request->hasParam("ubidots_token", true)) preferences.putString("ubidots_token", request->getParam("ubidots_token", true)->value());
    if (request->hasParam("device_label", true)) preferences.putString("device_label", request->getParam("device_label", true)->value());

    // Точка доступа: сохраняем, только если значения корректны — иначе можно остаться без доступа к плате
    bool ap_changed = false;
    bool ap_rejected = false;
    if (request->hasParam("ap_ssid", true)) {
      String newSsid = request->getParam("ap_ssid", true)->value();
      newSsid.trim();
      if (isValidApSsid(newSsid)) {
        preferences.putString("ap_ssid", newSsid);
        ap_changed = true;
      } else {
        ap_rejected = true;
      }
    }
    if (request->hasParam("ap_pass", true)) {
      String newPass = request->getParam("ap_pass", true)->value();
      if (isValidApPass(newPass)) {
        preferences.putString("ap_pass", newPass);
        ap_changed = true;
      } else {
        ap_rejected = true;
      }
    }

    if (request->hasParam("start_date", true)) {
      String dateStr = request->getParam("start_date", true)->value(); 
      if (dateStr.length() >= 10) {
        DateTime startDate(dateStr.substring(0,4).toInt(), dateStr.substring(5,7).toInt(), dateStr.substring(8,10).toInt(), 0, 0, 0);
        preferences.putUInt("start_time", startDate.unixtime());
      }
    }
    
    temp_target = preferences.getFloat("temp_target", 25.0);
    temp_delta = preferences.getFloat("temp_delta", 2.0);
    temp_target_night = preferences.getFloat("temp_night", 20.0);
    max_hum_night = preferences.getFloat("max_hum_night", 60.0);
    led_on_hour = preferences.getInt("led_on_hour", 6);
    led_off_hour = preferences.getInt("led_off_hour", 18);
    led_on_minute = preferences.getInt("led_on_minute", 0);
    led_off_minute = preferences.getInt("led_off_minute", 0);
    fan1_min_limit = preferences.getInt("fan1_min_limit", 20);
    fan1_max_limit = preferences.getInt("fan1_max_limit", 100);
    fan2_min_limit = preferences.getInt("fan2_min_limit", 20);
    fan2_max_limit = preferences.getInt("fan2_max_limit", 100);
    led_min_limit = preferences.getInt("led_min_limit", 10);
    led_max_limit = preferences.getInt("led_max_limit", 100);
    fan_night_min_limit = preferences.getInt("fan_night_min", 30);
    fan_night_max_limit = preferences.getInt("fan_night_max", 100);
    min_hum_night = preferences.getFloat("min_hum_night", 40.0);
    start_timestamp = preferences.getUInt("start_time", 0);

    watering_days = preferences.getUChar("watering_days", 0);
    watering_hour = preferences.getInt("watering_hour", 8);
    watering_minute = preferences.getInt("watering_minute", 0);
    watering_duration_sec = preferences.getInt("watering_dur", 30);
    heater_mode = preferences.getInt("heater_mode", 2);

    wifi_ssid = preferences.getString("wifi_ssid", DEFAULT_WIFI_SSID);
    wifi_pass = preferences.getString("wifi_pass", DEFAULT_WIFI_PASS);
    ubidots_token = preferences.getString("ubidots_token", DEFAULT_UBIDOTS_TOKEN);
    device_label = preferences.getString("device_label", DEFAULT_DEVICE_LABEL);
    ap_ssid = preferences.getString("ap_ssid", DEFAULT_AP_SSID);
    ap_pass = preferences.getString("ap_pass", DEFAULT_AP_PASS);

    // Применяем новые SSID/пароль точки доступа немедленно, без перезагрузки платы.
    // Текущие клиенты AP при этом отключатся и должны будут подключиться заново с новыми данными.
    if (ap_changed) {
      WiFi.softAP(ap_ssid.c_str(), ap_pass.length() > 0 ? ap_pass.c_str() : NULL);
    }

    if (ap_rejected || wifi_rejected) {
      String errParam = "";
      if (ap_rejected) errParam += "ap";
      if (wifi_rejected) errParam += String(errParam.length() ? "," : "") + "wifi";
      request->redirect("/settings?error=" + errParam);
    } else {
      request->redirect("/settings");
    }
  });

  server.on("/set-time", HTTP_POST, [](AsyncWebServerRequest *request){
    if (request->hasParam("datetime", true)) {
      String dtStr = request->getParam("datetime", true)->value(); 
      DateTime userTime(dtStr.substring(0,4).toInt(), dtStr.substring(5,7).toInt(), dtStr.substring(8,10).toInt(), dtStr.substring(11,13).toInt(), dtStr.substring(14,16).toInt(), 0);
      if (rtc_online) {
        rtc.adjust(userTime);
      } else {
        backup_unixtime = userTime.unixtime();
        last_rtc_check_ms = millis();
      }
    }
    request->redirect("/settings");
  });

  server.on("/api/log", HTTP_GET, [](AsyncWebServerRequest *request){
      String logDate = request->hasParam("date") ? request->getParam("date")->value() : "";
      if (logDate == "") {
        DateTime now = getSafeDateTime();
        char buf[16];
        snprintf(buf, sizeof(buf), "%04d-%02d-%02d", now.year(), now.month(), now.day());
        logDate = String(buf);
      }
      String filename = "/" + logDate + ".csv";
      if (SD.exists(filename)) {
        request->send(SD, filename, "text/csv"); // Убедись, что тип text/csv
      } else {
        request->send(200, "text/plain", "timestamp;temp;hum;led;fan1;fan2\n");
      }
  });

  server.begin();

  ledcAttach(LED_PWM_PIN, PWM_FREQ, PWM_RES);
  ledcAttach(FAN1_PWM_PIN, PWM_FREQ, PWM_RES);
  ledcAttach(FAN2_PWM_PIN, PWM_FREQ, PWM_RES);
}

void loop() {
  static unsigned long lastLogTime = 0;
  unsigned long currentMillis = millis();
  tryRecoverRTC(currentMillis); // Не блокирует: сам ограничивает частоту попыток внутри
  DateTime now = getSafeDateTime();

  if (currentMillis - lastLogTime >= 10000) {
    lastLogTime = currentMillis;

    int current_hour = now.hour();
    int current_minutes = current_hour * 60 + now.minute();
    int on_minutes = led_on_hour * 60 + led_on_minute;
    int off_minutes = led_off_hour * 60 + led_off_minute;

    if (on_minutes == off_minutes) is_day = true; // время включения == времени выключения — считаем "весь день"
    else if (on_minutes < off_minutes) is_day = (current_minutes >= on_minutes && current_minutes < off_minutes);
    else is_day = (current_minutes >= on_minutes || current_minutes < off_minutes);

    int pwm_fan1_min = map(fan1_min_limit, 0, 100, 0, 255);
    int pwm_fan1_max = map(fan1_max_limit, 0, 100, 0, 255);
    int pwm_fan2_min = map(fan2_min_limit, 0, 100, 0, 255);
    int pwm_fan2_max = map(fan2_max_limit, 0, 100, 0, 255);
    int pwm_led_min = map(led_min_limit, 0, 100, 0, 255);
    int pwm_led_max = map(led_max_limit, 0, 100, 0, 255);
    int pwm_fan_night_min = map(fan_night_min_limit, 0, 100, 0, 255);
    int pwm_fan_night_max = map(fan_night_max_limit, 0, 100, 0, 255);

    int target_led, target_fan1, target_fan2;
    float read_temp = current_temp; // По умолчанию — последнее известное валидное значение, а не 0.0
    float read_hum = current_hum;
    bool got_valid_reading = false;

    // Чтение датчика с проверкой на ошибку
    sensors_event_t humidity, temp;
    if (sht_online) {
      if (sht40.getEvent(&humidity, &temp)) {
        read_temp = temp.temperature;
        read_hum = humidity.relative_humidity;

        // Защита от "зависших" нереалистичных данных (за пределами работы датчика)
        if (read_temp < -20.0 || read_temp > 80.0 || read_hum < 0.0 || read_hum > 100.0) {
          sht_online = false;
        } else {
          got_valid_reading = true;
        }
      } else {
        sht_online = false;
      }
    }

    // Датчик офлайн — периодически пробуем восстановиться, не дожидаясь перезагрузки платы.
    // Нужно несколько (SHT_RECOVERY_STREAK_NEEDED) подряд успешных попыток с интервалом
    // SHT_RETRY_INTERVAL_MS, прежде чем снова начать доверять показаниям.
    if (!sht_online && (currentMillis - last_sht_retry >= SHT_RETRY_INTERVAL_MS)) {
      last_sht_retry = currentMillis;
      sensors_event_t retryHumidity, retryTemp;
      bool retry_ok = sht40.begin() && sht40.getEvent(&retryHumidity, &retryTemp) &&
                       retryTemp.temperature >= -20.0 && retryTemp.temperature <= 80.0 &&
                       retryHumidity.relative_humidity >= 0.0 && retryHumidity.relative_humidity <= 100.0;

      if (retry_ok) {
        sht_recovery_streak++;
        Serial.printf("[SHT4x] Попытка восстановления %d/%d успешна\n", sht_recovery_streak, SHT_RECOVERY_STREAK_NEEDED);
        if (sht_recovery_streak >= SHT_RECOVERY_STREAK_NEEDED) {
          sht_online = true;
          got_valid_reading = true;
          read_temp = retryTemp.temperature;
          read_hum = retryHumidity.relative_humidity;
          sht_recovery_streak = 0;
          Serial.println("[SHT4x] Датчик восстановлен, выходим из аварийного режима.");
        }
      } else {
        sht_recovery_streak = 0; // Сбрасываем счётчик серии при любой неудачной попытке
      }
    }

    // ЛОГИКА АВАРИЙНОГО РЕЖИМА ИЛИ НОРМАЛЬНОЙ РАБОТЫ
    if (!sht_online) {
      // --- АВАРИЯ: Датчик сломан. Включаем безопасный пресет ---
      // Вентиляторы на 50% выбранного диапазона (день — температурный диапазон, ночь — ночной диапазон)
      if (is_day) {
        target_fan1 = map(50, 0, 100, pwm_fan1_min, pwm_fan1_max);
        target_fan2 = map(50, 0, 100, pwm_fan2_min, pwm_fan2_max);
      } else {
        target_fan1 = map(50, 0, 100, pwm_fan_night_min, pwm_fan_night_max);
        target_fan2 = target_fan1;
      }
      // Светильник на минимальный уровень дня, чтобы не сжечь растения светом/жаром
      target_led = is_day ? pwm_led_min : 0; 
      
      // Датчик недоступен — не доверяем показаниям, обогрев выключаем из соображений безопасности
      heater_active = false;
      digitalWrite(HEATER_PIN, LOW);
      
      Serial.println("[АВАРИЙНЫЙ РЕЖИМ]: Отказ SHT4x! Климат зафиксирован на безопасных уровнях.");
    } 
    else {
      // --- НОРМАЛЬНАЯ РАБОТА ---
      // Защита от temp_delta == 0, чтобы map() не делил на ноль
      float safe_delta = max(temp_delta, 0.1f);
      float current_min = temp_target - safe_delta;
      float current_max = temp_target + safe_delta;

      // Обогрев: своя цель ночью (temp_target_night), днём — общая temp_target.
      // На вентиляторы/лампу (current_min/current_max выше) это не влияет — они всегда считаются от дневной temp_target.
      float heater_target = is_day ? temp_target : temp_target_night;
      float heater_min = heater_target - safe_delta;

      bool heater_schedule_ok = (heater_mode == 2) || (heater_mode == 0 && is_day) || (heater_mode == 1 && !is_day);
      if (!heater_schedule_ok) {
        heater_active = false;
      } else if (!heater_active && read_temp <= heater_min) {
        heater_active = true;
      } else if (heater_active && read_temp >= heater_target) {
        heater_active = false;
      }
      digitalWrite(HEATER_PIN, heater_active ? HIGH : LOW);

      if (read_temp <= current_min) {
        target_led = is_day ? pwm_led_max : 0;
        target_fan1 = pwm_fan1_min;
        target_fan2 = pwm_fan2_min;
      } 
      else if (read_temp >= current_max) {
        target_led = is_day ? pwm_led_min : 0;
        target_fan1 = pwm_fan1_max; 
        target_fan2 = pwm_fan2_max;
      } 
      else {
        target_led = is_day ? map(read_temp * 100, current_min * 100, current_max * 100, pwm_led_max, pwm_led_min) : 0;
        target_fan1 = map(read_temp * 100, current_min * 100, current_max * 100, pwm_fan1_min, pwm_fan1_max);
        target_fan2 = map(read_temp * 100, current_min * 100, current_max * 100, pwm_fan2_min, pwm_fan2_max);
      }

      if (!is_day) {
        // НОЧЬ: оба вентилятора управляются влажностью с плавным (пропорциональным) регулированием скорости,
        // независимо от дневной температурной логики выше. Диапазон скорости задаётся отдельно (fan_night_min/max_limit).
        // min_hum_night — нижняя граница (мин. скорость), max_hum_night — верхняя граница (макс. скорость).
        float night_hum_lo = min_hum_night;
        float night_hum_hi = max_hum_night;
        int night_fan_pwm;

        if (night_hum_hi <= night_hum_lo) {
          // Некорректная настройка (границы совпадают/перепутаны) — работаем по порогу без плавности
          night_fan_pwm = (read_hum >= night_hum_hi) ? pwm_fan_night_max : pwm_fan_night_min;
        } else if (read_hum <= night_hum_lo) {
          night_fan_pwm = pwm_fan_night_min;
        } else if (read_hum >= night_hum_hi) {
          night_fan_pwm = pwm_fan_night_max;
        } else {
          night_fan_pwm = map(read_hum * 100, night_hum_lo * 100, night_hum_hi * 100, pwm_fan_night_min, pwm_fan_night_max);
        }

        target_fan1 = night_fan_pwm;
        target_fan2 = night_fan_pwm;
      }
    }

    // Безопасно обновляем глобальные переменные под мьютексом
    if (xSemaphoreTake(xMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
      current_temp = read_temp;
      current_hum = read_hum;
      current_led_pwm = target_led;
      current_fan1_pwm = target_fan1;
      current_fan2_pwm = target_fan2;
      xSemaphoreGive(xMutex);
    }

    // Управляем исполнительными устройствами
    ledcWrite(LED_PWM_PIN, current_led_pwm);
    ledcWrite(FAN1_PWM_PIN, current_fan1_pwm);
    ledcWrite(FAN2_PWM_PIN, current_fan2_pwm);
  }

  // Запись лога на SD-карту с флагами состояния
  static unsigned long lastLogBackupTime = 0;
  if (currentMillis - lastLogBackupTime >= 600000) {
    lastLogBackupTime = currentMillis;
    char logFilename[20];
    snprintf(logFilename, sizeof(logFilename), "/%04d-%02d-%02d.csv", now.year(), now.month(), now.day());

    bool fileExists = SD.exists(logFilename);
    File logFile = SD.open(logFilename, FILE_APPEND);
    if (logFile) {
      if (!fileExists) logFile.println("timestamp;temp;hum;led;fan1;fan2;sht_ok;rtc_ok");
      logFile.print(now.timestamp(DateTime::TIMESTAMP_FULL)); logFile.print(";");
      logFile.print(current_temp, 2); logFile.print(";");
      logFile.print(current_hum, 2); logFile.print(";");
      logFile.print(current_led_pwm); logFile.print(";");
      logFile.print(current_fan1_pwm); logFile.print(";");
      logFile.print(current_fan2_pwm); logFile.print(";");
      logFile.print(sht_online ? "1" : "0"); logFile.print(";");
      logFile.println(rtc_online ? "1" : "0");
      logFile.close();
    }
  }

  // --- АВТОПОЛИВ ---
  static unsigned long lastWaterCheck = 0;
  if (currentMillis - lastWaterCheck >= 1000) {
    lastWaterCheck = currentMillis;
    DateTime now_w = getSafeDateTime();

    // RTClib: dayOfTheWeek() возвращает 0=Вс...6=Сб. Переводим в формат watering_days: 0=Пн...6=Вс
    int rtc_dow = now_w.dayOfTheWeek();
    int iso_dow = (rtc_dow == 0) ? 6 : rtc_dow - 1;
    uint32_t today_code = now_w.unixtime() / 86400;

    if (!pump_active) {
      bool day_enabled = (watering_days >> iso_dow) & 0x01;
      if (day_enabled && now_w.hour() == watering_hour && now_w.minute() == watering_minute && last_watering_day != today_code) {
        pump_active = true;
        pump_start_time = now_w.unixtime();
        last_watering_day = today_code;
        digitalWrite(PUMP_PIN, HIGH);
        Serial.println("[ПОЛИВ] Старт автополива");
      }
    } else {
      if (now_w.unixtime() - pump_start_time >= (uint32_t)watering_duration_sec) {
        pump_active = false;
        digitalWrite(PUMP_PIN, LOW);
        Serial.println("[ПОЛИВ] Полив завершён");
      }
    }
  }

  esp_task_wdt_reset();
}