# SDLC Agent: Update Notification Mechanisms

**Date**: November 21, 2025  
**Requirement**: Notify users when new versions are available

---

## Problem

Users install from git:

```bash
pip install git+https://github.com/VincentPereira/sdlc-agent.git
```

Later, you push updates to GitHub. **How do users know there's an update?**

---

## Solution 1: Auto-Check on Every Invocation ⭐ **RECOMMENDED**

### How It Works

Every time user runs `sdlc` command, it checks for updates:

```python
# In sdlc_agent/cli/main.py

import requests
from packaging import version

__version__ = "2.1.0"  # Current installed version
GITHUB_REPO = "VincentPereira/sdlc-agent"

def check_for_updates():
    """Check if newer version available on GitHub"""
    try:
        # Get latest release from GitHub API
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(url, timeout=2)

        if response.status_code == 200:
            latest_version = response.json()["tag_name"].lstrip("v")

            if version.parse(latest_version) > version.parse(__version__):
                print(f"\n⚠️  SDLC Agent update available!")
                print(f"   Installed: v{__version__}")
                print(f"   Latest: v{latest_version}")
                print(f"   Update: pip install --upgrade git+https://github.com/{GITHUB_REPO}.git")
                print(f"   Changelog: https://github.com/{GITHUB_REPO}/releases/tag/v{latest_version}\n")
                return True
    except Exception:
        # Silently fail if no internet or API issue
        pass

    return False

def main():
    """Main CLI entry point"""
    # Check for updates (non-blocking)
    check_for_updates()

    # Continue with normal CLI execution
    # ...
```

### User Experience

```bash
$ sdlc execute --phase "Phase 5"

⚠️  SDLC Agent update available!
   Installed: v2.1.0
   Latest: v2.2.0
   Update: pip install --upgrade git+https://github.com/VincentPereira/sdlc-agent.git
   Changelog: https://github.com/VincentPereira/sdlc-agent/releases/tag/v2.2.0

Executing Phase 5...
[continues normally]
```

### Configuration (Optional)

Users can disable auto-check:

```yaml
# ~/.sdlc/config.yaml
check_for_updates: false # Disable update checks
```

### Pros ✅

- ✅ **Automatic**: Users see notification without doing anything
- ✅ **Non-intrusive**: Doesn't block execution
- ✅ **Informative**: Shows version info and update command
- ✅ **Fast**: 2-second timeout, doesn't slow down CLI
- ✅ **Graceful**: Silently fails if no internet

### Cons ❌

- ❌ **Requires internet**: Won't work offline
- ❌ **API rate limit**: GitHub API has limits (60 requests/hour unauthenticated)

---

## Solution 2: Daily Check with Cache

### How It Works

Check once per day, cache result:

```python
import os
import json
from datetime import datetime, timedelta

CACHE_FILE = os.path.expanduser("~/.sdlc/update_check_cache.json")

def should_check_for_updates():
    """Check if we should check for updates (once per day)"""
    if not os.path.exists(CACHE_FILE):
        return True

    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
            last_check = datetime.fromisoformat(data['last_check'])

            # Check if last check was more than 24 hours ago
            if datetime.now() - last_check > timedelta(days=1):
                return True
    except Exception:
        return True

    return False

def update_check_cache(has_update=False, latest_version=None):
    """Update cache with check result"""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)

    data = {
        'last_check': datetime.now().isoformat(),
        'has_update': has_update,
        'latest_version': latest_version
    }

    with open(CACHE_FILE, 'w') as f:
        json.dump(data, f)

def check_for_updates():
    """Check for updates with caching"""
    if not should_check_for_updates():
        # Check cache for existing update notification
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                if data.get('has_update'):
                    print(f"\n⚠️  Update available: v{data['latest_version']}")
                    print(f"   Run: pip install --upgrade git+https://github.com/{GITHUB_REPO}.git\n")
        except Exception:
            pass
        return

    # Perform actual check
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(url, timeout=2)

        if response.status_code == 200:
            latest_version = response.json()["tag_name"].lstrip("v")

            if version.parse(latest_version) > version.parse(__version__):
                print(f"\n⚠️  SDLC Agent update available!")
                print(f"   Installed: v{__version__}")
                print(f"   Latest: v{latest_version}")
                print(f"   Update: pip install --upgrade git+https://github.com/{GITHUB_REPO}.git\n")

                update_check_cache(has_update=True, latest_version=latest_version)
                return True
            else:
                update_check_cache(has_update=False)
    except Exception:
        pass

    return False
```

### Pros ✅

- ✅ **Efficient**: Only checks once per day
- ✅ **Respects API limits**: Fewer GitHub API calls
- ✅ **Persistent notification**: Shows update message daily until updated

### Cons ❌

- ❌ **Delayed notification**: Users might not see update for up to 24 hours

---

## Solution 3: Manual Check Command

### How It Works

Users explicitly check for updates:

```bash
# Check for updates
$ sdlc update --check

Checking for updates...
✅ You have the latest version (v2.1.0)

# Or if update available:
$ sdlc update --check

Checking for updates...
⚠️  Update available!
   Installed: v2.1.0
   Latest: v2.2.0

Install update? [y/N]: y
Updating SDLC Agent...
Done! ✅
```

### Implementation

```python
def check_and_install_update():
    """Check for update and optionally install"""
    # Check for update
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    response = requests.get(url)
    latest_version = response.json()["tag_name"].lstrip("v")

    if version.parse(latest_version) > version.parse(__version__):
        print(f"⚠️  Update available: v{latest_version}")

        # Ask user if they want to install
        choice = input("Install update? [y/N]: ")

        if choice.lower() == 'y':
            print("Updating SDLC Agent...")

            # Run pip install --upgrade
            import subprocess
            subprocess.run([
                "pip", "install", "--upgrade", "--force-reinstall",
                f"git+https://github.com/{GITHUB_REPO}.git"
            ])

            print("✅ Updated successfully!")
    else:
        print(f"✅ You have the latest version (v{__version__})")
```

### Pros ✅

- ✅ **User control**: Only checks when user wants
- ✅ **One-command update**: Can install directly
- ✅ **No surprise notifications**: User initiates check

### Cons ❌

- ❌ **Manual**: User must remember to check
- ❌ **Likely forgotten**: Users rarely check manually

---

## Solution 4: GitHub Notifications (for Developers)

### How It Works

Use GitHub's built-in notification system:

1. **Watch the repository**: Users click "Watch" on GitHub
2. **Release notifications**: GitHub emails on new releases
3. **RSS feed**: Subscribe to releases RSS feed

### Pros ✅

- ✅ **Native GitHub**: No custom code needed
- ✅ **Reliable**: GitHub handles notifications

### Cons ❌

- ❌ **Requires GitHub account**: Not all users have one
- ❌ **Email only**: Not visible in CLI
- ❌ **Opt-in**: Users must manually watch repo

---

## Solution 5: Webhook/Email Notification Service

### How It Works

**Setup**:

1. Maintain email list of users (opt-in)
2. When you release new version, send email notification

**Implementation**:

```python
# When user first installs, optionally register for notifications
$ sdlc register --email vincent@example.com

Registered for update notifications! ✅
You'll receive email when updates are available.

# Your release script:
# release.py
import smtplib

def notify_users(version, changelog):
    """Send email to registered users"""
    users = load_user_emails()  # From database/file

    for email in users:
        send_email(
            to=email,
            subject=f"SDLC Agent v{version} released",
            body=f"""
            New version available: v{version}

            Update: pip install --upgrade git+https://github.com/VincentPereira/sdlc-agent.git

            Changelog:
            {changelog}
            """
        )
```

### Pros ✅

- ✅ **Direct notification**: Email reaches users immediately
- ✅ **Opt-in**: Users choose to receive notifications

### Cons ❌

- ❌ **Privacy concerns**: Collecting email addresses
- ❌ **Infrastructure**: Need email service
- ❌ **Maintenance**: User list to manage
- ❌ **Spam risk**: Emails might be filtered

---

## Recommended Approach: Hybrid ⭐

### Combine Solutions 1 + 2 + 3

```python
# In sdlc_agent/cli/main.py

def check_for_updates(force=False):
    """
    Check for updates with smart caching

    Args:
        force: If True, skip cache and check immediately (for 'sdlc update' command)
    """
    # Solution 2: Daily cache check
    if not force and not should_check_for_updates():
        # Show cached notification if update available
        show_cached_update_notification()
        return

    # Solution 1: Auto-check on invocation
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(url, timeout=2)

        if response.status_code == 200:
            latest = response.json()
            latest_version = latest["tag_name"].lstrip("v")

            if version.parse(latest_version) > version.parse(__version__):
                # Show update notification
                print(f"\n⚠️  SDLC Agent update available!")
                print(f"   Installed: v{__version__}")
                print(f"   Latest: v{latest_version}")
                print(f"   Update: sdlc update --install")
                print(f"   Changelog: {latest['html_url']}\n")

                # Cache result
                update_check_cache(has_update=True, latest_version=latest_version)
                return True
            else:
                update_check_cache(has_update=False)
    except Exception:
        # Fail gracefully
        pass

    return False

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')

    # Solution 3: Manual update command
    update_parser = subparsers.add_parser('update', help='Check for updates')
    update_parser.add_argument('--check', action='store_true', help='Check for updates')
    update_parser.add_argument('--install', action='store_true', help='Install update')

    args = parser.parse_args()

    if args.command == 'update':
        if args.install:
            install_update()
        else:
            check_for_updates(force=True)
    else:
        # Auto-check on every invocation (cached)
        check_for_updates()

        # Continue with normal execution
        # ...
```

### User Experience

**Automatic notification** (once per day):

```bash
$ sdlc execute --phase "Phase 5"

⚠️  SDLC Agent update available!
   Installed: v2.1.0
   Latest: v2.2.0
   Update: sdlc update --install
   Changelog: https://github.com/VincentPereira/sdlc-agent/releases/tag/v2.2.0

Executing Phase 5...
```

**Manual check**:

```bash
$ sdlc update --check

Checking for updates...
⚠️  Update available: v2.2.0
   Run: sdlc update --install
```

**One-command install**:

```bash
$ sdlc update --install

Downloading update v2.2.0...
Installing...
✅ Updated successfully!
Restart your terminal to use new version.
```

### Configuration

```yaml
# ~/.sdlc/config.yaml or .sdlc/config.yaml in project

update_notifications:
  enabled: true # Enable/disable update checks
  check_frequency: "daily" # daily, weekly, never
  auto_install: false # Auto-install updates (not recommended)
```

---

## Release Process (Your Side)

To trigger notifications, follow semantic versioning:

```bash
# 1. Make your changes
git add .
git commit -m "Enhanced Data Engineer agent with better Kafka support"

# 2. Update version in code
# Edit sdlc_agent/__version__.py:
__version__ = "2.2.0"

# 3. Create git tag
git tag -a v2.2.0 -m "Release v2.2.0: Enhanced Data Engineer"
git push origin main
git push origin v2.2.0

# 4. Create GitHub release (triggers notifications)
gh release create v2.2.0 \
  --title "v2.2.0: Enhanced Data Engineer" \
  --notes "
## What's New
- Improved Kafka producer performance
- Added Schema Registry validation
- Better error handling in data ingestion

## Breaking Changes
None

## Installation
\`\`\`bash
pip install --upgrade git+https://github.com/VincentPereira/sdlc-agent.git
\`\`\`
"
```

**Users see notification next time they run `sdlc` command!**

---

## Summary: Recommended Solution

**Use**: Daily auto-check with cache + manual update command

**Benefits**:

- ✅ Users see notifications automatically (once/day)
- ✅ Non-intrusive (doesn't spam every invocation)
- ✅ One-command update: `sdlc update --install`
- ✅ Respects GitHub API limits
- ✅ Configurable (can disable)
- ✅ Works offline (gracefully fails)

**Implementation**: Will include in SDLC agent package setup
