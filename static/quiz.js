/* Student quiz. Questions, labels and courses come from /static/quiz-data.json,
   the same file the server uses to score and to show the admin pages. */
(async function () {
  var app = document.getElementById("app");
  var D;
  try {
    var res = await fetch("/static/quiz-data.json?v=8");
    D = await res.json();
  } catch (e) {
    app.textContent = "வினாடி வினா ஏற்றப்படவில்லை. பக்கத்தைப் புதுப்பிக்கவும் (Refresh).";
    return;
  }
  var COLORS = D.colors, CL = D.cl, ORDER = D.order, CLUSTER_INFO = D.cluster_info;
  var QCOLOR = "--purple";            // every question screen uses this one colour
  var SCHOOL_Q = D.q;                 // 12th-class quiz
  var Q = SCHOOL_Q;                   // the question set this student is answering
  var curSet = "school";
  var DOING = D.doing;

  /* ---- Tamil / English. Tamil is the base text; the English text lives in quiz-data.json "en". ---- */
  var EN = D.en || {};
  var L = "ta";
  try { if (localStorage.getItem("quiz-lang") === "en") L = "en"; } catch (e) {}
  function tr(s) { return L === "en" && EN.ui && EN.ui[s] ? EN.ui[s] : s; }
  function pickL(ta, en) { return L === "en" && en != null ? en : ta; }
  function syncLang() {
    document.documentElement.lang = L === "en" ? "en" : "ta";
  }
  syncLang();
  /* question text in the chosen language (scoring always uses the Tamil/base Q, answers are indexes) */
  function qdef(i) {
    var e = L === "en" ? (curSet === "school" ? EN.school : (EN.sets || {})[curSet]) : null;
    return e && e[i] ? e[i] : Q[i];
  }
  function introFor(key) {
    return pickL(D.set_intro[key] || D.set_intro.school, EN.set_intro && (EN.set_intro[key] || EN.set_intro.school));
  }
  var current = function () {};       // re-draws the screen the student is on
  var captureDraft = null;            // copies half-typed start-form values before a re-draw

  var answers = Q.map(function () { return null; });
  var meta = { name: "", phone: "", doing: "" };
  var timer = null;
  var LET = ["A", "B", "C", "D", "E", "F", "G"];   // longest question has 7 options

  /* Which quiz a student gets depends only on the "doing now" choice (quiz-data.json "set_of"):
     one choice = one quiz, so questions of different quizzes never mix. */
  function setFor(doing) { return D.set_of[doing]; }
  function useSet(key) {
    var q = key === "school" ? SCHOOL_Q : D.sets[key].q;
    if (key !== curSet || Q !== q) { curSet = key; Q = q; answers = Q.map(function () { return null; }); }
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function setAccent(node, token) { node.style.setProperty("--q", "var(" + token + ")"); }
  function mount(view, focusEl) {
    app.innerHTML = "";
    app.appendChild(view);
    window.scrollTo(0, 0);
    if (focusEl) { focusEl.setAttribute("tabindex", "-1"); focusEl.focus({ preventScroll: true }); }
  }

  /* Same scoring as the server (app.py compute). Only the after-12th quiz is scored.
     An option whose "m" entry is null (e.g. "still exploring") adds nothing. */
  function compute(ans) {
    var score = { tech: 0, creative: 0, business: 0, people: 0 };
    var max = 0;
    Q.forEach(function (q, i) {
      if (!q.m) return;
      max += q.w;
      var a = ans[i];
      if (a == null || !q.m[a]) return;
      score[q.m[a]] += q.w;
    });
    var ranked = ORDER.slice().sort(function (a, b) { return score[b] - score[a]; });
    return { score: score, max: max, ranked: ranked };
  }

  function showStart() {
    current = showStart;
    var v = el("section", "view start");
    var left = el("div");
    var brand = el("div", "inst");
    var logo = el("img", "inst-logo");
    logo.src = "/static/img/logo.jpg"; logo.alt = "TATTI logo"; logo.width = 56; logo.height = 56;
    brand.appendChild(logo);
    brand.appendChild(el("p", "eyebrow", "Tamil Nadu Advanced Technical Training Institute · Chennai"));
    left.appendChild(brand);
    var h = el("h1", null, tr("12-ஆம் வகுப்புக்குப் பிறகு உங்கள் பாதை என்ன?"));
    left.appendChild(h);
    var sub = el("p", "sub", introFor("school"));
    left.appendChild(sub);

    var form = el("form", "form");
    form.noValidate = true;
    function field(id, label, node) {
      var f = el("div", "field");
      var l = el("label", null, label);
      l.setAttribute("for", id);
      node.id = id;
      f.appendChild(l);
      f.appendChild(node);
      form.appendChild(f);
      return node;
    }
    var nm = el("input"); nm.type = "text"; nm.maxLength = 60; nm.autocomplete = "name"; nm.value = meta.name;
    field("f-name", tr("உங்கள் பெயர் (Your Name)"), nm);
    var ph = el("input"); ph.type = "tel"; ph.maxLength = 15; ph.autocomplete = "tel"; ph.inputMode = "numeric"; ph.value = meta.phone;
    field("f-phone", tr("தொலைபேசி எண் (Phone Number), விருப்பம். நிர்வாகம் தொடர்புகொள்வதற்கு மட்டும் பயன்படும்."), ph);
    var gr = el("select");
    var o0 = el("option", null, tr("தேர்ந்தெடுக்கவும் (Select)")); o0.value = ""; o0.disabled = true; gr.appendChild(o0);
    DOING.forEach(function (d) { var o = el("option", null, L === "en" ? d.en : d.ta + " (" + d.en + ")"); o.value = d.key; gr.appendChild(o); });
    gr.value = meta.doing;
    function syncIntro() { sub.textContent = introFor(setFor(gr.value)); }
    gr.addEventListener("change", syncIntro);
    syncIntro();
    field("f-doing", tr("12-ஆம் வகுப்பு முடித்த பிறகு தற்போது என்ன செய்கிறீர்கள்? (What are you doing now after 12th?)"), gr);
    var err = el("p", "err"); err.id = "f-err"; err.setAttribute("role", "alert");
    form.appendChild(err);
    var b = el("button", "go", tr("தொடங்கலாம் (Start) →"));
    b.type = "submit";
    b.id = "start-btn";
    form.appendChild(b);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var n = nm.value.trim();
      if (!n) { err.textContent = tr("பெயரை உள்ளிடவும் (Please enter your name)."); nm.focus(); return; }
      if (!/^[0-9+\- ]{0,15}$/.test(ph.value.trim())) { err.textContent = tr("தொலைபேசி எண்ணில் இலக்கங்கள் மட்டும் உள்ளிடவும்."); ph.focus(); return; }
      if (!gr.value) { err.textContent = tr("நீங்கள் இப்போது என்ன செய்கிறீர்கள் என்பதைத் தேர்ந்தெடுக்கவும்."); gr.focus(); return; }
      meta = { name: n, phone: ph.value.trim(), doing: gr.value };
      useSet(setFor(meta.doing));
      showQ(0);
    });
    captureDraft = function () { meta.name = nm.value; meta.phone = ph.value; meta.doing = gr.value; };
    left.appendChild(form);
    left.appendChild(el("p", "fine", tr("சுமார் 2 நிமிடங்கள் போதும். சரியான பதில், தவறான பதில் என்று எதுவும் இல்லை.")));
    v.appendChild(left);

    var ring = el("div", "ring");
    ring.setAttribute("aria-hidden", "true");
    ring.innerHTML = '<div><div><svg viewBox="0 0 64 64" width="96" height="96" fill="var(--brand)"><path d="M32 12 4 22l28 10 28-10z"/><path d="M14 30v12c0 4 8 8 18 8s18-4 18-8V30l-18 6.5z"/><rect x="56" y="24" width="3" height="18" rx="1.5"/></svg></div></div>';
    v.appendChild(ring);
    mount(v, h);
  }

  function showQ(i) {
    current = function () { showQ(i); };
    captureDraft = null;
    clearTimeout(timer);
    var q = qdef(i);
    var v = el("section", "view");
    setAccent(v, QCOLOR);

    var top = el("div", "top");
    var back = el("button", "back", tr("← முந்தைய கேள்வி"));
    back.type = "button";
    back.id = "back-btn";
    if (i === 0) back.hidden = true;
    back.addEventListener("click", function () { showQ(i - 1); });
    top.appendChild(back);
    top.appendChild(el("span", "qno", tr("கேள்வி ") + (i + 1) + " / " + Q.length));
    v.appendChild(top);

    var segs = el("div", "segs");
    segs.setAttribute("role", "progressbar");
    segs.setAttribute("aria-valuemin", "1");
    segs.setAttribute("aria-valuemax", String(Q.length));
    segs.setAttribute("aria-valuenow", String(i + 1));
    Q.forEach(function (_, n) {
      var s = el("span", "seg");
      if (n <= i) s.style.background = "var(" + QCOLOR + ")";
      segs.appendChild(s);
    });
    v.appendChild(segs);

    var h = el("h2", "q", q.t);
    v.appendChild(h);

    var list = el("div", "opts");
    q.o.forEach(function (txt, k) {
      var b = el("button", "opt");
      b.type = "button";
      b.id = "q" + i + "-" + LET[k];
      b.setAttribute("aria-pressed", answers[i] === k ? "true" : "false");
      b.appendChild(el("span", "k", LET[k]));
      b.appendChild(el("span", "t", txt));
      b.addEventListener("click", function () {
        answers[i] = k;
        Array.prototype.forEach.call(list.children, function (c, n) {
          c.setAttribute("aria-pressed", n === k ? "true" : "false");
        });
        clearTimeout(timer);
        timer = setTimeout(function () {
          if (i + 1 < Q.length) showQ(i + 1); else showResult();
        }, 380);
      });
      list.appendChild(b);
    });
    v.appendChild(list);
    mount(v, h);
  }

  function showResult(redraw) {
    current = function () { showResult(true); };
    captureDraft = null;
    clearTimeout(timer);
    if (curSet !== "school") { showSetResult(redraw); return; }
    var r = compute(answers);
    var top = r.ranked[0];
    var second = r.ranked[1];
    var info = CLUSTER_INFO[top];
    var v = el("section", "view result");
    setAccent(v, CL[top].color);

    v.appendChild(el("p", "eyebrow", (meta.name ? meta.name + " · " : "") + tr("உங்கள் முடிவு")));
    var h = el("h1", null, CL[top].name);
    v.appendChild(h);
    v.appendChild(el("p", "lead", pickL(info.lead, EN.lead && EN.lead[top])));

    var bars = el("div", "bars");
    r.ranked.forEach(function (c, n) {
      var pct = Math.round((r.score[c] / r.max) * 100);
      var row = el("div", "bar" + (n === 0 ? " top1" : ""));
      row.style.setProperty("--c", "var(" + CL[c].color + ")");
      row.appendChild(el("span", "name", CL[c].name));
      var trk = el("span", "track");
      var f = el("span", "fill");
      f.style.width = pct + "%";
      trk.appendChild(f);
      row.appendChild(trk);
      row.appendChild(el("span", "pct", pct + "%"));
      bars.appendChild(row);
    });
    v.appendChild(bars);

    var box = el("div", "save-state");
    box.id = "save-state";
    v.appendChild(box);

    v.appendChild(highlightsBlock());

    var courses = el("div", "courses");
    courses.appendChild(el("h2", null, tr("இந்தத் துறையில் பார்க்க வேண்டிய படிப்புகள்")));
    courses.appendChild(el("p", "eyebrow", tr("பட்டப் படிப்பு / பட்டயப் படிப்பு (Degree / Diploma)")));
    var c1 = el("div", "chips");
    info.degree.forEach(function (t) { c1.appendChild(el("span", "chip", t)); });
    courses.appendChild(c1);
    courses.appendChild(el("p", "eyebrow", tr("குறுகியகாலத் திறன் படிப்புகள் (Short-term Skill Courses)")));
    var c2 = el("div", "chips");
    info.short.forEach(function (t) { c2.appendChild(el("span", "chip", t)); });
    courses.appendChild(c2);
    v.appendChild(courses);
    v.appendChild(tattiBlock(tattiGroups("school", answers, r.ranked)));
    v.appendChild(contactBlock());

    var sec = r.score[second] > 0 ? CL[second].name + tr(" துறையிலும் உங்களுக்கு ஆர்வம் உள்ளது. அந்தத் துறைப் படிப்புகளையும் ஒருமுறை பாருங்கள். ") : "";
    v.appendChild(el("p", "note", sec + tr("இது ஒரு வழிகாட்டி மட்டுமே. தகுதி, கட்-ஆஃப், கட்டணம் ஆகியவை ஒவ்வொரு கல்லூரிக்கும் மாறுபடும். சேர்க்கைக்கு முன் கல்லூரியின் இணையதளத்தில் சரிபார்த்துக்கொள்ளுங்கள்.")));

    var act = el("div", "actions");
    var again = el("button", "go", tr("மீண்டும் முயற்சி செய்யுங்கள்"));
    again.type = "button";
    again.id = "retry-btn";
    again.addEventListener("click", function () {
      answers = Q.map(function () { return null; });
      showStart();
    });
    var edit = el("button", "go ghost", tr("பதில்களை மாற்றுங்கள்"));
    edit.type = "button";
    edit.id = "edit-btn";
    edit.addEventListener("click", function () { showQ(0); });
    var pdf = el("button", "go ghost", tr("முடிவை PDF-ஆகச் சேமிக்கவும்"));
    pdf.type = "button";
    pdf.id = "pdf-btn";
    pdf.addEventListener("click", function () { window.print(); });
    act.appendChild(again);
    act.appendChild(edit);
    act.appendChild(pdf);
    v.appendChild(act);

    mount(v, h);
    if (redraw) renderSave();
    else doSave({ name: meta.name, phone: meta.phone, doing: meta.doing, answers: answers.slice() });
  }

  /* TATTI course suggestions. Groups come from answers (rules in quiz-data.json "tatti"). */
  function tattiGroups(set, ans, ranked) {
    var T = D.tatti, out = [];
    function add(list) { (list || []).forEach(function (g) { if (T.groups[g] && out.indexOf(g) < 0) out.push(g); }); }
    if (set === "school" && ranked) {
      add(T.cluster[ranked[0]]);
      add((T.always || {}).school);   // degree programmes always make the list
      add((T.cluster[ranked[1]] || []).slice(0, 1));
    } else {
      (T.rules[set] || []).forEach(function (rule) {
        var a = ans[rule[0]];
        if (a != null) add(rule[1][String(a)]);
      });
    }
    add((T.always || {})[set]);
    return out.slice(0, T.max_groups);
  }
  function tattiBlock(groups) {
    var T = D.tatti;
    var box = el("div", "courses tatti");
    var TE = EN.tatti || {};
    box.appendChild(el("h2", null, pickL(T.title, TE.title)));
    if (!groups.length) box.appendChild(el("p", "note", pickL(T.empty, TE.empty)));
    groups.forEach(function (g) {
      box.appendChild(el("p", "eyebrow", T.groups[g].title));
      var chips = el("div", "chips");
      T.groups[g].courses.forEach(function (c) { chips.appendChild(el("span", "chip", c)); });
      box.appendChild(chips);
    });
    var a = el("a", "btn-sm", pickL(T.link, TE.link));
    a.href = T.url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.id = "tatti-link";
    box.appendChild(a);
    return box;
  }

  /* "What you told us": the answers to the highlighted questions of the quiz this student took. */
  function highlightsBlock() {
    var finds = el("div", "finds");
    D.highlights[curSet].forEach(function (hl, hi) {
      var a = answers[hl[0]];
      if (a == null) return;
      var d = el("div", "find");
      d.appendChild(el("p", "eyebrow", pickL(hl[1], EN.highlights && EN.highlights[curSet] && EN.highlights[curSet][hi])));
      d.appendChild(el("h3", null, qdef(hl[0]).o[a]));
      finds.appendChild(d);
    });
    return finds;
  }

  function contactBlock() {
    var C = D.contact, CE = EN.contact || {}, box = el("div", "contact");
    box.appendChild(el("h2", null, pickL(C.title, CE.title)));
    var row = el("div", "contact-row");
    C.numbers.forEach(function (n, i) {
      var a = el("a", "go call", "📞 " + n.label);
      a.href = "tel:" + n.tel; a.id = "call-" + i;
      row.appendChild(a);
    });
    var w = el("a", "go wa", pickL(C.wa_label, CE.wa_label));
    w.href = "https://wa.me/" + C.wa + "?text=" + encodeURIComponent(pickL(C.wa_msg, CE.wa_msg).replace("{name}", meta.name || ""));
    w.target = "_blank"; w.rel = "noopener noreferrer"; w.id = "wa-link";
    row.appendChild(w);
    box.appendChild(row);
    return box;
  }

  /* College-student and certificate-course quizzes: no interest scoring, so show what the student told us. */
  function showSetResult(redraw) {
    current = function () { showResult(true); };
    captureDraft = null;
    var v = el("section", "view result");
    setAccent(v, QCOLOR);
    v.appendChild(el("p", "eyebrow", (meta.name ? meta.name + " · " : "") + D.sets[curSet].name));
    var h = el("h1", null, tr("நன்றி! உங்கள் தேவைகள் பதிவாகிவிட்டன"));
    v.appendChild(h);
    v.appendChild(el("p", "lead", pickL(D.set_note[curSet], EN.set_note && EN.set_note[curSet])));

    var box = el("div", "save-state");
    box.id = "save-state";
    v.appendChild(box);

    v.appendChild(highlightsBlock());
    v.appendChild(tattiBlock(tattiGroups(curSet, answers, null)));
    v.appendChild(contactBlock());

    var act = el("div", "actions");
    var again = el("button", "go", tr("மீண்டும் முயற்சி செய்யுங்கள்"));
    again.type = "button";
    again.id = "retry-btn";
    again.addEventListener("click", function () {
      answers = Q.map(function () { return null; });
      showStart();
    });
    var edit = el("button", "go ghost", tr("பதில்களை மாற்றுங்கள்"));
    edit.type = "button";
    edit.id = "edit-btn";
    edit.addEventListener("click", function () { showQ(0); });
    var pdf = el("button", "go ghost", tr("முடிவை PDF-ஆகச் சேமிக்கவும்"));
    pdf.type = "button";
    pdf.id = "pdf-btn";
    pdf.addEventListener("click", function () { window.print(); });
    act.appendChild(again);
    act.appendChild(edit);
    act.appendChild(pdf);
    v.appendChild(act);

    mount(v, h);
    if (redraw) renderSave();
    else doSave({ name: meta.name, phone: meta.phone, doing: meta.doing, answers: answers.slice() });
  }

  /* ---- saving ---- */
  var saveStatus = "idle", savePayload = null;
  function renderSave() {
    var box = document.getElementById("save-state");
    if (!box) return;
    var cls = "save-state", txt = "";
    if (saveStatus === "saving") txt = tr("உங்கள் பதில்கள் சேமிக்கப்படுகின்றன…");
    else if (saveStatus === "ok") { cls += " ok"; txt = tr("உங்கள் பதில்கள் நிர்வாகத்திற்குச் சென்றுவிட்டன."); }
    else {
      cls += " bad";
      txt = saveStatus === "429" ? tr("தற்போது பலர் சமர்ப்பிக்கிறார்கள். சிறிது நேரம் கழித்து மீண்டும் சேமிக்கவும். உங்கள் முடிவு இங்கே தெரியும்.")
          : saveStatus === "net" ? tr("இணையத் தொடர்பில் சிக்கல். சேமிக்க இயலவில்லை. ")
          : tr("சேமிக்க இயலவில்லை. ");
    }
    box.className = cls;
    box.textContent = txt;
    if (saveStatus === "429" || saveStatus === "err" || saveStatus === "net") addRetry(box);
  }
  function doSave(payload) {
    savePayload = payload;
    saveStatus = "saving";
    renderSave();
    fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (res) {
      saveStatus = res.ok ? "ok" : (res.status === 429 ? "429" : "err");
      renderSave();
    }).catch(function () {
      saveStatus = "net";
      renderSave();
    });
  }
  function addRetry(box) {
    var rb = el("button", "btn-sm", tr("மீண்டும் சேமிக்கவும்"));
    rb.type = "button";
    rb.id = "resave-btn";
    rb.addEventListener("click", function () { doSave(savePayload); });
    box.appendChild(rb);
  }

  /* ---- language switch (top right) ---- */
  var bar = document.getElementById("langbar");
  function drawLangBar() {
    if (!bar) return;
    bar.innerHTML = "";
    [["ta", "தமிழ்"], ["en", "English"]].forEach(function (x) {
      var b = el("button", "lang", x[1]);
      b.type = "button";
      b.id = "lang-" + x[0];
      b.setAttribute("aria-pressed", L === x[0] ? "true" : "false");
      b.addEventListener("click", function () {
        if (L === x[0]) return;
        if (captureDraft) captureDraft();
        L = x[0];
        try { localStorage.setItem("quiz-lang", L); } catch (e) {}
        syncLang();
        drawLangBar();
        current();
      });
      bar.appendChild(b);
    });
  }
  drawLangBar();

  showStart();
})();