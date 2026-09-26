#include <esp_task_wdt.h>
#include <Arduino.h>
#include <stdarg.h>
#include <stddef.h>
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
#include <atomic>
#include <esp_random.h>
#include <time.h>
#include "Safety.h"
#include "SafetyTests.h"
#include "UbidotsCA.h"

// --- Настройки подключения к домашнему роутеру и Ubidots ---
// Значения по умолчанию используются только при первой прошивке / если NVS пуст.
// Реальные значения хранятся в Preferences и редактируются на вкладке "WiFi / Ubidots".
#define DEFAULT_WIFI_SSID ""
#define DEFAULT_WIFI_PASS ""
#define DEFAULT_UBIDOTS_TOKEN ""
#define DEFAULT_DEVICE_LABEL  "kireal"
#define DEFAULT_AP_SSID       "KiReal"
#define DEFAULT_AP_PASS ""

String admin_password; // Immutable after setup, never returned through HTTP.
String csrf_token;

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

#define PWM_FREQ      5000
#define PWM_RES       8

// --- Ограничения длины строковых настроек ---
#define WIFI_SSID_MAX 32   // стандарт 802.11
#define WIFI_PASS_MAX 63   // WPA2
#define TOKEN_MAX     128
#define LABEL_MAX     64

// =====================================================================================
// ДАННЫЕ ПРОШИВКИ: НАСТРОЙКИ И СОСТОЯНИЕ
// =====================================================================================
// Раньше это были ~50 отдельных глобальных переменных, которые три задачи на двух ядрах
// (loop, веб-сервер, Ubidots) читали и писали кто как, — отсюда была большая часть гонок.
// Теперь правило одно:
//   * Settings — то, что задал пользователь. Меняет только обработчик /save-settings:
//     разбирает форму в свою копию и публикует её целиком (publishSettings()).
//     Все остальные работают со своей копией (settingsSnapshot()).
//   * State — то, что происходит сейчас. Пишет только loop() в рабочую копию `state`
//     и публикует её (publishState()); веб и Ubidots читают stateSnapshot().
// Обе структуры — простые данные без String и указателей, поэтому копируются одним memcpy
// под спинлоком: без аллокаций, без таймаутов и без 503 на ровном месте.
//
// Типы объявлены до первой функции файла намеренно: Arduino IDE вставляет свои
// автоматические прототипы функций именно туда, и типы из их сигнатур должны быть известны.

struct Settings {
  // Климат
  float temp_target;        // Целевая температура дня, °C (от неё считаются лампа и вентиляторы)
  float temp_delta;         // Полуширина рабочего диапазона и гистерезис обогрева, °C
  float temp_target_night;  // Цель обогревателя ночью, °C (гистерезис temp_delta общий)
  float min_hum_night;      // Ночью ниже этой влажности вентиляторы держат минимум, %
  float max_hum_night;      // ...а выше этой — максимум, %

  // Свет
  int led_on_hour, led_on_minute;
  int led_off_hour, led_off_minute;
  int led_min_limit, led_max_limit;              // Мощность лампы днём, %

  // Вентиляция
  int fan1_min_limit, fan1_max_limit;            // Днём, по температуре, %
  int fan2_min_limit, fan2_max_limit;
  int fan_night_min_limit, fan_night_max_limit;  // Ночью, обоими вентиляторами по влажности, %

  // Обогрев: 0 = только день, 1 = только ночь, 2 = всегда, 3 = никогда
  int heater_mode;

  // Автополив
  uint8_t watering_days;       // Битовая маска: бит0=Пн, бит1=Вт, ... бит6=Вс
  int watering_hour, watering_minute;
  int watering_duration_sec;
  bool water_sensor_enabled;   // Учитывать ли датчик уровня воды перед стартом/во время полива

  uint32_t start_timestamp;    // Начало цикла выращивания (unixtime), 0 = цикл не начат

  // Сеть и облако
  char wifi_ssid[WIFI_SSID_MAX + 1];
  char wifi_pass[WIFI_PASS_MAX + 1];
  char ubidots_token[TOKEN_MAX + 1];
  char device_label[LABEL_MAX + 1];
  char ap_ssid[WIFI_SSID_MAX + 1];   // Точка доступа платы — к ней подключается телефон/ноутбук
  char ap_pass[WIFI_PASS_MAX + 1];   // WPA2 only; empty form means keep existing password
};

struct State {
  float temp;           // Последнее валидное показание SHT4x, °C
  float hum;            // ...и влажности, %
  int led_pwm;          // Текущий ШИМ, 0-255
  int fan1_pwm;
  int fan2_pwm;
  bool is_day;
  bool sht_online;
  bool rtc_online;
  bool clock_trusted;
  bool pump_active;
  bool heater_active;
};

// Описание одной настройки для таблицы SETTING_DEFS (см. ниже)
enum SettingType : uint8_t { ST_FLOAT, ST_INT, ST_U8, ST_BOOL, ST_U32, ST_STRING };

enum SettingFlags : uint8_t {
  SF_SECRET  = 1 << 0,  // Наружу не отдаётся (только <param>_set), пустое поле формы = "не менять"
  SF_TRIM    = 1 << 1,  // Обрезать пробелы по краям
  SF_NO_FORM = 1 << 2,  // Из формы автоматически не разбирается (для поля есть особый обработчик)
};

struct SettingDef {
  const char *param;     // Имя поля в форме и в JSON /api/settings
  const char *nvsKey;    // Ключ в NVS (до 15 символов!) — исторически не везде совпадает с param
  SettingType type;
  uint16_t offset;       // Где поле лежит внутри Settings
  uint16_t size;         // Его размер (для строк — размер буфера)
  float lo, hi;          // Числа: диапазон клэмпа. Строки: допустимая длина непустого значения
  float def;             // Значение по умолчанию для чисел
  const char *defStr;    // ...и для строк
  uint8_t flags;
  const char *errGroup;  // Строки: какой баннер ошибки показать на странице, если значение отклонено
};

// Рабочая копия состояния. Трогает ТОЛЬКО loop() (и setup() до старта остальных задач)
State state = {};

// Опубликованные копии для остальных задач — доступ только через функции ниже
static State stateShared = {};
static portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;
static Settings settingsShared = {};
static portMUX_TYPE settingsMux = portMUX_INITIALIZER_UNLOCKED;

// --- Кольцевой буфер для показа Serial.print()-сообщений на веб-странице (/api/console) ---
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

// Экранирование строки для безопасной вставки в JSON: имена файлов SD, а также SSID,
// имя устройства и прочее, что вводит пользователь (одна кавычка ломала разбор на странице)
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

// --- Внутреннее состояние loop(): никто, кроме loop() и setup(), эти переменные не трогает ---
uint32_t pump_start_ms = 0;   // Отсчёт длительности полива по millis(), а не по RTC
uint32_t pump_duration_ms = 0;
uint32_t last_watering_day = 0;    // Защита от повторного срабатывания в тот же день (хранится в NVS)

unsigned long last_sht_retry = 0;                  // Когда последний раз пытались восстановить датчик
const unsigned long SHT_RETRY_INTERVAL_MS = 30000; // Пауза между попытками восстановления, мс
int sht_recovery_streak = 0;                       // Счётчик подряд успешных попыток восстановления
const int SHT_RECOVERY_STREAK_NEEDED = 3;          // Сколько подряд удачных попыток нужно, чтобы снова доверять датчику
unsigned long last_rtc_retry = 0;                  // Когда последний раз пытались восстановить RTC
const unsigned long RTC_RETRY_INTERVAL_MS = 30000; // Пауза между попытками восстановления, мс
int rtc_recovery_streak = 0;                       // Счётчик подряд успешных попыток восстановления
const int RTC_RECOVERY_STREAK_NEEDED = 3;          // Сколько подряд удачных попыток нужно, чтобы снова доверять RTC

// Переменные для программного дублирования времени (на случай отказа RTC)
uint32_t backup_unixtime = 1774838400; // Дефолтный 2026 год, если RTC умер сразу при старте
uint32_t last_rtc_check_ms = 0;

// Время и запросы к RTC трогает только loop(). Веб-обработчики крутятся в задаче
// AsyncWebServer (другое ядро): раньше они звали getSafeDateTime() и rtc.adjust() напрямую,
// то есть лезли в I2C параллельно с опросом SHT4x и одновременно правили rtc_online/backup_unixtime.
std::atomic<uint32_t> cached_unixtime{0};  // Снимок времени для веб-обработчиков, обновляет loop()
std::atomic<uint32_t> pending_time_set{0}; // Запрос "выставить часы" с формы; применяет loop()

// --- Хендлы FreeRTOS для многоядерности ---
TaskHandle_t UbidotsTaskHandle = NULL;

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
  return validCalendar(y, m, d, 0, 0, 0);
}

// "YYYY-MM-DDTHH:MM" — формат, который отдаёт <input type="datetime-local">
bool parseDateTimeLocal(const String &str, DateTime &out) {
  int y, m, d;
  if (!parseDate(str, y, m, d)) return false;
  if (str.length() != 16 || str[10] != 'T' || str[13] != ':') return false;
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

// =====================================================================================
// ОБМЕН ДАННЫМИ МЕЖДУ ЗАДАЧАМИ
// =====================================================================================
// Спинлок, а не мьютекс: под ним только memcpy (~40 байт State, ~500 байт Settings —
// единицы микросекунд), поэтому захват не может "не успеть", и читателям не нужен
// запасной путь на случай таймаута.

State stateSnapshot() {
  State s;
  portENTER_CRITICAL(&stateMux);
  memcpy(&s, &stateShared, sizeof(State));
  portEXIT_CRITICAL(&stateMux);
  return s;
}

// Публикует рабочую копию loop() для остальных задач, если она изменилась. Вызывается
// в конце каждой итерации loop(): сравнить 40 байт дешевле, чем помнить, где именно
// состояние поменялось. Читать stateShared без спинлока здесь можно — кроме этой
// функции, его никто не пишет.
void publishState() {
  if (memcmp(&state, &stateShared, sizeof(State)) == 0) return;
  portENTER_CRITICAL(&stateMux);
  memcpy(&stateShared, &state, sizeof(State));
  portEXIT_CRITICAL(&stateMux);
}

Settings settingsSnapshot() {
  Settings s;
  portENTER_CRITICAL(&settingsMux);
  memcpy(&s, &settingsShared, sizeof(Settings));
  portEXIT_CRITICAL(&settingsMux);
  return s;
}

void publishSettings(const Settings &s) {
  portENTER_CRITICAL(&settingsMux);
  memcpy(&settingsShared, &s, sizeof(Settings));
  portEXIT_CRITICAL(&settingsMux);
}

// =====================================================================================
// ТАБЛИЦА НАСТРОЕК
// =====================================================================================
// Единственное место, где описана каждая настройка: имя в форме/JSON, ключ NVS, диапазон
// и значение по умолчанию. Из неё работают загрузка из NVS, разбор формы, сохранение и
// выдача в /api/settings. Раньше каждое поле было выписано руками в трёх местах, и они
// расходились (так "терялась" temp_target_night, так разъехались дефолты led_off_hour).
//
// Чтобы добавить настройку: поле в struct Settings + одна строка здесь. Всё.
//
// Ключи NVS менять нельзя: по ним уже прошитые платы читают сохранённые значения.

// Проверка типов на этапе компиляции. Эти функции только объявлены и используются
// исключительно внутри sizeof(), то есть никогда не вызываются. Если тип в строке таблицы
// не совпадает с типом поля (скажем, SET_INT для uint8_t), сборка упадёт с ошибкой —
// вместо того чтобы молча записать 4 байта в однобайтовое поле.
char requireFloat(float *);
char requireInt(int *);
char requireU8(uint8_t *);
char requireBool(bool *);
char requireU32(uint32_t *);
char requireChars(char *);

#define S_PTR(field) (&((Settings *)0)->field)
#define S_LOC(field) (uint16_t)offsetof(Settings, field), (uint16_t)sizeof(((Settings *)0)->field)

#define SET_FLOAT(param, key, field, lo, hi, def) \
  { param, key, ST_FLOAT, S_LOC(field) + 0 * sizeof(requireFloat(S_PTR(field))), lo, hi, def, nullptr, 0, nullptr }
#define SET_INT(param, key, field, lo, hi, def) \
  { param, key, ST_INT, S_LOC(field) + 0 * sizeof(requireInt(S_PTR(field))), lo, hi, def, nullptr, 0, nullptr }
#define SET_U8(param, key, field, lo, hi, def) \
  { param, key, ST_U8, S_LOC(field) + 0 * sizeof(requireU8(S_PTR(field))), lo, hi, def, nullptr, 0, nullptr }
#define SET_BOOL(param, key, field, def) \
  { param, key, ST_BOOL, S_LOC(field) + 0 * sizeof(requireBool(S_PTR(field))), 0, 1, (def) ? 1 : 0, nullptr, 0, nullptr }
#define SET_U32_NOFORM(param, key, field) \
  { param, key, ST_U32, S_LOC(field) + 0 * sizeof(requireU32(S_PTR(field))), 0, 0, 0, nullptr, SF_NO_FORM, nullptr }
// Для строк заодно проверяется, что максимальная длина влезает в буфер поля
#define SET_STR(param, key, field, minLen, maxLen, def, flags, errGroup) \
  { param, key, ST_STRING, S_LOC(field) + 0 * sizeof(requireChars(((Settings *)0)->field)) \
      + 0 * sizeof(char[(maxLen) < sizeof(((Settings *)0)->field) ? 1 : -1]), \
    minLen, maxLen, 0, def, flags, errGroup }

static const SettingDef SETTING_DEFS[] = {
  //        param (форма/JSON)     ключ NVS           поле                   мин   макс   по умолч.
  // --- Климат ---
  SET_FLOAT("temp_target",         "temp_target",     temp_target,           0,    50,    25),
  SET_FLOAT("temp_delta",          "temp_delta",      temp_delta,            0.1,  20,    2),
  SET_FLOAT("temp_target_night",   "temp_night",      temp_target_night,     0,    50,    20),
  SET_FLOAT("min_hum_night",       "min_hum_night",   min_hum_night,         0,    100,   40),
  SET_FLOAT("max_hum_night",       "max_hum_night",   max_hum_night,         0,    100,   60),
  // --- Свет ---
  SET_INT  ("led_on_hour",         "led_on_hour",     led_on_hour,           0,    23,    6),
  SET_INT  ("led_on_minute",       "led_on_minute",   led_on_minute,         0,    59,    0),
  SET_INT  ("led_off_hour",        "led_off_hour",    led_off_hour,          0,    23,    18),
  SET_INT  ("led_off_minute",      "led_off_minute",  led_off_minute,        0,    59,    0),
  SET_INT  ("led_min_limit",       "led_min_limit",   led_min_limit,         0,    100,   10),
  SET_INT  ("led_max_limit",       "led_max_limit",   led_max_limit,         0,    100,   100),
  // --- Вентиляция ---
  SET_INT  ("fan1_min_limit",      "fan1_min_limit",  fan1_min_limit,        0,    100,   20),
  SET_INT  ("fan1_max_limit",      "fan1_max_limit",  fan1_max_limit,        0,    100,   100),
  SET_INT  ("fan2_min_limit",      "fan2_min_limit",  fan2_min_limit,        0,    100,   20),
  SET_INT  ("fan2_max_limit",      "fan2_max_limit",  fan2_max_limit,        0,    100,   100),
  SET_INT  ("fan_night_min_limit", "fan_night_min",   fan_night_min_limit,   0,    100,   30),
  SET_INT  ("fan_night_max_limit", "fan_night_max",   fan_night_max_limit,   0,    100,   100),
  // --- Обогрев ---
  SET_INT  ("heater_mode",         "heater_mode",     heater_mode,           0,    3,     3),
  // --- Автополив ---
  SET_U8   ("watering_days",       "watering_days",   watering_days,         0,    127,   0),
  SET_INT  ("watering_hour",       "watering_hour",   watering_hour,         0,    23,    8),
  SET_INT  ("watering_minute",     "watering_minute", watering_minute,       0,    59,    0),
  SET_INT  ("watering_duration",   "watering_dur",    watering_duration_sec, 1,    3600,  30),
  SET_BOOL ("water_sensor_enabled","water_sensor",    water_sensor_enabled,               false),
  // --- Цикл выращивания: из формы приходит строкой start_date, разбирается в /save-settings ---
  SET_U32_NOFORM("start_time",     "start_time",      start_timestamp),
  // --- Сеть и облако. Мин./макс. — допустимая длина непустого значения ---
  //        param                  ключ NVS           поле            мин  макс            по умолч.              флаги                баннер
  SET_STR  ("wifi_ssid",           "wifi_ssid",       wifi_ssid,      0,   WIFI_SSID_MAX,  DEFAULT_WIFI_SSID,     SF_TRIM,             "wifi"),
  SET_STR  ("wifi_pass",           "wifi_pass",       wifi_pass,      8,   WIFI_PASS_MAX,  DEFAULT_WIFI_PASS,     SF_SECRET,           "wifi"),
  SET_STR  ("ubidots_token",       "ubidots_token",   ubidots_token,  1,   TOKEN_MAX,      DEFAULT_UBIDOTS_TOKEN, SF_SECRET | SF_TRIM, nullptr),
  SET_STR  ("device_label",        "device_label",    device_label,   0,   LABEL_MAX,      DEFAULT_DEVICE_LABEL,  SF_TRIM,             nullptr),
  SET_STR  ("ap_ssid",             "ap_ssid",         ap_ssid,        1,   WIFI_SSID_MAX,  DEFAULT_AP_SSID,       SF_TRIM,             "ap"),
  SET_STR  ("ap_pass",             "ap_pass",         ap_pass,        8,   WIFI_PASS_MAX,  DEFAULT_AP_PASS,       SF_SECRET,           "ap"),
};
static const size_t SETTING_DEFS_COUNT = sizeof(SETTING_DEFS) / sizeof(SETTING_DEFS[0]);

uint8_t *fieldAddr(Settings &s, const SettingDef &d) {
  return (uint8_t *)&s + d.offset;
}

const uint8_t *fieldAddr(const Settings &s, const SettingDef &d) {
  return (const uint8_t *)&s + d.offset;
}

// Empty router password means an open upstream network; empty token disables cloud.
// The device AP itself always requires WPA2.
bool settingStringValid(const SettingDef &d, const char *v) {
  size_t len = strlen(v);
  if (len == 0) return strcmp(d.param, "ap_pass") != 0 && (d.lo == 0 || (d.flags & SF_SECRET));
  return len >= (size_t)d.lo && len <= (size_t)d.hi;
}

void orderRange(int &lo, int &hi) {
  if (lo > hi) { int t = lo; lo = hi; hi = t; }
}

void orderRange(float &lo, float &hi) {
  if (lo > hi) { float t = lo; lo = hi; hi = t; }
}

// Подстраховка от "перевёрнутых" границ (min > max): меняем местами, чтобы устройство
// не осталось с невозможным диапазоном. Срабатывает и на форму, и на испорченный NVS.
void normalizeRanges(Settings &s) {
  orderRange(s.led_min_limit, s.led_max_limit);
  orderRange(s.fan1_min_limit, s.fan1_max_limit);
  orderRange(s.fan2_min_limit, s.fan2_max_limit);
  orderRange(s.fan_night_min_limit, s.fan_night_max_limit);
  orderRange(s.min_hum_night, s.max_hum_night);
}

// Загрузка всех настроек из NVS. Числа клэмпятся и здесь — на случай испорченных
// значений; строки недопустимой длины откатываются на дефолт (раньше так защищалась
// только точка доступа, чтобы не остаться без доступа к плате).
void loadSettingsFromNVS(Settings &s) {
  memset(&s, 0, sizeof(Settings));
  for (size_t i = 0; i < SETTING_DEFS_COUNT; i++) {
    const SettingDef &d = SETTING_DEFS[i];
    uint8_t *p = fieldAddr(s, d);
    switch (d.type) {
      case ST_FLOAT:
        *(float *)p = clampFloat(preferences.getFloat(d.nvsKey, d.def), d.lo, d.hi);
        break;
      case ST_INT:
        *(int *)p = clampInt(preferences.getInt(d.nvsKey, (int)d.def), (int)d.lo, (int)d.hi);
        break;
      case ST_U8:
        *(uint8_t *)p = (uint8_t)clampInt(preferences.getUChar(d.nvsKey, (uint8_t)d.def), (int)d.lo, (int)d.hi);
        break;
      case ST_BOOL:
        *(bool *)p = preferences.getBool(d.nvsKey, d.def != 0);
        break;
      case ST_U32:
        *(uint32_t *)p = preferences.getUInt(d.nvsKey, (uint32_t)d.def);
        break;
      case ST_STRING: {
        String v = preferences.getString(d.nvsKey, d.defStr);
        if (!settingStringValid(d, v.c_str())) v = d.defStr;
        strlcpy((char *)p, v.c_str(), d.size);
        break;
      }
    }
  }
  normalizeRanges(s);
}

// "ap,wifi" — без повторов, если в одной группе отклонено сразу несколько полей
void addErrorGroup(String &list, const char *group) {
  String padded = "," + list + ",";
  if (padded.indexOf("," + String(group) + ",") >= 0) return;
  if (list.length()) list += ",";
  list += group;
}

// Применяет поля формы к копии настроек (значения клэмпятся в разумные пределы, даже если
// запрос пришёл в обход веб-формы). Возвращает отклонённые группы через запятую — по ним
// страница показывает баннеры ошибок.
String applyFormToSettings(AsyncWebServerRequest *request, Settings &s) {
  String rejected;
  for (size_t i = 0; i < SETTING_DEFS_COUNT; i++) {
    const SettingDef &d = SETTING_DEFS[i];
    if (d.flags & SF_NO_FORM) continue;
    uint8_t *p = fieldAddr(s, d);

    if (d.type == ST_STRING && (d.flags & SF_SECRET)) {
      // Пустое поле пароля = "оставить как есть" (форма его не подставляет). Стереть
      // пароль можно только явно — галочкой <param>_clear ("сеть без пароля").
      String clearParam = String(d.param) + "_clear";
      if (request->hasParam(clearParam, true) && request->getParam(clearParam, true)->value() == "1") {
        if (strcmp(d.param, "ap_pass") == 0) { addErrorGroup(rejected, "ap"); continue; }
        ((char *)p)[0] = '\0';
        continue;
      }
    }

    if (!request->hasParam(d.param, true)) continue;
    String v = request->getParam(d.param, true)->value();

    switch (d.type) {
      case ST_FLOAT: *(float *)p = clampFloat(v.toFloat(), d.lo, d.hi); break;
      case ST_INT:   *(int *)p = clampInt(v.toInt(), (int)d.lo, (int)d.hi); break;
      case ST_U8:    *(uint8_t *)p = (uint8_t)clampInt(v.toInt(), (int)d.lo, (int)d.hi); break;
      case ST_BOOL:  *(bool *)p = (v == "1"); break;
      case ST_U32:   *(uint32_t *)p = strtoul(v.c_str(), nullptr, 10); break;
      case ST_STRING:
        if (d.flags & SF_TRIM) v.trim();
        if ((d.flags & SF_SECRET) && v.length() == 0) break;  // пусто = не менять
        if (settingStringValid(d, v.c_str())) strlcpy((char *)p, v.c_str(), d.size);
        else if (d.errGroup) addErrorGroup(rejected, d.errGroup);
        break;
    }
  }
  normalizeRanges(s);
  return rejected;
}

// Пишет в NVS только изменившиеся поля: неизменные значения не переписываются на каждое
// сохранение любой из форм, и флеш изнашивается меньше
void saveChangedSettings(const Settings &prev, const Settings &next) {
  for (size_t i = 0; i < SETTING_DEFS_COUNT; i++) {
    const SettingDef &d = SETTING_DEFS[i];
    const uint8_t *a = fieldAddr(prev, d);
    const uint8_t *b = fieldAddr(next, d);
    bool changed = (d.type == ST_STRING) ? strcmp((const char *)a, (const char *)b) != 0
                                         : memcmp(a, b, d.size) != 0;
    if (!changed) continue;
    switch (d.type) {
      case ST_FLOAT:  preferences.putFloat(d.nvsKey, *(const float *)b); break;
      case ST_INT:    preferences.putInt(d.nvsKey, *(const int *)b); break;
      case ST_U8:     preferences.putUChar(d.nvsKey, *(const uint8_t *)b); break;
      case ST_BOOL:   preferences.putBool(d.nvsKey, *(const bool *)b); break;
      case ST_U32:    preferences.putUInt(d.nvsKey, *(const uint32_t *)b); break;
      case ST_STRING: preferences.putString(d.nvsKey, (const char *)b); break;
    }
  }
}

// Even authenticated clients receive only <param>_set flags, never stored secrets.
void appendSettingsJson(String &json, const Settings &s) {
  for (size_t i = 0; i < SETTING_DEFS_COUNT; i++) {
    const SettingDef &d = SETTING_DEFS[i];
    const uint8_t *p = fieldAddr(s, d);
    json += "\"";
    json += d.param;
    if (d.type == ST_STRING && (d.flags & SF_SECRET)) {
      json += "_set\":";
      json += (((const char *)p)[0] != '\0') ? "true" : "false";
      json += ",";
      continue;
    }
    json += "\":";
    switch (d.type) {
      case ST_FLOAT:  json += String(*(const float *)p, 1); break;
      case ST_INT:    json += String(*(const int *)p); break;
      case ST_U8:     json += String((int)*(const uint8_t *)p); break;
      case ST_BOOL:   json += (*(const bool *)p) ? "true" : "false"; break;
      case ST_U32:    json += String((unsigned long)*(const uint32_t *)p); break;
      case ST_STRING: json += "\""; json += jsonEscape((const char *)p); json += "\""; break;
    }
    json += ",";
  }
}

// Фоновая задача на Core 0 для работы с облаком Ubidots
void vUbidotsTask(void *pvParameters) {
  // С какими данными роутера поднято текущее STA-соединение
  char connectedSsid[WIFI_SSID_MAX + 1] = "";
  char connectedPass[WIFI_PASS_MAX + 1] = "";

  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(120000)); // 2 минуты сна

    logPrintln("[Core 0] Пробуждение задачи Ubidots...");

    // Свои копии: глобальные данные других задач здесь напрямую не читаются
    Settings cfg = settingsSnapshot();
    State st = stateSnapshot();

    if (cfg.wifi_ssid[0] == '\0') {
      if (WiFi.status() == WL_CONNECTED) WiFi.disconnect();
      logPrintln("[Core 0] Wi-Fi роутера не настроен — телеметрия пропущена.");
      continue;
    }

    // Данные роутера поменяли через веб — рвём старое соединение. Иначе плата так и
    // сидела бы на прежней сети до первого обрыва связи.
    bool credsChanged = strcmp(cfg.wifi_ssid, connectedSsid) != 0 || strcmp(cfg.wifi_pass, connectedPass) != 0;
    if (credsChanged && WiFi.status() == WL_CONNECTED) {
      logPrintln("[Core 0] Настройки Wi-Fi изменились — переподключаемся.");
      WiFi.disconnect();
      vTaskDelay(pdMS_TO_TICKS(200));
    }

    // Режим AP+STA поднят один раз в setup() и больше не переключается. Раньше задача
    // каждые 2 минуты делала mode()/disconnect(true), из-за чего точка доступа
    // передёргивалась и телефон отваливался от веб-интерфейса прямо во время работы.
    if (WiFi.status() != WL_CONNECTED) {
      WiFi.begin(cfg.wifi_ssid, cfg.wifi_pass);
      strlcpy(connectedSsid, cfg.wifi_ssid, sizeof(connectedSsid));
      strlcpy(connectedPass, cfg.wifi_pass, sizeof(connectedPass));
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
    if (st.sht_online) {
      payload += "\"temperature\":" + String(st.temp, 2) + ",";
      payload += "\"humidity\":" + String(st.hum, 2) + ",";
    }
    payload += "\"led-power\":" + String(round(st.led_pwm / 2.55)) + ",";
    payload += "\"fan1-power\":" + String(round(st.fan1_pwm / 2.55)) + ",";
    payload += "\"fan2-power\":" + String(round(st.fan2_pwm / 2.55)) + ",";
    payload += "\"sensor-status\":" + String(st.sht_online ? 1 : 0); // Статус датчика в облако
    payload += "}";

    if (!cfg.ubidots_token[0] || !cfg.device_label[0]) continue;
    // System UTC for certificate validation; never modifies the local DS3231 schedule.
    configTime(0, 0, "pool.ntp.org", "time.cloudflare.com");
    for (int i = 0; time(nullptr) < 1704067200 && i < 40; ++i) vTaskDelay(pdMS_TO_TICKS(250));
    if (time(nullptr) < 1704067200) { logPrintln("[TLS] Waiting for UTC time; telemetry skipped."); continue; }
    WiFiClientSecure client;
    client.setCACert(UBIDOTS_ROOT_CA);
    client.setHandshakeTimeout(15);
    HTTPClient http;
    http.setTimeout(10000);

    if (http.begin(client, String("https://industrial.api.ubidots.com/api/v1.6/devices/") + cfg.device_label)) {
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Auth-Token", cfg.ubidots_token);
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

// Принудительное восстановление I2C-шины: если одно из устройств (SHT4x/RTC) зависло
// посреди транзакции и держит SDA в LOW, обычный Wire.begin()/sensor.begin() это НЕ чинит —
// нужно вручную "протактовать" SCL, чтобы slave-устройство доотправило начатый байт и
// освободило линию, затем сформировать STOP и переинициализировать Wire.
void recoverI2CBus() {
  Wire.end(); // Stop the driver before temporarily taking over its GPIOs.
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  pinMode(I2C_SCL_PIN, OUTPUT_OPEN_DRAIN);
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
  pinMode(I2C_SDA_PIN, OUTPUT_OPEN_DRAIN);
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

// Do not use rtc.now() for failure detection: its API does not report I2C errors.
bool readRTC(DateTime &result) {
  uint8_t raw[7];
  Wire.beginTransmission(0x68);
  Wire.write(uint8_t(0));
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(uint8_t(0x68), size_t(7), true) != 7) return false;
  for (int i = 0; i < 7; ++i) raw[i] = Wire.read();
  Wire.beginTransmission(0x68);
  Wire.write(uint8_t(0x0f));
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(uint8_t(0x68), size_t(1), true) != 1) return false;
  RtcFields fields{};
  if (!decodeRtc(raw, Wire.read(), fields)) return false;
  result = DateTime(fields.year, fields.month, fields.day, fields.hour, fields.minute, fields.second);
  return true;
}

// Безопасное время: из RTC или из программного бэкапа. Вызывается только из setup()/loop().
DateTime getSafeDateTime() {
  if (state.rtc_online) {
    DateTime now;
    if (readRTC(now)) {
      state.clock_trusted = true;
      backup_unixtime = now.unixtime(); // Синхронизируем бэкап
      last_rtc_check_ms = millis();     // ...и точку отсчёта программного таймера
      return now;
    }
    logPrintln("[КРИТИКА] RTC вернул некорректную дату! Переход на программный таймер.");
    state.rtc_online = false;
  }

  // Если RTC сломан, рассчитываем время программно на основе millis()
  advanceBackupClock(millis(), last_rtc_check_ms, backup_unixtime);
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
  if (state.rtc_online) return;
  if (currentMillis - last_rtc_retry < RTC_RETRY_INTERVAL_MS) return;
  last_rtc_retry = currentMillis;
  recoverI2CBus(); // Освобождаем шину на случай, если она физически "залипла"

  bool retry_ok = false;
  if (rtc.begin()) {
    DateTime now;
    // 2024..2099 — грубая защита от "проснувшегося после разряда батарейки" RTC,
    // который обычно сбрасывается на заводскую дату (например, 2000 или 2021 год)
    if (readRTC(now)) {
      retry_ok = true;
      rtc_recovery_streak++;
      logPrintf("[RTC] Попытка восстановления %d/%d успешна\n", rtc_recovery_streak, RTC_RECOVERY_STREAK_NEEDED);
      if (rtc_recovery_streak >= RTC_RECOVERY_STREAK_NEEDED) {
        state.rtc_online = true;
        state.clock_trusted = true;
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

String randomSecret() {
  char value[33];
  uint8_t bytes[16];
  esp_fill_random(bytes, sizeof(bytes));
  for (int i = 0; i < 16; ++i) snprintf(value + i * 2, 3, "%02x", bytes[i]);
  return String(value);
}

// Eight easy-to-type characters; keep the longer randomSecret() for CSRF.
String randomPassword() {
  static const char alphabet[] = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
  char password[9];
  for (size_t i = 0; i < 8; ++i) {
    uint8_t sample;
    esp_fill_random(&sample, 1);
    password[i] = alphabet[sample & 31];
  }
  password[8] = '\0';
  return String(password);
}

bool isLegacyGeneratedPassword(const String &password) {
  if (password.length() != 32) return false;
  for (size_t i = 0; i < password.length(); ++i) {
    char c = password[i];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

bool authorize(AsyncWebServerRequest *request) {
  if (!request->authenticate("admin", admin_password.c_str(), "GI")) {
    request->requestAuthentication("GI", true);
    return false;
  }
  if (request->method() == HTTP_POST) {
    String token;
    if (request->hasHeader("X-CSRF-Token")) token = request->getHeader("X-CSRF-Token")->value();
    else if (request->hasParam("csrf_token", true)) token = request->getParam("csrf_token", true)->value();
    if (token != csrf_token) {
      request->send(403, "text/plain", "Reload settings and retry");
      return false;
    }
  }
  return true;
}

void setup() {
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW);
  pinMode(HEATER_PIN, OUTPUT);
  digitalWrite(HEATER_PIN, LOW);
  Serial.begin(115200);
  // Внутри setup() после инициализации Serial
  #ifdef ESP_IDF_VERSION_VAL
    // Инициализация WDT на 15 секунды
    esp_task_wdt_config_t wdt_config = {
        .timeout_ms = 15000,
        .idle_core_mask = (1 << 0) | (1 << 1), // Мониторим оба ядра
        .trigger_panic = true
    };
    if (esp_task_wdt_reconfigure(&wdt_config) == ESP_ERR_INVALID_STATE) esp_task_wdt_init(&wdt_config);
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

  WiFi.mode(WIFI_STA); // RF entropy before generating passwords, no open AP.
  if (!preferences.begin("grow-box", false)) {
    Serial.println("Cannot initialize settings; outputs remain off.");
    while (true) delay(1000);
  }
  // A one-time upgrade rotates the old publicly documented AP password.
  if (!preferences.getBool("security_v1", false)) {
    String generated = randomPassword();
    if (!preferences.putString("ap_pass", generated) || !preferences.putBool("security_v1", true)) {
      Serial.println("Cannot persist AP password");
      while (true) delay(1000);
    }
  }
  admin_password = preferences.getString("admin_pass", "");
  if (admin_password.length() != 8) {
    admin_password = randomPassword();
    if (!preferences.putString("admin_pass", admin_password)) {
      Serial.println("Cannot persist admin password");
      while (true) delay(1000);
    }
  }
  csrf_token = randomSecret();

  // One-time migration of the previous generator's 32-character hex AP password.
  if (!preferences.getBool("short_pass_v1", false)) {
    String previous = preferences.getString("ap_pass", "");
    if (isLegacyGeneratedPassword(previous) && !preferences.putString("ap_pass", randomPassword())) {
      Serial.println("Cannot persist AP password"); while (true) delay(1000);
    }
    if (!preferences.putBool("short_pass_v1", true)) {
      Serial.println("Cannot persist password migration"); while (true) delay(1000);
    }
  }

  Settings cfg;
  loadSettingsFromNVS(cfg);
  if (strlen(cfg.ap_pass) < 8) {
    String generated = randomPassword();
    strlcpy(cfg.ap_pass, generated.c_str(), sizeof(cfg.ap_pass));
    if (!preferences.putString("ap_pass", cfg.ap_pass)) {
      Serial.println("Cannot persist AP password"); while (true) delay(1000);
    }
  }
  // USB only: credentials never enter the HTTP console buffer.
  Serial.printf("AP password: %s\nWeb login: admin / %s\n", cfg.ap_pass, admin_password.c_str());
  publishSettings(cfg);
  last_watering_day = preferences.getUInt("last_water", 0);

  state.is_day = true;

  // Безопасная инициализация датчиков с проверкой работоспособности.
  // Пробуем несколько раз с паузой — при старте платы I2C-шина/датчик могут быть
  // ещё не готовы (просадка питания от одновременного старта WiFi/вентиляторов/SD).
  state.sht_online = false;
  for (int i = 0; i < 5 && !state.sht_online; i++) {
    if (sht40.begin()) {
      state.sht_online = true;
    } else {
      logPrintf("[SHT4x] Попытка инициализации %d/5 не удалась, повтор через 200мс...\n", i + 1);
      delay(200);
    }
  }
  if (!state.sht_online) logPrintln("ОШИБКА: SHT4x не найден после 5 попыток!");

  state.rtc_online = false;
  for (int i = 0; i < 5 && !state.rtc_online; i++) {
    DateTime initialTime;
    if (rtc.begin() && readRTC(initialTime)) {
      backup_unixtime = initialTime.unixtime();
      last_rtc_check_ms = millis();
      state.clock_trusted = true;
      state.rtc_online = true;
    } else {
      logPrintf("[RTC] Попытка инициализации %d/5 не удалась, повтор через 200мс...\n", i + 1);
      delay(200);
    }
  }
  if (!state.rtc_online) {
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
  WiFi.softAP(cfg.ap_ssid, cfg.ap_pass[0] ? cfg.ap_pass : NULL);

  cached_unixtime = getSafeDateTime().unixtime(); // Веб-обработчики читают только этот снимок
  publishState(); // Первое состояние — до старта задач, которые его читают

  xTaskCreatePinnedToCore(vUbidotsTask, "UbidotsTask", 12288, NULL, 1, &UbidotsTaskHandle, 0); // 12 КБ: mbedTLS не влезает в 8

  // The same guard covers pages, static assets, APIs and future routes.
  server.addMiddleware([](AsyncWebServerRequest *request, ArMiddlewareNext next) {
    if (authorize(request)) next();
  });
  DefaultHeaders::Instance().addHeader("Cache-Control", "no-store");
  DefaultHeaders::Instance().addHeader("X-Frame-Options", "DENY");
  DefaultHeaders::Instance().addHeader("X-Content-Type-Options", "nosniff");

  // --- МАРШРУТИЗАЦИЯ ВЕБ-СЕРВЕРА ---
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/index.html", "text/html"); });
  server.on("/settings", HTTP_GET, [](AsyncWebServerRequest *request){ request->send(SPIFFS, "/settings.html", "text/html"); });
  // Остальная статика (css/js и всё, что появится в data/) раздаётся одним обработчиком —
  // регистрируется ниже, после API-маршрутов, чтобы точно не перехватывать /api/*

  server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest *request){
    State st = stateSnapshot();
    uint32_t start_ts = settingsSnapshot().start_timestamp;
    DateTime now = getWebDateTime();
    int grow_day = (start_ts > 0 && now.unixtime() >= start_ts) ? ((now.unixtime() - start_ts) / 86400) + 1 : 0;

    String json = "{";
    json += "\"temp\":" + String(st.temp, 2) + ",";
    json += "\"hum\":" + String(st.hum, 2) + ",";
    json += "\"led\":" + String(st.led_pwm) + ",";
    json += "\"fan1\":" + String(st.fan1_pwm) + ",";
    json += "\"fan2\":" + String(st.fan2_pwm) + ",";
    json += "\"time\":\"" + now.timestamp(DateTime::TIMESTAMP_TIME) + "\",";
    json += "\"date\":\"" + now.timestamp(DateTime::TIMESTAMP_DATE) + "\",";
    json += "\"is_day\":" + String(st.is_day ? "true" : "false") + ",";
    json += "\"grow_day\":" + String(grow_day) + ",";
    json += "\"sht_online\":" + String(st.sht_online ? "true" : "false") + ","; // Передаем статус в UI
    json += "\"rtc_online\":" + String(st.rtc_online ? "true" : "false") + ",";
    json += "\"clock_trusted\":" + String(st.clock_trusted ? "true" : "false") + ",";
    json += "\"pump_active\":" + String(st.pump_active ? "true" : "false") + ",";
    json += "\"heater_active\":" + String(st.heater_active ? "true" : "false");
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
    Settings cfg = settingsSnapshot();
    DateTime now = getWebDateTime();
    char buf[24]; snprintf(buf, sizeof(buf), "%02d.%02d.%04d %02d:%02d:%02d", now.day(), now.month(), now.year(), now.hour(), now.minute(), now.second());

    String json = "{";
    appendSettingsJson(json, cfg);
    json += "\"csrf_token\":\"" + csrf_token + "\",";
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
    // Работаем с копией: разбираем форму, проверяем, пишем в NVS и только потом публикуем
    // целиком — loop() и Ubidots никогда не видят наполовину применённые настройки.
    // Обработчики AsyncWebServer выполняются по одному, так что два сохранения
    // одновременно не случаются и изменения друг друга не затирают.
    Settings prev = settingsSnapshot();
    Settings next = prev;
    String rejected = applyFormToSettings(request, next);

    // Дата начала цикла приходит строкой YYYY-MM-DD — в таблицу не укладывается
    if (request->hasParam("start_date", true)) {
      int y, m, d;
      if (isValidLogDate(request->getParam("start_date", true)->value()) &&
          parseDate(request->getParam("start_date", true)->value(), y, m, d)) {
        next.start_timestamp = DateTime(y, m, d, 0, 0, 0).unixtime();
      } else {
        request->send(400, "text/plain", "Invalid start date"); return;
      }
    }

    saveChangedSettings(prev, next);
    publishSettings(next);

    // Новые SSID/пароль точки доступа применяем сразу, без перезагрузки платы.
    // Текущие клиенты при этом отключатся и должны подключиться заново с новыми данными.
    if (strcmp(prev.ap_ssid, next.ap_ssid) != 0 || strcmp(prev.ap_pass, next.ap_pass) != 0) {
      WiFi.softAP(next.ap_ssid, next.ap_pass[0] ? next.ap_pass : NULL);
    }

    if (rejected.length()) request->redirect("/settings?error=" + rejected);
    else request->redirect("/settings");
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
  server.serveStatic("/", SPIFFS, "/").setCacheControl("no-store");
  server.onNotFound([](AsyncWebServerRequest *request){ request->send(404, "text/plain", "Not found"); });

  server.begin();

  ledcAttach(LED_PWM_PIN, PWM_FREQ, PWM_RES);
  ledcAttach(FAN1_PWM_PIN, PWM_FREQ, PWM_RES);
  ledcAttach(FAN2_PWM_PIN, PWM_FREQ, PWM_RES);
}

void loop() {
  static unsigned long lastClimateTime = 0;
  unsigned long currentMillis = millis();
  if (state.pump_active && elapsedMs(currentMillis, pump_start_ms) >= pump_duration_ms) {
    state.pump_active = false;
    digitalWrite(PUMP_PIN, LOW);
    logPrintln("[Watering] Pump stopped at deadline.");
  }
  tryRecoverRTC(currentMillis); // Не блокирует: сам ограничивает частоту попыток внутри

  // Время читаем раз в секунду, а не на каждой итерации loop(): rtc.now() — полноценная
  // транзакция по I2C, и раньше она крутилась тысячи раз в секунду на той же шине,
  // по которой опрашивается SHT4x. Там же обновляем свою копию настроек: изменения из
  // веба вступают в силу не позже чем через секунду, а весь цикл видит одну цельную версию.
  static DateTime now((uint32_t)0);
  static Settings cfg;
  static unsigned long lastTimeRead = 0;
  if (lastTimeRead == 0 || currentMillis - lastTimeRead >= 1000) {
    lastTimeRead = currentMillis;
    now = getSafeDateTime();
    cached_unixtime = now.unixtime(); // Снимок, который отдают веб-обработчики
    cfg = settingsSnapshot();
  }

  // Часы, выставленные из веб-формы, применяем здесь: в I2C ходит только loop()
  uint32_t requested = pending_time_set.exchange(0);
  if (requested != 0) {
    DateTime userTime(requested);
    state.rtc_online = false;
    if (rtc.begin()) {
      rtc.adjust(userTime);
      DateTime checked;
      state.rtc_online = readRTC(checked) && checked.unixtime() >= requested && checked.unixtime() - requested <= 2;
    }
    state.clock_trusted = true;
    rtc_recovery_streak = 0;
    backup_unixtime = requested;
    last_rtc_check_ms = millis();
    now = userTime;
    cached_unixtime = requested;
    logPrintln("[RTC] Часы выставлены вручную через веб-интерфейс");
  }

  if (currentMillis - lastClimateTime >= 10000) {
    lastClimateTime = currentMillis;

    int current_hour = now.hour();
    int current_minutes = current_hour * 60 + now.minute();
    int on_minutes = cfg.led_on_hour * 60 + cfg.led_on_minute;
    int off_minutes = cfg.led_off_hour * 60 + cfg.led_off_minute;

    if (on_minutes == off_minutes) state.is_day = true; // время включения == времени выключения — считаем "весь день"
    else if (on_minutes < off_minutes) state.is_day = (current_minutes >= on_minutes && current_minutes < off_minutes);
    else state.is_day = (current_minutes >= on_minutes || current_minutes < off_minutes);
    const bool is_day = state.is_day;

    int pwm_fan1_min = map(cfg.fan1_min_limit, 0, 100, 0, 255);
    int pwm_fan1_max = map(cfg.fan1_max_limit, 0, 100, 0, 255);
    int pwm_fan2_min = map(cfg.fan2_min_limit, 0, 100, 0, 255);
    int pwm_fan2_max = map(cfg.fan2_max_limit, 0, 100, 0, 255);
    int pwm_led_min = map(cfg.led_min_limit, 0, 100, 0, 255);
    int pwm_led_max = map(cfg.led_max_limit, 0, 100, 0, 255);
    int pwm_fan_night_min = map(cfg.fan_night_min_limit, 0, 100, 0, 255);
    int pwm_fan_night_max = map(cfg.fan_night_max_limit, 0, 100, 0, 255);

    int target_led, target_fan1, target_fan2;
    float read_temp = state.temp; // По умолчанию — последнее известное валидное значение, а не 0.0
    float read_hum = state.hum;

    // Чтение датчика с проверкой на ошибку
    sensors_event_t humidity, temp;
    if (state.sht_online) {
      if (sht40.getEvent(&humidity, &temp)) {
        read_temp = temp.temperature;
        read_hum = humidity.relative_humidity;

        // Защита от "зависших" нереалистичных данных (за пределами работы датчика)
        if (read_temp < -20.0 || read_temp > 80.0 || read_hum < 0.0 || read_hum > 100.0) {
          state.sht_online = false;
        }
      } else {
        state.sht_online = false;
      }
    }

    // Датчик офлайн — периодически пробуем восстановиться, не дожидаясь перезагрузки платы.
    // Нужно несколько (SHT_RECOVERY_STREAK_NEEDED) подряд успешных попыток с интервалом
    // SHT_RETRY_INTERVAL_MS, прежде чем снова начать доверять показаниям.
    if (!state.sht_online && (currentMillis - last_sht_retry >= SHT_RETRY_INTERVAL_MS)) {
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
          state.sht_online = true;
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
    if (!state.sht_online) {
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
      state.heater_active = false;
      digitalWrite(HEATER_PIN, LOW);

      logPrintln("[АВАРИЙНЫЙ РЕЖИМ]: Отказ SHT4x! Климат зафиксирован на безопасных уровнях.");
    }
    else {
      // --- НОРМАЛЬНАЯ РАБОТА ---
      // Защита от temp_delta == 0, чтобы map() не делил на ноль
      float safe_delta = max(cfg.temp_delta, 0.1f);
      float current_min = cfg.temp_target - safe_delta;
      float current_max = cfg.temp_target + safe_delta;

      // Обогрев: своя цель ночью (temp_target_night), днём — общая temp_target.
      // На вентиляторы/лампу (current_min/current_max выше) это не влияет — они всегда считаются от дневной temp_target.
      float heater_target = is_day ? cfg.temp_target : cfg.temp_target_night;
      float heater_min = heater_target - safe_delta;

      bool heater_schedule_ok = (cfg.heater_mode == 2) || (cfg.heater_mode == 0 && is_day) || (cfg.heater_mode == 1 && !is_day);
      if (!heater_schedule_ok) {
        state.heater_active = false;
      } else if (!state.heater_active && read_temp <= heater_min) {
        state.heater_active = true;
      } else if (state.heater_active && read_temp >= heater_target) {
        state.heater_active = false;
      }
      digitalWrite(HEATER_PIN, state.heater_active ? HIGH : LOW);

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
        float night_hum_lo = cfg.min_hum_night;
        float night_hum_hi = cfg.max_hum_night;
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

    state.temp = read_temp;
    state.hum = read_hum;
    state.led_pwm = target_led;
    state.fan1_pwm = target_fan1;
    state.fan2_pwm = target_fan2;

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
      logFile.print(state.temp, 2); logFile.print(";");
      logFile.print(state.hum, 2); logFile.print(";");
      logFile.print(state.led_pwm); logFile.print(";");
      logFile.print(state.fan1_pwm); logFile.print(";");
      logFile.print(state.fan2_pwm); logFile.print(";");
      logFile.print(state.sht_online ? "1" : "0"); logFile.print(";");
      logFile.println(state.rtc_online ? "1" : "0");
      logFile.close();
    }
  }

  // --- АВТОПОЛИВ ---
  static unsigned long lastWaterCheck = 0;
  if (currentMillis - lastWaterCheck >= 1000) {
    lastWaterCheck = currentMillis;

    // RTClib: dayOfTheWeek() возвращает 0=Вс...6=Сб. Переводим в формат watering_days: 0=Пн...6=Вс
    int rtc_dow = now.dayOfTheWeek();
    int iso_dow = (rtc_dow == 0) ? 6 : rtc_dow - 1;
    uint32_t today_code = now.unixtime() / 86400;

    // Если датчик уровня воды выключен в настройках — считаем, что вода есть всегда (старое поведение)
    bool water_ok = !cfg.water_sensor_enabled || isWaterAvailable();

    if (!state.pump_active) {
      bool day_enabled = (cfg.watering_days >> iso_dow) & 0x01;
      if (day_enabled && now.hour() == cfg.watering_hour && now.minute() == cfg.watering_minute && wateringDayAllowed(state.clock_trusted, today_code, last_watering_day)) {
        // Persist before energizing the pump; reboot during this minute must not repeat it.
        last_watering_day = today_code;
        if (preferences.putUInt("last_water", today_code) != sizeof(uint32_t)) {
          logPrintln("[Watering] NVS write failed; pump remains off.");
        } else if (water_ok) {
          state.pump_active = true;
          pump_start_ms = millis();
          pump_duration_ms = uint32_t(cfg.watering_duration_sec) * 1000U;
          digitalWrite(PUMP_PIN, HIGH);
          logPrintln("[ПОЛИВ] Старт автополива");
        } else {
          last_watering_day = today_code; // Не пробуем каждую секунду до конца минуты — ждём до завтра
          logPrintln("[ПОЛИВ] Пропущен: датчик не видит воду в баке");
        }
      }
    } else {
      if (!water_ok) {
        // Аварийная остановка: вода закончилась прямо во время полива — не гоняем насос всухую
        state.pump_active = false;
        digitalWrite(PUMP_PIN, LOW);
        logPrintln("[ПОЛИВ] Аварийная остановка: вода закончилась во время полива");
      } else if (elapsedMs(millis(), pump_start_ms) >= pump_duration_ms) {
        // Длительность — по millis(), а не по RTC: если посреди полива восстановится RTC
        // (tryRecoverRTC) и время прыгнет, насос иначе либо выключится мгновенно, либо
        // будет лить, пока не сработает датчик уровня воды.
        state.pump_active = false;
        digitalWrite(PUMP_PIN, LOW);
        logPrintln("[ПОЛИВ] Полив завершён");
      }
    }
  }

  publishState(); // Сравнение с опубликованной копией; если ничего не менялось — no-op
  esp_task_wdt_reset();
  delay(1); // Yield to the monitored idle task.
}
