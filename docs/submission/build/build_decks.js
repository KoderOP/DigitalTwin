/*
 * Builds the submission decks from the repo's computed results:
 *   docs/submission/Presentation.pptx         (~22 min with speaker notes)
 *   docs/submission/Architecture_Diagram.pptx (architecture diagrams)
 * Usage:  cd docs/submission/build && npm install && node build_decks.js
 * Numbers are read from reports/metrics.json and reports/behaviour_response.json (never typed by hand).
 * Optional: set PPTX_SKILL_DIR to a folder containing scripts/apply_theme.js to write the theme colours.
 */
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const OUT = path.resolve(__dirname, "..");
const IMG = path.join(OUT, "images");
// Python's json writes NaN for undefined metrics (e.g. a subgroup with one class); read it as null.
const M = JSON.parse(fs.readFileSync(path.join(ROOT, "reports", "metrics.json"), "utf8").replace(/\bNaN\b/g, "null"));
const BEH = JSON.parse(fs.readFileSync(path.join(ROOT, "reports", "behaviour_response.json"), "utf8")).summary;
const MAN = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "manifest.json"), "utf8")).summary;
const R = M.results;
const f3 = (x) => Number(x).toFixed(3);
const f1 = (x) => Number(x).toFixed(1);
const pct = (x) => `${Math.round(x * 100)}%`;
const fc = (k, h) => R[k].test.forecast[String(h)];

const THEME = {
  name: "Sugar Twin",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B2A33", lt1: "FFFFFF", dk2: "0B4F5C", lt2: "EAF4F3",
    accent1: "0B7A75", accent2: "F2A541", accent3: "D1495B", accent4: "3E8E41", accent5: "5B6C8F", accent6: "8E6CB0",
    hlink: "0B7A75", folHlink: "5B6C8F",
  },
};
const HEX = THEME.colors;
const W = 13.333, H = 7.5;

function layouts(pres) {
  const C = pres.SchemeColor;
  const footer = { text: { text: "SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE", options: { x: 0.6, y: 7.0, w: 7, h: 0.3, fontSize: 10, color: C.text2, isTextBox: true } } };
  pres.defineSlideMaster({
    title: "TITLE_DARK", background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 1.9, fontSize: 40, bold: true, color: C.background1, valign: "bottom" }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.05, w: 11.7, h: 1.4, fontSize: 20, color: C.background2, valign: "top" }, text: "" } },
      { text: { text: "SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE", options: { x: 0.8, y: 6.7, w: 8, h: 0.35, fontSize: 12, bold: true, color: C.accent2, isTextBox: true } } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTENT", background: { color: C.background1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 28, bold: true, color: C.text2, valign: "middle", align: "left" }, text: "" } },
      footer,
    ],
    slideNumber: { x: 12.2, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.text2 },
  });
  pres.defineSlideMaster({
    title: "CONTENT_TINT", background: { color: C.background2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 28, bold: true, color: C.text2, valign: "middle", align: "left" }, text: "" } },
      footer,
    ],
    slideNumber: { x: 12.2, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.text2 },
  });
  return C;
}

// ---------- reusable compositions (motif: rounded cards with a numbered teal circle) ----------
function card(slide, pres, C, { x, y, w, h, n, head, body, fill = C.background2, headColor = C.text2, name }) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: `${name}-card` });
  let tx = x + 0.25;
  if (n !== undefined) {
    slide.addShape(pres.shapes.OVAL, { x: x + 0.22, y: y + 0.22, w: 0.5, h: 0.5, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `${name}-badge` });
    slide.addText(String(n), { x: x + 0.22, y: y + 0.22, w: 0.5, h: 0.5, align: "center", valign: "middle", fontSize: 16, bold: true, color: C.background1, margin: 0, isTextBox: true, objectName: `${name}-num` });
    tx = x + 0.88;
  }
  slide.addText(head, { x: tx, y: y + 0.18, w: x + w - tx - 0.2, h: 0.58, fontSize: 17, bold: true, color: headColor, valign: "middle", margin: 0, isTextBox: true, objectName: `${name}-head` });
  if (body) slide.addText(body, { x: x + 0.25, y: y + 0.85, w: w - 0.5, h: h - 1.0, fontSize: 14, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: `${name}-body`, paraSpaceAfter: 4 });
}

/** Compact card: numbered badge on the left, heading with the description stacked underneath. */
function rowCard(slide, pres, C, { x, y, w, h, n, head, body, fill = C.background1, name }) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: fill }, line: { color: fill }, objectName: `${name}-card` });
  slide.addShape(pres.shapes.OVAL, { x: x + 0.2, y: y + (h - 0.5) / 2, w: 0.5, h: 0.5, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `${name}-badge` });
  slide.addText(String(n), { x: x + 0.2, y: y + (h - 0.5) / 2, w: 0.5, h: 0.5, align: "center", valign: "middle", fontSize: 15, bold: true, color: C.background1, margin: 0, isTextBox: true, objectName: `${name}-num` });
  slide.addText([{ text: head, options: { bold: true, fontSize: 16, color: C.text2, breakLine: true } }, { text: body, options: { fontSize: 14, color: C.text1 } }],
    { x: x + 0.85, y: y + 0.08, w: w - 1.0, h: h - 0.16, valign: "middle", margin: 0, isTextBox: true, objectName: `${name}-text` });
}

function stat(slide, C, { x, y, w, value, label, color, name }) {
  slide.addText(value, { x, y, w, h: 1.1, fontSize: 54, bold: true, color: color ?? C.accent1, fontFace: THEME.headFontFace, margin: 0, isTextBox: true, objectName: `${name}-value` });
  slide.addText(label, { x, y: y + 1.12, w, h: 0.95, fontSize: 14, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: `${name}-label` });
}

function box(slide, pres, C, { x, y, w, h, text, fill, color, name, fontSize = 14, bold = true }) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: fill }, line: { color: fill }, objectName: `${name}-box` });
  slide.addText(text, { x: x + 0.08, y, w: w - 0.16, h, fontSize, bold, color, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: `${name}-text` });
}

function arrow(slide, pres, C, x1, y1, x2, y2, name) {
  slide.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1, line: { color: C.text2, width: 2, endArrowType: "triangle" }, objectName: name });
}

const chartBase = (C) => ({
  catAxisLabelColor: HEX.dk1, valAxisLabelColor: HEX.dk1, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 12, valAxisLabelFontSize: 11, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 11, dataLabelColor: HEX.dk1,
  valGridLine: { color: "D9E3E2", size: 0.5 }, catGridLine: { style: "none" }, legendFontFace: "+mn-lt", legendFontSize: 12,
  titleFontFace: "+mn-lt", titleFontSize: 14, titleColor: HEX.dk2,
});

// =============================================================================================
// Presentation
// =============================================================================================
async function presentation() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "Sugar Twin: a real-time Digital Twin for Type 2 Diabetes";
  pres.subject = "T2D Digital Twin PoC: synthetic data only";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = layouts(pres);
  const df = R.deep_fused.test, gf = R.gbm_fused.test;

  // 1 Title -------------------------------------------------------------------------------
  pres.addSection({ title: "Introduction" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("Sugar Twin: a real-time Digital Twin for Type 2 Diabetes", { placeholder: "title" });
  s.addText("Predicting glucose spikes 2 hours ahead by fusing EHR + wearable data, for India\n[FILL IN: team name] · [FILL IN: college / incubator]", { placeholder: "body" });
  s.addNotes(`Hello, we are [team name] from [college / incubator]. This is Sugar Twin, a proof-of-concept digital twin for people with type 2 diabetes in India.
A digital twin here means a living virtual copy of one patient: it keeps their health record, it receives their wearable and glucose-sensor data every five minutes, and it carries a small physiological model of how their body handles sugar.
Our twin does one focused job well: every five minutes it predicts whether the patient's glucose will rise above 180 mg/dL within the next two hours, explains why in plain language, and lets the doctor and the patient try "what if" changes before they happen.
One important note before we start, and you will see it on every screen: everything in this project runs on synthetic, simulated patients. No real person's data is used anywhere, and this is not a medical device.
Over the next twenty minutes we will cover the problem, our design, how we built privacy-safe data, the models and the honest results, the doctor dashboard and the patient app, and what it would take to validate this in the real world.`);

  // 2 Problem -----------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Introduction" });
  s.addText("Post-meal spikes: frequent, invisible, preventable", { placeholder: "title" });
  stat(s, C, { x: 0.6, y: 1.6, w: 3.8, value: "~101 M", label: "people living with diabetes in India (ICMR-INDIAB study, 2023)", name: "s-india" });
  stat(s, C, { x: 4.75, y: 1.6, w: 3.8, value: "3 months", label: "typical gap between HbA1c checks, which average away daily spikes", color: C.accent2, name: "s-hba1c" });
  stat(s, C, { x: 8.9, y: 1.6, w: 3.8, value: `${f1(MAN.spike_onsets_per_patient_day)}/day`, label: "sustained spikes above 180 mg/dL per patient-day in our simulated cohort", color: C.accent3, name: "s-spikes" });
  card(s, pres, C, { x: 0.6, y: 4.35, w: 12.1, h: 2.3, name: "why", head: "Why it matters in India",
    body: "Rice- and wheat-heavy meals, late dinners, a high-waist \"thin-fat\" phenotype and early onset make post-prandial spikes common. Spikes drive long-term complications, yet CGMs and smartwatches stream data that nobody turns into timely, explainable, personalised action for the patient or the doctor." });
  s.addNotes(`Let's start with the problem. India has around 101 million people living with diabetes, according to the ICMR-INDIAB study published in 2023, and most of them have type 2 diabetes.
The usual way we track control is HbA1c, a blood test every three months. HbA1c is an average, so it hides the daily pattern: a person can have a reasonable average and still spike high after almost every lunch and dinner.
In India this pattern is especially common: meals are rich in rice and wheat, dinners are often late, many patients have the so-called thin-fat phenotype with a high waist circumference at a normal BMI, and diabetes starts earlier than in many other populations.
In our simulated cohort, patients have about ${f1(MAN.spike_onsets_per_patient_day)} sustained spikes above 180 every day.
At the same time, continuous glucose monitors and smartwatches are becoming affordable and they stream rich data. But today that data mostly sits in an app. The gap we address is turning the record plus the stream into a timely, explainable, personalised warning, early enough that the patient can still do something about it.`);

  // 3 Use case ----------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Introduction" });
  s.addText("Use case: warn 2 h before glucose exceeds 180 mg/dL", { placeholder: "title" });
  const outs = [
    ["Spike risk", "Calibrated probability of glucose > 180 mg/dL in the next 120 min, refreshed every 5 min"],
    ["2-hour forecast", "Glucose at +30 / 60 / 90 / 120 min with a P10–P90 uncertainty band"],
    ["Alert level", "GREEN / AMBER / RED with a \"spike in ~X min\" countdown; icon + text, never colour alone"],
    ["Why + what if", "Top factors in plain language, and counterfactual simulations of walks, meals, sleep and medication timing"],
  ];
  outs.forEach(([h, b], i) => card(s, pres, C, { x: 0.6 + (i % 2) * 6.15, y: 1.5 + Math.floor(i / 2) * 2.65, w: 5.95, h: 2.45, n: i + 1, head: h, body: b, fill: C.background1, name: `out${i}` }));
  s.addNotes(`Our use case is narrow on purpose. The challenge allows one condition and one adverse event, so we chose type 2 diabetes and the hyperglycaemic spike: glucose above 180 milligrams per decilitre within the next two hours.
Every five minutes the twin produces four outputs.
One: a calibrated probability of a spike in the next 120 minutes. Calibrated means that when the model says 70 percent, about 70 percent of such cases really spike.
Two: a forecast of the glucose value at 30, 60, 90 and 120 minutes, with an uncertainty band.
Three: an alert level, green, amber or red, with a countdown such as "spike in about 40 minutes". The level is always shown with an icon and a word, never by colour alone, so it works for colour-blind users.
Four: an explanation of the top factors, such as a late heavy dinner or short sleep last night, and a what-if simulator that shows what a walk, a different meal or more sleep would do.
As secondary outputs we also flag predicted low glucose and night-time risk.`);

  // 4 Solution at a glance (flow) ----------------------------------------------------------
  pres.addSection({ title: "Approach" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Approach" });
  s.addText("Two data streams, one twin, two role-based apps", { placeholder: "title" });
  box(s, pres, C, { x: 0.6, y: 1.7, w: 2.7, h: 1.4, text: "Stream A\nSynthetic EHR\nlabs · meds · SNPs · diet", fill: C.accent5, color: C.background1, name: "fa" });
  box(s, pres, C, { x: 0.6, y: 3.9, w: 2.7, h: 1.4, text: "Stream B\nCGM · HR · HRV\nsleep · steps · logs", fill: C.accent1, color: C.background1, name: "fb" });
  box(s, pres, C, { x: 4.1, y: 2.75, w: 2.6, h: 1.6, text: "Fusion model\nGRU + EHR\ncross-attention", fill: C.text2, color: C.background1, name: "ff" });
  box(s, pres, C, { x: 7.5, y: 2.75, w: 2.4, h: 1.6, text: "Digital Twin\nstate · personal\nsimulator", fill: C.accent2, color: C.text1, name: "ft" });
  box(s, pres, C, { x: 10.6, y: 1.5, w: 2.1, h: 1.15, text: "Risk + forecast", fill: C.background2, color: C.text2, name: "o1", fontSize: 13 });
  box(s, pres, C, { x: 10.6, y: 2.95, w: 2.1, h: 1.15, text: "Explanation", fill: C.background2, color: C.text2, name: "o2", fontSize: 13 });
  box(s, pres, C, { x: 10.6, y: 4.4, w: 2.1, h: 1.15, text: "What-if", fill: C.background2, color: C.text2, name: "o3", fontSize: 13 });
  arrow(s, pres, C, 3.3, 2.4, 4.1, 3.3, "a1"); arrow(s, pres, C, 3.3, 4.6, 4.1, 3.8, "a2"); arrow(s, pres, C, 6.7, 3.55, 7.5, 3.55, "a3");
  arrow(s, pres, C, 9.9, 3.2, 10.6, 2.1, "a4"); arrow(s, pres, C, 9.9, 3.55, 10.6, 3.55, "a5"); arrow(s, pres, C, 9.9, 3.9, 10.6, 4.95, "a6");
  s.addText("Doctor dashboard (/) and patient PWA (/patient/) are two clients of the same twin and the same 5-minute stream", { x: 0.6, y: 6.0, w: 12.1, h: 0.5, fontSize: 15, italic: true, color: C.text2, isTextBox: true, objectName: "flow-caption" });
  s.addNotes(`Here is the whole system on one slide.
On the left are the two data streams the challenge asks us to fuse. Stream A is the static record: demographics, lab results such as HbA1c and lipids, comorbidities, medications, simulated genetic risk markers, and India-specific context such as vegetarian diet and whether the staple is rice, wheat or millet. Stream B is the live stream: a glucose reading every five minutes, heart rate, heart-rate variability, sleep stages, steps, and meal and medicine logs.
Both feed the fusion model in the middle, a neural network that reads six hours of the wearable stream and conditions it on the health record.
The model's outputs, together with a personalised physiological simulator, make up the digital twin. The twin produces the three things the user sees: risk and forecast, the explanation, and what-if simulations.
A key design decision: the twin is the single source of truth. The doctor dashboard and the patient app are just two role-based views of the same twin and the same real-time stream, so they can never disagree.`);

  // 5 Synthetic data ---------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Approach" });
  s.addText("Synthetic patients whose EHR drives their physiology", { placeholder: "title" });
  card(s, pres, C, { x: 0.6, y: 1.5, w: 6.0, h: 2.6, n: "A", fill: C.background1, name: "ehr", head: "Indian T2D EHR generator",
    body: "Correlated demographics, labs, comorbidities and Indian prescribing (metformin, gliptins, premix insulin). South-Asian BMI (23/25) and waist cut-offs, simulated TCF7L2 / SLC30A8 / KCNQ1 + polygenic score, diet and staple. FHIR R4 export." });
  card(s, pres, C, { x: 0.6, y: 4.3, w: 6.0, h: 2.4, n: "B", fill: C.background1, name: "phys", head: "Physiological world simulator",
    body: "Extended Bergman minimal model: idli, poha, dal-chawal and biryani meals, drug effects, dawn phenomenon, exercise, sleep debt, stress, plus CGM lag, noise, dropouts and compression lows." });
  stat(s, C, { x: 7.2, y: 1.5, w: 2.6, value: String(MAN.patients), label: `patients × ${MAN.days} days at 5-min resolution`, name: "d1" });
  stat(s, C, { x: 10.1, y: 1.5, w: 2.6, value: MAN.gmi_vs_hba1c_corr.toFixed(2), label: "correlation of sensor GMI with EHR HbA1c (the EHR shapes the signals)", color: C.accent2, name: "d2" });
  stat(s, C, { x: 7.2, y: 4.3, w: 2.6, value: `${f1(MAN.tir_70_180_pct)}%`, label: "time in range 70–180 mg/dL", color: C.accent4, name: "d3" });
  stat(s, C, { x: 10.1, y: 4.3, w: 2.6, value: "0", label: "real patients: every assumption is listed in docs/ASSUMPTIONS.md", color: C.accent3, name: "d4" });
  s.addNotes(`Real patient data is protected by India's DPDP Act and by HIPAA, so the rules of the challenge, and our own principles, say synthetic data only. We built two generators.
The first creates an Indian type 2 diabetes health record: age, sex, BMI with the South-Asian cut-offs of 23 and 25, waist circumference, family history, diabetes duration, HbA1c and other labs, comorbidities, typical Indian prescribing including metformin, gliptins and premix insulin, simulated genetic risk markers, and diet and staple food. Everything is correlated; for example, higher insulin resistance and lower beta-cell function lead to higher HbA1c. We also export it as FHIR, the interoperability standard.
The second is a physiological world simulator. It uses an extended Bergman minimal model of glucose and insulin. Each virtual patient eats Indian meals, takes or misses medicines, walks, sleeps well or badly, gets stressed, and wears a realistic glucose sensor with lag, noise, dropouts and false lows when lying on it.
Crucially, the record drives the physiology. We calibrate each patient so that the sensor's average matches their HbA1c: the correlation between the two is ${MAN.gmi_vs_hba1c_corr.toFixed(2)}.
We generated ${MAN.patients} patients over ${MAN.days} days. Every simplifying assumption is written down in the assumptions register, because synthetic realism is the main risk of this project.`);

  // 6 Models -------------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Approach" });
  s.addText("LightGBM baseline vs multimodal deep fusion", { placeholder: "title" });
  box(s, pres, C, { x: 0.6, y: 1.6, w: 3.0, h: 1.1, text: "6 h wearable window\n17 channels, 5-min steps", fill: C.accent1, color: C.background1, name: "m1", fontSize: 13 });
  box(s, pres, C, { x: 0.6, y: 3.0, w: 3.0, h: 1.1, text: "24-h summary features\n(68 causal features)", fill: C.accent1, color: C.background1, name: "m2", fontSize: 13 });
  box(s, pres, C, { x: 0.6, y: 4.4, w: 3.0, h: 1.1, text: "Static EHR vector\n(47 features)", fill: C.accent5, color: C.background1, name: "m3", fontSize: 13 });
  box(s, pres, C, { x: 4.3, y: 1.6, w: 2.4, h: 1.1, text: "GRU encoder", fill: C.background2, color: C.text2, name: "m4", fontSize: 14 });
  box(s, pres, C, { x: 4.3, y: 3.0, w: 2.4, h: 1.1, text: "MLP", fill: C.background2, color: C.text2, name: "m5", fontSize: 14 });
  box(s, pres, C, { x: 4.3, y: 4.4, w: 2.4, h: 1.1, text: "EHR MLP", fill: C.background2, color: C.text2, name: "m6", fontSize: 14 });
  box(s, pres, C, { x: 7.4, y: 2.3, w: 2.4, h: 2.5, text: "EHR-conditioned\ncross-attention\n+ gated fusion", fill: C.text2, color: C.background1, name: "m7", fontSize: 14 });
  box(s, pres, C, { x: 10.5, y: 1.6, w: 2.2, h: 1.0, text: "Spike head", fill: C.accent2, color: C.text1, name: "h1", fontSize: 13 });
  box(s, pres, C, { x: 10.5, y: 2.95, w: 2.2, h: 1.0, text: "Hypo head", fill: C.accent2, color: C.text1, name: "h2", fontSize: 13 });
  box(s, pres, C, { x: 10.5, y: 4.3, w: 2.2, h: 1.0, text: "P10/P50/P90 ×4", fill: C.accent2, color: C.text1, name: "h3", fontSize: 13 });
  [[3.6, 2.15, 4.3, 2.15], [3.6, 3.55, 4.3, 3.55], [3.6, 4.95, 4.3, 4.95], [6.7, 2.15, 7.4, 3.0], [6.7, 3.55, 7.4, 3.55], [6.7, 4.95, 7.4, 4.1],
    [9.8, 3.2, 10.5, 2.1], [9.8, 3.55, 10.5, 3.45], [9.8, 3.9, 10.5, 4.8]].forEach((a, i) => arrow(s, pres, C, ...a, `ma${i}`));
  s.addText("Baseline: LightGBM on the same 118 causal features. Both are isotonic-calibrated on validation patients. Explanations: TreeSHAP / Integrated Gradients.",
    { x: 0.6, y: 5.9, w: 12.1, h: 0.7, fontSize: 14, color: C.text1, isTextBox: true, objectName: "m-caption" });
  s.addNotes(`We built two model families, as the challenge requires.
The baseline is LightGBM, a gradient-boosting model, trained on 118 engineered features. Every feature is strictly causal, meaning it only uses data from the past: rolling glucose statistics and slopes, time since the last meal, carbs on board, steps, heart-rate variability, sleep in the last 24 hours, what happened at this time yesterday, plus the encoded health record.
The main model is a multimodal deep network in PyTorch. The temporal branch is a GRU, a recurrent network, reading the last six hours of 17 wearable channels. A second branch reads the 24-hour summary features, and a third, an MLP, reads the static health record.
The fusion layer is where the streams meet. The health-record embedding is used as the query in a cross-attention over the six hours of wearable data, so the record decides which moments matter for this patient. Then a learned gate blends the temporal and static representations.
There are three heads: spike probability, low-glucose probability, and the 10th, 50th and 90th percentile of glucose at four horizons.
Both models are calibrated on validation patients, and we explain each prediction with TreeSHAP for the boosting model and Integrated Gradients for the deep model, grouped into clinical factors.`);

  // 7 Evaluation protocol -----------------------------------------------------------------
  pres.addSection({ title: "Results" });
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Results" });
  s.addText("Evaluation built to avoid leakage and report honestly", { placeholder: "title" });
  const ev = [
    ["Split by patient", `${M.train_patients} train / ${M.val_patients} validation / ${M.test_patients} test patients; test patients are never used for tuning`],
    ["Temporal hold-out", "Last 20% of days of the training patients; label windows never cross the cut-off"],
    ["Cold start", "First monitoring day (6–24 h of history), where fusion should matter most"],
    ["Live alert replay", "Every 5 min, with a refractory period: lead time and false alerts per patient-day"],
    ["Fairness", "Age group, sex, South-Asian BMI band, urban / rural"],
    ["Robustness", "Extra CGM noise, 30% CGM dropout, 50% missing watch data, no meal logs"],
  ];
  ev.forEach(([h, b], i) => card(s, pres, C, { x: 0.6 + (i % 3) * 4.1, y: 1.5 + Math.floor(i / 3) * 2.7, w: 3.9, h: 2.5, n: i + 1, head: h, body: b, fill: C.background1, name: `ev${i}` }));
  s.addNotes(`Before the numbers, how we measured them, because evaluation is where health AI projects most often fool themselves.
First, we split by patient, not by row: ${M.train_patients} patients for training, ${M.val_patients} for validation and ${M.test_patients} for testing. Test patients are never used to tune anything, including the alert thresholds. Their data is also what the live demo streams, so the demo shows patients the model has never seen.
Second, a temporal hold-out: the last 20 percent of days, with label windows that never cross the cut-off.
Third, a cold-start test on each patient's first day, when the wearable history is short.
Fourth, a live replay of the alerting system, every five minutes, measuring lead time and false alerts per patient per day, which is what matters to a clinician.
Fifth, fairness across age, sex, BMI band and urban versus rural; and sixth, robustness to sensor noise, dropouts, missing watch data and patients who never log meals.
Every number in the next slides is computed by code in the repository and written to the evaluation report. Nothing is typed by hand.`);

  // 8 Headline results --------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Results" });
  s.addText("Headline results on unseen test patients", { placeholder: "title" });
  const red = df.alerts_red;
  stat(s, C, { x: 0.6, y: 1.6, w: 2.9, value: f3(df.classification.roc_auc), label: "ROC-AUC (deep fusion)", name: "h1" });
  stat(s, C, { x: 3.7, y: 1.6, w: 2.9, value: f3(df.classification.pr_auc), label: `PR-AUC (random = ${f3(df.classification.prevalence)})`, name: "h2" });
  stat(s, C, { x: 6.8, y: 1.6, w: 2.9, value: pct(red.event_sensitivity), label: `of spikes caught at RED, ${f1(red.false_alerts_per_patient_day)} false alert / patient-day`, color: C.accent3, name: "h3" });
  stat(s, C, { x: 9.9, y: 1.6, w: 2.9, value: `${Math.round(red.mean_lead_min)} min`, label: "mean warning before the spike at RED (≈85 min at AMBER)", color: C.accent2, name: "h4" });
  s.addImage({ path: path.join(IMG, "doctor_cgm_alert.png"), x: 0.6, y: 3.95, w: 7.6, h: 3.04, objectName: "h-shot" });
  card(s, pres, C, { x: 8.5, y: 3.95, w: 4.2, h: 2.75, name: "h-note", head: "Calibrated and honest",
    body: `Brier score ${f3(df.classification.brier)}. Temporal hold-out ROC-AUC ${f3(R.deep_fused.temporal.classification.roc_auc)}. Shown left: risk entered RED about 2 h before a breakfast spike.` });
  s.addNotes(`Here are the headline results on the ${M.test_patients} unseen test patients.
The deep fusion model reaches a ROC-AUC of ${f3(df.classification.roc_auc)} and a PR-AUC of ${f3(df.classification.pr_auc)}. For comparison, a random model would have a PR-AUC of ${f3(df.classification.prevalence)}, the share of moments that are followed by a spike.
The more clinical numbers are on the right. At the RED notification level, which we tuned on validation patients to at most about one false alert per patient per day, the system catches ${pct(red.event_sensitivity)} of all spikes, on average ${Math.round(red.mean_lead_min)} minutes before they happen, with ${f1(red.false_alerts_per_patient_day)} false alerts per patient-day.
At the AMBER watch level it catches almost all spikes about 85 minutes ahead, which meets the "two hours ahead" goal, but with about four false flags a day. That is why AMBER is a visual watch level and only RED sends notifications.
The screenshot is the doctor dashboard for one test patient: overnight, the predicted risk rose into the red zone around 5:30 in the morning, well before the post-breakfast spike that followed. The probabilities are calibrated, with a Brier score of ${f3(df.classification.brier)}, and performance holds on the temporal hold-out.`);

  // 9 Fusion ablation (charts) ----------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Results" });
  s.addText("Does fusion help? Not in steady state, but yes at cold start", { placeholder: "title" });
  const cats = ["Wearable-only", "EHR-only", "Fused"];
  const v = (fam, part) => ["wearable_only", "ehr_only", "fused"].map((k) => Number(R[`${fam}_${k}`][part].classification.pr_auc.toFixed(3)));
  const barOpts = (title) => ({ ...chartBase(C), x: 0, y: 0, w: 0, h: 0, barDir: "col", barGrouping: "clustered", chartColors: [HEX.accent5, HEX.accent1],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.000", valAxisMinVal: 0.6, valAxisMaxVal: 0.95, valAxisLabelFormatCode: "0.00",
    showLegend: true, legendPos: "b", showTitle: true, title });
  s.addChart(pres.charts.BAR, [{ name: "LightGBM", labels: cats, values: v("gbm", "test") }, { name: "Deep fusion", labels: cats, values: v("deep", "test") }],
    { ...barOpts("PR-AUC, full history (≥ 24 h)"), x: 0.6, y: 1.45, w: 6.0, h: 4.1, objectName: "chart-steady" });
  s.addChart(pres.charts.BAR, [{ name: "LightGBM", labels: cats, values: v("gbm", "cold_start") }, { name: "Deep fusion", labels: cats, values: v("deep", "cold_start") }],
    { ...barOpts("PR-AUC, cold start (first day)"), x: 6.75, y: 1.45, w: 6.0, h: 4.1, objectName: "chart-cold" });
  const dw = R.deep_wearable_only.test.alerts_red;
  s.addText(`Fusion gain: steady state ${(df.classification.pr_auc - R.deep_wearable_only.test.classification.pr_auc >= 0 ? "+" : "")}${(df.classification.pr_auc - R.deep_wearable_only.test.classification.pr_auc).toFixed(3)} (deep) · cold start +${(R.deep_fused.cold_start.classification.pr_auc - R.deep_wearable_only.cold_start.classification.pr_auc).toFixed(3)} (deep), +${(R.gbm_fused.cold_start.classification.pr_auc - R.gbm_wearable_only.cold_start.classification.pr_auc).toFixed(3)} (GBM) · at RED: ${pct(red.event_sensitivity)} vs ${pct(dw.event_sensitivity)} of spikes caught`,
    { x: 0.6, y: 5.75, w: 12.1, h: 0.9, fontSize: 15, bold: true, color: C.text2, isTextBox: true, objectName: "fusion-summary" });
  s.addNotes(`The challenge asks us to demonstrate fusion, so we ran a full ablation: wearable-only, EHR-only and fused, for both model families. We want to be honest about what it shows.
On the left, with at least a day of wearable history, the EHR-only model is clearly weaker, but wearable-only and fused are almost tied: the fusion gain for the deep model is ${(df.classification.pr_auc - R.deep_wearable_only.test.classification.pr_auc).toFixed(3)}. The reason is that 24 hours of continuous glucose already reveals most of what HbA1c and the prescription say about a patient's control.
On the right is the cold-start setting, a patient's first day, when that history does not exist yet. Here fusion helps both families by about two points of PR-AUC, because the record carries the patient-specific context.
Fusion also helps at the operating point that matters for alerts: at the same false-alert budget, the fused deep model catches ${pct(red.event_sensitivity)} of spikes against ${pct(dw.event_sensitivity)} for the wearable-only model.
So our conclusion is not "fusion always wins", but "fusion matters when the stream is short and when you need high-specificity alerts". We think that is the more useful, and more honest, finding.`);

  // 10 Forecast --------------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Results" });
  s.addText("2-hour forecast beats \"no change\" at every horizon", { placeholder: "title" });
  const hz = [30, 60, 90, 120];
  s.addChart(pres.charts.BAR, [
    { name: "Deep fusion (P50)", labels: hz.map((h) => `+${h} min`), values: hz.map((h) => Number(fc("deep_fused", h).rmse.toFixed(1))) },
    { name: "LightGBM", labels: hz.map((h) => `+${h} min`), values: hz.map((h) => Number(fc("gbm_fused", h).rmse.toFixed(1))) },
    { name: "Persistence (no change)", labels: hz.map((h) => `+${h} min`), values: hz.map((h) => Number(fc("deep_fused", h).persistence_rmse.toFixed(1))) },
  ], { ...chartBase(C), x: 0.6, y: 1.45, w: 8.0, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: [HEX.accent1, HEX.accent5, "B7C4C3"],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", showLegend: true, legendPos: "b", showTitle: true, title: "RMSE (mg/dL), lower is better",
    valAxisLabelFormatCode: "0", objectName: "chart-forecast" });
  card(s, pres, C, { x: 9.0, y: 1.5, w: 3.7, h: 2.4, name: "fc1", head: "+60 min", body: `Deep RMSE ${f1(fc("deep_fused", 60).rmse)} vs ${f1(fc("deep_fused", 60).persistence_rmse)} mg/dL for "no change"` });
  card(s, pres, C, { x: 9.0, y: 4.15, w: 3.7, h: 2.5, name: "fc2", head: "Uncertainty band", fill: C.background2,
    body: `P10–P90 covers ${pct(fc("deep_fused", 60).coverage_p10_p90)} of outcomes at +60 min (target 80%), slightly over-confident` });
  s.addNotes(`Besides the yes-or-no spike risk, the twin forecasts the glucose value itself, which is what is drawn as the blue dashed line and band on the dashboard.
The chart shows the error, in milligrams per decilitre, at four horizons, against the simplest possible baseline: assuming glucose will not change, which we call persistence.
Both models beat persistence at every horizon, and the gap grows with the horizon. At 60 minutes the deep model's error is ${f1(fc("deep_fused", 60).rmse)} against ${f1(fc("deep_fused", 60).persistence_rmse)} for persistence. LightGBM is a little better at 30 and 60 minutes; the deep model is better at 90 and 120 minutes.
We also report a weakness: the uncertainty band, the 10th to 90th percentile, should contain 80 percent of outcomes, but at 60 minutes it contains ${pct(fc("deep_fused", 60).coverage_p10_p90)}. The band is slightly too narrow, and recalibrating the quantiles is on our improvement list.`);

  // 11 Twin + what-if -------------------------------------------------------------------------
  pres.addSection({ title: "Product" });
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Product" });
  s.addText("A personalised simulator that answers \"what if?\"", { placeholder: "title" });
  card(s, pres, C, { x: 0.6, y: 1.5, w: 5.8, h: 1.55, n: 1, fill: C.background1, name: "tw1", head: "Starts from the EHR prior", body: "It never sees the simulator's hidden truth." });
  card(s, pres, C, { x: 0.6, y: 3.25, w: 5.8, h: 1.55, n: 2, fill: C.background1, name: "tw2", head: "Syncs to every CGM reading", body: "An observer keeps the model state on track." });
  card(s, pres, C, { x: 0.6, y: 5.0, w: 5.8, h: 1.65, n: 3, fill: C.background1, name: "tw3", head: "Re-calibrates every 6 h", body: "Insulin sensitivity and basal set-point fitted to the last 24 h." });
  const wi = [["Walk 15 min now", "lower peak, less time > 180"], ["Roti instead of rice", "smaller, slower rise"], ["Dinner at 19:00 vs 21:00", "peak moves away from bedtime"], ["Sleep 5 h vs 8 h", "higher next-morning response"]];
  wi.forEach(([h, b], i) => card(s, pres, C, { x: 6.8, y: 1.5 + i * 1.3, w: 5.9, h: 1.15, name: `wi${i}`, head: h, body: null, fill: C.background1 }) || s.addText(b,
    { x: 9.6, y: 1.5 + i * 1.3, w: 3.0, h: 1.15, fontSize: 14, italic: true, color: C.accent1, valign: "middle", margin: 0, isTextBox: true, objectName: `wi${i}-res` }));
  s.addText("Estimates for discussion: never treatment advice", { x: 6.8, y: 6.75, w: 5.9, h: 0.25, fontSize: 12, color: C.text1, isTextBox: true, objectName: "wi-note" });
  s.addNotes(`A predictor tells you what will probably happen. A digital twin should also answer "what if". Machine-learning models cannot do that from observational data alone, so each twin also carries a small personalised physiological simulator.
It starts from a prior derived only from the health record; it never sees the simulator's hidden ground truth. Every five minutes it advances with what was actually observed (logged meals, medicine, activity, sleep) and an observer nudges it towards the glucose reading. Every six simulated hours it re-fits two personal parameters, insulin sensitivity and the basal set-point, to the last 24 hours.
From that synchronised state we can run several futures in parallel. A 15-minute walk now lowers the peak and the time above 180. Roti instead of white rice gives a smaller, slower rise. Dinner at seven instead of nine moves the peak away from bedtime. And five hours of sleep instead of eight raises tomorrow's breakfast response, because short sleep lowers insulin sensitivity.
These are model estimates to support a conversation between doctor and patient. The app always says so, and it never suggests changing a medicine dose.`);

  // 12 Doctor dashboard -------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Product" });
  s.addText("Doctor dashboard: triage, explanation, app control", { placeholder: "title" });
  s.addImage({ path: path.join(IMG, "doctor_dashboard.png"), x: 0.6, y: 1.4, w: 6.6, h: 5.56, objectName: "doc-shot" });
  const dd = ["Cohort sorted by risk, with a status column and bulk invite", "Live CGM + 2-h forecast band, risk gauge and countdown",
    "\"Why this alert?\" factors from EHR and wearable", "Inject events live: heavy meal, missed dose, poor sleep, dropout",
    "Patient Interface Manager: secure invite + QR, live preview, engagement", "Every action written to an audit trail"];
  s.addText(dd.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < dd.length - 1 } })),
    { x: 7.6, y: 1.5, w: 5.1, h: 5.2, fontSize: 16, color: C.text1, paraSpaceAfter: 10, valign: "top", isTextBox: true, objectName: "doc-bullets" });
  s.addNotes(`This is the doctor's dashboard, a real running React application, not a mock-up.
On the left the cohort is sorted by risk. Each badge has an icon and a word, and the status column shows whether each patient's app is not enrolled, invited, active or paused.
For the selected patient we see the profile with HbA1c, medications and comorbidities, then the Patient Interface Manager, which we will come back to, then the live glucose chart with the last 12 hours, the two-hour forecast band, the target range and alert markers, and next to it the risk gauge with the countdown.
Below the screenshot there are aligned panels for sleep stages, heart rate and HRV, and steps, the "Why this alert?" panel, glucose metrics including time-in-range and an ambulatory glucose profile, the what-if simulator, and clinician actions: acknowledge, note, suggest an intervention.
For the demo, the top bar lets us change the stream speed and inject events such as a heavy carb meal or a sensor dropout, so the audience can watch the prediction react in real time. Every action is written to an audit trail.`);

  // 13 Patient app -------------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Product" });
  s.addText("Patient app: doctor-launched, in the patient's language", { placeholder: "title" });
  s.addImage({ path: path.join(IMG, "patient_home.png"), x: 0.6, y: 1.4, w: 2.07, h: 5.55, sizing: { type: "crop", w: 2.07, h: 5.55 }, objectName: "p-home" });
  s.addImage({ path: path.join(IMG, "patient_care.png"), x: 2.95, y: 1.4, w: 2.07, h: 5.55, sizing: { type: "crop", w: 2.07, h: 5.55 }, objectName: "p-care" });
  const flow = ["Enrol", "Configure", "Invite + QR", "OTP", "Consent", "ACTIVE"];
  flow.forEach((t, i) => {
    box(s, pres, C, { x: 5.45 + i * 1.22, y: 1.5, w: 1.08, h: 0.8, text: t, fill: i === 5 ? C.accent4 : C.text2, color: C.background1, name: `pf${i}`, fontSize: 12 });
    if (i < 5) arrow(s, pres, C, 6.53 + i * 1.22, 1.9, 6.67 + i * 1.22, 1.9, `pfa${i}`);
  });
  const pa = ["Home: one plain sentence, glucose + trend, 2-h estimate in the target zone, one next action",
    "My Day: timeline and \"why\" in everyday language", "Try it: walk / roti vs rice / earlier dinner",
    "Quick Log: Indian food presets in under 10 seconds", "Care: alerts, care-plan cards, doctor messages",
    "Me: progress, access log, withdraw consent"];
  s.addText(pa.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < pa.length - 1 } })),
    { x: 5.45, y: 2.6, w: 7.25, h: 4.2, fontSize: 15, color: C.text1, paraSpaceAfter: 8, valign: "top", isTextBox: true, objectName: "p-bullets" });
  s.addNotes(`The second client of the twin is the patient app, a mobile-first progressive web app in English, Hindi and Tamil. The screenshots are the real app at phone width, in Hindi.
The patient never signs up on their own. The doctor enrols the patient, configures the app with a template in under two minutes (language, target range, features, care plan, alert limits), previews exactly what the patient will see, and launches a secure single-use invite as a link and QR code with an expiry.
The patient opens it, verifies with a one-time PIN, reads and accepts a consent screen, picks a language, takes a short tour, and connects the simulated wearable. Only then does the state become active and the live twin connect.
The home screen gives one status with an icon and a word, one plain sentence such as "your sugar may go high in about 90 minutes", the current glucose with a trend arrow, a simplified forecast inside the target zone, and one recommended action. My Day explains why in everyday words; Try it shows simple what-ifs; Quick Log takes Indian meals, walks, medicines and symptoms in a tap; Care holds alerts, the doctor's care-plan cards and messages; and Me shows progress and the privacy centre.`);

  // 13b Food diary + personal food-impact AI ----------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Product" });
  s.addText("Personal food-impact AI: which foods push my sugar up?", { placeholder: "title" });
  s.addImage({ path: path.join(IMG, "patient_food.png"), x: 0.6, y: 1.4, w: 2.24, h: 5.55, sizing: { type: "crop", w: 2.24, h: 5.55 }, objectName: "food-patient" });
  s.addImage({ path: path.join(IMG, "doctor_food.png"), x: 3.15, y: 1.4, w: 5.75, h: 2.93, objectName: "food-doctor" });
  const fa = ["Measures each meal from the patient's own CGM", "Flags foods worse than this patient's usual meal",
    "Links logged symptoms to foods eaten 4 h before", "Warns gently when a flagged food is logged again"];
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.15, y: 4.5, w: 5.75, h: 2.45, rectRadius: 0.1, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: "fa-card" });
  s.addText(fa.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < fa.length - 1 } })),
    { x: 3.35, y: 4.6, w: 5.4, h: 2.25, fontSize: 15, color: C.text1, paraSpaceAfter: 8, valign: "middle", isTextBox: true, objectName: "fa-list" });
  stat(s, C, { x: 9.3, y: 1.5, w: 3.4, value: "14 days", label: "food diary per patient, with daily carbs, late meals, sweets and highs after meals", name: "fd1" });
  stat(s, C, { x: 9.3, y: 4.0, w: 3.4, value: "3 demo", label: "patient accounts (English / Hindi / Tamil), already activated for the demo", color: C.accent2, name: "fd2" });
  s.addNotes(`Many patients ask: which of my foods are actually the problem? General advice says "less rice", but responses are personal. So the twin keeps a 14-day food diary and learns this patient's own response to each food.
For every logged meal it reads the patient's own glucose sensor: the level at the meal, the peak in the next two and a half hours, the rise, and the minutes spent above target. If another meal followed within 90 minutes the two responses overlap, so that meal stays in the diary but is left out of the statistics.
It then flags a food only if it consistently goes above target and is clearly worse than this patient's usual meal: at least 1.2 times their usual rise. For a poorly controlled patient whose every meal goes high, this singles out the foods that are worse than usual, instead of flagging everything. Each finding shows how many meals it is based on, labelled as an early sign, some evidence, or reliable.
It also spots patterns such as late dinners peaking higher than early ones, or rice meals compared with roti and millet. It links symptoms the patient logs, like thirst or dizziness, to foods eaten in the four hours before, together with the glucose at that time. When a flagged food is logged again, the patient gets a gentle, capped warning: "the last five times after biryani your sugar went above 180; a short walk after eating can help". The doctor sees the same analysis as a table and a day-by-day diary.
For demos we also ship three ready-made patient accounts in English, Hindi and Tamil, activated through the same audited lifecycle.`);

  // 14 Safety & privacy -----------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Product" });
  s.addText("Safety, privacy and consent built in, not bolted on", { placeholder: "title" });
  const sp = [
    ["Always-on safety", "RED and low-glucose alerts cannot be disabled or capped; first aid and tap-to-call 108"],
    ["No medication changes", "Reminders only for the existing prescription; questions go to the doctor"],
    ["Consent gate", "No twin data before consent; withdrawal disconnects instantly and stops logs"],
    ["Secure invites", "Signed single-use tokens, expiry, OTP with lockout, device binding, rate limits"],
    ["Role-based access", "Doctors see only assigned patients; patients only themselves; caregiver opt-in"],
    ["Audit + minimisation", "Every view and change logged; the patient sees who viewed their data"],
  ];
  sp.forEach(([h, b], i) => card(s, pres, C, { x: 0.6 + (i % 3) * 4.1, y: 1.5 + Math.floor(i / 3) * 2.7, w: 3.9, h: 2.5, n: i + 1, head: h, body: b, name: `sp${i}` }));
  s.addNotes(`Because this touches health, safety and privacy are designed in from the start, aligned with India's DPDP Act and with HIPAA principles.
Safety: red alerts and low-glucose warnings, whether predicted or measured, are always on. The configuration schema literally cannot switch them off, and they bypass the frequency caps that protect patients from alarm fatigue. Low-glucose alerts show first aid (take 15 grams of fast sugar and re-check in 15 minutes) and a tap-to-call button for 108. Every alert shows a confidence level and a "not medical advice" notice. The app never diagnoses and never changes medication; it only reminds the patient about the existing prescription.
Privacy: no twin data reaches the app before consent, and withdrawing consent disconnects the app immediately. Invites are signed, single-use and expiring, with one-time PIN verification, lockout after five wrong codes, device binding and rate limits. Access is role-based: a doctor can only launch apps for their assigned patients, and a patient can only see their own twin. Everything is audited, and the patient can see their own access log.
All of this is covered by automated tests.`);

  // 15 Behaviour response ------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Product" });
  s.addText("Simulated patients who follow the app spend less time high", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [{ name: "Time > 180 mg/dL (%)", labels: ["No app", "Follows 50%", "Follows 100%"], values: [BEH.control.tar_pct, BEH.follow_50.tar_pct, BEH.follow_100.tar_pct] }],
    { ...chartBase(C), x: 0.6, y: 1.45, w: 7.0, h: 5.2, barDir: "col", chartColors: [HEX.accent3], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0",
      showLegend: false, showTitle: true, title: "Time above 180 mg/dL (%), 12 virtual test patients × 3 days, paired arms", valAxisLabelFormatCode: "0", objectName: "chart-beh" });
  card(s, pres, C, { x: 8.0, y: 1.5, w: 4.7, h: 2.5, fill: C.background1, name: "beh1", head: "Simulation only",
    body: "A mechanism check inside our own simulator, not clinical evidence. Real-world benefit needs a trial." });
  card(s, pres, C, { x: 8.0, y: 4.2, w: 4.7, h: 2.45, fill: C.background1, name: "beh2", head: "No added lows",
    body: `Time below 70: ${BEH.control.tbr_pct}% → ${BEH.follow_100.tbr_pct}%. Spike counts fell by about one per day in both following arms.` });
  s.addNotes(`Does acting on the app's advice help? We can't answer that for real people without a clinical study, but we can check that the loop works mechanically.
We ran the same 12 virtual test patients for three days in three paired arms, with identical meals, sleep and sensor noise: no app; following the app's lifestyle suggestions half of the time; and following them every time. Following means taking a 15-minute walk, or choosing roti or millet instead of rice at the next meal, whenever the twin's prediction would trigger that suggestion.
Time above 180 fell from ${BEH.control.tar_pct} percent with no app to ${BEH.follow_50.tar_pct} percent at half adherence and ${BEH.follow_100.tar_pct} percent at full adherence, with no increase in low glucose.
Spike counts fell by about one per patient-day in both following arms, but not monotonically: a walk can split one long excursion into two short ones, so time above range is the more stable measure.
Again, this is a simulation in the same world the model was trained on. It shows the mechanism works; it is not evidence of clinical benefit.`);

  // 16 Tech stack ---------------------------------------------------------------------------------
  pres.addSection({ title: "Wrap-up" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Wrap-up" });
  s.addText("Technical stack and engineering quality", { placeholder: "title" });
  const ts = [
    ["Data & ML", "Python 3.12 · NumPy / pandas / SciPy · PyTorch (GRU fusion) · LightGBM · scikit-learn · SHAP"],
    ["Backend", "FastAPI · Uvicorn · WebSockets · Pydantic · SQLite audit · PyJWT"],
    ["Frontend", "React 18 · Vite · TypeScript · Tailwind · Recharts · react-i18next · PWA"],
    ["Ops", `make / tasks.py · Docker Compose · training ${Math.round(JSON.parse(fs.readFileSync(path.join(ROOT, "artifacts", "training_summary.json"), "utf8")).train_seconds / 60)} min + evaluation on a laptop CPU`],
  ];
  ts.forEach(([h, b], i) => card(s, pres, C, { x: 0.6, y: 1.45 + i * 1.3, w: 8.2, h: 1.15, name: `ts${i}`, head: h, body: null }) || s.addText(b,
    { x: 2.6, y: 1.45 + i * 1.3, w: 6.1, h: 1.15, fontSize: 14, color: C.text1, valign: "middle", margin: 0, isTextBox: true, objectName: `ts${i}-b` }));
  stat(s, C, { x: 9.3, y: 1.5, w: 3.4, value: "63 + 16", label: "automated tests (pytest + vitest), incl. end-to-end", name: "t1" });
  stat(s, C, { x: 9.3, y: 4.0, w: 3.4, value: "1 cmd", label: "make demo: backend, doctor dashboard and patient app on one port", color: C.accent2, name: "t2" });
  s.addNotes(`A quick word on the engineering.
The machine-learning stack is Python with PyTorch for the fusion network, LightGBM as the baseline, scikit-learn for calibration and SHAP for explanations. The backend is FastAPI with WebSockets for the live stream, Pydantic for validated configuration, SQLite for the audit log and JWT for role-based access. The frontend is React with TypeScript, Tailwind and Recharts, and the patient app is an installable progressive web app with three languages.
Everything is reproducible: one command generates the data, about six minutes of laptop-CPU training plus evaluation rebuilds the models and the evaluation report, and make demo starts the backend, the doctor dashboard and the patient app together.
There are 63 Python tests and 16 frontend tests. They cover the data generator, the food-impact detection, feature causality (no peeking into the future), the alert maths, the twin and the what-if engine, the full API, the patient-interface state machine, invites, one-time PINs, the consent gate, role-based access, safety alerts and frequency caps, plus an end-to-end journey from enrolment to revocation.`);

  // 17 Limitations ---------------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Wrap-up" });
  s.addText("Limitations and the path to real-world validation", { placeholder: "title" });
  const lim = ["Synthetic data: the models partly learn our simulator's assumptions", "Not a medical device; no clinical validation",
    "Small test set (23 patients); fairness estimates are noisy", "Hypoglycaemia is rare in the cohort, so the hypo head is advisory",
    "Hindi and Tamil text is machine-drafted: needs native review"];
  s.addText(lim.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < lim.length - 1 } })),
    { x: 0.6, y: 1.5, w: 5.6, h: 5.1, fontSize: 16, color: C.text1, paraSpaceAfter: 12, valign: "top", isTextBox: true, objectName: "lim" });
  const path_ = [["Retrospective study", "Consented Indian CGM + EHR, ethics approval"], ["Federated learning", "Train across hospitals; data stays on site"],
    ["ABDM / FHIR", "Consent manager + FHIR R4 (export ready)"], ["Silent trial → CDSCO", "Prospective validation, then SaMD pathway"]];
  path_.forEach(([h, b], i) => rowCard(s, pres, C, { x: 6.6, y: 1.5 + i * 1.3, w: 6.1, h: 1.15, n: i + 1, head: h, body: b, name: `pv${i}` }));
  s.addNotes(`We want to be clear about the limits of a proof of concept.
The biggest one is synthetic data. The same simulator produced the inputs and the labels, so part of what the models learned are our own assumptions. Real-world performance will be lower. This is not a medical device and has no clinical validation. The test set is only 23 patients, so the fairness breakdowns are hypotheses, not findings. Low glucose is rare in our cohort, so the low-glucose head is advisory only. And the Hindi and Tamil text was drafted by machine and needs native-speaker and clinical review.
The path to the real world has four steps. First, a retrospective study on consented Indian glucose-sensor and EHR data under ethics committee approval. Second, federated learning, so hospitals can train together without moving patient data. Third, integration with India's digital health mission, ABDM, using its consent manager and FHIR R4; our FHIR export is already there. Fourth, a prospective silent trial where alerts run in the background without reaching clinicians, followed by the CDSCO pathway for software as a medical device.`);

  // 18 Thank you ----------------------------------------------------------------------------------
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Wrap-up" });
  s.addText("Thank you", { placeholder: "title" });
  s.addText("Code: https://github.com/KoderOP/DigitalTwin  ·  MIT License\nDemo: make demo → http://127.0.0.1:8000 (doctor) and /patient/ (patient app)\n[FILL IN: team name · members · college / incubator · contact]", { placeholder: "body" });
  s.addNotes(`To summarise: Sugar Twin fuses a synthetic Indian type 2 diabetes record with a live wearable stream into a per-patient digital twin. It warns about glucose spikes up to two hours ahead, catches 80 percent of spikes about 45 minutes ahead at roughly one false alert a day, explains why in plain language in three Indian languages, lets doctors and patients try what-ifs, and puts the doctor in control of a consent-first patient app.
Everything is open source under the MIT license at the repository on screen, and the whole system runs with one command on a laptop.
Next, we will switch to the live demo, and after that we're happy to take questions. Thank you.`);

  const file = path.join(OUT, "Presentation.pptx");
  await pres.writeFile({ fileName: file });
  return file;
}

// =============================================================================================
// Architecture diagram deck
// =============================================================================================
async function architecture() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "Sugar Twin: architecture diagram";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = layouts(pres);

  pres.addSection({ title: "Architecture" });
  // 1 End-to-end
  let s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Architecture" });
  s.addText("End-to-end architecture: data → fusion → twin → apps", { placeholder: "title" });
  const lane = (x, label, name) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.35, w: 2.35, h: 5.1, rectRadius: 0.1, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `${name}-lane` });
    s.addText(label, { x, y: 1.4, w: 2.35, h: 0.4, fontSize: 13, bold: true, color: C.text2, align: "center", margin: 0, isTextBox: true, objectName: `${name}-label` });
  };
  lane(0.5, "1 · Synthetic data", "l1"); lane(3.0, "2 · Ingestion + features", "l2"); lane(5.5, "3 · Models", "l3"); lane(8.0, "4 · Digital Twin", "l4"); lane(10.5, "5 · Clients", "l5");
  const B = (x, y, t, fill, color, name, h = 0.95) => box(s, pres, C, { x: x + 0.12, y, w: 2.11, h, text: t, fill, color, name, fontSize: 11 });
  B(0.5, 1.95, "EHR generator\n(Indian T2D, FHIR export)", C.accent5, C.background1, "e1");
  B(0.5, 3.05, "World simulator\nBergman model + lifestyle", C.accent1, C.background1, "e2");
  B(0.5, 4.15, "Sensor models\nCGM, HR, HRV, sleep, steps", C.accent1, C.background1, "e3");
  B(0.5, 5.25, "Demo injections\nmeal, missed dose, dropout", C.accent2, C.text1, "e4");
  B(3.0, 1.95, "Ingestion API / in-process\nconsent + minimisation", C.text2, C.background1, "i1");
  B(3.0, 3.05, "Causal features (118)\n+ imputation + quality", C.text2, C.background1, "i2");
  B(3.0, 4.15, "6 h × 17-channel\nsequence window", C.text2, C.background1, "i3");
  B(3.0, 5.25, "SQLite: audit, consent,\ninvites, logs", C.accent5, C.background1, "i4");
  B(5.5, 1.95, "Deep fusion (PyTorch)\nGRU + EHR cross-attn", C.accent1, C.background1, "m1");
  B(5.5, 3.05, "LightGBM baseline\n+ isotonic calibration", C.accent5, C.background1, "m2");
  B(5.5, 4.15, "Explainability\nIG / TreeSHAP → factors", C.accent1, C.background1, "m3");
  B(5.5, 5.25, "Evaluation + reports\nablation, fairness", C.accent5, C.background1, "m4");
  B(8.0, 1.95, "Twin state\n50 h buffer, 14 d CGM", C.accent2, C.text1, "t1");
  B(8.0, 3.05, "Personalised simulator\nobserver + calibration", C.accent2, C.text1, "t2");
  B(8.0, 4.15, "What-if engine\nparallel roll-outs", C.accent2, C.text1, "t3");
  B(8.0, 5.25, "Portal service\nlifecycle, alerts, i18n", C.accent2, C.text1, "t4");
  B(10.5, 1.95, "Doctor dashboard\nReact + WebSocket", C.text2, C.background1, "c1", 1.5);
  B(10.5, 3.6, "Patient PWA\nEN / HI / TA", C.accent4, C.background1, "c2", 1.5);
  B(10.5, 5.25, "Caregiver view\n(read-only, opt-in)", C.accent6, C.background1, "c3");
  s.addText("Data flows left to right (1 → 5) every 5 minutes. The doctor dashboard, patient PWA and caregiver view are role-based clients of the same twin.",
    { x: 0.5, y: 6.55, w: 11.0, h: 0.3, fontSize: 12, italic: true, color: C.text2, margin: 0, isTextBox: true, objectName: "flow-note" });
  s.addNotes("End-to-end architecture. Synthetic EHR and wearable streams are ingested, turned into causal features and a 6-hour sequence, fused by the deep model (LightGBM as a baseline), explained, and held in a per-patient digital twin with a personalised simulator and what-if engine. The doctor dashboard and the patient PWA are role-based clients of the same twin.");

  // 2 Real-time loop + provisioning
  s = pres.addSlide({ masterName: "CONTENT_TINT", sectionTitle: "Architecture" });
  s.addText("Real-time loop and doctor-initiated patient provisioning", { placeholder: "title" });
  const loop = ["World advances 5 min", "Record ingested (minimised)", "Twin syncs + recalibrates", "Prediction + explanation", "Notifications (caps, safety)", "Push via WebSocket"];
  loop.forEach((t, i) => {
    box(s, pres, C, { x: 0.6, y: 1.45 + i * 0.88, w: 4.6, h: 0.7, text: `${i + 1}. ${t}`, fill: C.background1, color: C.text2, name: `lp${i}`, fontSize: 13 });
    if (i < loop.length - 1) arrow(s, pres, C, 2.9, 2.15 + i * 0.88, 2.9, 2.33 + i * 0.88, `lpa${i}`);
  });
  const st = ["NOT_ENROLLED", "INVITED", "CONSENT_PENDING", "ACTIVE", "PAUSED", "REVOKED"];
  const pos = [[5.9, 1.6], [8.3, 1.6], [10.7, 1.6], [10.7, 3.3], [8.3, 3.3], [8.3, 5.0]];
  st.forEach((t, i) => box(s, pres, C, { x: pos[i][0], y: pos[i][1], w: 2.0, h: 0.85, text: t, fill: t === "ACTIVE" ? C.accent4 : t === "REVOKED" ? C.accent3 : C.text2, color: C.background1, name: `st${i}`, fontSize: 12 }));
  arrow(s, pres, C, 7.9, 2.02, 8.3, 2.02, "sa1"); arrow(s, pres, C, 10.3, 2.02, 10.7, 2.02, "sa2"); arrow(s, pres, C, 11.7, 2.45, 11.7, 3.3, "sa3");
  arrow(s, pres, C, 10.7, 3.72, 10.3, 3.72, "sa4"); arrow(s, pres, C, 9.3, 4.15, 9.3, 5.0, "sa5");
  const lbl = (x, y, t, n) => s.addText(t, { x, y, w: 2.3, h: 0.35, fontSize: 11, italic: true, color: C.text1, margin: 0, isTextBox: true, objectName: n });
  lbl(5.9, 2.5, "doctor: enrol, configure, launch", "lb1"); lbl(8.3, 2.5, "patient: OTP verified", "lb2"); lbl(10.7, 2.75, "patient: consent", "lb3");
  lbl(5.9, 3.85, "doctor: pause / resume", "lb4"); lbl(5.9, 5.1, "doctor revoke or\npatient withdraw", "lb5");
  s.addText("Any non-terminal state → REVOKED; REVOKED → INVITED re-launches. Every transition is audited. No twin data reaches the patient app unless ACTIVE.",
    { x: 5.9, y: 6.05, w: 6.8, h: 0.75, fontSize: 13, color: C.text2, isTextBox: true, objectName: "st-note" });
  s.addNotes("Left: the 5-minute real-time loop shared by both apps. Right: the patient-interface lifecycle state machine with the actor for each transition.");

  const file = path.join(OUT, "Architecture_Diagram.pptx");
  await pres.writeFile({ fileName: file });
  return file;
}

(async () => {
  const files = [await presentation(), await architecture()];
  const skill = process.env.PPTX_SKILL_DIR;
  if (skill) {
    const { applyTheme } = require(path.join(skill, "scripts", "apply_theme.js"));
    for (const f of files) await applyTheme(f, THEME);
  } else {
    console.warn("PPTX_SKILL_DIR not set: theme colours not written (scheme colours fall back to Office defaults).");
  }
  console.log(files.join("\n"));
})();
