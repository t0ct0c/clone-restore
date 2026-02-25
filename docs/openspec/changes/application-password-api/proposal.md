# Change: Application Password API Endpoint

## Why

Need a programmatic way to generate WordPress Application Passwords for REST API authentication. This enables external integrations, testing workflows, and automated credential management without manual intervention through the WordPress admin interface.

Current situation: To get an Application Password, users must:
1. Manually log into WordPress admin
2. Navigate to profile page
3. Create application password
4. Copy the password
5. Use it in their application

This is tedious for automated workflows and requires manual browser access.

## What Changes

- Add new `/create-app-password` REST API endpoint that generates WordPress Application Passwords
- Standalone utility endpoint - does NOT modify any existing endpoints
- Takes WordPress credentials, returns generated application password
- Enables programmatic credential management

## Impact

**Affected specs**: 
- `app-password` (new capability)

**Affected code**:
- `custom-wp-migrator-poc/wp-setup-service/app/browser_setup.py` - New `create_application_password()` function
- `custom-wp-migrator-poc/wp-setup-service/app/main.py` - New `/create-app-password` endpoint

**Benefits**:
- Programmatic application password generation
- No manual WordPress admin access needed
- Enables automated testing workflows
- Enables external integrations
- Passwords can be revoked from WordPress admin
- Standard WordPress authentication mechanism

**Constraints**:
- Requires WordPress 5.6+ on target sites
- User must have permission to create application passwords
- Application passwords must be enabled (some hosts disable them)
- Requires browser automation (Camoufox/Playwright)
