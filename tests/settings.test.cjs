const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function page() {
  const fields = new Map();
  const forms = Array.from({length: 8}, () => ({
    inputs: [], querySelector() { return this.inputs[0]; },
    appendChild(input) { this.inputs.push(input); }
  }));
  const calls = [], alerts = [];
  const context = vm.createContext({
    console, URLSearchParams, Date,
    window: {},
    document: {
      getElementById(id) {
        if (!fields.has(id)) fields.set(id, {value: 'previous', style: {}});
        return fields.get(id);
      },
      querySelectorAll() { return forms; },
      createElement() { return {}; }
    },
    confirm: () => true,
    alert: text => alerts.push(text),
    fetch: async (url, options) => {
      calls.push({url, options});
      return {ok: true, json: async () => ({csrf_token: 'random-per-boot-token',
        wifi_ssid: 'Box"\\Lab', ap_ssid: 'Private AP', device_label: 'box',
        led_on_hour: 6, led_on_minute: 0, led_off_hour: 18, led_off_minute: 0,
        watering_days: 0, start_time: 0})};
    }
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../gi/data/settings.js'), 'utf8'), context);
  return {context, fields, forms, calls, alerts};
}

test('settings keep secrets empty, preserve special characters and attach CSRF to every form', async () => {
  const p = page();
  await vm.runInContext('loadCurrentSettings()', p.context);
  assert.equal(p.fields.get('wifi_ssid').value, 'Box"\\Lab');
  for (const name of ['wifi_pass', 'ap_pass', 'ubidots_token']) assert.equal(p.fields.get(name).value, '');
  for (const form of p.forms) {
    assert.equal(form.inputs[0].name, 'csrf_token');
    assert.equal(form.inputs[0].value, 'random-per-boot-token');
    assert.equal(form.inputs[0].type, 'hidden');
  }
  await vm.runInContext('loadCurrentSettings()', p.context);
  for (const form of p.forms) assert.equal(form.inputs.length, 1);
});

test('clear logs refuses to run before token is loaded', () => {
  const p = page();
  vm.runInContext('clearSDLogs()', p.context);
  assert.equal(p.calls.length, 0);
  assert.equal(p.alerts.length, 1);
});

test('clear logs uses authenticated same-origin POST with CSRF', async () => {
  const p = page();
  await vm.runInContext('loadCurrentSettings()', p.context);
  vm.runInContext('clearSDLogs()', p.context);
  const request = p.calls.find(c => c.url === '/api/clearlogs');
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.headers['X-CSRF-Token'], 'random-per-boot-token');
});
