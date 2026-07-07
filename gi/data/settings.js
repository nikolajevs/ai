const wateringDayIds = ["wd_mon", "wd_tue", "wd_wed", "wd_thu", "wd_fri", "wd_sat", "wd_sun"];

function packWateringDays() {
    let mask = 0;
    wateringDayIds.forEach((id, i) => {
        if (document.getElementById(id).checked) mask |= (1 << i);
    });
    document.getElementById('watering_days').value = mask;
}

function unpackWateringDays(mask) {
    wateringDayIds.forEach((id, i) => {
        document.getElementById(id).checked = !!(mask & (1 << i));
    });
}

// "6" / "0" -> "06:00", для подстановки в <input type="time">
function formatTime(hour, minute) {
    return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

// Перекладывает выбранное время из <input type="time"> в скрытые поля часов/минут перед отправкой формы
function packLedTimes() {
    const [onHour, onMinute] = document.getElementById('led_on_time').value.split(':');
    const [offHour, offMinute] = document.getElementById('led_off_time').value.split(':');
    document.getElementById('led_on_hour').value = onHour;
    document.getElementById('led_on_minute').value = onMinute;
    document.getElementById('led_off_hour').value = offHour;
    document.getElementById('led_off_minute').value = offMinute;
}

function togglePasswordField(id) {
    const el = document.getElementById(id);
    el.type = (el.type === 'password') ? 'text' : 'password';
}

// Показываем баннер ошибки, если сервер отклонил сохранение (?error=ap,wifi в адресе после редиректа)
function showServerErrors() {
    const params = new URLSearchParams(window.location.search);
    const errors = (params.get('error') || '').split(',').filter(Boolean);
    if (errors.includes('ap')) {
        document.getElementById('ap-error-banner').style.display = 'block';
        document.querySelector('[data-tab="tab-network"]').click();
    }
    if (errors.includes('wifi')) {
        document.getElementById('wifi-error-banner').style.display = 'block';
        document.querySelector('[data-tab="tab-network"]').click();
    }
    if (errors.length) {
        // Убираем ?error=... из адресной строки, чтобы баннер не всплывал повторно при обновлении страницы
        window.history.replaceState({}, '', window.location.pathname);
    }
}

// Показывает текстовое сообщение в баннере ошибки конкретной формы и не даёт её отправить
function showFieldError(bannerId, message) {
    const banner = document.getElementById(bannerId);
    banner.textContent = message;
    banner.style.display = 'block';
}

function clearFieldError(bannerId) {
    const banner = document.getElementById(bannerId);
    banner.style.display = 'none';
    banner.textContent = '';
}

// Проверка, что значение поля "мин" не превышает значение поля "макс"; при ошибке — блокирует отправку формы
function attachMinMaxValidation(formId, minId, maxId, bannerId, label) {
    const form = document.getElementById(formId);
    if (!form) return;
    form.addEventListener('submit', (e) => {
        const minVal = parseFloat(document.getElementById(minId).value);
        const maxVal = parseFloat(document.getElementById(maxId).value);
        if (isNaN(minVal) || isNaN(maxVal) || minVal > maxVal) {
            e.preventDefault();
            showFieldError(bannerId, `${label}: минимальное значение не может быть больше максимального.`);
        } else {
            clearFieldError(bannerId);
        }
    });
}

// WiFi роутера: та же логика валидации, что и на сервере (SSID до 32 символов, пароль пусто или 8-63 символа)
function attachWifiValidation() {
    const form = document.getElementById('wifi-form');
    if (!form) return;
    form.addEventListener('submit', (e) => {
        const ssid = document.getElementById('wifi_ssid').value.trim();
        const pass = document.getElementById('wifi_pass').value;
        const ssidOk = ssid.length <= 32;
        const passOk = pass.length === 0 || (pass.length >= 8 && pass.length <= 63);
        if (!ssidOk || !passOk) {
            e.preventDefault();
            showFieldError('wifi-error-banner', 'Имя сети — до 32 символов, пароль — пусто (открытая сеть) или от 8 до 63 символов.');
        } else {
            clearFieldError('wifi-error-banner');
        }
    });
}

function setCurrentTime() {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    const localISOTime = (new Date(now - offset)).toISOString().slice(0, 16);
    document.getElementById('datetime').value = localISOTime;
}

async function loadCurrentSettings() {
    try {
        const res = await fetch('/api/settings');
        if (!res.ok) throw new Error("Ошибка ответа сервера");
        
        const data = await res.json();
        
        document.getElementById('temp_target').value = data.temp_target;
        document.getElementById('temp_delta').value = data.temp_delta;
        document.getElementById('max_hum_night').value = data.max_hum_night;
        document.getElementById('led_on_time').value = formatTime(data.led_on_hour, data.led_on_minute);
        document.getElementById('led_off_time').value = formatTime(data.led_off_hour, data.led_off_minute);
        document.getElementById('fan1_min_limit').value = data.fan1_min_limit;
        document.getElementById('fan1_max_limit').value = data.fan1_max_limit;
        document.getElementById('fan2_min_limit').value = data.fan2_min_limit;
        document.getElementById('fan2_max_limit').value = data.fan2_max_limit;
        document.getElementById('led_min_limit').value = data.led_min_limit; 
        document.getElementById('led_max_limit').value = data.led_max_limit;
        document.getElementById('min_hum_night').value = data.min_hum_night;
        document.getElementById('fan_night_min_limit').value = data.fan_night_min_limit;
        document.getElementById('fan_night_max_limit').value = data.fan_night_max_limit;
        document.getElementById('rtc-time-label').innerText = data.rtc_time;

        document.getElementById('watering_hour').value = data.watering_hour;
        document.getElementById('watering_minute').value = data.watering_minute;
        document.getElementById('watering_duration').value = data.watering_duration;
        unpackWateringDays(data.watering_days);
        document.getElementById('heater_mode').value = data.heater_mode;

        document.getElementById('wifi_ssid').value = data.wifi_ssid;
        document.getElementById('wifi_pass').value = data.wifi_pass;
        document.getElementById('ubidots_token').value = data.ubidots_token;
        document.getElementById('device_label').value = data.device_label;
        document.getElementById('ap_ssid').value = data.ap_ssid;
        document.getElementById('ap_pass').value = data.ap_pass;
        
        if (data.start_time > 0) {
            const d = new Date(data.start_time * 1000);
            const yyyy = d.getFullYear();
            const mm = String(d.getMonth() + 1).padStart(2, '0');
            const dd = String(d.getDate()).padStart(2, '0');
            document.getElementById('start_date').value = `${yyyy}-${mm}-${dd}`;
        }
        const today = new Date();
        document.getElementById('start_date').max =
            `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    } catch (e) {
        console.error("Ошибка загрузки настроек:", e);
        document.getElementById('rtc-time-label').innerText = "Ошибка связи";
    }
}

function initTabs() {
    const buttons = document.querySelectorAll('.tab-btn');
    const panels = document.querySelectorAll('.tab-panel');

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            panels.forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(btn.dataset.tab).classList.add('active');
        });
    });
}

window.onload = () => {
    setCurrentTime();
    loadCurrentSettings();
    document.getElementById('watering-form').addEventListener('submit', packWateringDays);
    document.getElementById('light-form').addEventListener('submit', packLedTimes);
    initTabs();
    showServerErrors();

    attachMinMaxValidation('climate-form', 'min_hum_night', 'max_hum_night', 'climate-error-banner', 'Ночная влажность (нижний/верхний предел)');
    attachMinMaxValidation('light-form', 'led_min_limit', 'led_max_limit', 'light-error-banner', 'Мощность лампы (мин/макс)');
    attachMinMaxValidation('fans-night-form', 'fan_night_min_limit', 'fan_night_max_limit', 'fans-night-error-banner', 'Ночная вентиляция (мин/макс)');
    attachWifiValidation();

    // Форма "Лимиты вентиляторов" содержит сразу 2 пары мин/макс (вентилятор 1 и 2) — проверяем обе одним обработчиком
    document.getElementById('fans-limits-form').addEventListener('submit', (e) => {
        const fan1Min = parseFloat(document.getElementById('fan1_min_limit').value);
        const fan1Max = parseFloat(document.getElementById('fan1_max_limit').value);
        const fan2Min = parseFloat(document.getElementById('fan2_min_limit').value);
        const fan2Max = parseFloat(document.getElementById('fan2_max_limit').value);
        if (!isNaN(fan1Min) && !isNaN(fan1Max) && fan1Min > fan1Max) {
            e.preventDefault();
            showFieldError('fans-limits-error-banner', 'Вентилятор 1 (мин/макс): минимальное значение не может быть больше максимального.');
            return;
        }
        if (!isNaN(fan2Min) && !isNaN(fan2Max) && fan2Min > fan2Max) {
            e.preventDefault();
            showFieldError('fans-limits-error-banner', 'Вентилятор 2 (мин/макс): минимальное значение не может быть больше максимального.');
            return;
        }
        clearFieldError('fans-limits-error-banner');
    });
};