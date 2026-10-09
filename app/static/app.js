(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  const initData = tg ? tg.initData : "";
  const TZ = "Europe/Istanbul";
  const DAY_KEYS = ["pazar", "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi"];
  const WEEKDAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma"];
  const $ = (id) => document.getElementById(id);
  const TRASH = '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M7 7l1 13h8l1-13M9.5 7V4.5h5V7"/></svg>';

  const state = { view: "today", settings: null, settingsDraft: null, schedules: null, kind: "okul", day: "pazartesi", lessonsDraft: null, saveFn: null };

  function haptic(type) {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(type);
  }

  let toastTimer;
  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  function confirmAsk(text) {
    return new Promise((resolve) => {
      if (tg && tg.showConfirm) tg.showConfirm(text, resolve);
      else resolve(window.confirm(text));
    });
  }

  async function api(method, path, body) {
    const opts = { method, headers: { Authorization: "tma " + initData } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Sunucuya ulaşılamadı");
    return data;
  }

  function fail(err) {
    haptic("error");
    toast(err.message);
  }

  function esc(text) {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(text).replace(/[&<>"']/g, (c) => map[c]);
  }

  const fmtTime = (iso) => new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", timeZone: TZ });
  const fmtDate = (iso) => new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "long", weekday: "long", timeZone: TZ });
  const fmtShort = (iso) => new Date(iso).toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ });

  function todayKey() {
    const now = new Date(new Date().toLocaleString("en-US", { timeZone: TZ }));
    return DAY_KEYS[now.getDay()];
  }

  function setMainButton(text, fn) {
    state.saveFn = fn;
    if (!tg) return;
    if (fn) {
      tg.MainButton.setText(text);
      tg.MainButton.show();
    } else {
      tg.MainButton.hide();
    }
  }

  async function runSave() {
    if (!state.saveFn) return;
    if (tg) tg.MainButton.showProgress();
    try {
      await state.saveFn();
      haptic("success");
    } catch (err) {
      fail(err);
    } finally {
      if (tg) tg.MainButton.hideProgress();
    }
  }

  function showView(name) {
    state.view = name;
    document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== "view-" + name));
    document.querySelectorAll(".tabs button").forEach((b) => {
      if (b.dataset.view === name) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    setMainButton(null, null);
    window.scrollTo(0, 0);
    if (name === "settings") loadSettings().catch(fail);
    if (name === "program") loadProgram().catch(fail);
    if (name === "notes") loadNotes().catch(fail);
    if (name === "today") loadToday().catch(fail);
  }

  function skyLine(hourly) {
    const pts = hourly.slice(6, 24);
    const lo = Math.min(...pts);
    const hi = Math.max(...pts);
    const span = Math.max(hi - lo, 4);
    const base = (lo + hi) / 2 - span / 2;
    const xy = pts.map((t, i) => [(i / (pts.length - 1)) * 360, 56 - ((t - base) / span) * 46]);
    const line = xy.map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1)).join(" ");
    $("sky-line").innerHTML = `<path class="area" d="${line} L360 64 L0 64 Z"/><path class="stroke" d="${line}"/>`;
  }

  function lessonItems(list, emptyText) {
    if (list === null || list === undefined) return `<p class="empty">${emptyText}</p>`;
    if (!list.length) return '<p class="empty">Bugün ders yok.</p>';
    return list
      .map((l) => `<div class="item"><span class="item-time">${esc(l.saat || "")}</span><div class="item-main"><p class="item-title">${esc(l.ders)}</p></div></div>`)
      .join("");
  }

  async function loadToday() {
    $("sky-date").textContent = fmtDate(new Date().toISOString());
    const [status, schedules] = await Promise.all([api("GET", "/api/status"), api("GET", "/api/schedules")]);
    state.settings = status.settings;
    state.schedules = schedules;

    if (status.next_briefing) {
      $("next-time").textContent = fmtTime(status.next_briefing);
      const mins = Math.max(0, Math.round((new Date(status.next_briefing) - new Date()) / 60000));
      $("next-left").textContent = mins >= 60 ? `${Math.floor(mins / 60)} sa ${mins % 60} dk sonra` : `${mins} dk sonra`;
    } else {
      $("next-time").textContent = status.settings.briefing_time;
      $("next-left").textContent = "her gün";
    }

    const key = todayKey();
    const list = WEEKDAYS.includes(key) ? (schedules.okul ? schedules.okul[key] || [] : null) : schedules[key];
    $("today-lessons").innerHTML = lessonItems(list, "Bugün için kayıtlı program yok. Program sekmesinden ekleyebilirsin.");

    $("errors").innerHTML = status.errors.length
      ? status.errors
          .slice(0, 5)
          .map((e) => `<div class="item"><div class="item-main"><p class="item-title">${esc(e.message)}</p><p class="item-sub">${fmtShort(e.time)}${e.error ? " — " + esc(e.error) : ""}</p></div></div>`)
          .join("")
      : '<p class="empty">Sorun yok, her şey çalışıyor.</p>';

    const h = Math.floor(status.uptime_s / 3600);
    $("uptime").textContent = `Bot ${h ? h + " saattir" : Math.max(1, Math.round(status.uptime_s / 60)) + " dakikadır"} çalışıyor, ${status.reminder_count} bekleyen hatırlatıcı`;

    api("GET", "/api/weather")
      .then((w) => {
        $("sky").dataset.cond = w.condition;
        $("sky-temp").textContent = Math.round(w.t_max) + "°";
        $("sky-cond").textContent = w.label || "Bugün";
        $("sky-range").textContent = `En düşük ${Math.round(w.t_min)}°, yağış %${w.rain_prob}`;
        if (w.hourly.length === 24) skyLine(w.hourly);
      })
      .catch(() => {
        $("sky-cond").textContent = "Hava alınamadı";
      });
  }

  async function preview() {
    const btn = $("btn-preview");
    btn.disabled = true;
    btn.textContent = "Hazırlanıyor";
    try {
      const data = await api("GET", "/api/briefing/preview");
      const img = $("preview-card");
      img.hidden = !data.card;
      if (data.card) img.src = "data:image/png;base64," + data.card;
      $("preview-text").textContent = (data.caption ? data.caption + "\n\n" : "") + data.text;
      $("preview").hidden = false;
    } catch (err) {
      fail(err);
    } finally {
      btn.disabled = false;
      btn.textContent = "Önizle";
    }
  }

  async function sendNow() {
    const btn = $("btn-send");
    btn.disabled = true;
    try {
      await api("POST", "/api/briefing/send");
      haptic("success");
      toast("Özet Telegram'a gönderildi");
    } catch (err) {
      fail(err);
    } finally {
      btn.disabled = false;
    }
  }

  function renderSettings() {
    const s = state.settingsDraft;
    $("set-time").value = s.briefing_time;
    $("set-photo").checked = s.photo_card;
    document.querySelectorAll("[data-section]").forEach((el) => (el.checked = s.sections[el.dataset.section]));
    $("news-count").textContent = s.news_count;
    const dirty = JSON.stringify(s) !== JSON.stringify(state.settings);
    setMainButton("Kaydet", dirty ? saveSettings : null);
  }

  async function loadSettings() {
    state.settings = await api("GET", "/api/settings");
    state.settingsDraft = structuredClone(state.settings);
    renderSettings();
  }

  async function saveSettings() {
    state.settings = await api("PUT", "/api/settings", state.settingsDraft);
    state.settingsDraft = structuredClone(state.settings);
    renderSettings();
    toast(`Kaydedildi. Özet her gün ${state.settings.briefing_time}'da gelecek`);
  }

  function currentLessons() {
    const s = state.schedules || {};
    if (state.kind === "okul") return s.okul ? s.okul[state.day] || [] : [];
    return s[state.kind] || [];
  }

  function renderProgram() {
    document.querySelectorAll("#prog-kind button").forEach((b) => b.setAttribute("aria-selected", b.dataset.kind === state.kind));
    $("prog-days").hidden = state.kind !== "okul";
    document.querySelectorAll("#prog-days button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.day === state.day));
    const rows = state.lessonsDraft;
    $("lessons").innerHTML = rows.length
      ? rows
          .map(
            (l, i) => `<div class="lesson" data-i="${i}">
              <input class="time" value="${esc(l.saat)}" placeholder="08:30" inputmode="numeric" aria-label="Saat" data-field="saat">
              <input value="${esc(l.ders)}" placeholder="Ders adı" aria-label="Ders" data-field="ders">
              <button class="icon-btn" data-remove="${i}" aria-label="Dersi kaldır">${TRASH}</button>
            </div>`
          )
          .join("")
      : '<p class="empty">Bu gün için ders yok. Aşağıdan ekleyebilirsin.</p>';
    const dirty = JSON.stringify(rows) !== JSON.stringify(currentLessons());
    setMainButton("Programı kaydet", dirty ? saveProgram : null);
  }

  function resetDraft() {
    state.lessonsDraft = structuredClone(currentLessons());
    renderProgram();
  }

  async function loadProgram() {
    state.schedules = await api("GET", "/api/schedules");
    const key = todayKey();
    if (WEEKDAYS.includes(key) && state.kind === "okul") state.day = key;
    resetDraft();
  }

  async function saveProgram() {
    const lessons = state.lessonsDraft.filter((l) => l.ders.trim() || l.saat.trim());
    if (state.kind === "okul") {
      const okul = structuredClone(state.schedules.okul || Object.fromEntries(WEEKDAYS.map((d) => [d, []])));
      okul[state.day] = lessons;
      state.schedules.okul = await api("PUT", "/api/schedules/okul", okul);
    } else {
      state.schedules[state.kind] = await api("PUT", `/api/schedules/dershane/${state.kind}`, lessons);
    }
    resetDraft();
    toast("Program kaydedildi");
  }

  async function clearProgram() {
    const name = state.kind === "okul" ? "okul programını" : `${state.kind} dershane programını`;
    if (!(await confirmAsk(`Tüm ${name} silmek istiyor musun?`))) return;
    const path = state.kind === "okul" ? "/api/schedules/okul" : `/api/schedules/dershane/${state.kind}`;
    await api("DELETE", path);
    state.schedules[state.kind === "okul" ? "okul" : state.kind] = null;
    resetDraft();
    toast("Program silindi");
  }

  function reminderItems(list) {
    if (!list.length) return '<p class="empty">Bekleyen hatırlatıcı yok.</p>';
    return list
      .map((r) => `<div class="item"><div class="item-main"><p class="item-title">${esc(r.text)}</p><p class="item-sub">${fmtShort(r.due_at)}</p></div><button class="icon-btn" data-rem="${r.id}" aria-label="Hatırlatıcıyı sil">${TRASH}</button></div>`)
      .join("");
  }

  function noteItems(list, q) {
    if (!list.length) return `<p class="empty">${q ? "Bu aramayla eşleşen not yok." : "Henüz not yok. Bota sesli mesaj atınca burada görünür."}</p>`;
    return list
      .map((n) => `<div class="item"><div class="item-main"><p class="item-title">${esc(n.text)}</p><p class="item-sub">${fmtShort(n.created_at)}</p></div><button class="icon-btn" data-note="${n.id}" aria-label="Notu sil">${TRASH}</button></div>`)
      .join("");
  }

  async function loadReminders() {
    $("reminders").innerHTML = reminderItems(await api("GET", "/api/reminders"));
  }

  async function loadNoteList() {
    const q = $("note-search").value.trim();
    $("notes").innerHTML = noteItems(await api("GET", "/api/notes?q=" + encodeURIComponent(q)), q);
  }

  async function loadNotes() {
    await Promise.all([loadReminders(), loadNoteList()]);
  }

  function bind() {
    document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
    $("btn-preview").addEventListener("click", preview);
    $("btn-send").addEventListener("click", sendNow);

    $("set-time").addEventListener("change", (e) => {
      if (e.target.value) state.settingsDraft.briefing_time = e.target.value;
      renderSettings();
    });
    $("set-photo").addEventListener("change", (e) => {
      state.settingsDraft.photo_card = e.target.checked;
      renderSettings();
    });
    document.querySelectorAll("[data-section]").forEach((el) =>
      el.addEventListener("change", () => {
        state.settingsDraft.sections[el.dataset.section] = el.checked;
        renderSettings();
      })
    );
    $("news-minus").addEventListener("click", () => {
      state.settingsDraft.news_count = Math.max(1, state.settingsDraft.news_count - 1);
      renderSettings();
    });
    $("news-plus").addEventListener("click", () => {
      state.settingsDraft.news_count = Math.min(10, state.settingsDraft.news_count + 1);
      renderSettings();
    });

    $("prog-kind").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state.kind = b.dataset.kind;
      resetDraft();
    });
    $("prog-days").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state.day = b.dataset.day;
      resetDraft();
    });
    $("lessons").addEventListener("input", (e) => {
      const row = e.target.closest(".lesson");
      if (!row) return;
      state.lessonsDraft[+row.dataset.i][e.target.dataset.field] = e.target.value;
      const dirty = JSON.stringify(state.lessonsDraft) !== JSON.stringify(currentLessons());
      setMainButton("Programı kaydet", dirty ? saveProgram : null);
    });
    $("lessons").addEventListener("click", (e) => {
      const b = e.target.closest("[data-remove]");
      if (!b) return;
      state.lessonsDraft.splice(+b.dataset.remove, 1);
      renderProgram();
    });
    $("add-lesson").addEventListener("click", () => {
      state.lessonsDraft.push({ saat: "", ders: "" });
      renderProgram();
      const inputs = $("lessons").querySelectorAll('input[data-field="ders"]');
      inputs[inputs.length - 1].focus();
    });
    $("clear-program").addEventListener("click", () => clearProgram().catch(fail));

    $("rem-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = $("rem-input");
      const text = input.value.trim();
      if (!text) return;
      input.disabled = true;
      try {
        const r = await api("POST", "/api/reminders", { text });
        input.value = "";
        haptic("success");
        toast(`Hatırlatıcı kuruldu: ${fmtShort(r.due_at)}`);
        await loadReminders();
      } catch (err) {
        fail(err);
      } finally {
        input.disabled = false;
      }
    });
    $("reminders").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-rem]");
      if (!b || !(await confirmAsk("Bu hatırlatıcı silinsin mi?"))) return;
      try {
        await api("DELETE", "/api/reminders/" + b.dataset.rem);
        toast("Hatırlatıcı silindi");
        await loadReminders();
      } catch (err) {
        fail(err);
      }
    });
    $("notes").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-note]");
      if (!b || !(await confirmAsk("Bu not silinsin mi?"))) return;
      try {
        await api("DELETE", "/api/notes/" + b.dataset.note);
        toast("Not silindi");
        await loadNoteList();
      } catch (err) {
        fail(err);
      }
    });
    let searchTimer;
    $("note-search").addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadNoteList().catch(fail), 250);
    });

    if (tg) tg.MainButton.onClick(runSave);
  }

  function start() {
    if (tg) {
      tg.ready();
      tg.expand();
    }
    if (!initData) {
      document.querySelectorAll(".view").forEach((v) => (v.hidden = true));
      $("tabs").hidden = true;
      $("gate").hidden = false;
      return;
    }
    bind();
    const initial = new URLSearchParams(location.search).get("view");
    showView(["today", "program", "notes", "settings"].includes(initial) ? initial : "today");
  }

  start();
})();
