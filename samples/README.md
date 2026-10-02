# Sample data (fictional)

Everything in this folder is **made up**. "Northwind Robotics", "Maya Lindqvist" and every other person, company, product, school and number here are fictional; any resemblance to real ones is coincidental. The repo is public, so real CVs never go here (they live in the gitignored `docs/applications/`).

## `demo_application/`

A complete application for a mock interview: Machine Learning Engineer, Perception at Northwind Robotics.

| File | Document kind | Required |
|---|---|---|
| `jd.md` | job description (`jd`) | yes |
| `cv.md` | CV (`cv`) | yes |
| `cover_letter.md` | cover letter (`cover_letter`) | no |
| `company_notes.md` | company notes (`company_notes`) | no |

The CV deliberately has gaps against the JD (no production C++ / embedded deployment, little 3D / LiDAR work, no ROS 2) so the interviewer has something real to probe.

How it is used:

- **Demo and manual testing:** paste the files into the Applications page (or upload them after printing to PDF) to try the app without exposing personal data.
- **Tests:** `tests/test_applications.py` loads all four files with `create_application` to make sure the sample stays valid (within the size limits, all kinds present).
- **Prompt lab:** the `lab/` scripts (later PR) use it as a fixed, reproducible application.
