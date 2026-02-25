# Async Restore Test Scenario

## Overview
1. Clone betaweb.ai to create a test clone
2. Edit the clone (manual - you'll do this in browser)
3. Restore the edited clone back to a target site

## Step 1: Create a Clone

```bash
cd /home/chaz/Desktop/clone-restore
python3 scripts/clone-single.py restore-test-clone
```

**Expected output:**
```
🚀 Creating WordPress clone: restore-test-clone
============================================================
✓ Job submitted: <job-id>
⏳ Waiting for clone to complete...
  Status: running (10%)
  Status: running (30%)
  Status: running (50%)
  Status: running (70%)
✓ Clone completed! (55s)

📍 URL:      https://restore-test-clone.clones.betaweb.ai
👤 Username: admin
🔒 Password: <generated-password>
```

**Save these credentials!** You'll need them for steps 2 and 3.

## Step 2: Edit the Clone (Manual)

1. Open browser and go to: `https://restore-test-clone.clones.betaweb.ai/wp-admin`
2. Login with the credentials from Step 1
3. Make some visible changes:
   - Change site title: Settings → General → Site Title → "EDITED CLONE TEST"
   - Or create a new post: Posts → Add New → "Test Post from Clone"
   - Or change homepage content

**This simulates making changes to a staging site.**

## Step 3: Restore the Clone to Target

Now we'll restore your edited clone back to betaweb.ai (or another target).

### Option A: Restore to betaweb.ai itself (full circle)

**Edit the restore script first:**
```bash
nano scripts/restore-single.py
```

**Update these lines:**
```python
# Source (the clone you just created and edited)
SOURCE_URL = "https://restore-test-clone.clones.betaweb.ai"
SOURCE_USERNAME = "admin"
SOURCE_PASSWORD = "<password-from-step-1>"

# Target (betaweb.ai - full circle test)
TARGET_URL = "https://betaweb.ai"
TARGET_USERNAME = "Charles@toctoc.com.au"
TARGET_PASSWORD = "6(4b`Nde1i_D"
```

**Run the restore:**
```bash
python3 scripts/restore-single.py
```

**Expected output:**
```
🚀 Starting WordPress restore: restore-test-20260225-HHMMSS
============================================================
Source: https://restore-test-clone.clones.betaweb.ai
Target: https://betaweb.ai
============================================================
✓ Job submitted: <job-id>
⏳ Waiting for restore to complete...
  Status: running (10%)
  Status: running (30%)   # Source setup complete
  Status: running (50%)   # Target setup complete
  Status: running (100%)  # Restore complete
✓ Restore completed! (120s)

📊 Restore Result:
============================================================
Success: True
Message: Restore completed successfully
```

### Option B: Quick Commands (All in One)

If you want to run everything quickly:

```bash
# Step 1: Create clone
python3 scripts/clone-single.py restore-test-clone

# Save the password shown, then...
# Step 2: Edit clone in browser (manual)
# Visit: https://restore-test-clone.clones.betaweb.ai/wp-admin

# Step 3: After editing, restore back
# First, update restore-single.py with your credentials, then:
python3 scripts/restore-single.py
```

## Expected Timeline

- **Clone creation**: ~55 seconds
- **Manual editing**: ~2-5 minutes (your time)
- **Restore**: ~90-120 seconds
- **Total**: ~4-7 minutes

## Verification

After restore completes:

1. Go to target site: `https://betaweb.ai`
2. Verify your changes from Step 2 are now on the target
   - Check site title if you changed it
   - Check for new post if you created one

## What You'll Prove

✅ Clone endpoint creates working WordPress clones
✅ Clones are editable and functional
✅ Async restore endpoint works end-to-end
✅ Progress tracking works (10%, 30%, 50%, 100%)
✅ Changes from clone successfully restore to target
✅ No timeouts or hanging requests

## Troubleshooting

**If clone fails:**
- Check cluster status: `kubectl get pods -n wordpress-staging`
- Check service logs: `kubectl logs -n wordpress-staging deployment/wp-k8s-service -c dramatiq-worker --tail=50`

**If restore fails:**
- Verify clone is accessible: `curl -I https://restore-test-clone.clones.betaweb.ai/`
- Check job status manually: `curl https://clones.betaweb.ai/api/v2/job-status/<job-id> -H "Host: clones.betaweb.ai"`
- Check logs for errors

## Cleanup After Test

```bash
# Delete the test clone
kubectl delete service,ingress,pod -n wordpress-staging -l clone-id=restore-test-clone
```
