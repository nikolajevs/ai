#include <esp_task_wdt.h>
#include <Arduino.h>
#include <stdarg.h>
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
#include <WiFiClientSecure.h>
#include <vector>

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
#define I2C_SDA_PIN   21 // Стандартные пины I2C для ESP32 (то, что использует Wire.begin() без аргументов)
#define I2C_SCL_PIN   22
#define WATER_LEVEL_PIN 32 // Датчик уровня воды в баке (свободный GPIO, не занят другой периферией)

// --- Кольцевой буфер для показа Serial.print()-сообщений на веб-странице (/api/log) ---
#define LOG_BUFFER_SIZE 4096
static char logBuffer[LOG_BUFFER_SIZE];
static volatile size_t logHead = 0;
static volatile bool logWrapped = false;
static portMUX_TYPE logMux = portMUX_INITIALIZER_UNLOCKED;

void logRaw(const char *data, size_t len) {
  portENTER_CRITICAL(&logMux);
  for (size_t i = 0; i < len; i++) {
    logBuffer[logHead] = data[i];
    logHead = (logHead + 1) % LOG_BUFFER_SIZE;
    if (logHead == 0) logWrapped = true;
  }
  portEXIT_CRITICAL(&logMux);
}

// Замена logPrintln()/logPrintf() — пишет и на аппаратный UART, и в буфер для веба.
// Core 0 (задача Ubidots) и Core 1 (loop/setup) могут писать одновременно, поэтому буфер
// защищён спинлоком (portENTER_CRITICAL), а не мьютексом — запись короткая и частая.
void logPrintln(const String &msg) {
  Serial.println(msg);
  String line = msg + "\n";
  logRaw(line.c_str(), line.length());
}

void logPrintf(const char *fmt, ...) {
  char buf[192];
  va_list args;
  va_start(args, fmt);
  vsnprintf(buf, sizeof(buf), fmt, args);
  va_end(args);
  Serial.print(buf);
  logRaw(buf, strlen(buf));
}

// Возвращает содержимое буфера в правильном хронологическом порядке одной строкой.
// Под спинлоком делаем ТОЛЬКО memcpy: собирать String (а значит, дёргать кучу) с
// выключенными прерываниями нельзя — на 4 КБ это тысячи реаллокаций и реальный риск
// паники/срыва watchdog, а страница дёргает /api/console каждые 3 секунды.
// Буфер статический (4 КБ на стеке async-задачи не поместятся); обработчики
// AsyncWebServer выполняются последовательно в одной задаче, поэтому гонки за него нет.
String getLogSnapshot() {
  static char snapshotCopy[LOG_BUFFER_SIZE + 1];
  size_t len;

  portENTER_CRITICAL(&logMux);
  size_t head = logHead;
  bool wrapped = logWrapped;
  if (!wrapped) {
    memcpy(snapshotCopy, logBuffer, head);
    len = head;
  } else {
    size_t tailLen = LOG_BUFFER_SIZE - head;
    memcpy(snapshotCopy, logBuffer + head, tailLen);
    memcpy(snapshotCopy + tailLen, logBuffer, head);
    len = LOG_BUFFER_SIZE;
  }
  portEXIT_CRITICAL(&logMux);

  snapshotCopy[len] = 0;
  return String(snapshotCopy);
}

// Экранирование строки для безопасной вставки в JSON (используется для имён файлов SD —
// теоретически может содержать что угодно, в отличие от контролируемых нами полей настроек)
String jsonEscape(const char* s) {
  String out;
  for (int i = 0; s[i] != '\0'; i++) {
    char c = s[i];
    if (c == '"' || c == '\\') { out += '\\'; out += c; }
    else if (c == '\n' || c == '\r' || c == '\t') { out += ' '; }
    else if ((uint8_t)c < 0x20) { /* прочие control-символы пропускаем */ }
    else out += c;
  }
  return out;
}

// Та же защита для String: SSID, пароль AP и device_label вводит пользователь,
// и одна кавычка внутри ломала разбор JSON на странице настроек.
String jsonEscape(const String &s) { return jsonEscape(s.c_str()); }

// uint64_t -> String: обычный String(uint64_t) в Arduino не поддерживается,
// а SD.totalBytes()/usedBytes() возвращают именно uint64_t
String u64str(uint64_t v) {
  if (v == 0) return "0";
  char buf[21];
  int i = 20;
  buf[i] = '\0';
  while (v > 0 && i > 0) { buf[--i] = '0' + (char)(v % 10); v /= 10; }
  return String(&buf[i]);
}

// Удаляет из корня SD только файлы логов (*.csv). Раньше здесь был рекурсивный
// wipePath("/"), который сносил вообще всё содержимое карты — включая файлы, не имеющие
// к логам отношения. Сначала собираем список, потом удаляем: удалять во время обхода
// каталога нельзя, это ломает итератор FatFS.
int clearCsvLogs() {
  int removed = 0;
  std::vector<String> victims;

  File dir = SD.open("/");
  if (!dir) return 0;
  if (!dir.isDirectory()) { dir.close(); return 0; }

  File entry = dir.openNextFile();
  while (entry) {
    if (!entry.isDirectory()) {
      String full = String(entry.path()); // абсолютный путь (ESP32 core 3.x)
      String lower = full;
      lower.toLowerCase();
      if (lower.endsWith(".csv")) victims.push_back(full);
    }
    entry.close();
    entry = dir.openNextFile();
  }
  dir.close();

  for (size_t i = 0; i < victims.size(); i++) {
    if (SD.remove(victims[i])) removed++;
  }
  return removed;
}

#define PWM_FREQ      5000
#define PWM_RES       8

// --- Значения по умолчанию для настроек (единый источник правды) ---
// Используются и при объявлении переменных, и как fallback в loadAllSettingsFromNVS().
// Раньше два списка расходились: led_off_hour был 23 в объявлении и 18 в NVS, heater_mode — 3 и 2.
#define DEF_TEMP_TARGET       25.0f
#define DEF_TEMP_DELTA        2.0f
#define DEF_TEMP_NIGHT        20.0f
#define DEF_MAX_HUM_NIGHT     60.0f
#define DEF_MIN_HUM_NIGHT     40.0f
#define DEF_LED_ON_HOUR       6
#define DEF_LED_OFF_HOUR      18
#define DEF_LED_ON_MINUTE     0
#define DEF_LED_OFF_MINUTE    0
#define DEF_FAN_MIN_LIMIT     20
#define DEF_FAN_MAX_LIMIT     100
#define DEF_LED_MIN_LIMIT     10
#define DEF_LED_MAX_LIMIT     100
#define DEF_FAN_NIGHT_MIN     30
#define DEF_FAN_NIGHT_MAX     100
#define DEF_WATERING_DAYS     0
#define DEF_WATERING_HOUR     8
#define DEF_WATERING_MINUTE   0
#define DEF_WATERING_DUR_SEC  30
#define DEF_WATER_SENSOR      false
#define DEF_HEATER_MODE       2

// --- Переменные параметров климата и автоматизации ---
float temp_target = DEF_TEMP_TARGET;
float temp_delta = DEF_TEMP_DELTA;
float temp_target_night = DEF_TEMP_NIGHT;  // Целевая температура для обогревателя ночью (гистерезис temp_delta общий)
float max_hum_night = DEF_MAX_HUM_NIGHT;

int led_on_hour = DEF_LED_ON_HOUR;
int led_off_hour = DEF_LED_OFF_HOUR;
int led_on_minute = DEF_LED_ON_MINUTE;
int led_off_minute = DEF_LED_OFF_MINUTE;
int fan1_min_limit = DEF_FAN_MIN_LIMIT;
int fan1_max_limit = DEF_FAN_MAX_LIMIT;
int fan2_min_limit = DEF_FAN_MIN_LIMIT;
int fan2_max_limit = DEF_FAN_MAX_LIMIT;
int led_min_limit = DEF_LED_MIN_LIMIT;
int led_max_limit = DEF_LED_MAX_LIMIT;
int fan_night_min_limit = DEF_FAN_NIGHT_MIN;  // Ночной минимум скорости обоих вентиляторов, % (при низкой влажности)
int fan_night_max_limit = DEF_FAN_NIGHT_MAX;  // Ночной максимум скорости обоих вентиляторов, % (при высокой влажности)
float min_hum_night = DEF_MIN_HUM_NIGHT;  // Влажность, ниже которой ночью вентиляторы держат минимум (верхняя граница — max_hum_night)
uint32_t start_timestamp = 0; 

// --- Настройки автополива ---
uint8_t watering_days = DEF_WATERING_DAYS;  // битовая маска: бит0=Пн, бит1=Вт, ... бит6=Вс
int watering_hour = DEF_WATERING_HOUR;
int watering_minute = DEF_WATERING_MINUTE;
int watering_duration_sec = DEF_WATERING_DUR_SEC;
bool water_sensor_enabled = DEF_WATER_SENSOR;  // Учитывать ли датчик уровня воды перед стартом/во время полива

// --- Состояние насоса ---
bool pump_active = false;
unsigned long pump_start_ms = 0;   // Отсчёт длительности полива по millis(), а не по RTC
uint32_t last_watering_day = 0;   // защита от повторного срабатывания в ту же минуту

// --- Настройки обогрева ---
// heater_mode: 0 = только день, 1 = только ночь, 2 = всегда, 3 = никогда
int heater_mode = DEF_HEATER_MODE;
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

// Время и запросы к RTC трогает только loop(). Веб-обработчики крутятся в задаче
// AsyncWebServer (другое ядро): раньше они звали getSafeDateTime() и rtc.adjust() напрямую,
// то есть лезли в I2C параллельно с опросом SHT4x и одновременно правили rtc_online/backup_unixtime.
volatile uint32_t cached_unixtime = 0;  // Снимок времени для веб-обработчиков, обновляет loop()
volatile uint32_t pending_time_set = 0; // Запрос "выставить часы" с формы; применяет loop()

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

// "YYYY-MM-DD" -> компоненты. Раньше даты брались из формы как есть: короткая или
// битая строка давала substring("") -> toInt() == 0, и в RTC улетало 0000-00-00.
bool parseDate(const String &str, int &y, int &m, int &d) {
  if (str.length() < 10) return false;
  for (int i = 0; i < 10; i++) {
    char c = str[i];
    if (i == 4 || i == 7) { if (c != '-') return false; }
    else if (c < '0' || c > '9') return false;
  }
  y = str.substring(0, 4).toInt();
  m = str.substring(5, 7).toInt();
  d = str.substring(8, 10).toInt();
  return y >= 2000 && y <= 2099 && m >= 1 && m <= 12 && d >= 1 && d <= 31;
}

// "YYYY-MM-DDTHH:MM" — формат, который отдаёт <input type="datetime-local">
bool parseDateTimeLocal(const String &str, DateTime &out) {
  int y, m, d;
  if (!parseDate(str, y, m, d)) return false;
  if (str.length() < 16 || str[13] != ':') return false;
  for (int i = 11; i < 16; i++) {
    if (i == 13) continue;
    if (str[i] < '0' || str[i] > '9') return false;
  }
  int hh = str.substring(11, 13).toInt();
  int mm = str.substring(14, 16).toInt();
  if (hh > 23 || mm > 59) return false;
  out = DateTime(y, m, d, hh, mm, 0);
  return true;
}

// Имя файла лога собирается из параметра ?date=, поэтому его форма проверяется строго:
// ровно YYYY-MM-DD. Иначе запрос вида ?date=../../secret уводил чтение за пределы корня.
bool isValidLogDate(const String &str) {
  int y, m, d;
  return str.length() == 10 && parseDate(str, y, m, d);
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
  ClimateData localData;
  // Копии строковых настроек: работаем с ними, а не с глобалками, которые
  // в любой момент может перезаписать обработчик /save-settings с другого ядра
  String ssid, pass, token, label;

  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(120000)); // 2 минуты сна

    logPrintln("[Core 0] Пробуждение задачи Ubidots...");

    if (xSemaphoreTake(xMutex, pdMS_TO_TICKS(1000)) == pdTRUE) {
      localData.temp = current_temp;
      localData.hum = current_hum;
      localData.led = current_led_pwm;
      localData.fan1 = current_fan1_pwm;
      localData.fan2 = current_fan2_pwm;
      localData.sht_ok = sht_online;
      ssid = wifi_ssid;
      pass = wifi_pass;
      token = ubidots_token;
      label = device_label;
      xSemaphoreGive(xMutex); 
    } else {
      continue; 
    }

    if (ssid.length() == 0) {
      logPrintln("[Core 0] Wi-Fi роутера не настроен — телеметрия пропущена.");
      continue;
    }

    // Режим AP+STA поднят один раз в setup() и больше не переключается. Раньше задача
    // каждые 2 минуты делала mode()/disconnect(true), из-за чего точка доступа
    // передёргивалась и телефон отваливался от веб-интерфейса прямо во время работы.
    if (WiFi.status() != WL_CONNECTED) {
      WiFi.begin(ssid.c_str(), pass.c_str());
      int attempts = 0;
      while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        vTaskDelay(pdMS_TO_TICKS(500));
        attempts++;
      }
    }

    if (WiFi.status() != WL_CONNECTED) {
      logPrintln("[Core 0] Нет связи с роутером — телеметрия пропущена.");
      continue;
    }

    String payload = "{";
    if (localData.sht_ok) {
      payload += "\"temperature\":" + String(localData.temp, 2) + ",";
      payload += "\"humidity\":" + String(localData.hum, 2) + ",";
    }
    payload += "\"led-power\":" + String(round(localData.led / 2.55)) + ",";
    payload += "\"fan1-power\":" + String(round(localData.fan1 / 2.55)) + ",";
    payload += "\"fan2-power\":" + String(round(localData.fan2 / 2.55)) + ",";
    payload += "\"sensor-status\":" + String(localData.sht_ok ? 1 : 0); // Статус датчика в облако
    payload += "}";

    // HTTPS вместо HTTP: токен больше не уходит открытым текстом по эфиру.
    // setInsecure() — без проверки сертификата (корневых CA на плате нет), но канал зашифрован.
    WiFiClientSecure client;
    client.setInsecure();
    HTTPClient http;
    http.setTimeout(10000);

    if (http.begin(client, "https://industrial.api.ubidots.com/api/v1.6/devices/" + label)) {
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Auth-Token", token);
      int code = http.POST(payload);
      // Раньше код ответа присваивался и молча выбрасывался — узнать, дошла ли
      // телеметрия и не протух ли токен, было невозможно
      if (code > 0) logPrintf("[Core 0] Ubidots: HTTP %d\n", code);
      else          logPrintf("[Core 0] Ubidots: ошибка отправки (%d)\n", code);
      http.end();
    } else {
      logPrintln("[Core 0] Ubidots: не удалось открыть соединение.");
    }
  }
}

// Функция получения безопасного времени (из RTC или программного бэкапа)
// Принудительное восстановление I2C-шины: если одно из устройств (SHT4x/RTC) зависло
// посреди транзакции и держит SDA в LOW, обычный Wire.begin()/sensor.begin() это НЕ чинит —
// нужно вручную "протактовать" SCL, чтобы slave-устройство доотправило начатый байт и
// освободило линию, затем сформировать STOP и переинициализировать Wire.
void recoverI2CBus() {
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  pinMode(I2C_SCL_PIN, OUTPUT);
  digitalWrite(I2C_SCL_PIN, HIGH);

  if (digitalRead(I2C_SDA_PIN) == HIGH) {
    // Шина уже свободна — восстанавливать нечего, просто переинициализируем Wire
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    return;
  }

  logPrintln("[I2C] SDA удерживается в LOW — пробуем восстановить шину...");

  // До 9 тактов SCL — по спецификации I2C этого достаточно, чтобы slave, зависший
  // в середине передачи байта, дотактовал его до конца и отпустил SDA
  for (int i = 0; i < 9 && digitalRead(I2C_SDA_PIN) == LOW; i++) {
    digitalWrite(I2C_SCL_PIN, LOW);
    delayMicroseconds(5);
    digitalWrite(I2C_SCL_PIN, HIGH);
    delayMicroseconds(5);
  }

  // Формируем STOP-условие вручную (SDA LOW->HIGH, пока SCL HIGH), чтобы сбросить
  // внутренний автомат состояний slave-устройства в исходное состояние
  pinMode(I2C_SDA_PIN, OUTPUT);
  digitalWrite(I2C_SDA_PIN, LOW);
  delayMicroseconds(5);
  digitalWrite(I2C_SCL_PIN, HIGH);
  delayMicroseconds(5);
  digitalWrite(I2C_SDA_PIN, HIGH);
  delayMicroseconds(5);

  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  if (digitalRead(I2C_SDA_PIN) == LOW) {
    logPrintln("[I2C] Восстановить шину не удалось — SDA всё ещё LOW.");
  } else {
    logPrintln("[I2C] Шина восстановлена.");
  }

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
}

// Читает датчик уровня воды. Предполагаемая схема: пин подтянут к VCC (INPUT_PULLUP),
// датчик замыкает его на GND, когда вода есть — LOW = "вода в норме", HIGH = "воды нет".
// Если у конкретного датчика логика обратная — поменяй местами LOW/HIGH здесь, в одном месте.
bool isWaterAvailable() {
  return digitalRead(WATER_LEVEL_PIN) == LOW;
}

// Грубая, но честная проверка правдоподобности времени из RTC. Прежнее условие
// (now.minute() <= 60 && now.hour() <= 60) не ловило ничего: оба поля — uint8_t и в
// принципе не могут быть больше 60. Год отсекает DS3231 с севшей батарейкой —
// такой просыпается на заводской дате (2000 или 2021 год).
bool isPlausibleDateTime(const DateTime &t) {
  return t.isValid() && t.hour() < 24 && t.minute() < 60 && t.second() < 60 &&
         t.year() >= 2024 && t.year() <= 2099;
}

DateTime getSafeDateTime() {
  if (rtc_online) {
    DateTime now = rtc.now();
    if (isPlausibleDateTime(now)) {
      backup_unixtime = now.unixtime(); // Синхронизируем бэкап
      last_rtc_check_ms = millis();     // ...и точку отсчёта программного таймера
      return now;
    }
    logPrintln("[КРИТИКА] RTC вернул некорректную дату! Переход на программный таймер.");
    rtc_online = false;
    last_rtc_check_ms = millis(); // Иначе первый же расчёт ниже прыгнет на часы вперёд
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

// Время для веб-обработчиков: готовый снимок, без обращения к железу с чужого ядра
DateTime getWebDateTime() {
  return DateTime((uint32_t)cached_unixtime);
}

// Периодически пробует восстановить RTC после сбоя, без перезагрузки платы —
// та же схема, что и для датчика SHT4x. Нужно несколько подряд успешных
// попыток чтения вменяемой даты, прежде чем снова начать доверять RTC.
void tryRecoverRTC(unsigned long currentMillis) {
  if (rtc_online) return;
  if (currentMillis - last_rtc_retry < RTC_RETRY_INTERVAL_MS) return;
  last_rtc_retry = currentMillis;
  recoverI2CBus(); // Освобождаем шину на случай, если она физически "залипла"

  bool retry_ok = false;
  if (rtc.begin()) {
    DateTime now = rtc.now();
    // 2024..2099 — грубая защита от "проснувшегося после разряда батарейки" RTC,
    // который обычно сбрасывается на заводскую дату (например, 2000 или 2021 год)
    if (isPlausibleDateTime(now)) {
      retry_ok = true;
      rtc_recovery_streak++;
      logPrintf("[RTC] Попытка восстановления %d/%d успешна\n", rtc_recovery_streak, RTC_RECOVERY_STREAK_NEEDED);
      if (rtc_recovery_streak >= RTC_RECOVERY_STREAK_NEEDED) {
        rtc_online = true;
        backup_unixtime = now.unixtime();
        last_rtc_check_ms = millis();
        rtc_recovery_streak = 0;
        logPrintln("[RTC] DS3231 восстановлен, выходим из программного таймера.");
      }
    }
  }
  if (!retry_ok) {
    rtc_recovery_streak = 0; // Сбрасываем счётчик серии при любой неудачной попытке
  }
}

// Единая точка загрузки всех настроек из NVS (Preferences) — вызывается и при старте платы,
// и сразу после сохранения на /save-settings, чтобы не держать два места с одинаковым списком
// полей в ручную синхронизации (именно так на днях "потерялась" temp_target_night в одном из
// трёх мест при переименовании NVS-ключа). preferences.begin() сюда не входит — вызывается один
// раз в setup() до первого использования этой функции.
void loadAllSettingsFromNVS() {
  // Вызывается из setup() и из обработчика /save-settings, то есть из задачи веб-сервера.
  // Строковые настройки берём под мьютексом: присваивание String освобождает старый буфер,
  // а задача Ubidots в этот момент может читать wifi_ssid.c_str() — это use-after-free.
  bool locked = (xMutex != NULL) && (xSemaphoreTake(xMutex, pdMS_TO_TICKS(100)) == pdTRUE);

  temp_target = preferences.getFloat("temp_target", DEF_TEMP_TARGET);
  temp_delta = preferences.getFloat("temp_delta", DEF_TEMP_DELTA);
  temp_target_night = preferences.getFloat("temp_night", DEF_TEMP_NIGHT);
  max_hum_night = preferences.getFloat("max_hum_night", DEF_MAX_HUM_NIGHT);
  led_on_hour = preferences.getInt("led_on_hour", DEF_LED_ON_HOUR);
  led_off_hour = preferences.getInt("led_off_hour", DEF_LED_OFF_HOUR);
  led_on_minute = preferences.getInt("led_on_minute", DEF_LED_ON_MINUTE);
  led_off_minute = preferences.getInt("led_off_minute", DEF_LED_OFF_MINUTE);
  fan1_min_limit = preferences.getInt("fan1_min_limit", DEF_FAN_MIN_LIMIT);
  fan1_max_limit = preferences.getInt("fan1_max_limit", DEF_FAN_MAX_LIMIT);
  fan2_min_limit = preferences.getInt("fan2_min_limit", DEF_FAN_MIN_LIMIT);
  fan2_max_limit = preferences.getInt("fan2_max_limit", DEF_FAN_MAX_LIMIT);
  led_min_limit = preferences.getInt("led_min_limit", DEF_LED_MIN_LIMIT);
  led_max_limit = preferences.getInt("led_max_limit", DEF_LED_MAX_LIMIT);
  fan_night_min_limit = preferences.getInt("fan_night_min", DEF_FAN_NIGHT_MIN);
  fan_night_max_limit = preferences.getInt("fan_night_max", DEF_FAN_NIGHT_MAX);
  min_hum_night = preferences.getFloat("min_hum_night", DEF_MIN_HUM_NIGHT);
  start_timestamp = preferences.getUInt("start_time", 0);

  last_watering_day = preferences.getUInt("last_water", 0);
  watering_days = preferences.getUChar("watering_days", DEF_WATERING_DAYS);
  watering_hour = preferences.getInt("watering_hour", DEF_WATERING_HOUR);
  watering_minute = preferences.getInt("watering_minute", DEF_WATERING_MINUTE);
  watering_duration_sec = preferences.getInt("watering_dur", DEF_WATERING_DUR_SEC);
  water_sensor_enabled = preferences.getBool("water_sensor", DEF_WATER_SENSOR);
  heater_mode = preferences.getInt("heater_mode", DEF_HEATER_MODE);

  wifi_ssid = preferences.getString("wifi_ssid", DEFAULT_WIFI_SSID);
  wifi_pass = preferences.getString("wifi_pass", DEFAULT_WIFI_PASS);
  ubidots_token = preferences.getString("ubidots_token", DEFAULT_UBIDOTS_TOKEN);
  device_label = preferences.getString("device_label", DEFAULT_DEVICE_LABEL);
  ap_ssid = preferences.getString("ap_ssid", DEFAULT_AP_SSID);
  ap_pass = preferences.getString("ap_pass", DEFAULT_AP_PASS);

  if (locked) xSemaphoreGive(xMutex);
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
  delay(300); // Даём I2C-шине и датчикам (SHT4x/RTC) стабилизироваться после подачи питания —
              // без этой паузы begin() может провалиться из-за гонки при старте платы
  recoverI2CBus(); // На случай, если шина осталась "залипшей" ещё с прошлого включения
  
  xMutex = xSemaphoreCreateMutex();

  preferences.begin("grow-box", false);
  loadAllSettingsFromNVS();
  // На случай испорченных/некорректных значений в NVS откатываемся на дефолт, чтобы не остаться без доступа к плате
  if (!isValidApSsid(ap_ssid)) ap_ssid = DEFAULT_AP_SSID;
  if (!isValidApPass(ap_pass)) ap_pass = DEFAULT_AP_PASS;

  // Безопасная инициализация датчиков с проверкой работоспособности.
  // Пробуем несколько раз с паузой — при старте платы I2C-шина/датчик могут быть
  // ещё не готовы (просадка питания от одновременного старта WiFi/вентиляторов/SD).
  sht_online = false;
  for (int i = 0; i < 5 && !sht_online; i++) {
    if (sht40.begin()) {
      sht_online = true;
    } else {
      logPrintf("[SHT4x] Попытка инициализации %d/5 не удалась, повтор через 200мс...\n", i + 1);
      delay(200);
    }
  }
  if (!sht_online) logPrintln("ОШИБКА: SHT4x не найден после 5 попыток!");

  rtc_online = false;
  for (int i = 0; i < 5 && !rtc_online; i++) {
    if (rtc.begin()) {
      rtc_online = true;
    } else {
      logPrintf("[RTC] Попытка инициализации %d/5 не удалась, повтор через 200мс...\n", i + 1);
      delay(200);
    }
  }
  if (!rtc_online) {
    logPrintln("ОШИБКА: RTC DS3231 не найден после 5 попыток!");
    last_rtc_check_ms = millis();
  }

  if (!SD.begin(SD_CS_PIN)) logPrintln("SD-карта не обнаружена.");
  if (!SPIFFS.begin(true)) logPrintln("Ошибка SPIFFS!");

  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW); // насос выключен при старте

  pinMode(HEATER_PIN, OUTPUT);
  digitalWrite(HEATER_PIN, LOW); // обогреватель выключен при старте

  // Датчик уровня воды: подтяжка к VCC, замыкание на GND = "вода есть".
  // Если у твоего датчика логика обратная (замыкание = "воды нет") — поменяй LOW на HIGH в isWaterAvailable().
  pinMode(WATER_LEVEL_PIN, INPUT_PULLUP);

  // AP+STA сразу и навсегда: точка доступа больше не передёргивается задачей телеметрии
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(ap_ssid.c_str(), ap_pass.length() > 0 ? ap_pass.c_str() : NULL);

  xTaskCreatePinnedToCore(vUbidotsTask, "UbidotsTask", 12288, NULL, 1, &UbidotsTaskHandle, 0); // 12 КБ: mbedTLS не влезает в 8

  // --- МАРШРУТИЗАЦИЯ ВЕБ-СЕРВЕРА ---
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/index.html", "text/html"); });
  server.on("/settings", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/settings.html", "text/html"); });
  // Остальная статика (css/js и всё, что появится в data/) раздаётся одним обработчиком —
  // регистрируется ниже, после API-маршрутов, чтобы точно не перехватывать /api/*

  server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest *request){
    // Снимок состояния строго под мьютексом: раньше при неудачном захвате (таймаут 10 мс)
    // переменные оставались неинициализированными и в JSON уезжал мусор из стека.
    float t, h; int l, f1, f2; bool s_ok, r_ok;
    if (xSemaphoreTake(xMutex, pdMS_TO_TICKS(50)) != pdTRUE) {
      request->send(503, "application/json", "{\"error\":\"busy\"}");
      return;
    }
    t = current_temp; h = current_hum; l = current_led_pwm; f1 = current_fan1_pwm; f2 = current_fan2_pwm;
    s_ok = sht_online; r_ok = rtc_online;
    xSemaphoreGive(xMutex);

    DateTime now = getWebDateTime();
    int grow_day = (start_timestamp > 0 && now.unixtime() >= start_timestamp) ? ((now.unixtime() - start_timestamp) / 86400) + 1 : 0;

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

  // Отдаёт содержимое кольцевого буфера Serial.print()-сообщений как обычный текст —
  // без JSON-обёртки, чтобы не думать про экранирование кавычек/переводов строк в логах.
  // Названо /api/console, а не /api/log — последний уже занят историей CSV с SD-карты для графика.
  server.on("/api/console", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(200, "text/plain; charset=utf-8", getLogSnapshot());
  });

  server.on("/api/settings", HTTP_GET, [](AsyncWebServerRequest *request){
    DateTime now = getWebDateTime();
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
    json += "\"water_sensor_enabled\":" + String(water_sensor_enabled ? "true" : "false") + ",";
    json += "\"heater_mode\":" + String(heater_mode) + ",";
    json += "\"wifi_ssid\":\"" + jsonEscape(wifi_ssid) + "\",";
    // Пароли и токен наружу не отдаём: страницу настроек открывает любой, кто подключился
    // к точке доступа. Вместо значения — флаг "задано/не задано"; пустое поле формы = не менять.
    json += "\"wifi_pass_set\":" + String(wifi_pass.length() > 0 ? "true" : "false") + ",";
    json += "\"ubidots_token_set\":" + String(ubidots_token.length() > 0 ? "true" : "false") + ",";
    json += "\"device_label\":\"" + jsonEscape(device_label) + "\",";
    json += "\"ap_ssid\":\"" + jsonEscape(ap_ssid) + "\",";
    json += "\"ap_pass_set\":" + String(ap_pass.length() > 0 ? "true" : "false") + ",";
    json += "\"rtc_time\":\"" + String(buf) + "\",";

    uint64_t sdTotal = SD.totalBytes();
    uint64_t sdUsed  = SD.usedBytes();
    uint64_t sdFree  = (sdTotal > sdUsed) ? (sdTotal - sdUsed) : 0;
    json += "\"sdTotal\":" + u64str(sdTotal) + ",";
    json += "\"sdUsed\":"  + u64str(sdUsed)  + ",";
    json += "\"sdFree\":"  + u64str(sdFree);
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
    if (request->hasParam("water_sensor_enabled", true)) preferences.putBool("water_sensor", request->getParam("water_sensor_enabled", true)->value() == "1");
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
    // Пустое поле пароля = "оставить как есть" (форма его больше не подставляет).
    // Чтобы явно сделать сеть открытой, ставится галочка wifi_pass_clear.
    bool wifi_pass_clear = request->hasParam("wifi_pass_clear", true) &&
                           request->getParam("wifi_pass_clear", true)->value() == "1";
    if (wifi_pass_clear) {
      preferences.putString("wifi_pass", "");
    } else if (request->hasParam("wifi_pass", true)) {
      String newPass = request->getParam("wifi_pass", true)->value();
      if (newPass.length() > 0) {
        if (isValidStaPass(newPass)) preferences.putString("wifi_pass", newPass);
        else wifi_rejected = true;
      }
    }
    if (request->hasParam("ubidots_token", true)) {
      String newToken = request->getParam("ubidots_token", true)->value();
      newToken.trim();
      if (newToken.length() > 0) preferences.putString("ubidots_token", newToken);
    }
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
    bool ap_pass_clear = request->hasParam("ap_pass_clear", true) &&
                         request->getParam("ap_pass_clear", true)->value() == "1";
    if (ap_pass_clear) {
      preferences.putString("ap_pass", "");
      ap_changed = true;
    } else if (request->hasParam("ap_pass", true)) {
      String newPass = request->getParam("ap_pass", true)->value();
      if (newPass.length() > 0) {
        if (isValidApPass(newPass)) {
          preferences.putString("ap_pass", newPass);
          ap_changed = true;
        } else {
          ap_rejected = true;
        }
      }
    }

    if (request->hasParam("start_date", true)) {
      String dateStr = request->getParam("start_date", true)->value();
      int y, m, d;
      if (parseDate(dateStr, y, m, d)) {
        DateTime startDate(y, m, d, 0, 0, 0);
        preferences.putUInt("start_time", startDate.unixtime());
      }
    }
    
    loadAllSettingsFromNVS();

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
      DateTime userTime((uint32_t)0);
      if (!parseDateTimeLocal(request->getParam("datetime", true)->value(), userTime)) {
        request->redirect("/settings?error=time");
        return;
      }
      // Само применение — в loop(): rtc.adjust() из задачи веб-сервера означал бы
      // обращение к I2C с другого ядра, параллельно с опросом SHT4x
      pending_time_set = userTime.unixtime();
    }
    request->redirect("/settings");
  });

  server.on("/api/log", HTTP_GET, [](AsyncWebServerRequest *request){
      String logDate = request->hasParam("date") ? request->getParam("date")->value() : "";
      if (logDate.length() > 0 && !isValidLogDate(logDate)) {
        request->send(400, "text/plain", "Bad date");
        return;
      }
      if (logDate == "") {
        DateTime now = getWebDateTime();
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

  // Список последних файлов в корне SD (для вкладки "Общее" на странице настроек)
  server.on("/api/files", HTTP_GET, [](AsyncWebServerRequest *request){
    std::vector<String> names;
    std::vector<uint32_t> sizes;

    File root = SD.open("/");
    if (root && root.isDirectory()) {
      File entry = root.openNextFile();
      while (entry) {
        if (!entry.isDirectory()) {
          String n = String(entry.name());
          int slash = n.lastIndexOf('/');
          if (slash >= 0) n = n.substring(slash + 1); // только имя, без пути
          names.push_back(n);
          sizes.push_back((uint32_t)entry.size());
        }
        entry.close();
        entry = root.openNextFile();
      }
      root.close();
    }

    // Файлы датированы YYYY-MM-DD.csv — идут по возрастанию, значит "последние" = конец списка
    int total = names.size();
    int start = total > 10 ? total - 10 : 0;

    String json = "{\"total\":" + String(total) + ",\"files\":[";
    for (int i = start; i < total; i++) {
      if (i > start) json += ",";
      json += "{\"name\":\"" + jsonEscape(names[i].c_str()) + "\",\"size\":" + String(sizes[i]) + "}";
    }
    json += "]}";
    request->send(200, "application/json", json);
  });

  // Удаление логов: именно POST. GET-версию можно было выстрелить обычным <img src="...">
  // с любой открытой страницы, пока телефон подключён к точке доступа, — и карта стиралась.
  server.on("/api/clearlogs", HTTP_POST, [](AsyncWebServerRequest *request){
    int removed = clearCsvLogs();
    logPrintln("Очистка логов SD: удалено файлов " + String(removed));
    request->send(200, "text/plain", "OK");
  });

  // Статика регистрируется последней: так обработчик "/" гарантированно не встанет
  // перед /api/* ни в одной из версий ESPAsyncWebServer
  server.serveStatic("/", SPIFFS, "/").setCacheControl("max-age=600");
  server.onNotFound([](AsyncWebServerRequest *request){ request->send(404, "text/plain", "Not found"); });

  cached_unixtime = getSafeDateTime().unixtime(); // Веб-обработчики читают только этот снимок
  server.begin();

  ledcAttach(LED_PWM_PIN, PWM_FREQ, PWM_RES);
  ledcAttach(FAN1_PWM_PIN, PWM_FREQ, PWM_RES);
  ledcAttach(FAN2_PWM_PIN, PWM_FREQ, PWM_RES);
}

void loop() {
  static unsigned long lastLogTime = 0;
  unsigned long currentMillis = millis();
  tryRecoverRTC(currentMillis); // Не блокирует: сам ограничивает частоту попыток внутри

  // Время читаем раз в секунду, а не на каждой итерации loop(): rtc.now() — полноценная
  // транзакция по I2C, и раньше она крутилась тысячи раз в секунду на той же шине,
  // по которой опрашивается SHT4x.
  static DateTime now((uint32_t)0);
  static unsigned long lastTimeRead = 0;
  if (lastTimeRead == 0 || currentMillis - lastTimeRead >= 1000) {
    lastTimeRead = currentMillis;
    now = getSafeDateTime();
    cached_unixtime = now.unixtime(); // Снимок, который отдают веб-обработчики
  }

  // Часы, выставленные из веб-формы, применяем здесь: в I2C ходит только loop()
  uint32_t requested = pending_time_set;
  if (requested != 0) {
    pending_time_set = 0;
    DateTime userTime(requested);
    if (rtc_online) rtc.adjust(userTime);
    backup_unixtime = requested;
    last_rtc_check_ms = millis();
    now = userTime;
    cached_unixtime = requested;
    logPrintln("[RTC] Часы выставлены вручную через веб-интерфейс");
  }

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
      recoverI2CBus(); // Освобождаем шину на случай, если она физически "залипла"
      sensors_event_t retryHumidity, retryTemp;
      bool retry_ok = sht40.begin() && sht40.getEvent(&retryHumidity, &retryTemp) &&
                       retryTemp.temperature >= -20.0 && retryTemp.temperature <= 80.0 &&
                       retryHumidity.relative_humidity >= 0.0 && retryHumidity.relative_humidity <= 100.0;

      if (retry_ok) {
        sht_recovery_streak++;
        logPrintf("[SHT4x] Попытка восстановления %d/%d успешна\n", sht_recovery_streak, SHT_RECOVERY_STREAK_NEEDED);
        if (sht_recovery_streak >= SHT_RECOVERY_STREAK_NEEDED) {
          sht_online = true;
          got_valid_reading = true;
          read_temp = retryTemp.temperature;
          read_hum = retryHumidity.relative_humidity;
          sht_recovery_streak = 0;
          logPrintln("[SHT4x] Датчик восстановлен, выходим из аварийного режима.");
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
      
      logPrintln("[АВАРИЙНЫЙ РЕЖИМ]: Отказ SHT4x! Климат зафиксирован на безопасных уровнях.");
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

    // Страхуемся от выхода за пределы 8-битного ШИМ (map() с кривыми границами это умеет)
    target_led  = clampInt(target_led, 0, 255);
    target_fan1 = clampInt(target_fan1, 0, 255);
    target_fan2 = clampInt(target_fan2, 0, 255);

    // Безопасно обновляем глобальные переменные под мьютексом (их читают веб и Ubidots)
    if (xSemaphoreTake(xMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
      current_temp = read_temp;
      current_hum = read_hum;
      current_led_pwm = target_led;
      current_fan1_pwm = target_fan1;
      current_fan2_pwm = target_fan2;
      xSemaphoreGive(xMutex);
    }

    // Управляем исполнительными устройствами. Пишем ИМЕННО вычисленные значения:
    // раньше здесь стояли глобалки, и при неудачном захвате мьютекса весь расчёт цикла
    // молча терялся — ШИМ оставался прежним, хотя температура уже изменилась.
    ledcWrite(LED_PWM_PIN, target_led);
    ledcWrite(FAN1_PWM_PIN, target_fan1);
    ledcWrite(FAN2_PWM_PIN, target_fan2);
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
    DateTime now_w = now; // Время уже обновлено выше, повторно дёргать RTC незачем

    // RTClib: dayOfTheWeek() возвращает 0=Вс...6=Сб. Переводим в формат watering_days: 0=Пн...6=Вс
    int rtc_dow = now_w.dayOfTheWeek();
    int iso_dow = (rtc_dow == 0) ? 6 : rtc_dow - 1;
    uint32_t today_code = now_w.unixtime() / 86400;

    // Если датчик уровня воды выключен в настройках — считаем, что вода есть всегда (старое поведение)
    bool water_ok = !water_sensor_enabled || isWaterAvailable();

    if (!pump_active) {
      bool day_enabled = (watering_days >> iso_dow) & 0x01;
      if (day_enabled && now_w.hour() == watering_hour && now_w.minute() == watering_minute && last_watering_day != today_code) {
        if (water_ok) {
          pump_active = true;
          pump_start_ms = currentMillis;
          last_watering_day = today_code;
          // Запоминаем день в NVS: иначе ресет (или срабатывание watchdog) внутри
          // поливочной минуты запускал полив по второму разу
          preferences.putUInt("last_water", today_code);
          digitalWrite(PUMP_PIN, HIGH);
          logPrintln("[ПОЛИВ] Старт автополива");
        } else {
          last_watering_day = today_code; // Не пробуем каждую секунду до конца минуты — ждём до завтра
          preferences.putUInt("last_water", today_code);
          logPrintln("[ПОЛИВ] Пропущен: датчик не видит воду в баке");
        }
      }
    } else {
      if (!water_ok) {
        // Аварийная остановка: вода закончилась прямо во время полива — не гоняем насос всухую
        pump_active = false;
        digitalWrite(PUMP_PIN, LOW);
        logPrintln("[ПОЛИВ] Аварийная остановка: вода закончилась во время полива");
      } else if (currentMillis - pump_start_ms >= (unsigned long)watering_duration_sec * 1000UL) {
        // Длительность — по millis(), а не по RTC: если посреди полива восстановится RTC
        // (tryRecoverRTC) и время прыгнет, насос иначе либо выключится мгновенно, либо
        // будет лить, пока не сработает датчик уровня воды.
        pump_active = false;
        digitalWrite(PUMP_PIN, LOW);
        logPrintln("[ПОЛИВ] Полив завершён");
      }
    }
  }

  esp_task_wdt_reset();
}