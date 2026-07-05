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
        document.getElementById('led_on_hour').value = data.led_on_hour;
        document.getElementById('led_off_hour').value = data.led_off_hour;
        document.getElementById('fan1_min_limit').value = data.fan1_min_limit;
        document.getElementById('fan1_max_limit').value = data.fan1_max_limit;
        document.getElementById('fan2_min_limit').value = data.fan2_min_limit;
        document.getElementById('fan2_max_limit').value = data.fan2_max_limit;
        document.getElementById('led_min_limit').value = data.led_min_limit; 
        document.getElementById('led_max_limit').value = data.led_max_limit;
        document.getElementById('rtc-time-label').innerText = data.rtc_time;

        document.getElementById('watering_hour').value = data.watering_hour;
        document.getElementById('watering_minute').value = data.watering_minute;
        document.getElementById('watering_duration').value = data.watering_duration;
        unpackWateringDays(data.watering_days);
        document.getElementById('heater_mode').value = data.heater_mode;
        
        if (data.start_time > 0) {
            const d = new Date(data.start_time * 1000);
            const yyyy = d.getFullYear();
            const mm = String(d.getMonth() + 1).padStart(2, '0');
            const dd = String(d.getDate()).padStart(2, '0');
            document.getElementById('start_date').value = `${yyyy}-${mm}-${dd}`;
        }
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
    initTabs();
};