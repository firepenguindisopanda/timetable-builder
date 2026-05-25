# Extraction Comparison Report: Rule-Based vs LLM
Generated: 2026-05-24 21:22:19
PDFs analyzed: 10

## Methodology

- **Rule-based**: Deterministic extraction using `pdfplumber` geometry + keyword parsing
- **LLM**: NVIDIA NIM vision API (Llama 3.2 90B Vision) analyzing page image
- **Matching**: Entries matched by same day + nearest start time (within 90 min tolerance)
- **Fields compared**: start_time, end_time, room, staff, activity_type

## Errors
- `m36307.pdf`: LLM extraction failed: NVIDIA NIM API request timed out

## Key Findings

### 1. Systematic Time Differences

- **Average rule-based block duration**: 0 min (0.0 hours)
- **Average LLM block duration**: 0 min (0.0 hours)
- **The LLM consistently extracts only 1-hour slots** instead of the full class block duration (2-3 hours each)

### 2. Missing/Hallucinated Entries

- **Rule-only entries** (missed by LLM): 12
- **LLM-only entries** (potential hallucinations): 8
- The LLM frequently misses entries or adds entries on days not in the original timetable

### 3. Field-Level Accuracy

- **Matched entries with at least one field disagreement**: 15
- Room codes often differ (LLM appends direction suffixes like 'W', rule-based strips them)
- Activity types are occasionally mismatched

## Aggregate Summary

| Metric | Value |
|--------|-------|
| Total rule-based entries | 27 |
| Total LLM entries | 23 |
| Fuzzy-matched entries | 15 |
| Rule-only entries | 12 |
| LLM-only entries | 8 |
| Matched entries with disagreements | 15 |

## Per-PDF Summary

| PDF | Rule | LLM | Matched | Only Rule | Only LLM | Disagreements | Match Rate |
|-----|------|-----|---------|-----------|----------|---------------|------------|
| `m17329.pdf` | 3 | 4 | 3 | 0 | 1 | 3 | 75.0% |
| `m1266.pdf` | 2 | 2 | 0 | 2 | 2 | 0 | 0.0% |
| `m55716.pdf` | 4 | 4 | 2 | 2 | 2 | 2 | 50.0% |
| `m2215.pdf` | 1 | 1 | 0 | 1 | 1 | 0 | 0.0% |
| `m2143.pdf` | 2 | 2 | 2 | 0 | 0 | 2 | 100.0% |
| `m2080.pdf` | 8 | 4 | 4 | 4 | 0 | 4 | 50.0% |
| `m1764.pdf` | 2 | 2 | 1 | 1 | 1 | 1 | 50.0% |
| `m55714.pdf` | 4 | 3 | 3 | 1 | 0 | 3 | 75.0% |
| `m1707.pdf` | 1 | 1 | 0 | 1 | 1 | 0 | 0.0% |

## Field Disagreement Details

### m17329.pdf (Course timetable - MATH 1115, Fundamental Mathematics for the General Science I (Wks SUM W1-SUM W7))

- **Monday** rule=`01:00 PM` llm=`01:00PM` (diff=0 min)
  - `start_time`: rule=`01:00 PM` vs llm=`01:00PM`
  - `end_time`: rule=`03:00 PM` vs llm=`02:00PM`
  - `room`: rule=`FST 114 SUM W1- 1115` vs llm=`FST 114`
- **Tuesday** rule=`12:00 PM` llm=`01:00PM` (diff=60 min)
  - `start_time`: rule=`12:00 PM` vs llm=`01:00PM`
  - `end_time`: rule=`02:00 PM` vs llm=`02:00PM`
- **Thursday** rule=`12:00 PM` llm=`01:00PM` (diff=60 min)
  - `start_time`: rule=`12:00 PM` vs llm=`01:00PM`
  - `end_time`: rule=`02:00 PM` vs llm=`02:00PM`

### m55716.pdf (Course timetable - COMP 1601, Computer Programming I (Wks SUM W1-SUM W7))

- **Monday** rule=`04:00 PM` llm=`04:00PM` (diff=0 min)
  - `start_time`: rule=`04:00 PM` vs llm=`04:00PM`
  - `end_time`: rule=`06:00 PM` vs llm=`05:00PM`
- **Friday** rule=`10:00 AM` llm=`09:00AM` (diff=60 min)
  - `start_time`: rule=`10:00 AM` vs llm=`09:00AM`
  - `end_time`: rule=`12:00 PM` vs llm=`10:00AM`

### m2143.pdf (Course timetable - GEOM 2030, Adjustment Computations I (Wks SUM W1-SUM W7))

- **Monday** rule=`03:00 PM` llm=`03:00PM` (diff=0 min)
  - `start_time`: rule=`03:00 PM` vs llm=`03:00PM`
  - `end_time`: rule=`05:00 PM` vs llm=`04:00PM`
- **Wednesday** rule=`03:00 PM` llm=`03:00PM` (diff=0 min)
  - `start_time`: rule=`03:00 PM` vs llm=`03:00PM`
  - `end_time`: rule=`05:00 PM` vs llm=`04:00PM`

### m2080.pdf (Course timetable - FOUN 1210, Science Medicine & Technology in Society (Wks SUM W1-SUM W7))

- **Monday** rule=`05:00 PM` llm=`05:00PM` (diff=0 min)
  - `start_time`: rule=`05:00 PM` vs llm=`05:00PM`
  - `end_time`: rule=`07:00 PM` vs llm=`06:00PM`
  - `room`: rule=`FHE SOE South Block Old Library SOE Section` vs llm=`FHE SOE South Block Old Library`
- **Monday** rule=`05:00 PM` llm=`06:00PM` (diff=60 min)
  - `start_time`: rule=`05:00 PM` vs llm=`06:00PM`
  - `end_time`: rule=`08:00 PM` vs llm=`07:00PM`
  - `room`: rule=`FHE SOE South Block Old Library SOE Section` vs llm=`FHE SOE 203; FHE SOE 204`
  - `activity_type`: rule=`Lecture` vs llm=`Tutorial`
- **Tuesday** rule=`05:00 PM` llm=`05:00PM` (diff=0 min)
  - `start_time`: rule=`05:00 PM` vs llm=`05:00PM`
  - `end_time`: rule=`07:00 PM` vs llm=`06:00PM`
  - `staff`: rule=`None` vs llm=`FOUN 1210`
- **Tuesday** rule=`07:00 PM` llm=`06:00PM` (diff=60 min)
  - `start_time`: rule=`07:00 PM` vs llm=`06:00PM`
  - `end_time`: rule=`08:00 PM` vs llm=`07:00PM`
  - `staff`: rule=`None` vs llm=`FOUN 1210`

### m1764.pdf (Course timetable - ECNG 1015, Intro. to Electrical Energy Systems (Wks SUM W1-SUM W7))

- **Wednesday** rule=`01:00 PM` llm=`01:00PM` (diff=0 min)
  - `start_time`: rule=`01:00 PM` vs llm=`01:00PM`
  - `end_time`: rule=`04:00 PM` vs llm=`02:00PM`

### m55714.pdf (Course timetable - COMP 1600, Introduction to Computer Concepts (Wks SUM W1-SUM W7))

- **Monday** rule=`08:00 AM` llm=`08:00AM` (diff=0 min)
  - `start_time`: rule=`08:00 AM` vs llm=`08:00AM`
  - `end_time`: rule=`10:00 AM` vs llm=`09:00AM`
- **Tuesday** rule=`08:00 AM` llm=`08:00AM` (diff=0 min)
  - `start_time`: rule=`08:00 AM` vs llm=`08:00AM`
  - `end_time`: rule=`10:00 AM` vs llm=`09:00AM`
- **Friday** rule=`03:00 PM` llm=`04:00PM` (diff=60 min)
  - `start_time`: rule=`03:00 PM` vs llm=`04:00PM`
  - `end_time`: rule=`04:00 PM` vs llm=`05:00PM`
  - `activity_type`: rule=`Lecture` vs llm=`Tutorial`

## Rule-Only Entries (missed by LLM)

### m1266.pdf (2 entries)

- Tuesday 04:00 PM-06:00 PM | Type: Lecture | Course: AGBU 2002 | Room: FFA | Weeks: None
- Thursday 04:00 PM-06:00 PM | Type: Lecture | Course: AGBU 2002 | Room: FFA | Weeks: None

### m55716.pdf (2 entries)

- Tuesday 10:00 AM-12:00 PM | Type: Lecture | Course: None | Room: FST | Weeks: None
- Thursday 11:00 AM-01:00 PM | Type: Lab | Course: COMP 1601 | Room: FST CSL1 W1-SUM 1601 | Weeks: SUM W1-SUM W6

### m2215.pdf (1 entries)

- Thursday 10:00 AM-01:00 PM | Type: Lecture | Course: GOVT 3023 | Room: FSS 100 | Weeks: SUM W1-SUM W7

### m2080.pdf (4 entries)

- Monday 07:00 PM-08:00 PM | Type: Tutorial | Course: FOUN 1210 | Room: FHE SOE South Block Old Library SOE Section | Weeks: SUM W1-SUM W7
- Thursday 05:00 PM-08:00 PM | Type: Lecture | Course: FOUN 1210 | Room: None | Weeks: SUM W1-SUM W6
- Thursday 05:00 PM-07:00 PM | Type: Lecture | Course: FOUN 1210 | Room: FST C3 | Weeks: None
- Thursday 07:00 PM-08:00 PM | Type: Tutorial | Course: FOUN 1210 | Room: FST C3 | Weeks: SUM W1-SUM W7

### m1764.pdf (1 entries)

- Friday 09:00 AM-12:00 PM | Type: Lecture | Course: ECNG 1015 | Room: ENG 11 | Weeks: SUM W1-SUM W7

### m55714.pdf (1 entries)

- Friday 04:00 PM-05:00 PM | Type: Tutorial | Course: COMP 1600 | Room: FST CSL1 | Weeks: SUM W1-SUM W6

### m1707.pdf (1 entries)

- Thursday 01:00 PM-04:00 PM | Type: Lecture | Course: CVNG 3002 | Room: ENG 10 | Weeks: SUM W1-SUM W7

## LLM-Only Entries (not in rule-based)

### m17329.pdf (1 entries)

- Wednesday 01:00PM-02:00PM | Type: Lab | Room: FST CSL1

### m1266.pdf (2 entries)

- Monday 06:00PM-07:00PM | Type: Lecture | Room: FFA W
- Thursday 06:00PM-07:00PM | Type: Lecture | Room: FFA W

### m55716.pdf (2 entries)

- Tuesday 08:00AM-09:00AM | Type: Lecture | Room: FST CSL1
- Thursday 03:00PM-04:00PM | Type: Lab | Room: FST CSL1

### m2215.pdf (1 entries)

- Thursday 01:00PM-02:00PM | Type: Lecture | Room: FSS 100 W

### m1764.pdf (1 entries)

- Friday 01:00PM-02:00PM | Type: Lecture | Room: ENG 11

### m1707.pdf (1 entries)

- Wednesday 01:00PM-02:00PM | Type: Lecture | Room: ENG 10

---
*Report generated by compare_extractions.py*