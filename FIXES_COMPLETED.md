# Clone System - All Fixes Applied (Session Feb 26, 2026)

## ✅ FIXED ISSUES

### 1. TTL Cleaner - Services/Ingresses/Secrets Not Cleaned Up
**Status:** ✅ FIXED AND DEPLOYED
- Added TTL labels to Services, Ingresses, Secrets
- TTL cleaner now deletes all resources when pods expire
- **Commit:** Earlier session
- **Files:** k8s_provisioner.py, ttl_cleaner.py

### 2. Plugin Not Installed in Cold Clones
**Status:** ✅ FIXED AND DEPLOYED
- Root cause: entrypoint script in optimized-v14 image was outdated
- **Solution:** Rebuilt image with updated entrypoint that installs plugin
- **Image:** `plugin-fixed-20260226-083515` → `wp69-20260226-093654`
- **Commit:** `2049f22`
- **Files:** docker-entrypoint.sh

### 3. API Key Not Set (403 Invalid API Key)
**Status:** ✅ FIXED AND DEPLOYED
- Root cause: custom_migrator_api_key option never set in cold clones
- **Solution:** Added API key initialization in entrypoint after plugin install
- **API Key:** `migration-master-key`
- **Commit:** `19033b0`
- **Files:** docker-entrypoint.sh

### 4. Credentials Not Returned When Clone Fails
**Status:** ✅ FIXED AND DEPLOYED
- Root cause: Failed jobs returned result=null
- **Solution:** Include provision_result in failed job status
- **Commit:** `b1c2d92`
- **Files:** tasks.py (clone_wordpress function)
- **Result:** Users get credentials even on failure via API

### 5. WordPress Version Mismatch (Database Upgrade Prompt)
**Status:** ✅ FIXED AND DEPLOYED
- Root cause: Clone image was WP 6.4, source is WP 6.9
- **Solution:** Updated Dockerfile to use wordpress:6.9-apache
- **Commit:** `8dc6e77`
- **Files:** Dockerfile

### 6. HTTPS Redirect Loop on /wp-admin/
**Status:** ✅ FIXED, DEPLOYED, **NEEDS TESTING**
- Root cause: $_SERVER['HTTPS'] flag not set in wp-config.php
- Original fix used wrong pod name (customer_id vs actual pod name)
- **Solution:** Look up pod by label selector clone-id=customer_id
- **Commit:** `8b3fc88`
- **Files:** tasks.py
- **Deployed:** `bugfix-20260226-095517`
- **IMPORTANT:** Next clone should auto-fix this, old clones need manual fix

## 🚀 CURRENT DEPLOYMENT

**WordPress Clone Image:**
- `044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:wp69-20260226-093654`
- WordPress 6.9.1
- Plugin pre-installed
- API key auto-set

**wp-k8s-service:**
- `044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:bugfix-20260226-095517`
- Returns credentials on failure
- HTTPS flag injection (fixed)

## ⚠️ KNOWN REMAINING ISSUES

### 7. Log Directory Permissions (Pod Restarts)
**Status:** ❌ NOT FIXED
- Import plugin tries to write logs but gets "Permission denied"
- Causes site to become unresponsive (503 errors)
- Kubernetes kills pod due to failed health checks
- **Where seen:** Previous test clones
- **Impact:** May cause clone to fail after 70% progress
- **Fix needed:** Create logs directory with correct permissions in entrypoint

### 8. Old Clones Still Have Issues
**Status:** ⚠️ EXPECTED
- Clones created before fixes won't benefit from new code
- **Workaround:** Delete old clones and recreate
- **Example:** `final-wp69-test-1772070077` needs manual HTTPS flag injection

## 📋 NEXT ACTIONS

1. **Test new clone creation** - Should work end-to-end now
2. **Fix log directory permissions** - Prevent 503/restart issues
3. **Update README** with current working state
4. **Clean up old test clones**

## 🧪 TEST CHECKLIST

Create a fresh clone and verify:
- [ ] Clone completes successfully (100%)
- [ ] Credentials returned in API response
- [ ] Login to /wp-admin/ works (no redirect loop)
- [ ] No database upgrade prompt
- [ ] No pod restarts
- [ ] Import data is present

## 📝 COMMITS THIS SESSION

```
2049f22 - fix: rebuild WordPress image with plugin installation in entrypoint
19033b0 - fix: add API key initialization to WordPress clone entrypoint
b1c2d92 - fix: return clone credentials even when import fails
8dc6e77 - fix: upgrade WordPress clone image to 6.9 to match source sites
8b3fc88 - fix: use customer_id to find actual pod name for HTTPS flag injection
```

## 🎯 SUCCESS CRITERIA

A clone is working correctly when:
1. API returns credentials (success OR failure)
2. Login to wp-admin works immediately
3. Imported content is visible
4. No error messages or prompts
5. Pod stays running (no restarts)

---

**Last Updated:** 2026-02-26 09:55 UTC
**Branch:** feat/kubernetes-restore
**Deployed:** Yes
