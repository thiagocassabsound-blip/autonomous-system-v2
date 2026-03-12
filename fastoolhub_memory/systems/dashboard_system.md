# Dashboard System
Responsible for:
- Monitoring central system state.
- Presenting discovered opportunities.
- Displaying active products and analytics.
- Providing operational controls.

## Technical Architecture (Stabilization)
- **Centralized Formatting**: All data types and numeric formatting are handled in the Python Controller layer (`_get_base_context`) using `safe_float`.
- **Defensive Rendering**: Jinja2 templates use `if item is mapping` checks to prevent crashes from malformed persistence data.
- **Timezone**: All displays standardized to BRT.
