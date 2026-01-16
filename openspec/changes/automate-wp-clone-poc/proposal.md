# Change: Automated WP Clone POC using All-in-One WP Migration

## Why
We want a proof-of-concept that can take a running WordPress site and clone it automatically (no manual clicks), leveraging the existing All-in-One WP Migration export/import flows.

## What Changes
- Introduce a capability to trigger a full-site export via automation (e.g., WP-CLI or REST/AJAX endpoint) using the existing export pipeline.
- Introduce a capability to apply that export to a target WordPress instance automatically, reusing the existing import pipeline.
- Define constraints for the POC: single-source WordPress, single-target WordPress, same infrastructure, minimal configuration.
- Define how secrets (AI1WM secret key, HTTP auth) and archive storage/transport will be handled for automation.

## Impact
- Affected specs: `wp-clone-automation` (new capability).
- Affected code (future implementation): main controller integration points (WP-CLI or cron), export/import controllers, possibly new helper to orchestrate end-to-end clone.
