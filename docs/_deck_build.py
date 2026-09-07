from pptx import Presentation
from pptx.util import Inches as I, Pt, Emu
from pptx.dml.color import RGBColor as C
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

BG     = C(0x0B,0x0E,0x14)
PANEL  = C(0x15,0x1A,0x24)
PANEL2 = C(0x1D,0x24,0x31)
TEXT   = C(0xE8,0xEC,0xF3)
DIM    = C(0x8A,0x93,0xA6)
BLUE   = C(0x4C,0x8D,0xFF)
CYAN   = C(0x5A,0xC8,0xFA)
GREEN  = C(0x4E,0xD1,0x7F)
RED    = C(0xE5,0x48,0x4D)
AMBER  = C(0xE6,0xA0,0x20)
VIOLET = C(0x9B,0x85,0xFF)
WHITE  = C(0xFF,0xFF,0xFF)
BLACK  = C(0x00,0x00,0x00)

H, B = "Cambria", "Calibri"
URL  = "https://sentrywatch.onrender.com"
REPO = "https://github.com/abed101-glitch/sentrywatch"

prs = Presentation()
prs.slide_width, prs.slide_height = I(13.333), I(7.5)
BLANK = prs.slide_layouts[6]
W, HT = 13.333, 7.5
M = 0.75                       # margin
CW = W - 2*M                   # content width = 11.833


def slide():
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = BG
    bg.line.fill.background(); bg.shadow.inherit = False
    return s

def txt(s, x, y, w, h, text, size=15, color=TEXT, font=B, bold=False,
        align=PP_ALIGN.LEFT, italic=False, line=None, space=0,
        anchor=MSO_ANCHOR.TOP):
    tb = s.shapes.add_textbox(I(x), I(y), I(w), I(h)); tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, ln in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if line: p.line_spacing = line
        if space: p.space_after = Pt(space)
        r = p.add_run(); r.text = ln
        r.font.size = Pt(size); r.font.color.rgb = color
        r.font.name = font; r.font.bold = bold; r.font.italic = italic
    return tb

def box(s, x, y, w, h, fill=PANEL, line=None, r=0.05, lw=1.0):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, I(x), I(y), I(w), I(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line: sh.line.color.rgb = line; sh.line.width = Pt(lw)
    else: sh.line.fill.background()
    sh.shadow.inherit = False
    try: sh.adjustments[0] = r
    except Exception: pass
    return sh

def bar(s, x, y, w, h, fill):
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, I(x), I(y), I(w), I(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.fill.background(); sh.shadow.inherit = False
    return sh

def arrow(s, x, y, w=0.26, h=0.20, col=DIM):
    a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, I(x), I(y), I(w), I(h))
    a.fill.solid(); a.fill.fore_color.rgb = col
    a.line.fill.background(); a.shadow.inherit = False
    return a

def title(s, t, sub=None, kicker=None):
    y = 0.62
    if kicker:
        txt(s, M, y, CW, 0.28, kicker.upper(), 11.5, BLUE, B, bold=True)
        y += 0.40
    txt(s, M, y, CW, 0.72, t, 33, TEXT, H, bold=True)
    if sub:
        txt(s, M, y + 0.76, CW, 0.36, sub, 14.5, DIM, B, italic=True)

def chip(s, x, y, label, col, w=None, size=11.5):
    w = w or (0.15 * len(label) + 0.42)
    sh = box(s, x, y, w, 0.34, PANEL2, col, r=0.42, lw=1.0)
    tf = sh.text_frame; tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = label
    r.font.size = Pt(size); r.font.bold = True; r.font.color.rgb = col; r.font.name = B
    return sh, w

def stat(s, x, y, w, value, label, col=TEXT, vs=44, ls=12):
    txt(s, x, y, w, 0.72, value, vs, col, H, bold=True)
    txt(s, x, y + 0.74, w, 0.5, label, ls, DIM, B, line=1.2)

def link(shape, url):
    shape.click_action.hyperlink.address = url

def foot(s, text="SentryWatch  ·  Abed Gazi  ·  CSE 299"):
    txt(s, M, HT - 0.52, CW, 0.28, text, 10, C(0x59,0x61,0x72), B)

# ═══════════════════════════════════════════ 1 · title
s = slide()
bar(s, 0, 0, 0.10, HT, BLUE)
txt(s, M + 0.25, 2.05, 9.0, 0.5, "REAL-TIME FRAUD DETECTION", 13, BLUE, B, bold=True)
txt(s, M + 0.25, 2.55, 9.6, 1.05, "SentryWatch", 62, TEXT, H, bold=True)
txt(s, M + 0.25, 3.72, 8.4, 0.9,
    "Every order scored against that customer's own history —\nwith an answer before the payment clears.",
    18, DIM, B, line=1.35)
for i, (v, l, c) in enumerate([("284,807", "transactions evaluated", TEXT),
                               ("34.1%", "of real fraud caught", GREEN),
                               ("96", "automated tests", TEXT)]):
    stat(s, M + 0.25 + i*2.75, 5.05, 2.6, v, l, c, 30, 11)
c, cw = chip(s, M + 0.25, 6.42, "▶  Open the live demo", CYAN, 2.55, 12)
link(c, URL)
txt(s, M + 0.25, 6.95, 9.0, 0.3, "Abed Gazi  ·  2132538642  ·  CSE 299, Section 13", 11.5, DIM, B)

# ═══════════════════════════════════════════ 2 · the problem
s = slide()
title(s, "Fraud is rare, and that is the whole difficulty",
      "Kaggle Credit Card Fraud — 284,807 real transactions, 492 labelled frauds",
      "the problem")
y = 2.55
txt(s, M, y, 4.0, 0.3, "EVERY TRANSACTION", 11, DIM, B, bold=True)
bar(s, M, y + 0.38, CW, 0.42, PANEL2)
bar(s, M, y + 0.38, CW * 0.0173 * 8, 0.42, RED)     # exaggerated so it is visible
txt(s, M, y + 0.92, 6.0, 0.3, "the red sliver is fraud — drawn 8× wider than reality so it is visible at all",
    11, DIM, B, italic=True)
box(s, M, 4.35, 5.75, 1.62, PANEL)
txt(s, M + 0.35, 4.62, 5.1, 0.6, "0.173%", 40, RED, H, bold=True)
txt(s, M + 0.35, 5.35, 5.1, 0.4, "of transactions are fraudulent", 13, DIM, B)
box(s, M + 6.08, 4.35, 5.75, 1.62, PANEL)
txt(s, M + 6.43, 4.62, 5.1, 0.6, "99.83%", 40, AMBER, H, bold=True)
txt(s, M + 6.43, 5.35, 5.1, 0.6, "accuracy from a model that only ever says “not fraud”",
    13, DIM, B, line=1.25)
txt(s, M, 6.35, CW, 0.5,
    "So accuracy is the wrong measure. Everything in this project is reported as recall and precision, against real labels.",
    15, TEXT, B, bold=True)
foot(s)

# ═══════════════════════════════════════════ 3 · what runs
s = slide()
title(s, "What runs", "One service. One HTTP call from the merchant.", "the system")
nodes = [("Checkout", "the shop's own\npayment handler", PANEL, DIM),
         ("Scoring API", "model + per-account\nbaseline + throttle", PANEL, BLUE),
         ("SQLite", "every event,\nwith its label", PANEL, DIM),
         ("Alert", "Telegram, one\nper incident", PANEL, GREEN)]
nw, gap = 2.72, 0.32
x = M + (CW - (4*nw + 3*gap)) / 2
for i, (t, sub, fill, col) in enumerate(nodes):
    box(s, x, 2.62, nw, 1.32, fill, col, lw=1.25)
    txt(s, x + 0.2, 2.86, nw - 0.4, 0.32, t, 15, col if col != DIM else TEXT, B, bold=True)
    txt(s, x + 0.2, 3.26, nw - 0.4, 0.6, sub, 11.5, DIM, B, line=1.2)
    if i < 3: arrow(s, x + nw + 0.03, 3.18)
    x += nw + gap
txt(s, M, 4.35, CW, 0.42, "The merchant writes four lines", 19, TEXT, H, bold=True)
box(s, M, 4.88, CW, 1.52, PANEL)
txt(s, M + 0.35, 5.08, CW - 0.7, 1.16,
    'const { verdict } = await scoreOrder(order);\n'
    'if (verdict === "DECLINE") return reject();\n'
    'if (verdict === "REVIEW")  return queueForStaff(order);\n'
    'await takePayment(order);',
    13.5, CYAN, "Consolas", line=1.32)
foot(s)

# ═══════════════════════════════════════════ 4 · the core idea
s = slide()
title(s, "One yardstick per customer", None, "the core idea")
box(s, M, 2.35, 5.75, 2.75, PANEL, RED, lw=1.25)
txt(s, M + 0.38, 2.62, 5.0, 0.34, "BEFORE  ·  classes 2–6", 11.5, RED, B, bold=True)
txt(s, M + 0.38, 3.08, 5.0, 1.7,
    "Every amount compared to one global average over all 284,807 transactions.\n\n"
    "A 900 charge scores the same whether it comes from a wholesaler or a student.",
    14, TEXT, B, line=1.38, space=4)
box(s, M + 6.08, 2.35, 5.75, 2.75, PANEL, GREEN, lw=1.25)
txt(s, M + 6.46, 2.62, 5.0, 0.34, "AFTER  ·  class 7", 11.5, GREEN, B, bold=True)
txt(s, M + 6.46, 3.08, 5.0, 1.7,
    "Each account carries its own running mean and variance, updated on every order.\n\n"
    "The same 900 charge is routine for one and a 53-sigma outlier for the other.",
    14, TEXT, B, line=1.38, space=4)
txt(s, M, 5.42, CW, 0.4, "Welford's algorithm — the entire memory per account", 18, TEXT, H, bold=True)
labels = [("n", "count"), ("mean", "running average"), ("M²", "sum of squares")]
cw2, g2 = 2.55, 0.3
x = M
for t, sub in labels:
    box(s, x, 5.95, cw2, 0.82, PANEL2, BLUE, lw=1.0)
    txt(s, x, 6.08, cw2, 0.32, t, 17, CYAN, H, bold=True, align=PP_ALIGN.CENTER)
    txt(s, x, 6.44, cw2, 0.26, sub, 10.5, DIM, B, align=PP_ALIGN.CENTER)
    x += cw2 + g2
txt(s, x + 0.1, 6.05, 3.4, 0.7,
    "Three numbers. 127 bytes per account.\nNo transaction is ever stored.",
    13.5, TEXT, B, line=1.35)
foot(s)

# ═══════════════════════════════════════════ 5 · n8n
s = slide()
title(s, "Automated end to end with n8n",
      "Once the workflow is active, nothing is typed during a demo", "automation")
chain = [("Schedule", "every 10s"), ("Fetch", "next real txn"),
         ("Score", "model + baseline"), ("Route", "by severity"),
         ("Throttle", "seen it already?"), ("Telegram", "deliver")]
nw, gap = 1.76, 0.24
x = M + (CW - (6*nw + 5*gap)) / 2
for i, (t, sub) in enumerate(chain):
    last = i == 5
    box(s, x, 2.62, nw, 0.92, GREEN if last else PANEL, GREEN if last else BLUE, lw=1.25)
    txt(s, x, 2.80, nw, 0.3, t, 13, BLACK if last else TEXT, B, bold=True, align=PP_ALIGN.CENTER)
    txt(s, x, 3.14, nw, 0.26, sub, 10, C(0x11,0x33,0x22) if last else DIM, B, align=PP_ALIGN.CENTER)
    if not last: arrow(s, x + nw + 0.005, 2.98, 0.23, 0.18, BLUE)
    x += nw + gap
txt(s, M, 4.02, CW, 0.34, "n8n nodes  ·  the workflow is 8 nodes on one canvas", 11.5, DIM, B, italic=True)
box(s, M, 4.62, 5.75, 1.92, PANEL)
txt(s, M + 0.35, 4.88, 5.05, 0.32, "Policy lives in n8n", 15, BLUE, B, bold=True)
txt(s, M + 0.35, 5.28, 5.05, 1.1,
    "The Switch node routes high / medium / normal. Someone who does not write code can move the threshold.",
    13.5, TEXT, B, line=1.35)
box(s, M + 6.08, 4.62, 5.75, 1.92, PANEL)
txt(s, M + 6.43, 4.88, 5.05, 0.32, "Mechanism lives in Python", 15, GREEN, B, bold=True)
txt(s, M + 6.43, 5.28, 5.05, 1.1,
    "Statistics, message formatting and throttling — where they are covered by 96 automated tests.",
    13.5, TEXT, B, line=1.35)
foot(s)

# ═══════════════════════════════════════════ 6 · live demo
s = slide()
bar(s, 0, 0, 0.10, HT, GREEN)
txt(s, M + 0.25, 1.55, 9.0, 0.42, "LIVE  ·  HOSTED, NOT LOCALHOST", 13, GREEN, B, bold=True)
txt(s, M + 0.25, 2.10, 10.5, 1.0, "See it decide", 54, TEXT, H, bold=True)
steps = [("Set up", "create an account, import 35 orders"),
         ("Normal purchase", "APPROVE"),
         ("Unusually large", "REVIEW — 53 sigma vs its own history"),
         ("Card-testing burst", "REVIEW — the rate, not the amounts"),
         ("Dashboard", "recall and precision, live against real labels")]
for i, (t, d) in enumerate(steps):
    y = 3.32 + i*0.62
    b = box(s, M + 0.25, y, 0.44, 0.44, PANEL2, GREEN, r=0.4)
    txt(s, M + 0.25, y + 0.10, 0.44, 0.26, str(i+1), 12.5, GREEN, B, bold=True, align=PP_ALIGN.CENTER)
    txt(s, M + 0.92, y + 0.03, 3.3, 0.32, t, 15, TEXT, B, bold=True)
    txt(s, M + 4.35, y + 0.05, 7.0, 0.32, d, 13.5, DIM, B)
bx = M + 8.6
for label, path, col in [("Checkout", "/checkout", CYAN), ("Dashboard", "/dashboard", CYAN)]:
    c, cwid = chip(s, bx, 2.35, label, col, 1.5, 12)
    link(c, URL + path)
    bx += 1.66
foot(s)

# ═══════════════════════════════════════════ 7 · results
s = slide()
title(s, "Measured against real fraud labels",
      "3,000 real transactions containing 88 real frauds", "results")
for i, (v, l, c) in enumerate([("34.1%", "of real fraud caught", GREEN),
                               ("30.0%", "precision at the real base rate", GREEN),
                               ("4", "false alarms per 3,000 orders", TEXT),
                               ("0.008 ms", "added to checkout", TEXT)]):
    x = M + i*3.0
    box(s, x, 2.52, 2.75, 1.6, PANEL)
    txt(s, x + 0.28, 2.76, 2.25, 0.6, v, 30, c, H, bold=True)
    txt(s, x + 0.28, 3.42, 2.25, 0.55, l, 11, DIM, B, line=1.2)
txt(s, M, 4.42, 5.6, 0.36, "Confusion matrix", 16, TEXT, H, bold=True)
cells = [("30", "caught", GREEN), ("58", "missed", RED),
         ("4", "false alarms", AMBER), ("2,908", "correctly ignored", DIM)]
for i, (v, l, c) in enumerate(cells):
    cx = M + (i % 2) * 2.85
    cy = 4.92 + (i // 2) * 0.86
    box(s, cx, cy, 2.6, 0.72, PANEL2)
    txt(s, cx + 0.2, cy + 0.12, 1.1, 0.4, v, 18, c, H, bold=True)
    txt(s, cx + 1.25, cy + 0.22, 1.25, 0.3, l, 10.5, DIM, B)
box(s, M + 6.3, 4.42, 5.53, 2.16, PANEL, BLUE, lw=1.25)
txt(s, M + 6.65, 4.66, 4.85, 0.32, "Why two precision figures", 14.5, BLUE, B, bold=True)
txt(s, M + 6.65, 5.06, 4.85, 1.4,
    "The demo stream over-samples fraud about 17× so a demo is not 96 minutes long. "
    "Precision depends on class balance; recall does not.\n"
    "30.0% is rescaled to the real 0.173% rate — that is the number to quote.",
    12.5, TEXT, B, line=1.32, space=4)
foot(s)

# ═══════════════════════════════════════════ 8 · the policy experiment
s = slide()
title(s, "Then I measured the alerting policy",
      "Same stream, same labels, three ways of deciding when to escalate", "the experiment")
cards = [("One signal", "classes 6–9", "34.1%", "recall", "17.7%", "precision", DIM,
          "Amount, velocity or the model — any one alerts."),
         ("Two signals", "the obvious fix", "0%", "recall", "0%", "precision", RED,
          "Catches nothing. The detectors overlap on one transaction and it was legitimate."),
         ("Model first", "what ships", "34.1%", "recall", "30.0%", "precision", GREEN,
          "The model must flag it. The others only raise it to high.")]
cwid, g = 3.78, 0.25
x = M
for name, tag, r1, l1, r2, l2, col, note in cards:
    box(s, x, 2.55, cwid, 3.42, PANEL, col, lw=1.5 if col != DIM else 1.0)
    txt(s, x + 0.3, 2.80, cwid - 0.6, 0.34, name, 17, col if col != DIM else TEXT, B, bold=True)
    txt(s, x + 0.3, 3.18, cwid - 0.6, 0.28, tag.upper(), 10.5, DIM, B, bold=True)
    txt(s, x + 0.3, 3.66, 1.6, 0.46, r1, 25, col if col != DIM else TEXT, H, bold=True)
    txt(s, x + 0.3, 4.14, 1.6, 0.26, l1, 10.5, DIM, B)
    txt(s, x + 1.98, 3.66, 1.6, 0.46, r2, 25, col if col != DIM else TEXT, H, bold=True)
    txt(s, x + 1.98, 4.14, 1.6, 0.26, l2, 10.5, DIM, B)
    txt(s, x + 0.3, 4.66, cwid - 0.6, 1.1, note, 12.5, TEXT, B, line=1.35)
    x += cwid + g
box(s, M, 6.20, CW, 0.66, PANEL2)
txt(s, M + 0.35, 6.36, CW - 0.7, 0.36,
    "34 model  +  5 amount  −  38 total  =  1 overlap  —  and it was not fraud.",
    15, CYAN, "Consolas", bold=True)
foot(s)

# ═══════════════════════════════════════════ 9 · four for four
s = slide()
title(s, "Four times the obvious answer was wrong",
      "Each was found by measuring something I had assumed", "the result")
rows = [("4", "Apply machine learning", "0.20% recall — worse than a single z-score"),
        ("7", "Per-account baselines detect more", "No detection gain; exposed a calibration bug"),
        ("9", "Combining signals is safer", "Precision 30.0% → 17.7%, zero extra catches"),
        ("10", "Require two signals to agree", "Recall 34.1% → 0%")]
txt(s, M + 0.32, 2.48, 0.8, 0.28, "CLASS", 10.5, DIM, B, bold=True)
txt(s, M + 1.5, 2.48, 4.6, 0.28, "WHAT SEEMED OBVIOUS", 10.5, DIM, B, bold=True)
txt(s, M + 6.4, 2.48, 5.4, 0.28, "WHAT THE MEASUREMENT SAID", 10.5, DIM, B, bold=True)
for i, (n, a, b) in enumerate(rows):
    y = 2.88 + i*0.86
    box(s, M, y, CW, 0.74, PANEL if i % 2 == 0 else PANEL2)
    txt(s, M + 0.32, y + 0.20, 0.8, 0.36, n, 17, RED, H, bold=True)
    txt(s, M + 1.5, y + 0.23, 4.7, 0.32, a, 14, TEXT, B)
    txt(s, M + 6.4, y + 0.23, 5.2, 0.32, b, 14, TEXT, B, bold=True)
txt(s, M, 6.42, CW, 0.42,
    "The detector is almost a byproduct. The measurements are the project.",
    18, CYAN, H, bold=True)

# ═══════════════════════════════════════════ 10 · it's live
s = slide()
bar(s, 0, 0, 0.10, HT, CYAN)
txt(s, M + 0.25, 1.85, 9.0, 0.42, "DEPLOYED  ·  OPEN SOURCE", 13, CYAN, B, bold=True)
txt(s, M + 0.25, 2.38, 10.5, 1.0, "It's live", 58, TEXT, H, bold=True)
txt(s, M + 0.25, 3.55, 8.6, 0.44,
    "Hosted on Render, deployed from GitHub. Click any of these.", 16, DIM, B)
btns = [("Landing", URL + "/"), ("Set up", URL + "/setup"),
        ("Checkout", URL + "/checkout"), ("Dashboard", URL + "/dashboard")]
bw, bg2 = 2.72, 0.28
x = M + 0.25
for label, u in btns:
    b = box(s, x, 4.28, bw, 0.86, PANEL, CYAN, lw=1.5)
    tf = b.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = label
    r.font.size = Pt(15); r.font.bold = True; r.font.color.rgb = CYAN; r.font.name = B
    link(b, u)
    x += bw + bg2
g = box(s, M + 0.25, 5.42, 5.6, 0.78, PANEL2, DIM, lw=1.0)
tf = g.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
r = p.add_run(); r.text = "Source code on GitHub"
r.font.size = Pt(14); r.font.bold = True; r.font.color.rgb = TEXT; r.font.name = B
link(g, REPO)
txt(s, M + 0.25, 6.55, 10.0, 0.32,
    "Abed Gazi  ·  2132538642  ·  CSE 299, Section 13", 12, DIM, B)

# ═══════════════════════════════════════════ 11 · thanks
s = slide()
bar(s, 0, 0, 0.10, HT, BLUE)
txt(s, M + 0.25, 2.55, 10.0, 1.0, "Thank you", 54, TEXT, H, bold=True)
txt(s, M + 0.25, 3.72, 8.0, 0.44, "Questions?", 20, CYAN, B)
c, _ = chip(s, M + 0.25, 4.55, "▶  sentrywatch.onrender.com", CYAN, 3.0, 12.5)
link(c, URL)
txt(s, M + 0.25, 5.35, 9.0, 0.9,
    "Abed Gazi  ·  2132538642\nCSE 299, Section 13  ·  Real-Time Anomaly and Fraud Detection Pipeline",
    13, DIM, B, line=1.4)

prs.save("SentryWatch_CSE299.pptx")
print(f"saved · {len(prs.slides.__iter__.__self__._sldIdLst)} slides")
