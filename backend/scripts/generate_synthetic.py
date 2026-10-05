"""Generate a synthetic course-feedback dataset with ground-truth labels.

Outputs (default: ../data/synthetic):
  semesters.csv, faculty.csv, courses.csv, offerings.csv   reference data
  feedback_raw.csv     what an evaluation form export looks like (raw student ids, PII)
  ground_truth.csv     per-clause theme + sentiment labels, plus the PII strings that
                       were injected, keyed by response_ref. Used in Phase 6 to
                       measure topic/sentiment accuracy and in tests to prove the
                       scrubber removed every injected identifier.

Each faculty member has a hidden quality score per theme that drifts across
semesters, so later phases have real trends to detect.
"""
import argparse
import csv
import json
import math
import random
from pathlib import Path

SEMESTERS = ["2024-Autumn", "2025-Spring", "2025-Autumn", "2026-Spring"]
SEM_DATES = {"2024-Autumn": (2024, [9, 10, 11]), "2025-Spring": (2025, [2, 3, 4]),
             "2025-Autumn": (2025, [9, 10, 11]), "2026-Spring": (2026, [2, 3, 4])}

FACULTY = [("F01", "Dr. Anita Sharma", "CSE"), ("F02", "Prof. Rajesh Kulkarni", "CSE"),
           ("F03", "Dr. Meera Iyer", "CSE"), ("F04", "Mr. Vikram Sandhu", "ECE"),
           ("F05", "Dr. Pooja Malhotra", "ECE"), ("F06", "Prof. Harpreet Bedi", "MATH")]
COURSES = [("CSE201", "Data Structures", "CSE"), ("CSE305", "Operating Systems", "CSE"),
           ("CSE340", "Machine Learning", "CSE"), ("CSE310", "Database Systems", "CSE"),
           ("ECE210", "Digital Electronics", "ECE"), ("ECE330", "Signal Processing", "ECE"),
           ("MTH202", "Discrete Mathematics", "MATH"), ("MTH301", "Probability and Statistics", "MATH")]
TEACHER = {"CSE201": "F01", "CSE305": "F02", "CSE340": "F03", "CSE310": "F01",
           "ECE210": "F04", "ECE330": "F05", "MTH202": "F06", "MTH301": "F06"}
TEACHER_SWITCH = {("CSE310", "2025-Autumn"): "F02", ("CSE310", "2026-Spring"): "F02"}
SMALL_OFFERING = ("MTH301", "2026-Spring", 7, 3)   # enrolled 7, only 3 respond -> must be suppressed

THEMES = ["pace", "clarity", "support", "workload", "assessment", "engagement", "resources"]
THEME_WEIGHT = {"pace": 1.0, "clarity": 1.6, "support": 1.0, "workload": 1.0,
                "assessment": 1.0, "engagement": 1.2, "resources": 0.8}

# (faculty, theme) -> (starting quality, change per semester): gives visible trends
TRENDS = {("F02", "pace"): (-0.7, 0.35), ("F03", "workload"): (0.5, -0.4),
          ("F01", "support"): (0.3, 0.2), ("F04", "resources"): (-0.5, 0.3)}

T = {
 "pace": {
  "pos": ["The pace of the course was just right.", "Lectures moved at a comfortable speed and we never felt rushed.",
          "Topics were covered in a well paced manner.", "Good balance between depth and speed."],
  "neg": ["The syllabus was covered way too fast.", "Lectures felt rushed and it was hard to keep up.",
          "The pace was too slow and classes dragged on.", "We skipped through important topics in a hurry."],
  "neu": ["The pace was okay, neither fast nor slow.", "Speed of teaching was average."]},
 "clarity": {
  "pos": ["Concepts were explained very clearly.", "Examples made difficult topics easy to understand.",
          "The explanations were clear and well structured.", "Every doubt got cleared through simple examples."],
  "neg": ["Explanations were confusing and hard to follow.", "Many concepts were not explained properly.",
          "The teaching lacked clarity and examples.", "I could not understand most of the derivations."],
  "neu": ["Some topics were clear and some were not.", "Clarity of explanation was average."]},
 "support": {
  "pos": ["The faculty was very approachable and answered all our doubts.", "Always available for doubt clearing after class.",
          "Very supportive and encouraging towards students.", "Quick replies to our queries and helpful guidance."],
  "neg": ["The faculty was not approachable when we had doubts.", "Doubts were often ignored or brushed aside.",
          "There was no support for students who were struggling.", "Emails were never answered."],
  "neu": ["Support was available sometimes.", "Office hours existed but were rarely used."]},
 "workload": {
  "pos": ["The assignment load was manageable.", "Workload was balanced across the semester.",
          "A reasonable number of assignments and projects."],
  "neg": ["Too many assignments with very tight deadlines.", "The workload was overwhelming alongside other courses.",
          "Projects took up far too much time.", "Deadlines were piled up one after another."],
  "neu": ["Workload was average.", "A normal amount of assignments."]},
 "assessment": {
  "pos": ["Exams were fair and matched what was taught.", "Grading was transparent and feedback was timely.",
          "Quizzes helped us track our progress."],
  "neg": ["Exam questions were out of syllabus.", "Grading felt unfair and marks were not explained.",
          "Results were delayed and there was no feedback on answers.", "Evaluation criteria were never clear."],
  "neu": ["Exams were of moderate difficulty.", "The evaluation pattern was standard."]},
 "engagement": {
  "pos": ["Classes were interactive and interesting.", "The sessions were engaging with lots of discussion.",
          "Real world examples kept the class lively."],
  "neg": ["Classes were boring and monotonous.", "Lectures were just slide reading with no interaction.",
          "It was hard to stay interested during sessions.", "There was no discussion or activity in class."],
  "neu": ["Some sessions were interesting.", "Engagement was average."]},
 "resources": {
  "pos": ["Notes and slides shared were very useful.", "Good reference material and lab resources were provided.",
          "Recorded lectures and study material helped a lot."],
  "neg": ["Study material was outdated.", "Slides were not shared on time.",
          "Lab systems were poor and resources insufficient.", "No proper reference books were suggested."],
  "neu": ["Materials were okay.", "Resources were adequate."]},
 "overall": {
  "pos": ["Overall a great course.", "Would recommend this course to others.", "Really enjoyed this subject."],
  "neg": ["Overall I am not satisfied with this course.", "Would not recommend it.", "This course needs a lot of improvement."],
  "neu": ["Overall it was an average course."]},
}

FIRST = ["Aarav", "Vivaan", "Ishita", "Kavya", "Rohan", "Simran", "Tanvi", "Harsh", "Gurpreet", "Naman", "Diya", "Arjun"]
LAST = ["Verma", "Gill", "Chopra", "Bansal", "Arora", "Khanna", "Thakur", "Mehra"]


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def quality(rng_base, fac, theme, sem_idx):
    if (fac, theme) in TRENDS:
        start, step = TRENDS[(fac, theme)]
        return max(-1, min(1, start + step * sem_idx))
    return rng_base[(fac, theme)]


def lower_first(s):
    return s if s.startswith("I ") else s[0].lower() + s[1:]


def make_pii(rng):
    first, last = rng.choice(FIRST), rng.choice(LAST)
    reg = f"124{rng.randint(0, 99999):05d}"
    kind = rng.choice(["email", "phone", "intro", "regards", "friend"])
    if kind == "email":
        email = f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@gmail.com"
        return f"You can contact me at {email}.", [email]
    if kind == "phone":
        ph = f"9{rng.randint(0, 9999):04d} {rng.randint(0, 99999):05d}"
        return f"My number is {ph}.", [ph.replace(" ", ""), ph]
    if kind == "intro":
        return f"I am {first} {last} from section K22AB.", [f"{first} {last}", "K22AB"]
    if kind == "regards":
        return f"Regards, {first} {last} {reg}", [f"{first} {last}", reg]
    return f"My friend {first} also felt the same.", [first]


def build_comment(rng, fac, sem_idx, base_q, fac_name):
    n = rng.choices([1, 2, 3], [0.35, 0.45, 0.20])[0]
    weights = [THEME_WEIGHT[t] * (1 + 0.8 * abs(quality(base_q, fac, t, sem_idx))) for t in THEMES]
    themes = []
    while len(themes) < n:
        t = rng.choices(THEMES, weights)[0]
        if t not in themes:
            themes.append(t)
    pieces, qs = [], []
    for t in themes:
        q = quality(base_q, fac, t, sem_idx)
        qs.append(q)
        p_neu = 0.12
        p_pos = (1 - p_neu) * sigmoid(2.5 * q)
        pol = rng.choices(["pos", "neg", "neu"], [p_pos, 1 - p_neu - p_pos, p_neu])[0]
        pieces.append({"text": rng.choice(T[t][pol]), "theme": t, "sentiment": pol})
    if rng.random() < 0.15:
        q = sum(qs) / len(qs)
        pol = rng.choices(["pos", "neg", "neu"], [sigmoid(2.5 * q) * 0.88, (1 - sigmoid(2.5 * q)) * 0.88, 0.12])[0]
        pieces.append({"text": rng.choice(T["overall"][pol]), "theme": "overall", "sentiment": pol})
    if rng.random() < 0.10:
        surname = fac_name.split()[-1]
        pieces.append({"text": f"Thanks to {fac_name.split()[0]} {surname}.", "theme": "none", "sentiment": "neu"})

    # join clauses; contrast-join adjacent opposite polarities half the time
    out, i = [], 0
    while i < len(pieces):
        a = pieces[i]
        if i + 1 < len(pieces) and {a["sentiment"], pieces[i + 1]["sentiment"]} == {"pos", "neg"} and rng.random() < 0.5:
            out.append(f"{a['text'].rstrip('.')}, but {lower_first(pieces[i + 1]['text'])}")
            i += 2
        else:
            out.append(a["text"])
            i += 1
    text = " ".join(out)

    # surface noise
    if rng.random() < 0.25:
        text = text.rstrip(".")
    if rng.random() < 0.08:
        text = text.lower()
    if rng.random() < 0.06:
        words = text.split()
        idx = [k for k, w in enumerate(words) if len(w) > 4 and w.isalpha()]
        if idx:
            k = rng.choice(idx)
            w = words[k]
            j = rng.randint(1, len(w) - 3)
            words[k] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
            text = " ".join(words)

    pii = []
    if rng.random() < 0.07:
        sentence, pii = make_pii(rng)
        text = f"{text} {sentence}"
    return text, pieces, pii, sum(qs) / len(qs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "data" / "synthetic"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    base_q = {(f[0], t): rng.uniform(-0.4, 0.6) for f in FACULTY for t in THEMES}
    pool = [f"124{rng.randint(0, 99999):05d}" for _ in range(420)]
    names = {f[0]: f[1] for f in FACULTY}

    def write(name, header, rows):
        with open(out / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    write("semesters.csv", ["label", "sort_order"], [(s, i) for i, s in enumerate(SEMESTERS)])
    write("faculty.csv", ["faculty_id", "name", "department"], FACULTY)
    write("courses.csv", ["course_code", "title", "department"], COURSES)

    offerings, raw, truth, ref = [], [], [], 0
    for si, sem in enumerate(SEMESTERS):
        year, months = SEM_DATES[sem]
        for code, _, _ in COURSES:
            fac = TEACHER_SWITCH.get((code, sem), TEACHER[code])
            enrolled = rng.randint(35, 70)
            n_resp = int(enrolled * rng.uniform(0.55, 0.85))
            if (code, sem) == SMALL_OFFERING[:2]:
                enrolled, n_resp = SMALL_OFFERING[2], SMALL_OFFERING[3]
            offerings.append((code, fac, sem, enrolled))
            for sid in rng.sample(pool, enrolled)[:n_resp]:
                ref += 1
                rid = f"R{ref:06d}"
                text, pieces, pii, mq = build_comment(rng, fac, si, base_q, names[fac])
                rating = max(1, min(5, round(3 + 1.8 * mq + rng.gauss(0, 0.8))))
                date = f"{year}-{rng.choice(months):02d}-{rng.randint(1, 28):02d}"
                raw.append([rid, sid, code, fac, sem, rating, date, text])
                truth.append([rid, code, fac, sem, json.dumps(pieces), "|".join(pii)])

    write("offerings.csv", ["course_code", "faculty_id", "semester", "enrolled"], offerings)

    # messy rows so the pipeline's validation is exercised
    for k in range(4):                                  # re-submissions (duplicates)
        src = rng.choice(raw)
        ref += 1
        raw.append([f"R{ref:06d}", src[1], src[2], src[3], src[4], src[5], src[6], "Submitted again by mistake, please ignore."])
    for k in range(3):                                  # blank comments
        src = rng.choice(raw)
        ref += 1
        raw.append([f"R{ref:06d}", f"124{rng.randint(0, 99999):05d}", src[2], src[3], src[4], 4, src[6], ""])
    for k in range(2):                                  # too short
        src = rng.choice(raw)
        ref += 1
        raw.append([f"R{ref:06d}", f"124{rng.randint(0, 99999):05d}", src[2], src[3], src[4], 3, src[6], "ok"])
    for k in range(2):                                  # unknown course
        ref += 1
        raw.append([f"R{ref:06d}", f"124{rng.randint(0, 99999):05d}", "XXX999", "F01", "2025-Spring", 3, "2025-03-04", "No such course exists here."])
    rng.shuffle(raw)

    write("feedback_raw.csv", ["response_ref", "student_id", "course_code", "faculty_id", "semester", "rating", "submitted_on", "comment"], raw)
    write("ground_truth.csv", ["response_ref", "course_code", "faculty_id", "semester", "clauses_json", "pii_strings"], truth)
    print(f"Wrote {len(raw)} raw rows ({len(truth)} clean) to {out}")


if __name__ == "__main__":
    main()
