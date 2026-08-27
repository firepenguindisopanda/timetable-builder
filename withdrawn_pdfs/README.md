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

### Withdrawn between the publications of 21 August and 27 August 2026

| File | Was |
|---|---|
| `staff/s104423.pdf` | RAGBIR, Adrianna |
| `staff/s104424.pdf` | HARRIS, Shemwyn |
| `staff/s98195.pdf` | GUNAKALA, Rao |

All three are `staff` resources from one department, and all three had been
published since publication 1. None still teaches in publication 4: they held
1, 6 and 2 sessions respectively in publication 3 and none in 4, so these are
people leaving the timetable rather than a staff page being withdrawn from
under someone still teaching.

**This batch is the reason neither existing check is sufficient.** The same
republish added 13 resources while removing these 3, so the corpus stood at
1,643 against a 1,640-entry registry — a mismatch, but one that an addition of
exactly 3 would have cancelled out silently.

**A withdrawn `staff` PDF is invisible to the gate, and a withdrawn `course`
PDF is not.** This asymmetry is the part worth knowing, and it is why the two
earlier batches were caught by `validate_corpus.py` while this one was not. A
withdrawn course PDF carries a course code that is no longer in the registry,
so the gate's unknown-code check fails and exits 1. A withdrawn staff PDF
carries the *courses that lecturer taught* — `s104424.pdf` yields six entries
across `MATH 1115` and `MATH 1194` — and both are still published, so every
code in it resolves cleanly and the gate sees nothing wrong. The staff stray is
invisible because it is plausible, not because it is empty.

Loading `s104424.pdf` into publication 4 would have done two things:

- **Re-attached a departed lecturer.** Five of its six classes still exist in
  publication 4, so they would merge rather than duplicate — but each would
  gain HARRIS,Shemwyn as staff. Publication 4 currently attributes those
  MATH 1115 classes to ALEXANDER,Rhea, DYAANAND,Kiran and LATCHMAN,Gyshan, and
  has no link to HARRIS at all.
- **Resurrected a class that moved.** The MATH 1194 Lab ran Monday 13:00-15:00
  in publication 3 and runs Monday 16:00-18:00 in publication 4. The stale file
  would have reinserted the 13:00 sitting *alongside* the real 16:00 one, which
  is precisely the "moved classes insert alongside their old rows" failure the
  stale-registry rule in CLAUDE.md describes — reached here through a stale
  *file* rather than a stale registry. A student would see two labs and no way
  to tell which is real, and the stale entry would also raise the session's
  cross-confirmation count, making the phantom look better attested.

They were found by diffing the registry's `link=` attributes against the
filenames on disk, which is the check STATUS.md now prescribes. That diff is
the only one of the three that catches a staff withdrawal.

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
withdrawals, publication 2 for the 14-to-21 August ones, publication 3 for the
21-to-27 August ones — and every publication stays queryable in the warehouse.
