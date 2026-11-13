/* Student quiz. Questions, labels and courses come from /static/quiz-data.json,
   the same file the server uses to score and to show the admin pages. */
(async function () {
  var app = document.getElementById("app");
  var D;
  try {
    var res = await fetch("/static/quiz-data.json?v=3");
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
  var LEARN = D.learn, PLAN = D.plan, READY = D.ready, READY_TITLE = D.ready_title, FACTOR = D.factor, DOING = D.doing;

  var answers = Q.map(function () { return null; });
  var meta = { name: "", phone: "", doing: "" };
  var timer = null;
  var LET = ["A", "B", "C", "D", "E"];

  /* Which question set a student gets depends on what they are doing now (quiz-data.json "set_of"). */
  function setFor(doing) { return (D.set_of && D.set_of[doing]) || "school"; }
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

  /* Same scoring as the server (app.py compute). The server's result is the one stored. */
  function compute(ans) {
    var score = { tech: 0, creative: 0, business: 0, people: 0 };
    var tie = { tech: 0, creative: 0, business: 0, people: 0 };
    var max = 0;
    Q.forEach(function (q, i) {
      if (!q.m) return;
      max += q.w;
      var a = ans[i];
      if (a == null || !q.m[a]) return;
      score[q.m[a]] += q.w;
    });
    if (ans[2] != null && Q[2].m[ans[2]]) tie[Q[2].m[ans[2]]] += 0.2;
    if (ans[1] != null && Q[1].m[ans[1]]) tie[Q[1].m[ans[1]]] += 0.1;
    var ranked = ORDER.slice().sort(function (a, b) { return (score[b] + tie[b]) - (score[a] + tie[a]); });
    return { score: score, max: max, ranked: ranked };
  }

  function showStart() {
    var v = el("section", "view start");
    var left = el("div");
    var brand = el("div", "inst");
    var logo = el("img", "inst-logo");
    logo.src = "/static/img/logo.jpg"; logo.alt = "TATTI logo"; logo.width = 56; logo.height = 56;
    brand.appendChild(logo);
    brand.appendChild(el("p", "eyebrow", "Tamil Nadu Advanced Technical Training Institute · Chennai"));
    left.appendChild(brand);
    var h = el("h1", null, "12-ஆம் வகுப்புக்குப் பிறகு உங்கள் பாதை என்ன?");
    left.appendChild(h);
    var sub = el("p", "sub", D.set_intro.school);
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
    field("f-name", "உங்கள் பெயர் (Your Name)", nm);
    var ph = el("input"); ph.type = "tel"; ph.maxLength = 15; ph.autocomplete = "tel"; ph.inputMode = "numeric"; ph.value = meta.phone;
    field("f-phone", "தொலைபேசி எண் (Phone Number), விருப்பம். நிர்வாகம் தொடர்புகொள்வதற்கு மட்டும் பயன்படும்.", ph);
    var gr = el("select");
    var o0 = el("option", null, "தேர்ந்தெடுக்கவும் (Select)"); o0.value = ""; o0.disabled = true; gr.appendChild(o0);
    DOING.forEach(function (d) { var o = el("option", null, d.ta + " (" + d.en + ")"); o.value = d.key; gr.appendChild(o); });
    gr.value = meta.doing;
    function syncIntro() { sub.textContent = D.set_intro[setFor(gr.value)] || D.set_intro.school; }
    gr.addEventListener("change", syncIntro);
    syncIntro();
    field("f-doing", "12-ஆம் வகுப்பு முடித்த பிறகு தற்போது என்ன செய்கிறீர்கள்? (What are you doing now after 12th?)", gr);
    var err = el("p", "err"); err.id = "f-err"; err.setAttribute("role", "alert");
    form.appendChild(err);
    var b = el("button", "go", "தொடங்கலாம் (Start) →");
    b.type = "submit";
    b.id = "start-btn";
    form.appendChild(b);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var n = nm.value.trim();
      if (!n) { err.textContent = "பெயரை உள்ளிடவும் (Please enter your name)."; nm.focus(); return; }
      if (!/^[0-9+\- ]{0,15}$/.test(ph.value.trim())) { err.textContent = "தொலைபேசி எண்ணில் இலக்கங்கள் மட்டும் உள்ளிடவும்."; ph.focus(); return; }
      if (!gr.value) { err.textContent = "நீங்கள் இப்போது என்ன செய்கிறீர்கள் என்பதைத் தேர்ந்தெடுக்கவும்."; gr.focus(); return; }
      meta = { name: n, phone: ph.value.trim(), doing: gr.value };
      useSet(setFor(meta.doing));
      showQ(0);
    });
    left.appendChild(form);
    left.appendChild(el("p", "fine", "சுமார் 2 நிமிடங்கள் போதும். சரியான பதில், தவறான பதில் என்று எதுவும் இல்லை."));
    v.appendChild(left);

    var ring = el("div", "ring");
    ring.setAttribute("aria-hidden", "true");
    ring.innerHTML = '<div><div><svg viewBox="0 0 64 64" width="96" height="96" fill="var(--brand)"><path d="M32 12 4 22l28 10 28-10z"/><path d="M14 30v12c0 4 8 8 18 8s18-4 18-8V30l-18 6.5z"/><rect x="56" y="24" width="3" height="18" rx="1.5"/></svg></div></div>';
    v.appendChild(ring);
    mount(v, h);
  }

  function showQ(i) {
    clearTimeout(timer);
    var q = Q[i];
    var v = el("section", "view");
    setAccent(v, QCOLOR);

    var top = el("div", "top");
    var back = el("button", "back", "← முந்தைய கேள்வி");
    back.type = "button";
    back.id = "back-btn";
    if (i === 0) back.hidden = true;
    back.addEventListener("click", function () { showQ(i - 1); });
    top.appendChild(back);
    top.appendChild(el("span", "qno", "கேள்வி " + (i + 1) + " / " + Q.length));
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

  function showResult() {
    clearTimeout(timer);
    if (curSet !== "school") { showSetResult(); return; }
    var r = compute(answers);
    var top = r.ranked[0];
    var second = r.ranked[1];
    var info = CLUSTER_INFO[top];
    var v = el("section", "view result");
    setAccent(v, CL[top].color);

    v.appendChild(el("p", "eyebrow", (meta.name ? meta.name + " · " : "") + "உங்கள் முடிவு"));
    var h = el("h1", null, CL[top].name);
    v.appendChild(h);
    v.appendChild(el("p", "lead", info.lead));

    var bars = el("div", "bars");
    r.ranked.forEach(function (c, n) {
      var pct = Math.round((r.score[c] / r.max) * 100);
      var row = el("div", "bar" + (n === 0 ? " top1" : ""));
      row.style.setProperty("--c", "var(" + CL[c].color + ")");
      row.appendChild(el("span", "name", CL[c].name));
      var tr = el("span", "track");
      var f = el("span", "fill");
      f.style.width = pct + "%";
      tr.appendChild(f);
      row.appendChild(tr);
      row.appendChild(el("span", "pct", pct + "%"));
      bars.appendChild(row);
    });
    v.appendChild(bars);

    var box = el("div", "save-state");
    box.id = "save-state";
    v.appendChild(box);

    var finds = el("div", "finds");
    function find(label, title, text) {
      var d = el("div", "find");
      d.appendChild(el("p", "eyebrow", label));
      d.appendChild(el("h3", null, title));
      d.appendChild(el("p", null, text));
      finds.appendChild(d);
    }
    var ls = LEARN[answers[6] != null ? answers[6] : 0];
    var pl = PLAN[answers[9] != null ? answers[9] : 3];
    find("கற்றல் முறை (Learning Style)", ls[0], ls[1]);
    find("படிப்புத் திட்டம் (Study Plan)", pl[0], pl[1]);
    if (answers[8] != null) find("படிப்பைத் தேர்ந்தெடுக்கும்போது முக்கியமானது", FACTOR[answers[8]], "கல்லூரிகளை ஒப்பிடும்போது இதையே முதல் அளவுகோலாக வைத்துக்கொள்ளுங்கள்.");
    if (answers[0] != null) find("தற்போதைய நிலை", READY_TITLE[answers[0]], READY[answers[0]]);
    v.appendChild(finds);

    var courses = el("div", "courses");
    courses.appendChild(el("h2", null, "இந்தத் துறையில் பார்க்க வேண்டிய படிப்புகள்"));
    courses.appendChild(el("p", "eyebrow", "பட்டப் படிப்பு / பட்டயப் படிப்பு (Degree / Diploma)"));
    var c1 = el("div", "chips");
    info.degree.forEach(function (t) { c1.appendChild(el("span", "chip", t)); });
    courses.appendChild(c1);
    courses.appendChild(el("p", "eyebrow", "குறுகியகாலத் திறன் படிப்புகள் (Short-term Skill Courses)"));
    var c2 = el("div", "chips");
    info.short.forEach(function (t) { c2.appendChild(el("span", "chip", t)); });
    courses.appendChild(c2);
    v.appendChild(courses);

    var sec = r.score[second] > 0 ? CL[second].name + " துறையிலும் உங்களுக்கு ஆர்வம் உள்ளது. அந்தத் துறைப் படிப்புகளையும் ஒருமுறை பாருங்கள். " : "";
    v.appendChild(el("p", "note", sec + "இது ஒரு வழிகாட்டி மட்டுமே. தகுதி, கட்-ஆஃப், கட்டணம் ஆகியவை ஒவ்வொரு கல்லூரிக்கும் மாறுபடும். சேர்க்கைக்கு முன் கல்லூரியின் இணையதளத்தில் சரிபார்த்துக்கொள்ளுங்கள்."));

    var act = el("div", "actions");
    var again = el("button", "go", "மீண்டும் முயற்சி செய்யுங்கள்");
    again.type = "button";
    again.id = "retry-btn";
    again.addEventListener("click", function () {
      answers = Q.map(function () { return null; });
      showStart();
    });
    var edit = el("button", "go ghost", "பதில்களை மாற்றுங்கள்");
    edit.type = "button";
    edit.id = "edit-btn";
    edit.addEventListener("click", function () { showQ(0); });
    act.appendChild(again);
    act.appendChild(edit);
    v.appendChild(act);

    mount(v, h);
    doSave(box, { name: meta.name, phone: meta.phone, doing: meta.doing, answers: answers.slice() });
  }

  /* College-student and certificate-course quizzes: no interest scoring, so show what the student told us. */
  function showSetResult() {
    var v = el("section", "view result");
    setAccent(v, QCOLOR);
    v.appendChild(el("p", "eyebrow", (meta.name ? meta.name + " · " : "") + D.sets[curSet].name));
    var h = el("h1", null, "நன்றி! உங்கள் தேவைகள் பதிவாகிவிட்டன");
    v.appendChild(h);
    v.appendChild(el("p", "lead", D.set_note[curSet]));

    var box = el("div", "save-state");
    box.id = "save-state";
    v.appendChild(box);

    var finds = el("div", "finds");
    D.highlights[curSet].forEach(function (hl) {
      var a = answers[hl[0]];
      if (a == null) return;
      var d = el("div", "find");
      d.appendChild(el("p", "eyebrow", hl[1]));
      d.appendChild(el("h3", null, Q[hl[0]].o[a]));
      finds.appendChild(d);
    });
    v.appendChild(finds);

    var act = el("div", "actions");
    var again = el("button", "go", "மீண்டும் முயற்சி செய்யுங்கள்");
    again.type = "button";
    again.id = "retry-btn";
    again.addEventListener("click", function () {
      answers = Q.map(function () { return null; });
      showStart();
    });
    var edit = el("button", "go ghost", "பதில்களை மாற்றுங்கள்");
    edit.type = "button";
    edit.id = "edit-btn";
    edit.addEventListener("click", function () { showQ(0); });
    act.appendChild(again);
    act.appendChild(edit);
    v.appendChild(act);

    mount(v, h);
    doSave(box, { name: meta.name, phone: meta.phone, doing: meta.doing, answers: answers.slice() });
  }

  function doSave(box, payload) {
    box.className = "save-state";
    box.textContent = "உங்கள் பதில்கள் சேமிக்கப்படுகின்றன…";
    fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (res) {
      if (!box.isConnected) return;
      box.textContent = "";
      if (res.ok) {
        box.className = "save-state ok";
        box.textContent = "உங்கள் பதில்கள் நிர்வாகத்திற்குச் சென்றுவிட்டன.";
        return;
      }
      box.className = "save-state bad";
      if (res.status === 429) {
        box.textContent = "தற்போது பலர் சமர்ப்பிக்கிறார்கள். சிறிது நேரம் கழித்து மீண்டும் சேமிக்கவும். உங்கள் முடிவு இங்கே தெரியும்.";
      } else {
        box.textContent = "சேமிக்க இயலவில்லை. ";
      }
      addRetry(box, payload);
    }).catch(function () {
      if (!box.isConnected) return;
      box.className = "save-state bad";
      box.textContent = "இணையத் தொடர்பில் சிக்கல். சேமிக்க இயலவில்லை. ";
      addRetry(box, payload);
    });
  }

  function addRetry(box, payload) {
    var rb = el("button", "btn-sm", "மீண்டும் சேமிக்கவும்");
    rb.type = "button";
    rb.id = "resave-btn";
    rb.addEventListener("click", function () { doSave(box, payload); });
    box.appendChild(rb);
  }

  showStart();
})();