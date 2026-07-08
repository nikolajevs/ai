let currentSelectedDate = "";
let chartPoints = [];
let chartViewBox = { width: 1000, height: 400 };

async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.sht_online) {
            document.getElementById('t-val').innerHTML = data.temp.toFixed(1) + '<span class="unit">°C</span>';
            document.getElementById('h-val').innerHTML = data.hum.toFixed(1) + '<span class="unit">%</span>';
            document.getElementById('sensor-status-badge').style.display = 'none';
        } else {
            document.getElementById('t-val').innerHTML = '--:--';
            document.getElementById('h-val').innerHTML = '--:--';
            document.getElementById('sensor-status-badge').style.display = 'inline-block';
        }
        document.getElementById('led-val').innerHTML = Math.round(data.led / 2.55) + '<span class="unit">%</span>';
        document.getElementById('fan1-val').innerHTML = Math.round(data.fan1 / 2.55) + '<span class="unit">%</span>';
        document.getElementById('fan2-val').innerHTML = Math.round(data.fan2 / 2.55) + '<span class="unit">%</span>';

        const timeEl = document.getElementById('box-time');
        timeEl.innerText = data.time;
        if (!timeEl.classList.contains('status-badge')) {
            timeEl.className = "status-badge time-badge";
        }

        const pumpEl = document.getElementById('pump-val');
        if (data.pump_active) {
            pumpEl.innerText = 'ВКЛЮЧЕН 💦';
            pumpEl.style.color = 'var(--warning)';
        } else {
            pumpEl.innerText = 'Выключен';
            pumpEl.style.color = 'var(--text-muted)';
        }

        const heaterEl = document.getElementById('heater-val');
        if (data.heater_active) {
            heaterEl.innerText = 'ВКЛЮЧЕН 🌞';
            heaterEl.style.color = 'var(--warning)';
        } else {
            heaterEl.innerText = 'Выключен';
            heaterEl.style.color = 'var(--text-muted)';
        }
        
        // Первоначальное выставление даты в календаре, если пользователь её ещё не менял
        if (!currentSelectedDate) {
            currentSelectedDate = data.date;
            const dateInput = document.getElementById('chart-date-selector');
            if (dateInput) {
                dateInput.value = data.date;
                drawSvgChart(); // Запуск отрисовки текущего дня
            }
        }

        const cycleEl = document.getElementById('cycle-str');
        
        if (data.grow_day > 0) {
            cycleEl.innerText = `ДЕНЬ: ${data.grow_day}`;
        } else {
            cycleEl.innerText = `ЦИКЛ НЕ НАЧАТ`;
        }
        
        if(data.is_day) {
            cycleEl.className = "status-badge day-badge";
        } else {
            cycleEl.className = "status-badge night-badge";
        }
    } catch (e) { console.error("Ошибка API:", e); }
}

async function drawSvgChart() {
    if (!currentSelectedDate) return;
    try {
        // Запрашиваем конкретный файл лога через API
        const res = await fetch(`/api/log?date=${currentSelectedDate}`);
        const text = await res.text();
        const lines = text.trim().split('\n');
        
        // Проверяем, есть ли данные кроме заголовка
        if (lines.length <= 1) {
            document.getElementById('svgChart').innerHTML = `<text x="500" y="200" fill="var(--text-muted)" text-anchor="middle" font-size="16">Нет записей лога за выбранный день</text>`;
            chartPoints = [];
            return;
        }

        const dataLines = lines.slice(1);
        const data = [];
        // Берем каждую точку для отображения суточного хода (так как точек за день много, прореживаем по надобности)
        // Для суточного файла можно отображать каждую 10-ю или 15-ю запись для красивой плавности
        const step = dataLines.length > 300 ? Math.floor(dataLines.length / 100) : 1; 

        for (let i = 0; i < dataLines.length; i += step) {
            const cols = dataLines[i].split(';');
            if (cols.length >= 3) {
                // Извлекаем "HH:MM" из полной метки времени YYYY-MM-DDTHH:MM:SS
                const timePart = cols[0].split('T')[1]?.substring(0, 5) || "--:--";
                data.push({ time: timePart, temp: parseFloat(cols[1]), hum: parseFloat(cols[2]) });
            }
        }
        
        if (data.length === 0) return;

        const width = 1000, height = 400, padding = { top: 40, right: 60, bottom: 40, left: 60 };
        const chartWidth = width - padding.left - padding.right, chartHeight = height - padding.top - padding.bottom;
        
        const temps = data.map(d => d.temp), hums = data.map(d => d.hum);
        const minTemp = Math.floor(Math.min(...temps) - 1), maxTemp = Math.ceil(Math.max(...temps) + 1);
        const minHum = Math.floor(Math.min(...hums) - 5), maxHum = Math.ceil(Math.max(...hums) + 5);
        
        const getX = (index) => padding.left + (index / (data.length - 1)) * chartWidth;
        const getYTemp = (val) => padding.top + chartHeight - ((val - minTemp) / (maxTemp - minTemp)) * chartHeight;
        const fillYHum = (val) => padding.top + chartHeight - ((val - minHum) / (maxHum - minHum)) * chartHeight;
        
        let tempPath = `M ${getX(0)} ${getYTemp(data[0].temp)}`, humPath = `M ${getX(0)} ${fillYHum(data[0].hum)}`;
        for (let i = 1; i < data.length; i++) {
            tempPath += ` L ${getX(i)} ${getYTemp(data[i].temp)}`;
            humPath += ` L ${getX(i)} ${fillYHum(data[i].hum)}`;
        }
        
        const svg = document.getElementById('svgChart');
        let svgContent = '';
        
        // Сетка
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (chartHeight / 4) * i;
            svgContent += `<line class="grid-line" x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" />`;
            svgContent += `<text class="axis-text" x="${padding.left - 10}" y="${y + 4}" text-anchor="end">${(maxTemp - ((maxTemp - minTemp) / 4) * i).toFixed(1)}°C</text>`;
            svgContent += `<text class="axis-text" x="${width - padding.right + 10}" y="${y + 4}" text-anchor="start">${Math.round(maxHum - ((maxHum - minHum) / 4) * i)}%</text>`;
        }
        
        // Временные метки по оси X
        const timeStep = Math.max(1, Math.floor(data.length / 6));
        for (let i = 0; i < data.length; i += timeStep) {
            svgContent += `<text class="axis-text" x="${getX(i)}" y="${height - padding.bottom + 20}" text-anchor="middle">${data[i].time}</text>`;
        }
        
        svgContent += `<path class="line-temp" d="${tempPath}" /><path class="line-hum" d="${humPath}" />`;

        // Элементы наведения (изначально скрыты через opacity в CSS)
        svgContent += `<line id="hoverLine" class="hover-line" x1="0" y1="${padding.top}" x2="0" y2="${height - padding.bottom}" />`;
        svgContent += `<circle id="hoverDotTemp" class="hover-dot hover-dot-temp" cx="0" cy="0" />`;
        svgContent += `<circle id="hoverDotHum" class="hover-dot hover-dot-hum" cx="0" cy="0" />`;
        // Прозрачный слой поверх графика — ловит движения мыши по всей области
        svgContent += `<rect class="chart-overlay" x="${padding.left}" y="${padding.top}" width="${chartWidth}" height="${chartHeight}" />`;

        svg.innerHTML = svgContent;

        // Сохраняем точки для обработчика наведения мыши
        chartViewBox = { width, height };
        chartPoints = data.map((d, i) => ({
            x: getX(i), yTemp: getYTemp(d.temp), yHum: fillYHum(d.hum),
            time: d.time, temp: d.temp, hum: d.hum
        }));
    } catch (e) { console.error("Ошибка построения графиков:", e); }
}

function handleChartHover(e) {
    if (chartPoints.length === 0) return;
    const svg = document.getElementById('svgChart');
    const rect = svg.getBoundingClientRect();
    const scaleX = chartViewBox.width / rect.width;

    const mouseXsvg = (e.clientX - rect.left) * scaleX;

    // Ищем ближайшую по X точку данных
    let nearest = chartPoints[0], minDist = Infinity;
    for (const p of chartPoints) {
        const dist = Math.abs(p.x - mouseXsvg);
        if (dist < minDist) { minDist = dist; nearest = p; }
    }

    document.getElementById('hoverLine').setAttribute('x1', nearest.x);
    document.getElementById('hoverLine').setAttribute('x2', nearest.x);
    document.getElementById('hoverLine').style.opacity = 1;

    document.getElementById('hoverDotTemp').setAttribute('cx', nearest.x);
    document.getElementById('hoverDotTemp').setAttribute('cy', nearest.yTemp);
    document.getElementById('hoverDotTemp').style.opacity = 1;

    document.getElementById('hoverDotHum').setAttribute('cx', nearest.x);
    document.getElementById('hoverDotHum').setAttribute('cy', nearest.yHum);
    document.getElementById('hoverDotHum').style.opacity = 1;

    const tooltip = document.getElementById('chart-tooltip');
    tooltip.innerHTML = `<div class="tt-time">${nearest.time}</div><div class="tt-temp">🌡 ${nearest.temp.toFixed(1)}°C</div><div class="tt-hum">💧 ${nearest.hum.toFixed(1)}%</div>`;
    tooltip.style.left = (nearest.x / chartViewBox.width) * rect.width + 'px';
    tooltip.style.top = ((nearest.yTemp < nearest.yHum ? nearest.yTemp : nearest.yHum) / chartViewBox.height) * rect.height + 'px';
    tooltip.style.opacity = 1;
}

function handleChartLeave() {
    const hoverLine = document.getElementById('hoverLine');
    const hoverDotTemp = document.getElementById('hoverDotTemp');
    const hoverDotHum = document.getElementById('hoverDotHum');
    if (hoverLine) hoverLine.style.opacity = 0;
    if (hoverDotTemp) hoverDotTemp.style.opacity = 0;
    if (hoverDotHum) hoverDotHum.style.opacity = 0;
    document.getElementById('chart-tooltip').style.opacity = 0;
}

document.getElementById('svgChart').addEventListener('mousemove', handleChartHover);
document.getElementById('svgChart').addEventListener('mouseleave', handleChartLeave);

// Слушатель ручного выбора даты в календаре
document.getElementById('chart-date-selector').addEventListener('change', (e) => {
    currentSelectedDate = e.target.value;
    drawSvgChart();
});

setInterval(updateStatus, 3000);
updateStatus(); 

// Автоматически раз в 5 минут обновляем текущий график, если смотрим сегодняшний день
setInterval(() => {
    const todayStr = new Date().toISOString().split('T')[0];
    if (currentSelectedDate === todayStr) {
        drawSvgChart();
    }
}, 300000);
