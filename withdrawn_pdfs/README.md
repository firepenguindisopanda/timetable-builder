# Withdrawn timetables

Resources UWI has published in the past and has since removed from
`finder.xml`. **They cannot be re-downloaded**, which is why they are kept
here rather than deleted.

This directory is deliberately a sibling of `downloaded_pdfs/` rather than a
subdirectory of it. `validate_corpus.py` and `database.cli load` both scan
`downloaded_pdfs` and would otherwise read these files, which is exactly the
failure that put them here.

## Why they matter

`sync pull` walks the links in the current `finder.xml`, so a resource UWI
withdraws is never re-fetched and never deleted. It simply stays on disk,
frozen at the last version pulled, and the next load reads it as though it
were still published.

On the 14 August 2026 republish that meant 1,638 PDFs on disk against a
1,630-entry registry. The eight strays still carried the previous semester
label (`Semester_1_TT2026_2027` against the new `Semester_I_2026_2027`), and
`validate_corpus.py` failed on their course codes being absent from the
registry — which is the gate doing its job.

## What is here

### Withdrawn between the publications of 14 August and 21 August 2026

| File | Was |
|---|---|
| `m1668.pdf` | COMS 2202, Principles of Mass Communication |
| `m2413.pdf` | LING 2006, Speech & Hearing Science |
| `m2439.pdf` | LING 6105, Principles & Approaches in TESOL |
| `m2480.pdf` | LITS 6007, Modern Cultural & Critical Theory |
| `m2485.pdf` | LITS 6201, Women's Writing & Feminist Theory |
| `m34166.pdf` | LING 6804, Language Acquisition in Creole Contexts |
| `m69565.pdf` | CLL DELE PREP, CLL DELE PREP |
| `staff/s105482.pdf` | RAMSAROOP, Rabindranath |
| `staff/s105939.pdf` | WHITTIER, Simone |
| `staff/s97914.pdf` | HAQUE, Shirin |

None of these is a rename. The same republish added nine module resources
(COMP 6104, COMP 6801, LITS 6005, LITS 6691, MGMT 8014 and GEOG 0101-0104)
and one staff resource, and no added course code matches a withdrawn one.
`m2479.pdf`/`m2480.pdf` and `m2413.pdf`/`m62936.pdf` share a department and
faculty id and look like re-keyings, but they carry different courses.

### Withdrawn between the publications of 6 August and 14 August 2026

| File | Was |
|---|---|
| `m110817.pdf` | BEDP 22XX, Teaching Mathematics I |
| `m111714.pdf` | EDTL 12**, Clinical Teaching: Theory and Practice of Teaching |
| `m2417.pdf` | LING 2304, Language Situations in the Modern World |
| `m62787.pdf` | MENG 6509, Introduction to Operations Research |
| `m7106.pdf` | PLAN 6011, Planning in the Coastal Zone |
| `staff/s105461.pdf` | CLARKE, Grace |
| `staff/s89900.pdf` | BALWANT, Paul |
| `staff/s99429.pdf` | JOHN, Kara |

`EDMA 11**` (`m111688.pdf`) is *not* here. It was renamed to `EDMA 1142` in
the same republish, so its resource is still published and was re-downloaded
normally.

The sessions these files produced are not lost either way: each batch belongs
to the last publication that carried it — publication 1 for the 6-to-14 August
withdrawals, publication 2 for the 14-to-21 August ones — and every publication
stays queryable in the warehouse.
