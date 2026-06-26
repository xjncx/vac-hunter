const $ = (selector) => document.querySelector(selector);
let savedMailPassword = false;

function updateGmailStatus(config={}) {
  const node = $('#gmail-status');
  if (!node) return;
  const email = String(config.mail_username || '').trim();
  const password = String(config.mail_password || '').trim();
  const host = String(config.imap_host || '').trim() || 'imap.gmail.com';
  const connected = Boolean(email && password);
  node.classList.toggle('is-connected', connected);
  node.classList.toggle('is-missing', !connected);
  node.textContent = connected
    ? `Gmail подключен: ${email} (${host})`
    : 'Gmail не подключен: укажите почту и app password';
}

function validateServiceConfig(form, payload) {
  form.querySelectorAll('.is-invalid').forEach(field => field.classList.remove('is-invalid'));
  const errors = [];
  const required = [
    ['imap_host', 'IMAP host'],
    ['imap_port', 'IMAP port'],
    ['mail_username', 'Почта, которую читать'],
    ['mail_sender_filter', 'Фильтр отправителя'],
    ['notification_email', 'Email для уведомлений'],
    ['desired_roles', 'Желаемые роли'],
    ['desired_skills', 'Ключевые навыки'],
    ['excluded_terms', 'Стоп-слова'],
    ['resume_text', 'Резюме / профиль кандидата'],
  ];

  if (!savedMailPassword) required.push(['mail_password', 'App password почты']);
  if (payload.auto_sync_enabled) required.push(['sync_interval_minutes', 'Интервал проверки']);

  for (const [name, label] of required) {
    if (!String(payload[name] || '').trim()) {
      errors.push(label);
      form.elements[name]?.classList.add('is-invalid');
    }
  }

  const port = Number(payload.imap_port);
  if (payload.imap_port && (!Number.isInteger(port) || port <= 0)) {
    errors.push('IMAP port должен быть положительным числом');
    form.elements.imap_port?.classList.add('is-invalid');
  }

  const threshold = Number(payload.match_threshold || 75);
  if (!Number.isFinite(threshold) || threshold < 0 || threshold > 100) {
    errors.push('Порог совпадения должен быть от 0 до 100');
    form.elements.match_threshold?.classList.add('is-invalid');
  }

  const scanLimit = Number(payload.market_scan_limit || 30);
  if (!Number.isInteger(scanLimit) || scanLimit < 1 || scanLimit > 100) {
    errors.push('Количество вакансий для оценки ИИ должно быть от 1 до 100');
    form.elements.market_scan_limit?.classList.add('is-invalid');
  }

  const interval = Number(payload.sync_interval_minutes || 15);
  if (payload.auto_sync_enabled && (!Number.isFinite(interval) || interval < 5)) {
    errors.push('Интервал проверки должен быть не меньше 5 минут');
    form.elements.sync_interval_minutes?.classList.add('is-invalid');
  }

  return errors;
}

async function api(url, options={}) {
  const response = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  const contentType = response.headers.get('Content-Type') || '';
  const raw = await response.text();
  let data = {};
  if (contentType.includes('application/json')) {
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch (error) {
      throw new Error(`Сервер вернул поврежденный JSON: ${error.message}`);
    }
  } else {
    const plain = raw.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
    throw new Error(plain ? `Сервер вернул не JSON: ${plain.slice(0, 240)}` : `Сервер вернул HTTP ${response.status} без JSON`);
  }
  if (!response.ok) throw new Error(data.details ? `${data.error}: ${JSON.stringify(data.details)}` : data.error);
  return data;
}

function setBusy(isBusy, text='Работаю…') {
  const progress = $('#progress');
  const progressText = $('#progress-text');
  if (progress) progress.hidden = !isBusy;
  if (progressText) progressText.textContent = text;
  document.querySelectorAll('button').forEach(button => {
    button.disabled = isBusy;
  });
}

async function waitForJob(jobId, progressText='Работаю…') {
  setBusy(true, progressText);
  while (true) {
    const job = await api(`/api/job?id=${encodeURIComponent(jobId)}`);
    if (job.status === 'done') {
      setBusy(false);
      return job.result || {};
    }
    if (job.status === 'error') {
      setBusy(false);
      throw new Error(job.message || 'Задача завершилась с ошибкой');
    }
    setBusy(true, job.message || progressText);
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
}

async function loadStatus() {
  const status = await api('/api/status');
  $('#status').textContent = status.user_agent_configured
    ? 'Сервис готов · email-дайджест'
    : 'Укажите контактный email в .env';
}

async function loadServiceConfig() {
  const data = await api('/api/service-config');
  savedMailPassword = Boolean(data.mail_password);
  const form = $('#service-config-form');
  for (const [key, value] of Object.entries(data)) {
    const field = form.elements[key];
    if (!field) continue;
    if (field.type === 'checkbox') {
      field.checked = ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
      continue;
    }
    if (key === 'mail_password' && value === '********') continue;
    field.value = value ?? '';
  }
  updateGmailStatus(data);
}

async function loadLastSync() {
  const data = await api('/api/last-sync');
  if (!data.ts) return;
  const when = new Date(data.ts * 1000).toLocaleString('ru');
  const errors = data.errors?.length ? `, ошибок: ${data.errors.length}` : '';
  $('#last-sync').textContent = `Последняя синхронизация: ${when}, писем: ${data.emails || 0}, вакансий: ${data.vacancies || 0}${errors}`;
}

$('#service-config-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('#notice').textContent = 'Сохраняю настройки…';
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  payload.ai_enabled = event.currentTarget.elements.ai_enabled.checked ? 'on' : '';
  payload.auto_sync_enabled = event.currentTarget.elements.auto_sync_enabled.checked ? 'on' : '';
  if (payload.mail_password === '********') delete payload.mail_password;
  const errors = validateServiceConfig(event.currentTarget, payload);
  if (errors.length) {
    $('#notice').textContent = `Заполните обязательные поля: ${errors.join(', ')}`;
    return;
  }
  try {
    const result = await api('/api/service-config', {method:'POST', body:JSON.stringify(payload)});
    savedMailPassword = Boolean(result.config?.mail_password || payload.mail_password);
    updateGmailStatus(result.config || payload);
    $('#notice').textContent = 'Настройки сохранены';
  } catch (error) {
    $('#notice').textContent = error.message;
  }
});

$('#mail-sync').addEventListener('click', async () => {
  $('#notice').textContent = 'Читаю почту, ранжирую вакансии и готовлю письмо…';
  setBusy(true, 'Читаю почту и оцениваю вакансии…');
  try {
    const data = await api('/api/mail/sync', {
      method: 'POST',
      body: JSON.stringify({
        limit: 50,
        fetch_descriptions: true,
      }),
    });
    const emailCount = data.emails?.length || 0;
    const vacancyCount = data.vacancies?.length || 0;
    const errors = data.errors?.length ? `, ошибок: ${data.errors.length}` : '';
    $('#notice').textContent = `Писем обработано: ${emailCount}, вакансий найдено: ${vacancyCount}${errors}${data.notification_sent ? ', подборка отправлена' : ', подходящих вакансий для отправки нет'}`;
    await loadLastSync();
  } catch (error) {
    $('#notice').textContent = error.message;
  } finally {
    setBusy(false);
  }
});

$('#market-scan').addEventListener('click', async () => {
  $('#notice').textContent = 'Сканирую рынок, оцениваю вакансии ИИ и готовлю письмо…';
  setBusy(true, 'Запускаю сканирование рынка…');
  try {
    const limit = Number($('#service-config-form').elements.market_scan_limit.value || 30);
    const started = await api('/api/market/scan-job', {
      method: 'POST',
      body: JSON.stringify({limit}),
    });
    const data = await waitForJob(started.job_id, 'Сканирую рынок и оцениваю вакансии…');
    const vacancyCount = data.vacancies?.length || 0;
    const errors = data.errors?.length ? `, ошибок: ${data.errors.length}` : '';
    $('#notice').textContent = `Запрос: ${data.query}. Вакансий оценено: ${vacancyCount}${errors}${data.notification_sent ? ', подборка отправлена' : ', подходящих вакансий для отправки нет'}`;
    await loadLastSync();
  } catch (error) {
    $('#notice').textContent = error.message;
    setBusy(false);
  }
});
loadStatus().catch(error => $('#status').textContent = error.message);
loadServiceConfig().catch(error => $('#notice').textContent = error.message);
loadLastSync().catch(() => {});
