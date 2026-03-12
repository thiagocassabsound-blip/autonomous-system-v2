# Important Decisions
- **Decision**: Centralize all numeric formatting in the Controller (Python) layer instead of the View (Jinja2).
- **Rationale**: Prevents 500 errors caused by Jinja2 filter crashes on unexpected data types (e.g. string "None").
- **Decision**: Use Absolute Path Anchoring for all persistence files.
- **Rationale**: Ensures environmental independence and fixes "Persistence read failed" errors in different runtime contexts.
