# WordPress Migration Service - Complete Integration Architecture

## Overview
The wp-setup-service provides a complete WordPress migration workflow with automatic plugin installation and activation using Playwright for browser automation.

## Current Working Endpoints

### 1. `/setup` - WordPress Site Setup
**Status**: ✅ WORKING
- Sets up WordPress site with Custom WP Migrator plugin
- Uses async Playwright for reliable plugin activation
- Returns API key for migration operations

### 2. `/clone` - Complete WordPress Clone
**Status**: ✅ FIXED (async bug resolved)
- Sets up both source and target WordPress sites
- Performs complete site migration
- Uses working plugin activation system

### 3. `/restore` - WordPress Restore
**Status**: ✅ WORKING (alias for clone)
- Semantic alias for clone operation
- Same functionality as clone

### 4. `/provision` - AWS EC2 Provisioning
**Status**: ⚠️ NEEDS TESTING
- Provisions ephemeral WordPress targets on AWS EC2
- Integrates with setup workflow

## Integration Points

### Plugin Activation System
- **Browser Method**: Uses async Playwright (PRIMARY - most reliable)
- **REST API Method**: Fallback for API-enabled sites
- **Traditional Method**: Final fallback with proper headers

### Authentication Flow
1. Cookie-based authentication
2. Nonce extraction for security
3. Session management across requests

### Error Handling
- Comprehensive error codes and messages
- Graceful fallbacks between activation methods
- Detailed logging for debugging

## Complete Workflow Integration

### Single Site Setup
```
POST /setup
├── Authenticate with WordPress
├── Check plugin status
├── Upload plugin (if needed)
├── Activate plugin (Playwright → REST → Traditional)
└── Return API key
```

### Full Migration
```
POST /clone
├── Setup source site (/setup)
├── Setup target site (/setup)
├── Export from source
├── Import to target
└── Return migration results
```

### Provisioned Migration
```
POST /provision → POST /clone
├── Provision AWS EC2 target
├── Setup source site
├── Setup target site (on EC2)
├── Perform migration
└── Return results with EC2 details
```

## Key Integration Features

1. **Async/Await Consistency**: All endpoints properly handle async operations
2. **Playwright Integration**: Reliable browser-based plugin activation
3. **Fallback Mechanisms**: Multiple activation methods for reliability
4. **Error Propagation**: Clear error messages throughout the workflow
5. **Session Management**: Proper cookie and nonce handling
6. **Logging**: Comprehensive logging for debugging and monitoring

## Next Steps

1. Test complete clone workflow end-to-end
2. Validate AWS EC2 provisioning integration
3. Add status tracking for long-running operations
4. Implement webhook notifications for completion
5. Add retry mechanisms for transient failures
