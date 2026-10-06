# Evaluation report

Gold labels: **synthetic ground truth**, covering 2252 of 2320 stored clauses.

> **Read this first.** The synthetic data is generated from templates that share vocabulary with the keyword and lexicon methods, so these numbers are an upper bound, not an estimate of performance on real student comments. Re-run with `--labels` on a hand-labelled sample of real feedback (`export-sample`) before quoting accuracy.

## 1. Theme classification (topic modeling)

| Method | Run | Clauses | Accuracy | Macro F1 | Weighted F1 | Purity | Topics | Coherence (NPMI) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| keyword | 1 | 2252 | 0.934 | 0.957 | 0.961 | 0.958 | 9 | n/a |
| lda | 2 | 2252 | 0.317 | 0.262 | 0.276 | 0.412 | 10 | -0.308 |

_Purity: share of clauses that fall in the majority gold theme of their topic. Coherence: mean NPMI of each topic's top keywords over all clauses (only meaningful for learned topics: LDA, BERTopic)._

### Best theme method: keyword (run 1)

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| pace | 1.000 | 0.892 | 0.943 | 295 |
| clarity | 1.000 | 0.998 | 0.999 | 402 |
| support | 1.000 | 1.000 | 1.000 | 269 |
| workload | 1.000 | 0.985 | 0.992 | 265 |
| assessment | 1.000 | 0.808 | 0.894 | 286 |
| engagement | 1.000 | 0.948 | 0.973 | 328 |
| resources | 1.000 | 0.826 | 0.905 | 213 |
| overall | 0.918 | 0.985 | 0.950 | 194 |

Confusion matrix:

| gold \ predicted | pace | clarit | suppor | worklo | assess | engage | resour | overal | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pace | 263 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 32 |
| clarity | 0 | 401 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| support | 0 | 0 | 269 | 0 | 0 | 0 | 0 | 0 | 0 |
| workload | 0 | 0 | 0 | 261 | 0 | 0 | 0 | 0 | 4 |
| assessment | 0 | 0 | 0 | 0 | 231 | 0 | 0 | 0 | 55 |
| engagement | 0 | 0 | 0 | 0 | 0 | 311 | 0 | 17 | 0 |
| resources | 0 | 0 | 0 | 0 | 0 | 0 | 176 | 0 | 37 |
| overall | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 191 | 3 |

## 2. Sentiment analysis

| Method | Run | Clauses | Accuracy | Macro F1 | Weighted F1 | Rating correlation (Spearman) |
|---|---:|---:|---:|---:|---:|---:|
| lexicon | 1 | 2252 | 0.969 | 0.938 | 0.968 | 0.230 (n=1113) |

_Rating correlation compares each comment's mean sentiment score with the 1-5 star rating the same student gave. It needs no hand labels, so it is a useful check on real data._

### Best sentiment method: lexicon (run 1)

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| positive | 0.950 | 0.993 | 0.971 | 1147 |
| neutral | 0.949 | 0.758 | 0.843 | 248 |
| negative | 1.000 | 0.998 | 0.999 | 857 |

Confusion matrix:

| gold \ predicted | positi | neutra | negati |
|---|---:|---:|---:|
| positive | 1139 | 8 | 0 |
| neutral | 60 | 188 | 0 |
| negative | 0 | 2 | 855 |

## 3. Limitations

- Clause alignment between ground truth and stored clauses is by text similarity; clauses that could not be matched are excluded rather than guessed.
- Mixed or hedged clauses ("some sessions were interesting") are the main source of sentiment errors.
- Themes are single-label per clause; a clause that touches two themes is scored on one.
