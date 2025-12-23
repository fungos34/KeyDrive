<!--
PRODUCT_NAME: KeyDrive
BAT_LAUNCHER_NAME: KeyDrive.bat
GUI_BAT_LAUNCHER_NAME: KeyDriveGUI.bat
SH_LAUNCHER_NAME: keydrive.sh
GUI_EXE_NAME: KeyDriveGUI.exe
KeyDrive_DIR_NAME: .smartdrive
-->

# {PRODUCT_NAME} – Encrypted External Drive with YubiKey + GPG + VeraCrypt

A cross-platform, self-contained encrypted storage system for external drives (USB stick, HDD, SSD) that combines:
- **VeraCrypt** for data-at-rest encryption
- **GPG public-key encryption** to protect the keyfile (optional)
- **Two YubiKeys** (main + backup) for multi-factor authentication (optional)
- **Emergency Recovery Kit** with 24-word phrase for disaster recovery (optional)

---

## 🚨 CRITICAL SECURITY WARNING

**⚠️ BEFORE USING {PRODUCT_NAME}, YOU MUST VERIFY YOUR DRIVE HAS NOT BEEN COMPROMISED! ⚠️**

{PRODUCT_NAME} cannot protect you if your drive has already been tampered with. **Automated verification CANNOT detect sophisticated system compromises.** 

**For true security, you MUST perform MANUAL verification:**
- Access the official server endpoint (verify domain authenticity)
- Manually copy salt files to your LAUNCHER partition  
- Manually hash your entire partition using trusted tools
- Personally witness server validation responses

**Read the "Drive Compromise Detection" section below BEFORE proceeding.**

---

## 🔑 Security Modes

{PRODUCT_NAME} supports **four security levels** - choose what fits your needs:

| Mode | Protection | Use Case |
|------|------------|----------|
| **Password Only** | VeraCrypt password | Simple, portable (no YubiKey needed) |
| **Plain Keyfile** | Password + unencrypted keyfile | Defense in depth (keyfile on separate device) |
| **YubiKey + GPG** | Password + YubiKey-encrypted keyfile | Maximum security (requires hardware token) |
| **GPG Password-Only** | YubiKey-derived password | Ultimate convenience (PIN/touch only, no typing) |

### Full YubiKey Mode (Recommended)
- VeraCrypt volume protected by: **password + keyfile**
- Keyfile stored **only in GPG-encrypted form** (`keyfile.vc.gpg`)
- Decryption requires: **YubiKey + PIN** (and optionally touch)
- Effective security: **Something you know (password) + Something you have (YubiKey + PIN)**

---

## 💪 Strengths

### Risks REDUCED vs Vanilla VeraCrypt (Password-Only)

This is what {PRODUCT_NAME} actually improves:

| Risk | Vanilla VeraCrypt | {PRODUCT_NAME} (Hardware Token) | Improvement |
|------|-------------------|----------------------------|-------------|
| **Password theft (keylogger)** | 🔴 Full compromise | 🟢 Still need token + PIN | Attacker with password alone cannot decrypt |
| **Password theft (shoulder surfing)** | 🔴 Full compromise | 🟢 Still need token + PIN | Physical observation insufficient |
| **Password in breach database** | 🔴 Full compromise if reused | 🟢 Still need token + PIN | Breached password alone is useless |
| **Brute-force attack** | 🟡 Depends on password strength | 🟢 Must also brute-force keyfile | 256-bit keyfile makes brute-force infeasible |
| **Weak password chosen** | 🔴 Easily cracked | 🟡 Token adds protection layer | Weak password + strong 2FA > weak password alone |
| **Stolen drive** | 🟡 Password protects | 🟢 Password + token + PIN required | Three factors vs one |
| **Remote/network attack** | 🟡 Must steal password | 🟢 Must steal physical token | Hardware token cannot be remotely exfiltrated |
| **Malware stealing secrets** | 🔴 Can capture password | 🟡 Can capture password, but not token | Private key never leaves hardware |
| **Lost backup (forgotten password)** | 🔴 Data lost forever | 🟡 Backup token can decrypt | Redundancy via multiple hardware tokens |

**Key insight:** Hardware token mode transforms password theft from "game over" to "still protected."

### Plain Keyfile vs Hardware Token Keyfile

What does the YubiKey/GPG layer add compared to a plain (unencrypted) keyfile?

| Risk | Password + Plain Keyfile | Password + YubiKey (PIN + Touch) | Improvement |
|------|--------------------------|----------------------------------|-------------|
| **Keyfile stolen (copied)** | 🔴 Full compromise with password | 🟢 Encrypted keyfile useless without token | Keyfile is GPG-encrypted, not usable alone |
| **Keyfile on compromised system** | 🔴 Malware copies keyfile | 🟢 Only encrypted `.gpg` file exposed | Plain keyfile never touches disk |
| **Drive + keyfile backup stolen** | 🔴 Only password protects | 🟢 Still need token + PIN | Physical token required |
| **Keyfile accidentally shared** | 🔴 Shared file = shared access | 🟢 `.gpg` file harmless without token | Safe to backup to cloud |
| **Insider threat (IT admin)** | 🟡 Can copy keyfile if accessible | 🟢 Cannot extract key from hardware | Private key locked in silicon |
| **Cold boot / RAM forensics** | 🟡 Keyfile in RAM during mount | 🟡 Keyfile in RAM during mount | Same - both expose keyfile in RAM |
| **Lost keyfile** | 🔴 Data lost (unless backup) | 🟢 Any enrolled token can decrypt | Multi-token redundancy built-in |
| **Keyfile rotation** | 🟡 Manual process, error-prone | 🟢 `rekey.py` automates safely | Verified credential changes |

**Key differences:**

| Aspect | Plain Keyfile | YubiKey + GPG |
|--------|---------------|---------------|
| **Keyfile storage** | Plaintext file on disk | GPG-encrypted (`.gpg`) |
| **Keyfile exposure** | Visible, copyable | Encrypted blob - useless without token |
| **Decryption requires** | File access | Physical token + PIN (+ optional touch) |
| **Backup strategy** | Copy file securely | Enroll multiple hardware tokens |
| **Cloud backup safe?** | ❌ No - exposes keyfile | ✅ Yes - `.gpg` is encrypted |
| **Can be remotely stolen?** | ✅ Yes - it's just a file | ❌ No - private key in hardware |

**When plain keyfile is sufficient:**
- Air-gapped systems where keyfile is on separate USB
- Threat model doesn't include sophisticated attackers
- Convenience priority over maximum security

**When hardware token is better:**
- Keyfile might be exposed (backups, cloud sync, shared systems)
- Need to prove "something you have" (compliance, audits)
- Want protection even if password is compromised
- Multiple people need controlled access (multi-token encryption)

### Security Advantages (All Modes)

| Feature | Benefit | Modes |
|---------|---------|-------|
| **VeraCrypt AES-256 encryption** | Military-grade encryption for data at rest | All |
| **Password + keyfile** | Two secrets required to decrypt | Keyfile modes |
| **RAM-backed temp files** | Decrypted keyfiles never touch persistent disk storage | GPG mode |
| **Secure deletion** | Multiple overwrite passes prevent forensic recovery | All |
| **No plaintext keyfile on disk** | Keyfile exists only in RAM during mount | GPG mode |
| **Verified credential changes** | `rekey.py` test-mounts before committing - no accidental lockouts | All |
| **Safety checks** | Prevents accidental encryption of system drives | All |

### Security Advantages (YubiKey/Hardware Token Mode)

| Feature | Benefit |
|---------|---------|
| **True hardware 2FA** | Private key never leaves the device - cannot be remotely compromised |
| **GPG public-key encryption** | Keyfile encrypted to multiple recipients (main + backup keys) |
| **PIN-protected decryption** | Even if token is stolen, attacker needs PIN (3 attempts before lockout) |
| **Optional touch requirement** | Hardware token can require physical touch for every decryption |
| **Multi-key redundancy** | Encrypt to 2+ hardware tokens - lose one, use the backup |

### Usability Advantages

| Feature | Benefit |
|---------|---------|
| **5-phase setup wizard** | Fully automated drive preparation with `ERASE` safety gate |
| **3 security modes** | Choose your level: password-only → plain keyfile → hardware token |
| **Cross-platform** | Works on Windows, Linux, and macOS |
| **Self-contained** | Scripts + config + keyfile all on the LAUNCHER partition |
| **No Python dependencies** | Python 3.7+ standard library only (GPG/VeraCrypt installed separately) |
| **Portable** | Plug drive into any computer with Python + VeraCrypt (+ GPG for token mode) |
| **MBR partitioning** | Maximum USB drive compatibility across systems |

### Operational Advantages

| Feature | Benefit |
|---------|---------|
| **Credential rotation** | Easy hardware token replacement without data loss |
| **Automatic verification** | Scripts verify operations before finalizing |
| **Backup keyfile** | Old `.gpg.old` preserved during rekey operations |

### Language & Theme Customization

| Feature | Benefit |
|---------|---------|
| **6 languages supported** | English, German, Bosnian, Spanish, French, Chinese |
| **Live language switching** | Change language instantly without restart - updates all UI text immediately |
| **4 color themes** | Green (default), Blue, Dark mode, Light mode - switch themes on the fly |
| **Persistent preferences** | Language and theme choices saved to config and restored automatically |
| **Structured translations** | Error messages use parametrized templates for consistent localization |

**How to use:**
1. Click the **Settings** button (⚙️) in the GUI
2. Select your preferred **language** from the dropdown
3. Select your preferred **theme** from the dropdown
4. Changes apply **instantly** (no application restart needed)
5. Your choices persist across sessions automatically

---

## 🔧 Technical Architecture

### PathResolver - Single Source of Truth (SSOT)

All file system paths are managed by `PathResolver` to ensure:
- **Cross-drive setup**: Setup can run from Drive A and target Drive B
- **No duplicates**: Exactly one `config.json` and one `static/` directory per deployment
- **Authorized writes**: All writes must be under authorized roots (fails loudly otherwise)
- **CWD independence**: Scripts work regardless of current working directory

**Canonical paths:**
```
DRIVE_ROOT/
├── .smartdrive/                  # Hidden runtime directory (canonical)
│   ├── scripts/
│   │   ├── config.json           # ONLY config location (SSOT)
│   │   ├── mount.py
│   │   └── ...
│   ├── static/                   # ONLY static directory (SSOT)
│   │   ├── LOGO_main.ico
│   │   └── LOGO_main.png
│   ├── docs/                     # Documentation shipped with deployment
│   ├── keys/                     # Keyfiles (GPG-encrypted)
│   └── logs/                     # Operation logs
├── KeyDrive.lnk                  # Windows entrypoint (clickable)
├── KeyDriveGUI.lnk               # Windows GUI entrypoint (clickable)
├── keydrive.sh                   # Linux entrypoint (clickable)
└── KeyDrive.command              # macOS entrypoint (clickable)
```

#### ⚠️ Critical Files & Folders Preservation

These files and folders are essential for your encrypted drive to function. **Back them up regularly** and handle with care:

| File/Folder | Purpose | Backup Priority |
|-------------|---------|-----------------|
| `config.json` | Drive configuration, mount settings, security mode | **HIGH** – Required for operation |
| `keys/` | GPG-encrypted keyfiles for VeraCrypt | **CRITICAL** – Loss = permanent lockout |
| `recovery/` | Recovery kit files (if generated) | **HIGH** – Your safety net |
| `seed.gpg` | GPG-encrypted random seed (if using Yubikey) | **CRITICAL** – Required for 2FA |
| `scripts/` | Operational scripts (can be redeployed) | MEDIUM – Restorable from source |

**Backup Safety:**
- Store backups in a **secure, separate location** (not on the same drive)
- Consider offline backups for `keys/` and `seed.gpg`
- The `config.json` should be backed up after any settings changes

**⚠️ What NOT to Modify:**
- Never manually edit encrypted keyfiles in `keys/`
- Never modify `seed.gpg` – it's cryptographically generated
- Configuration changes should be made through the GUI/CLI, not by hand-editing `config.json`

**Usage in code:**
```python
from core.path_resolver import RuntimePaths

# Create paths for explicit target (cross-drive support)
paths = RuntimePaths.for_target(Path("G:\\"), create_dirs=True)

# All paths are now SSOT
config = paths.config_file        # G:\.smartdrive\scripts\config.json
static = paths.static_dir         # G:\.smartdrive\static
keys = paths.keys_dir             # G:\.smartdrive\keys

# Writes outside authorized roots fail loudly
paths.validate_write_path(some_path)  # Raises SecurityError if unauthorized
```

### Settings System

Settings are managed via schema-driven validation:
- **Schema validation**: All settings validated against `settings_schema.py`
- **Unknown key preservation**: Config merges preserve unknown keys (even nested)
- **Atomic writes**: Config updates are atomic (temp file + rename)
- **Live refresh**: Settings UI reflects external config changes immediately

### Cross-Drive Setup and Mounting

Setup supports running from one drive and targeting another:

**Scenario 1: Setup from Drive A, target Drive B**
```powershell
# Script runs from A:\setup.py
# Target drive specified: B:\
# PathResolver creates: B:\.keydrive\
# Automated mount mounts: B:\.keydrive\PAYLOAD partition
```

**Scenario 2: Setup from target drive itself**
```powershell
# Script runs from B:\setup.py  
# Target drive: B:\ (self-hosted)
# PathResolver creates: B:\.keydrive\
# Automated mount mounts: B:\.keydrive\PAYLOAD partition
```

**Key features:**
- Target drive is explicitly determined and validated
- No implicit CWD or script location inference
- Automated mount targets correct volume path (not script's drive)
- All path operations use PathResolver as SSOT

---

## ✅ E2E Release Gate

The `verify_e2e_windows.ps1` script is the **authoritative release gate**. All changes must pass this gate before release.

**What it verifies:**
1. **Safety guardrails**: Source disk cannot be selected as target
2. **Security modes**: All 4 modes have correct prerequisites
3. **Run from anywhere**: Scripts work from any CWD
4. **GUI terminal spawning**: Terminal placement and command correctness
5. **Atomic writes**: Config updates are atomic
6. **Disk identity**: DiskIdentity.matches() uses UniqueId
7. **Settings UI**: Live language/theme switching works
8. **No duplicates**: Exactly one config.json and one static/ directory
9. **Branding compliance**: No forbidden terms in documentation

**How to run:**
```powershell
.\tools\verify_e2e_windows.ps1
```

**Exit codes:**
- `0`: All verifications passed (RELEASE READY)
- `1`: One or more verifications failed (NOT READY)

---

## 📊 Severity vs Likelihood: Understanding Risk

**Risk = Severity × Likelihood**

Understanding these two components helps you choose the right security level.

### Definitions

| Term | Meaning | Example |
|------|---------|---------|
| **Severity** | Damage/impact if attack succeeds | Full data breach = high; minor inconvenience = low |
| **Likelihood** | Probability the attack will occur | Mass breach = high; nation-state targeting you = low |
| **Risk** | Severity × Likelihood | The actual threat level you face |

```
                         LIKELIHOOD
                    Low ◄─────────────────► High
              ┌─────────────────────────────────┐
              │                │                │
         High │   LOW RISK     │   HIGH RISK    │
              │   (rare but    │   (common and  │
   SEVERITY   │    severe)     │    severe)     │
              ├────────────────┼────────────────┤
              │                │                │
         Low  │  NEGLIGIBLE    │   LOW RISK     │
              │   (rare and    │   (common but  │
              │    minor)      │    minor)      │
              └─────────────────────────────────┘
```

### Network Attacks vs Close-Circle Attacks

| Attack Type | Severity | Likelihood (Trend) | **Overall Risk** | {PRODUCT_NAME} Protection |
|-------------|----------|-------------------|------------------|----------------------|
| **Mass credential breaches** | 🔴 High | 📈 High & increasing | 🔴 **HIGH RISK** | ✅ Password alone insufficient |
| **Automated password spraying** | 🔴 High | 📈 High & increasing | 🔴 **HIGH RISK** | ✅ Hardware token blocks remote |
| **Targeted phishing** | 🔴 High | 📈 Medium & increasing | 🟠 **MED-HIGH** | ✅ Token can't be phished |
| **Keylogger malware** | 🔴 High | 📈 Medium & increasing | 🟠 **MED-HIGH** | ✅ Password alone insufficient |
| **Remote exploitation** | 🔴 High | 📈 Low-Med & increasing | 🟡 **MEDIUM** | ✅ Can't steal hardware remotely |
| **Ransomware** | 🔴 High | 📈 Medium & increasing | 🟠 **MED-HIGH** | ⚠️ Only helps if unmounted |
|||
| **Intimate partner/family** | 🟡 Medium | ➡️ Low-Med (depends) | 🟡 **MEDIUM** | ✅ Need token + PIN + password |
| **Coworker/insider** | 🟡 Medium | ➡️ Low | 🟢 **LOW-MED** | ✅ Can't copy keyfile |
| **Theft (opportunistic)** | 🔴 High | ➡️ Low-Med | 🟡 **MEDIUM** | ✅ Three factors required |
| **Theft (targeted)** | 🔴 High | 📉 Very low | 🟢 **LOW** | ⚠️ Determined attacker may succeed |
| **Evil maid (physical)** | 🔴 High | 📉 Very low | 🟢 **LOW** | ⚠️ Can tamper with scripts |
| **Rubber hose (coercion)** | 🔴 High | 📉 Extremely low | 🟢 **VERY LOW** | ❌ No technical defense |

### Why This Matters: Trend Analysis

**Network attacks (High Severity + Increasing Likelihood = Rising Risk):**

| Factor | 2015 | 2025 | Trend |
|--------|------|------|-------|
| Breached credentials available | ~1 billion | ~15+ billion | 📈 15× |
| Cost of password cracking | $$ | ¢ | 📈 Cheaper |
| Infostealer malware variants | Hundreds | Tens of thousands | 📈 100× |
| AI-powered phishing | Non-existent | Widespread | 📈 New threat |

**Close-circle attacks (High Severity + Stable/Low Likelihood = Stable Risk):**

| Factor | 2015 | 2025 | Trend |
|--------|------|------|-------|
| Intimate partner threats | Relationship-dependent | Relationship-dependent | ➡️ Stable |
| Insider threats | Opportunity-dependent | Opportunity-dependent | ➡️ Stable |
| Physical theft | Location-dependent | Location-dependent | ➡️ Stable |

**Key insight:** Network attack *likelihood* has exploded while close-circle attack *likelihood* remains constant. This shifts where your risk actually lies.

### Risk-Based Recommendations

| Your Risk Profile | Primary Threats | Recommended Mode |
|-------------------|-----------------|------------------|
| **Most people** | Breaches, malware, phishing (HIGH likelihood) | 🔐 Hardware Token |
| **Trusted home environment** | Lost drive (LOW likelihood) | 🔑 Password-only acceptable |
| **Shared/work computer** | Insider, malware (MED likelihood) | 🔐 Hardware Token |
| **Journalist/activist** | Targeted + network (BOTH high) | 🔐 Hardware Token + Touch |
| **Celebrity/executive** | All vectors elevated | 🔐 Hardware Token + additional OPSEC |

### The Bottom Line

**For most people in 2025:**

| Threat Type | Severity | Likelihood | Risk | {PRODUCT_NAME} Value |
|-------------|----------|------------|------|------------------|
| 🌐 Network attacks | High | **HIGH & rising** | 🔴 HIGH | ✅ Primary protection |
| 👥 Close-circle | High | Low-Med & stable | 🟡 MEDIUM | ✅ Adds friction |
| 🕵️ Targeted physical | High | Very low | 🟢 LOW | ⚠️ Limited protection |

**{PRODUCT_NAME}'s value proposition:** Dramatically reduces risk from the **high-likelihood** threats (breaches, malware, remote attacks) that affect millions, while meaningfully increasing difficulty for **medium-likelihood** close-circle threats.

---

**Key trends:**

| Trend | Implication for {PRODUCT_NAME} |
|-------|---------------------------|
| 📈 **Network attacks scaling exponentially** | Password-only is increasingly dangerous; hardware 2FA blocks 99% of remote attacks |
| 📈 **Credential stuffing automated** | Reused passwords = compromised everywhere; hardware token = unique per-device |
| 📈 **Infostealers commoditized** | Malware captures passwords cheaply; can't capture hardware token remotely |
| ➡️ **Close-circle attacks stable** | Family/coworker threats haven't changed; hardware token still helps |
| 📉 **Physical attacks rare (for most)** | Unless you're a high-value target, "evil maid" is unlikely |

### Who Should Use Which Mode?

| Profile | Primary Threat | Recommended Mode |
|---------|----------------|------------------|
| **Average user** | Data breaches, opportunistic theft | Password + Hardware Token |
| **Journalist/activist** | Targeted surveillance, border crossing | Password + Hardware Token + Touch |
| **Business traveler** | Theft, customs inspection | Password + Hardware Token |
| **Home user (trusted environment)** | Lost drive, casual snooping | Password-only or Plain Keyfile |
| **Air-gapped system** | Physical access only | Plain Keyfile (on separate USB) |
| **High-value target** | Nation-state, organized crime | Hardware Token + additional OPSEC |

### The Bottom Line

**For most people in 2025:**
- 🔴 **Network attacks** are your biggest threat (high likelihood, high risk)
- 🟢 **Hardware token** effectively neutralizes remote/network attacks
- 🟡 **Close-circle attacks** are relationship-specific; hardware token helps but isn't foolproof
- ⚪ **Physical "spy movie" attacks** are rare unless you're specifically targeted

**{PRODUCT_NAME}'s sweet spot:** Protecting against the **high-likelihood** threats (breaches, malware, remote theft) that affect millions of people, while adding meaningful friction against **close-circle** threats.

---

## 🔐 Compatible Hardware Tokens

{PRODUCT_NAME} works with **any device that supports OpenPGP smartcard functionality** via GPG. The YubiKey is just one popular option.

### Tested / Recommended

| Device | OpenPGP Support | Notes |
|--------|-----------------|-------|
| **YubiKey 5 Series** (5, 5 NFC, 5C, 5Ci) | ✅ Full | Most popular; USB-A, USB-C, NFC variants |
| **YubiKey 5 FIPS** | ✅ Full | FIPS 140-2 certified for compliance requirements |
| **YubiKey Bio** | ✅ Full | Adds fingerprint authentication |

### Should Work (OpenPGP Compatible)

| Device | OpenPGP Support | Notes |
|--------|-----------------|-------|
| **Nitrokey Pro 2** | ✅ Full | Open-source hardware; tamper-resistant |
| **Nitrokey Storage 2** | ✅ Full | Adds encrypted storage partition |
| **Nitrokey 3** | ✅ Full | USB-C; open-source firmware |
| **OnlyKey** | ✅ Full | Open-source; also stores passwords |
| **Gnuk** | ✅ Full | Open-source firmware for STM32 devices |
| **SoloKeys Solo V2** | ⚠️ Partial | Primarily FIDO2; limited OpenPGP |
| **Ledger Nano S/X** | ✅ Via app | Requires GPG app installation |
| **Trezor Model T** | ✅ Via app | Requires GPG app; open-source |

### NOT Compatible

| Device | Why |
|--------|-----|
| **YubiKey FIDO-only** (Security Key series) | No OpenPGP support - FIDO2/U2F only |
| **Google Titan** | FIDO2/U2F only - no OpenPGP |
| **Feitian ePass** | FIDO2 only models lack OpenPGP |
| **Basic FIDO2 keys** | Need OpenPGP smartcard functionality |

### Requirements for Compatibility

For a hardware token to work with {PRODUCT_NAME}, it must:
1. **Support OpenPGP smartcard standard** (ISO 7816-4)
2. **Store RSA or ECC private keys** on the device
3. **Work with GnuPG** (`gpg --card-status` must detect it)
4. **Support decryption operations** (not just signing)

### Setting Up a New Hardware Token

```bash
# 1. Insert your hardware token
# 2. Check if GPG detects it
gpg --card-status

# 3. Generate or import keys to the device
gpg --edit-card
> admin
> generate    # Generate new keys on device
# OR
> keytocard   # Move existing keys to device

# 4. Get the 40-character fingerprint
gpg --list-keys --fingerprint

# 5. Use the fingerprint when setting up {PRODUCT_NAME}
python setup.py  # Select your key during Phase 2
```

---

## ⚠️ Weaknesses & Security Considerations

### ⚡ Temporary Decrypted Keyfile: Understanding the Real Risk

{PRODUCT_NAME} must decrypt the GPG-encrypted keyfile before VeraCrypt can use it. This creates a brief window where the plaintext keyfile exists.

#### Is This Worse Than Vanilla VeraCrypt? **NO!**

This is actually **better** than vanilla VeraCrypt with a keyfile:

| Scenario | Keyfile Exposure | Attacker Window |
|----------|------------------|-----------------|
| **Vanilla VeraCrypt + plain keyfile** | Plaintext file on disk **permanently** | ♾️ Unlimited - copy anytime |
| **{PRODUCT_NAME} (Hardware Token)** | Plaintext exists **~1-5 seconds** during mount | ⏱️ Tiny window, then gone |
| **Vanilla VeraCrypt (password-only)** | No keyfile | N/A |

**Key insight:** If you were going to use VeraCrypt with a keyfile anyway, {PRODUCT_NAME} **reduces** your exposure from "always" to "seconds."

#### Why Can't We Generate a New Keyfile Each Mount?

The keyfile is **not** a one-time token. It's **baked into the volume**:

```
Volume Creation:
  encryption_key = KDF(password + keyfile + salt)
  └── This key is used to encrypt your data

Every Mount:
  Must provide THE SAME password + keyfile
  └── Otherwise: wrong key → garbage data
```

Generating a new keyfile would require re-encrypting the volume header (what `rekey.py` does).

#### When Plaintext Keyfile Exists

| Operation | Duration | Location |
|-----------|----------|----------|
| **`mount.py`** | ~1-5 seconds | Temp dir (or `/dev/shm` on Linux) |
| **`rekey.py`** | ~30-120 seconds (GUI) | Temp directory |
| **`setup.py`** | ~30-120 seconds (GUI) | Temp directory |
| **Volume mounted** | N/A - keyfile deleted | Gone |

#### The Mount Process

```
┌─────────────────────────────────────────────────────────────────────┐
│  EVERY TIME YOU MOUNT:                                              │
│                                                                     │
│  1. GPG decrypts keyfile.vc.gpg → plaintext keyfile in TEMP        │
│  2. VeraCrypt reads plaintext keyfile + your password              │
│  3. {PRODUCT_NAME} DELETES plaintext keyfile (secure wipe)             │
│  4. Volume is mounted                                               │
│                                                                     │
│  Window of exposure: Steps 1-3 (~1-5 seconds)                       │
│  Compare to: Vanilla keyfile exposed 24/7/365                       │
└─────────────────────────────────────────────────────────────────────┘
```

#### Realistic Threat Assessment

| Attack | vs Vanilla+Keyfile | vs {PRODUCT_NAME} | Winner |
|--------|-------------------|---------------|--------|
| **Malware copies keyfile** | 🔴 Easy - file always there | 🟡 Hard - 5 second window | {PRODUCT_NAME} |
| **Attacker finds backup** | 🔴 Plaintext in backup | 🟢 Only `.gpg` in backup | {PRODUCT_NAME} |
| **Forensic recovery** | 🔴 File exists on disk | 🟡 Brief temp file | {PRODUCT_NAME} |
| **Shoulder surfing keyfile location** | 🔴 Can go copy it later | 🟢 Nothing to copy | {PRODUCT_NAME} |
| **Cold boot attack** | 🟡 Keyfile in RAM if mounted | 🟡 Same | Tie |
| **Admin/root malware** | 🔴 Game over | 🔴 Game over | Tie |

#### Mitigations We Implement

| Mitigation | Implementation | Effectiveness |
|------------|----------------|---------------|
| **Minimal exposure time** | Delete immediately after VeraCrypt reads it | ✅ Good |
| **RAM-backed temp files** | Automatic `/dev/shm` on Linux, secure temp on Windows/macOS | ✅ Excellent |
| **Secure deletion** | Multiple random overwrites before unlinking | ✅ Good |
| **Restrictive permissions** | `chmod 600` on Unix | ✅ Good |
| **Unique filenames** | Random hex prefix prevents prediction | ✅ Good |

#### The Unavoidable Constraint

| Limitation | Why |
|------------|-----|
| **Keyfile must exist briefly** | VeraCrypt CLI requires a file path - cannot pipe bytes directly |
| **Password still exposed to keyloggers** | Same as vanilla VeraCrypt - hardware token protects keyfile, not password |

#### Comparison: How Other Tools Handle This

| Tool | Approach | Keyfile Exposure | Trade-off |
|------|----------|------------------|-----------|
| **Vanilla VeraCrypt + keyfile** | User stores keyfile | **Permanent** | Must secure file yourself |
| **{PRODUCT_NAME}** | GPG decrypts → temp → delete | **~5 seconds** | Brief window, encrypted at rest |
| **LUKS + systemd-cryptenroll** | TPM/FIDO2 direct unlock | **None** | Tied to specific hardware |
| **BitLocker + TPM** | Key in TPM | **None** | Microsoft ecosystem only |

#### Bottom Line

**{PRODUCT_NAME}'s temporary keyfile is NOT a weakness compared to vanilla VeraCrypt with a keyfile - it's an improvement.** 

The only scenario where {PRODUCT_NAME} has "more" exposure is compared to **password-only** VeraCrypt (which has no keyfile at all). But password-only lacks the 2FA benefits that are the whole point of {PRODUCT_NAME}.

#### Recommendations to Minimize This Risk

1. **Automatic RAM usage:** {PRODUCT_NAME} automatically uses RAM-backed temp directories when available (`/dev/shm` on Linux, secure system temp on Windows/macOS)
2. **High-security needs:** Mount only on trusted, malware-free systems
3. **After mounting:** The keyfile is gone - ongoing use is safe

### Compared to Vanilla VeraCrypt

| Aspect | Vanilla VeraCrypt | {PRODUCT_NAME} |
|--------|-------------------|------------|
| **Attack surface** | VeraCrypt only | VeraCrypt + GPG + Python scripts |
| **Audit status** | Professionally audited | Scripts not audited |
| **Temp keyfile exposure** | None (user provides directly) | Brief window during mount |
| **Hidden volumes** | Supported | Not supported by scripts |
| **Password-only** | ✅ Supported | ✅ Supported |
| **Keyfile handling** | Manual | Automated (GPG encryption) |
| **Multi-factor** | External (manual keyfile) | Integrated (hardware token) |

### Attack Surface (Hardware Token Mode)

{PRODUCT_NAME} adds convenience but also introduces new attack vectors:

| Attack Vector | Risk | Mitigation |
|---------------|------|------------|
| **Temp keyfile during mount** | ⚠️ See detailed section above | Minimal window, secure delete, RAM on Linux |
| **GPG/GnuPG vulnerabilities** | GPG bugs could leak keyfile | Keep GPG updated; use well-audited builds |
| **Python script tampering** | Attacker modifies `mount.py` to steal password | Verify script integrity; store on read-only media |
| **Keyfile in RAM** | Cold boot attack could extract decrypted keyfile | Use systems with RAM encryption; hibernate instead of sleep |
| **config.json exposure** | Reveals volume path and mount points | Not sensitive (no secrets), but reveals drive structure |
| **GPG agent caching** | Decrypted keyfile may be cached by `gpg-agent` | Configure `gpg-agent` with short cache timeout |
| **LAUNCHER partition unencrypted** | Scripts and encrypted keyfile visible | By design - needed for portability; keyfile is GPG-encrypted |

### What an Attacker Would Need (Hardware Token Mode)

| Scenario | Requirements | Difficulty |
|----------|--------------|------------|
| **Remote attack** | VeraCrypt password + hardware token + PIN | 🔴 Nearly impossible |
| **Stolen drive only** | Crack VeraCrypt password + keyfile (GPG-encrypted) | 🔴 Very hard |
| **Stolen drive + token** | Crack VeraCrypt password + token PIN (3 tries) | 🟡 Hard |
| **Stolen drive + token + PIN** | Crack VeraCrypt password | 🟢 Feasible with weak password |
| **Physical access while mounted** | Direct data access | 🟢 Easy (true for any mounted volume) |

### What an Attacker Would Need (Password-Only Mode)

| Scenario | Requirements | Difficulty |
|----------|--------------|------------|
| **Stolen drive only** | Crack VeraCrypt password | 🟡 Depends on password strength |
| **Physical access while mounted** | Direct data access | 🟢 Easy |

### Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| **Requires GPG + VeraCrypt installed** | Not truly portable without pre-installed software | Future: bundle portable versions |
| **Python required** | Target system needs Python 3.7+ | Future: compile to standalone executable |
| **No plausible deniability** | VeraCrypt hidden volumes not supported by scripts | Use standard VeraCrypt GUI for hidden volumes |
| **Single volume per config** | One drive = one config.json | Create multiple config files manually |
| **GUI required for credential changes** | VeraCrypt CLI doesn't support partition header changes | By design - GUI is more reliable |

### Threat Model Summary

**{PRODUCT_NAME} protects against:**
- ✅ Remote attackers (no network access to decryption)
- ✅ Stolen/lost drive (encrypted data + encrypted keyfile in token mode)
- ✅ Casual physical access (need password, and token+PIN in hardware mode)
- ✅ Single point of failure (backup hardware token support)

**{PRODUCT_NAME} does NOT protect against:**
- ❌ Attacker with drive + token + PIN + weak password
- ❌ Malware on the host system while volume is mounted
- ❌ Physical access while the volume is mounted
- ❌ Nation-state adversaries with unlimited resources
- ❌ Rubber hose cryptanalysis (coercion/torture)

---

## 🛡️ Best Practices for Minimizing Risk

### Operational Security (OpSec)

#### Mounting on Untrusted/Foreign Systems

| Practice | Why | How |
|----------|-----|-----|
| **Rekey after foreign mount** | Invalidates any captured keyfile | Run `rekey.py` on trusted system after |
| **Change password too** | Keylogger captures password, not just keyfile | Change both in VeraCrypt GUI during rekey |
| **Minimize mount time** | Less exposure window | Mount → copy files → unmount immediately |
| **Check for keyloggers first** | Password is your weakest link | Use on-screen keyboard, check running processes |
| **Boot from live USB** | Avoids host system malware entirely | Tails, Ubuntu Live, etc. |

#### The "Rekey After Foreign Mount" Strategy

```
┌─────────────────────────────────────────────────────────────────────┐
│  SCENARIO: You mounted on a potentially compromised system          │
│                                                                     │
│  What attacker MAY have captured:                                   │
│    • Your password (keylogger) ─────────────────┐                   │
│    • Decrypted keyfile (temp file watcher) ─────┼── Both needed     │
│    • Your data (while mounted) ─────────────────┘   to decrypt      │
│                                                                     │
│  REMEDIATION (on trusted system):                                   │
│    1. Run: python rekey.py                                          │
│    2. Change BOTH password AND keyfile                              │
│    3. Old password + old keyfile = now useless                      │
│                                                                     │
│  ⚠️  This does NOT help if:                                         │
│    • Attacker already copied your data while mounted                │
│    • Attacker has ongoing access to your system                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### Risk vs Convenience Trade-offs

| Security Level | Practice | Inconvenience |
|----------------|----------|---------------|
| 🟢 **Low** | Mount anywhere, rekey monthly | Minimal |
| 🟡 **Medium** | Rekey after untrusted mounts | Moderate - few minutes |
| 🟠 **High** | Rekey after EVERY foreign mount | High - every time |
| 🔴 **Maximum** | Never mount on foreign systems | Very high - defeats portability |

### Technical Hardening

#### System Configuration

| Practice | Implementation | Impact |
|----------|----------------|--------|
| **Automatic RAM-backed temp** | {PRODUCT_NAME} uses `/dev/shm` on Linux, secure temp on Windows/macOS | Keyfile never touches persistent disk |
| **Short GPG agent timeout** | `default-cache-ttl 60` in `gpg-agent.conf` | Limits PIN caching |
| **Enable YubiKey touch** | `ykman openpgp keys set-touch dec on` | Requires physical presence |
| **Full-disk encryption on host** | BitLocker/LUKS on your main system | Protects temp files at rest |
| **Disable sleep, use hibernate** | Power settings | RAM cleared on hibernate |

#### Script Integrity

| Practice | Implementation | Why |
|----------|----------------|-----|
| **Hash verification** | Store SHA256 of scripts, verify before use | Detect tampering |
| **Read-only LAUNCHER** | Hardware write-protect switch (some USB drives) | Prevent script modification |
| **Git signature** | Sign commits, verify on clone | Ensure authentic source |
| **Minimal scripts on drive** | Only `mount.py`, `unmount.py`, `config.json` | Reduce attack surface |

Example hash verification:
```powershell
# Generate hashes (once, on trusted system)
Get-FileHash .\scripts\mount.py -Algorithm SHA256 | Select-Object Hash > mount.py.sha256

# Verify before use
$expected = Get-Content .\mount.py.sha256
$actual = (Get-FileHash .\scripts\mount.py -Algorithm SHA256).Hash
if ($expected.Trim() -eq $actual) { "✓ Verified" } else { "⚠️ TAMPERED!" }
```

#### Password Hygiene

| Practice | Why |
|----------|-----|
| **20+ character passphrase** | Brute-force infeasible even with keyfile |
| **Unique - never reused** | Breach of other service won't help attacker |
| **Not stored in password manager** | Manager compromise doesn't expose it |
| **Consider diceware** | "correct-horse-battery-staple" style |

### Physical Security

| Practice | Why |
|----------|-----|
| **Keep YubiKey on your person** | Attacker needs physical token |
| **Backup YubiKey in secure location** | Safe deposit box, trusted person |
| **Don't store drive + YubiKey together** | Theft of bag = both factors |
| **Use YubiKey with touch required** | Prevents background decryption |

### Paranoid Mode (High-Value Targets)

If you're a journalist, activist, or handle extremely sensitive data:

| Practice | Implementation |
|----------|----------------|
| **Air-gapped mounting** | Dedicated offline laptop for mounting |
| **Boot from read-only media** | Tails on DVD (not USB) |
| **Faraday bag for YubiKey** | Prevents relay attacks |
| **Duress password** | VeraCrypt hidden volume with decoy data |
| **Plausible deniability** | Use VeraCrypt GUI for hidden volumes (not {PRODUCT_NAME}) |
| **Regular rekey schedule** | Weekly/monthly regardless of use |
| **Secure erase after travel** | Wipe and restore from backup after border crossings |

### Quick Reference: After Mounting on Foreign System

```
□ Unmount immediately when done
□ On trusted system, run: python rekey.py
□ Change BOTH password and keyfile
□ Select same YubiKey(s) for new keyfile
□ Verify mount works with new credentials
□ Delete .old backup after verification
□ If truly paranoid: consider data may have been copied
```

---

## 📁 Project Structure

**Development Environment (this repo):**
```
VeraCrypt_Yubikey_2FA/
├── {BAT_LAUNCHER_NAME}               # Windows launcher (auto-detects structure)
├── {SH_LAUNCHER_NAME}                # Linux/macOS launcher
├── .smartdrive/               # CANONICAL RUNTIME TREE (deployed 1:1)
│   ├── core/                    # SSOT modules (authoritative)
│   │   ├── version.py           # VERSION constant
│   │   ├── constants.py         # ConfigKeys, UserInputs, etc.
│   │   ├── paths.py             # Paths class
│   │   ├── limits.py            # Limits class
│   │   └── modes.py             # SecurityMode, RecoveryOutcome
│   └── scripts/                 # Runtime scripts
│       ├── KeyDrive.py        # Unified CLI menu
│       ├── setup.py             # Drive setup wizard
│       ├── mount.py             # Mount encrypted volume
│       ├── unmount.py           # Unmount encrypted volume
│       ├── rekey.py             # Change password/keyfile
│       ├── keyfile.py           # Keyfile utilities
│       ├── gui.py               # GUI implementation
│       └── config.json          # Configuration
├── scripts/                     # DEV-ONLY wrappers (NOT deployed)
│   ├── setup.py                 # -> .smartdrive/scripts/setup.py
│   └── ...                      # Convenience wrappers for development
├── tests/                       # Test suite
├── keys/                        # Keyfiles (development/testing)
└── README.md
```

**Deployed on External Drive (after setup):**
```
LAUNCHER/                        (USB Drive - Unencrypted Partition)
├── KeyDrive.lnk                 # Windows entrypoint (clickable)
├── KeyDriveGUI.lnk              # Windows GUI entrypoint (clickable)
├── {SH_LAUNCHER_NAME}           # Linux entrypoint (clickable)
├── KeyDrive.command             # macOS entrypoint (clickable)
└── {KeyDrive_DIR_NAME}/         # Hidden folder (clean root; everything else lives here)
    ├── core/                    # SSOT modules (copied 1:1 from repo)
    │   ├── version.py
    │   ├── constants.py
    │   ├── paths.py
    │   ├── limits.py
    │   └── modes.py
    ├── scripts/
    │   ├── KeyDrive.py
    │   ├── mount.py
    │   ├── unmount.py
    │   ├── rekey.py
    │   ├── keyfile.py
    │   └── config.json          # Drive-specific configuration
   ├── static/                  # Icons/assets; Explorer drive icon points here via desktop.ini
   ├── docs/                    # Documentation shipped with deployment
   ├── keys/
    │   └── keyfile.vc.gpg       # Encrypted keyfile
    └── integrity/
        ├── scripts.sha256       # Hash for verification
        └── scripts.sha256.sig   # GPG signature
```

**Key Architecture Principle:**
- The repo's `.smartdrive/` directory is copied **1:1** to the deployed drive
- No path translation or mapping during deployment
- Dev wrappers in `scripts/` forward to `.smartdrive/scripts/` for convenience
- Tests and enforcement scripts remain at repo root (never deployed)

---

## 🏛️ Architecture Contract (Authoritative)

> **For developers and AI agents**: This section defines binding architectural constraints.
> See `AGENT_ARCHITECTURE.md` for the full governing document.

### Governing Document

**`AGENT_ARCHITECTURE.md`** is the authoritative source for all architectural decisions.
Any code change that violates that document is considered a defect, even if functionality appears correct.

### How AGENT_ARCHITECTURE.md Governs Implementation

| Section | Applies To | Enforcement |
|---------|------------|-------------|
| §3 SSOT | All modules | `check_single_source_of_truth.py` |
| §4 Path Handling | All file operations | `check_no_string_paths.py` |
| §5 Recovery Guarantees | `recovery.py`, `setup.py` | Unit tests |
| §7 Security Invariants | All crypto operations | Manual review |
| §16 Testing | All changes | CI pipeline |

### Single Source of Truth (SSOT)

The `.smartdrive/core/` directory is the **only** location for shared definitions:

| Module | Owns |
|--------|------|
| `.smartdrive/core/version.py` | `VERSION` constant |
| `.smartdrive/core/constants.py` | `ConfigKeys`, `UserInputs`, `CryptoParams`, `FileNames`, `Defaults`, `Prompts`, `GUIConfig`, `Branding` |
| `.smartdrive/core/paths.py` | `Paths` class (all filesystem paths), `normalize_mount_letter()` |
| `.smartdrive/core/limits.py` | `Limits` class (timeouts, retries, thresholds) |
| `.smartdrive/core/modes.py` | `SecurityMode`, `RecoveryOutcome` enums |

**Key SSOT Constants:**
- `FileNames.CONFIG_JSON` = `"config.json"` - configuration file name
- `ConfigKeys.LAST_UPDATED` = `"last_updated"` - timestamp key for updates
- `Paths.CONFIG_FILENAME` = `"config.json"` - equivalent path constant

**Rules:**
- No globals outside `.smartdrive/core/`
- No inline literals for shared concepts
- No star imports (`from module import *`)
- Path objects everywhere; `str()` only at I/O boundaries

### Deployed `.smartdrive` Layout is Canonical

The **deployed drive** is the authoritative execution context, not the development repo.
All scripts must work correctly when executed from `H:\.smartdrive\scripts\` (or equivalent).

**What "deployed-drive is canonical" means operationally:**
- Tests that only pass in repo context are insufficient
- Every script must bootstrap `sys.path` deterministically
- Missing files must cause explicit abort, not silent fallback
- Verification commands must target deployed paths

**Deployed Layout Verification:**
```powershell
# Verify recovery.py works from deployed path (Windows)
python H:\.smartdrive\scripts\recovery.py status
# Expected: exit 0, "recovery.py import verification: OK"
```

**Required Files in `.smartdrive/`:**
```
.smartdrive/
├── core/
│   ├── __init__.py
│   ├── version.py
│   ├── constants.py
│   ├── paths.py
│   ├── limits.py
│   └── modes.py
├── scripts/
│   ├── config.json
│   ├── recovery.py
│   ├── recovery_container.py
│   ├── mount.py
│   ├── unmount.py
│   └── ...
└── keys/
    └── keyfile.vc.gpg
```

If ANY required file is missing, setup MUST abort with explicit missing-file list.

### Path Computation Pattern for Deployed Scripts

All deployed scripts use a standardized path computation pattern:

```python
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
if _script_dir.parent.name == ".smartdrive":
   # Deployed context OR repo's .smartdrive/scripts/
   # DEPLOY_ROOT = .smartdrive/, add to sys.path for 'from core.x import y'
   smartdrive_root = _script_dir.parent     # .smartdrive/
   drive_root = smartdrive_root.parent      # DRIVE:\\ or repo_root
   if str(smartdrive_root) not in sys.path:
      sys.path.insert(0, str(smartdrive_root))
    # Detect if this is repo context (for deployment logic)
    is_repo = (drive_root / "AGENT_ARCHITECTURE.md").exists()
else:
    # Development: old scripts/script.py location (wrapper)
    _project_root = _script_dir.parent
```

**Key Terminology:**
- **smartdrive_root**: The `.smartdrive/` directory containing all runtime code
- **drive_root**: The parent of `.smartdrive/` (deployed drive root OR repo root)
- **is_repo**: True if running from repo (has `AGENT_ARCHITECTURE.md`), False if deployed

**Critical Invariant:** When running from `.smartdrive/scripts/`, `sys.path` must include
`smartdrive_root` (not `drive_root`) so that `from core.constants import ConfigKeys` works correctly.

### Module Responsibilities

| Script | Responsibility |
|--------|----------------|
| `setup.py` | Drive setup wizard; calls `recovery.generate_recovery_kit_from_setup()` directly |
| `recovery.py` | Recovery kit generation/usage; provides `generate_recovery_kit_from_setup()` for setup integration |
| `gui.py` | GUI implementation; uses `gui_i18n.tr()` for all user-visible strings |
| `gui_i18n.py` | GUI internationalization; `tr()` function with language fallback |

### Recovery Integration Invariant

When setup generates a recovery kit:
- Setup calls `recovery.generate_recovery_kit_from_setup(config_path, password, keyfile_bytes)` directly
- **No subprocess invocation** of `recovery.py`
- **No `--skip-auth` flag** exists in the codebase
- Credentials are passed in-memory from the verified setup context

**Why no subprocess/skip-auth:**
- Subprocess calls create security surface for flag injection
- `--skip-auth` semantics are dishonest (pretend to skip what was already done)
- Direct function call is explicit and auditable

**Failure behavior:**
- If recovery generation fails → setup HARD ABORTS
- User sees: "Recovery kit generation failed: [specific error]"
- Exit code: non-zero
- NO partial setup completion

### Windows VeraCrypt CLI Behavior

Windows and Linux use **different** VeraCrypt CLI syntaxes. Mixing them causes the "syntax incorrect" dialog.

| Platform | Flag Style | Example |
|----------|------------|---------|
| Windows | Forward slash | `/volume E: /letter Z /password secret /quit /silent` |
| Linux | Double dash | `--text --password=secret --mount /dev/sdb1 /mnt` |

**Why malformed argv causes errors:**
- VeraCrypt parses `/z` as flag, not mount letter
- Empty arguments confuse the parser
- Linux flags are unknown on Windows

**Single Allowed Windows Command Builder:**
```python
# In scripts/setup.py
def build_veracrypt_mount_cmd_windows(vc_exe, volume, mount_letter, password, ...):
    """
    ONLY function that builds Windows VeraCrypt commands.
    Uses normalize_mount_letter() to ensure canonical "Z" format.
    """
```

### GUI Internationalization (i18n)

**How GUI language is selected:**
1. Config key `gui_lang` in `config.json` (via `GUIConfig.GUI_LANG`)
2. If not set, defaults to `GUIConfig.DEFAULT_LANG` ("en")

**Translation fallback:**
1. Look up key in selected language
2. If missing, fall back to English
3. If missing in English → **KeyError** (fail loudly)

**Missing keys are handled by failing loudly:**
```python
# In gui_i18n.py
if key not in TRANSLATIONS.get("en", {}):
    raise KeyError(f"Translation key '{key}' not found")
```

**All GUI strings MUST use `tr()` function:**
```python
# CORRECT
self.mount_btn = QPushButton(tr("btn_mount", lang=get_lang()))

# FORBIDDEN
self.mount_btn = QPushButton("🔓 Mount")  # Hardcoded literal
```

### DO NOT Rules for Contributors and Agents

**DO NOT:**
- Add helpers outside `core/*` that influence behavior
- Use string concatenation for filesystem paths
- Claim behavior that is only unit-tested but not deployed-tested
- Add `--skip-auth` or similar bypass flags
- Use subprocess where direct function call is possible
- Leave hardcoded GUI strings
- Add silent fallbacks for security-critical operations
- Mix Windows and Linux VeraCrypt CLI flags
- Skip documentation when changing behavior

### Release Verification (No-Skips Policy)

{PRODUCT_NAME} enforces a **zero-skip release policy**. All tests must pass without skips for a release to be valid.

**Running release verification:**

```bash
# 1. Unit tests - must show 0 skipped, 0 failures
python -m pytest tests/ -v
# Expected: "XXX passed, 0 skipped"

# 2. E2E verification gate (Windows)
powershell -ExecutionPolicy Bypass -File tools/verify_e2e_windows.ps1 -SkipDestructiveTests
# Expected: "Passed: XX, Failed: 0, Skipped: 0"
```

**What E2E verifies:**

| Verification | Description |
|--------------|-------------|
| Safety Guardrail | Blocks setup on source disk |
| Security Modes | All 4 modes (PW_ONLY, PW_KEYFILE, PW_GPG_KEYFILE, GPG_PW_ONLY) |
| Run From Anywhere | Scripts work from any CWD |
| GUI Terminal Spawning | Terminal placement logic |
| Atomic Writes | Config saves atomically |
| Disk Identity | UniqueId-based matching |
| Settings UI | Headless Qt instantiation, schema round-trip |
| No Duplicates | Single config.json, single static/ |
| Branding Compliance | No forbidden terms |
| Cross-Drive Paths | PathResolver isolation |
| Update Flow SSOT | update.py uses Path exclusively |
| Cross-Drive Mount | Setup on A: can mount B: |
| tmp_key Regression | No UnboundLocalError |

**Cross-drive setup + mount behavior:**
- Setup executed from Drive A can target and mount volumes on Drive B
- `RuntimePaths.for_target()` creates isolated path bindings for the target drive
- Config path always resolves relative to the script location, not CWD
- Volume paths in config are passed directly to VeraCrypt unchanged

**Failure modes (explicit, deterministic):**
- Invalid volume path → RuntimeError with troubleshooting guide
- Missing keyfile → RuntimeError with path information  
- Mount failure → Detailed error with VeraCrypt exit code
- No silent fallbacks - all failures are loud

---

## 🔏 Script Integrity Verification
│  1. Verify GPG signature matches your key                       │
│     → Confirms signature is from YOUR key                       │
│  2. Recalculate hash, compare to stored hash                   │
│     → Confirms files haven't changed since signing             │
└─────────────────────────────────────────────────────────────────┘
```

### Using Integrity Verification

**Sign scripts (after setup or any modification):**
- From the LAUNCHER or System menu: Select "✍️ Sign scripts"
- Or manually:
  ```bash
  cd {KeyDrive_DIR_NAME}/integrity
  gpg --detach-sign scripts.sha256
  ```

**Verify scripts (before use, when you have suspicions):**
- From the LAUNCHER menu: Select "🔍 Verify script integrity"
- Or manually:
  ```bash
  cd {KeyDrive_DIR_NAME}/integrity
  gpg --verify scripts.sha256.sig scripts.sha256
  ```

### Security Notes

| Aspect | Detail |
|--------|--------|
| **What's protected** | All Python scripts in `{KeyDrive_DIR_NAME}/scripts/` folder |
| **Signing requires** | Your GPG private key (YubiKey if using hardware token) |
| **Verification requires** | Only your GPG public key (no YubiKey needed) |
| **When to verify** | After traveling, lending drive, or any suspicion of tampering |
| **Attack it prevents** | Modified scripts that steal credentials |
| **Attack it doesn't prevent** | Someone replacing EVERYTHING including your public key |

**Best practice:** Keep your GPG public key on a separate, trusted device or memorize the key fingerprint.

### ⚠️ Re-Signing Attack Vector

**Scenario:** An attacker gains access while your YubiKey is plugged in (e.g., you stepped away after mounting). They could:
1. Modify the scripts (add password stealer)
2. Re-sign with YOUR YubiKey that's still plugged in
3. Verification would PASS because it's a valid signature from your key!

**Mitigations:**

| Mitigation | How | Effectiveness |
|------------|-----|---------------|
| **Enable touch for signing** | `ykman openpgp keys set-touch sig on` | ✅ Best - blocks unattended signing |
| **Check signature timestamp** | Verification shows when scripts were signed | ✅ Good - notice unexpected recent signing |
| **Unplug YubiKey after mount** | Physical habit | ✅ Good - no key = no signing |
| **Separate signing key** | Use different YubiKey for signing | ✅ Best - decryption key can't sign |

**Recommended: Enable touch requirement for signing:**
```bash
# Requires physical touch for every signature operation
ykman openpgp keys set-touch sig on

# Check current touch policy
ykman openpgp info
```

With touch enabled, even if your YubiKey is plugged in, an attacker cannot sign without you physically touching the device.

## ⚠️ CRITICAL SECURITY WARNING: Drive Compromise Detection

**BEFORE USING ANY {PRODUCT_NAME} FEATURES, YOU MUST VERIFY YOUR DRIVE HAS NOT BEEN COMPROMISED.**

{PRODUCT_NAME} cannot protect you if your drive has already been tampered with. The only way to achieve true security is through **manual verification procedures** that you personally witness and control.

### Why Automated Verification Is Insufficient

Even the most sophisticated automated verification can be bypassed if your system is already compromised:

- **Malware can hook into hashing functions** and return correct responses
- **Tampered scripts can fake verification results**
- **Rootkits can intercept and modify verification calls**
- **Compromised systems can run "clean" verification software**

### The Only Secure Verification: Manual Partition Hashing

The **gold standard** for drive integrity verification is **manual hashing of your entire LAUNCHER partition** using tools you trust, following official server guidelines.

#### Manual Verification Process

1. **Verify Server Endpoint Authenticity**
   - **NEVER** enter a modified server URL
   - **ALWAYS** verify the domain is exactly the official one
   - Use HTTPS and verify SSL certificates
   - Cross-check the URL against official documentation

2. **Access Official Server**
   - Visit the official server website directly
   - Generate a challenge/salt manually
   - **Witness** that you're communicating with the legitimate server

3. **Manual Salt File Placement**
   - **Personally** copy the salt to your LAUNCHER partition
   - Place it in the correct directory as specified by official guidelines
   - **Verify** the file contents match what the server provided

4. **Manual Partition Hashing**
   - Use trusted, offline hashing tools
   - Hash your **entire LAUNCHER partition** (excluding config files that may move to VeraCrypt volume)
   - Follow the exact algorithm specified by the official server
   - **Witness** each step of the hashing process

5. **Manual Server Submission & Verification**
   - **Personally** submit the hash to the official server
   - **Witness** the server's validation response
   - **Verify** the response comes from the legitimate server

### Why This Manual Process Is Essential

| Automated Approach | Manual Approach |
|-------------------|-----------------|
| Can be spoofed by compromised system | Requires human witness at every step |
| Software can be tampered with | Uses trusted external tools |
| Results can be faked | Mathematically verifiable process |
| No user awareness required | Forces user understanding of security |

### Current Implementation Status

The current {PRODUCT_NAME} includes **automated directory hashing** as a **convenience feature only**. This provides basic integrity checking but **CANNOT** detect sophisticated compromises.

**For maximum security, always perform manual partition verification using official server guidelines.**

### When to Perform Verification

- **Before first use** of any {PRODUCT_NAME} on a new system
- **After any physical access** to your drive by others
- **After connecting to untrusted networks**
- **Before sensitive operations** (key changes, password resets)
- **Periodically** as part of your security routine
- **When you have any suspicion** of compromise

### Official Server Verification

**The server endpoint you enter must be the official, unaltered domain.** Any modification could indicate:
- DNS poisoning
- Man-in-the-middle attacks
- Compromised documentation
- Social engineering attempts

**Always verify the server URL against multiple trusted sources before entering it.**

## 🌐 Remote Integrity Verification (Challenge-Response)

{PRODUCT_NAME} provides **automated directory hashing** as a convenience feature, but **true security requires manual verification** that you personally witness and control.

### ⚠️ SECURITY LIMITATION

**The automated verification in {PRODUCT_NAME} CANNOT detect sophisticated system compromises.** For maximum security, follow the manual verification process above.

### Automated Directory Hashing (Convenience Feature)

For basic integrity checking, {PRODUCT_NAME} can automate the hashing process:

#### How Directory Hashing Works

```
Automated Client Side:
1. User enters server endpoint URL manually
2. User enters salt from server
3. System saves salt to scripts/.challenge_salt
4. System hashes entire scripts/ directory (including .challenge_salt)
5. System displays result for manual server submission
6. System cleans up .challenge_salt file

Automated Server Side:
1. Server has clean reference copy in reference_scripts/
2. Server saves same salt to reference_scripts/.challenge_salt  
3. Server hashes entire reference_scripts/ directory
4. Server compares with client hash
5. Server cleans up .challenge_salt file
```

#### Setup Automated Verification

1. **Set up the verification server:**
   ```bash
   pip install flask
   # Copy your clean scripts to reference_scripts/
   mkdir reference_scripts
   cp -r scripts/* reference_scripts/
   python hash_server.py
   ```

2. **Generate a challenge:**
   ```bash
   curl -X POST http://localhost:5000/api/generate-challenge \
     -H "Content-Type: application/json" \
     -d '{}'
   ```
   Response includes `challenge_id` and `salt`.

3. **Generate response hash:**
   - From {PRODUCT_NAME} menu: Select "🔐 Generate challenge hash"
   - Enter the server endpoint URL
   - Enter the salt from step 2
   - The system saves the salt to `.challenge_salt` in your scripts directory
   - Hashes the ENTIRE scripts directory including the salt file
   - Displays the resulting hash

4. **Verify with server:**
   ```bash
   curl -X POST http://localhost:5000/api/verify-challenge \
     -H "Content-Type: application/json" \
     -d '{
       "challenge_id": "your_challenge_id",
       "client_hash": "hash_from_KeyDrive",
       "server_endpoint": "your_server_endpoint"
     }'
   ```

### Security Comparison

| Method | Detects Script Tampering | Detects System Compromise | Requires User Witness |
|--------|-------------------------|--------------------------|---------------------|
| **Manual Partition Hashing** | ✅ Yes | ✅ Yes | ✅ Full witness required |
| **Automated Directory Hashing** | ✅ Yes | ❌ No (can be spoofed) | ⚠️ Partial witness |
| **Local GPG Only** | ⚠️ Limited | ❌ No | ❌ None |

**Recommendation:** Use automated verification for convenience, but perform manual partition verification for true security assurance.

---

## 🚀 Quick Start: Using the {PRODUCT_NAME} Manager

The easiest way to use {PRODUCT_NAME} is through the **unified CLI menu**:

**Windows:**
```
Double-click {BAT_LAUNCHER_NAME}
```

**Linux/macOS:**
```bash
./{SH_LAUNCHER_NAME}
```

**Or directly:**
```bash
python scripts/KeyDrive.py
```

### Unified Menu with Admin Gating

The CLI shows a **unified menu** with all operations organized into sections.
Operations that require administrator privileges are marked when not running as admin:

**Running WITHOUT administrator privileges:**
```
┌────────────────────────────────────────────────────────────────────┐
│  KeyDrive - Unified Menu                                         │
├────────────────────────────────────────────────────────────────────┤
│  VOLUME OPERATIONS                                                 │
│  [ 1] 🔓 Mount encrypted volume                                    │
│  [ 2] 🔒 Unmount volume                                            │
│                                                                    │
│  ────────────────────                                              │
│  SETUP & CONFIGURATION                                             │
│  [ 3] 🆕 Setup new encrypted drive                         [ADMIN] │
│  [ 4] 🔑 Change password / Rotate keyfile                  [ADMIN] │
│  [ 5] 🛠️  Keyfile utilities                                         │
│  [ 6] ℹ️  Show configuration & status                                │
│                                                                    │
│  ────────────────────                                              │
│  RECOVERY & SECURITY                                               │
│  [ 7] 🆘 Recovery Kit (emergency access)                           │
│  [ 8] ✍️  Sign scripts (create integrity signature)                  │
│  [ 9] 🔍 Verify script integrity (GPG signature)                   │
│  [10] 📋 Generate challenge hash (remote verification)             │
│                                                                    │
│  ────────────────────                                              │
│  SYSTEM                                                            │
│  [11] 📦 Update deployment drive                                   │
│  [12] 📖 Help / Documentation                                      │
│                                                                    │
│  [ 0] ❌ Exit                                                       │
├────────────────────────────────────────────────────────────────────┤
│  [ADMIN] = Requires administrator privileges to run                │
└────────────────────────────────────────────────────────────────────┘
```

**Admin requirements:**
- **Mount/Unmount**: Do NOT require admin - VeraCrypt handles its own UAC prompts
- **Setup**: Requires admin for disk partitioning
- **Rekey**: Requires admin for VeraCrypt password change operations

**Running AS administrator:**
- Same menu, but `[ADMIN]` markers are removed
- All operations are enabled and executable

**To run as administrator:**
- **Windows**: Right-click PowerShell → "Run as Administrator"
- **Linux/macOS**: `sudo python .KeyDrive/scripts/KeyDrive.py`

### System Drive Protection

Setup will **NEVER** allow a system drive as target, even when running as administrator.
System drives are shown in the drive selection list but cannot be selected:

```
⚠️  WARNING: System drives are shown but CANNOT be selected.
    Only external drives can be configured.
```

This protection is based on drive properties (`is_system`, `is_boot`), NOT on launch context.

---

## 🖥️ CLI Usage and Log Files

### CLI Entrypoint with --config

The CLI supports explicit config path specification for consistent behavior:

```bash
# Standard usage (auto-discovers config)
python .KeyDrive/scripts/KeyDrive.py

# Explicit config path (recommended for automation)
python .KeyDrive/scripts/KeyDrive.py --config /path/to/config.json

# Short form
python .KeyDrive/scripts/KeyDrive.py -c /path/to/config.json
```

**When to use `--config`:**
- Running from GUI → CLI transition (automatic)
- Automation scripts
- Multiple drives with separate configs
- Debugging path resolution issues

### Log File Locations

{PRODUCT_NAME} writes structured logs to help diagnose issues:

| Log Type | Location | Purpose |
|----------|----------|---------|
| **GUI Log** | `~/.KeyDrive/KeyDrive_gui.log` | GUI operations, window events |
| **Setup Log** | Console + structured events | Partition operations, safety checks |
| **Recovery Log** | `.KeyDrive/recovery/recovery.log` | Recovery attempts (sanitized) |

**Log format example:**
```
2024-01-15 10:23:45 INFO setup.mount_verification: path=E:\Payload expected_letter=V actual_letter=V result=success
2024-01-15 10:23:46 INFO safety.disk_identity.validated: unique_id=ABC123 bus_type=USB match=True
```

**Enabling verbose logging:**
- GUI: Window menu → "Open CLI Terminal" → logs appear in terminal
- CLI: Logs appear directly in console

---

## 🛡️ Safety Guardrails

### Disk Identity Protection

{PRODUCT_NAME} uses **unique disk identifiers** (not disk numbers) to prevent operations on the wrong drive:

| Check | Protection |
|-------|------------|
| **DiskIdentity.unique_id** | Hardware serial + unique GUID |
| **DiskIdentity.bus_type** | USB, SATA, NVMe validation |
| **System drive rejection** | Boot/system drives always blocked |
| **SSOT resolution** | All partition lookups use single resolver |

**Log evidence:**
```
safety.disk_identity.validated: unique_id=ABC123 bus_type=USB match=True
safety.disk_mismatch: expected_id=ABC123 actual_id=XYZ789 operation_blocked=True
```

### Security Mode Prerequisites

Each security mode has explicit prerequisites checked before operations:

| Mode | Requirements | Verification |
|------|--------------|--------------|
| **PW_ONLY** | Password only | Length + complexity check |
| **PW_KEYFILE** | Password + keyfile path | File exists + readable |
| **PW_GPG_KEYFILE** | Password + GPG-encrypted keyfile + YubiKey | GPG decrypt test |
| **GPG_PW_ONLY** | YubiKey + seed.gpg + HKDF params | GPG decrypt + KDF test |

**Log evidence:**
```
setup.mode_prerequisites.verified: mode=PW_GPG_KEYFILE gpg_ok=True keyfile_ok=True
```

---

## 🆘 Recovery & Emergency Access

### What is the Recovery System?

The Recovery System provides **emergency access** to your encrypted drive when you:
- 🔴 Lose your YubiKey (main + backup both lost/destroyed)
- 🔴 Forget your VeraCrypt password
- 🔴 Experience volume header corruption

**⚠️ CRITICAL SECURITY PRINCIPLES:**

| Principle | Description |
|-----------|-------------|
| **Container-based Recovery** | Your 24-word phrase decrypts an encrypted container holding your real credentials—it does NOT become a VeraCrypt password |
| **One-time after SUCCESS** | Each recovery kit is invalidated only after successful mount; a failed attempt does NOT burn your kit |
| **Mandatory Rekey** | After recovery, you MUST change credentials immediately |
| **Header Backup** | Separate from credential recovery; only used for corruption scenarios |
| **Argon2id Required** | No silent fallback to weaker KDF; recovery fails if `argon2-cffi` is missing |

### How Recovery Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  NORMAL ACCESS (YubiKey Mode):                                       │
│  Password + YubiKey → Decrypt keyfile → Mount VeraCrypt volume      │
│                                                                      │
│  RECOVERY ACCESS:                                                    │
│  24-word phrase → Decrypt recovery container → Extract real creds   │
│                 → Mount with original password + keyfile            │
│                 → ON SUCCESS: Container deleted + mandatory rekey   │
│                                                                      │
│  FAILED MOUNT: Container PRESERVED - retry recovery later           │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Security Properties:**

1. **BIP39 24-word phrase** (2048 words, proper checksum)
   - Generated using standard cryptocurrency wallet wordlist
   - 256 bits of entropy (same as strong encryption keys)

2. **Encrypted recovery container:**
   - AES-256-GCM encryption with Argon2id key derivation
   - Contains your actual mount credentials (password + keyfile bytes)
   - Stored on the encrypted volume at `.KeyDrive/recovery/`

3. **VeraCrypt header backup:**
   - Separate from credential recovery
   - Only used if volume header is corrupted
   - Allows recovery even if header is damaged

### Generating a Recovery Kit

**Prerequisites:**
- Volume must be mounted OR valid credentials must be provided
- Required dependencies: `pip install -r requirements.txt`

**Command:**
```bash
python scripts/recovery.py generate

# For offline-complete recovery (includes paper-encodable chunks):
python scripts/recovery.py generate --offline
```

**The generation process:**

1. **Authentication** - Verifies you have valid credentials
2. **Phrase generation** - Creates a 24-word BIP39 phrase
3. **Verification** - You must re-enter 3 random words to confirm recording
4. **Container creation** - Encrypts your credentials with the phrase
5. **Header export** - Backs up VeraCrypt volume header
6. **HTML kit** - Opens printable recovery document in browser

> **⏱️ Header Backup Timing:** The header backup step (step 5) may take up to 60 seconds due to VeraCrypt's PBKDF2 key derivation function. This is normal and expected - do not cancel the operation. If the VeraCrypt GUI opens, follow the on-screen instructions to complete the backup manually.

**What gets created:**

| File | Purpose |
|------|---------|
| `recovery_container.bin` | Encrypted credentials (AES-256-GCM) |
| `header_backup.hdr` | VeraCrypt header backup |
| `KeyDrive_Recovery_Kit.html` | Printable recovery document |

### Storing Your Recovery Kit

**⚠️ CRITICAL WARNINGS:**

- **PRINT the HTML document** immediately
- **DELETE the digital file** after printing
- **ANYONE with the phrase** can access your encrypted data
- **Store separately** from your encrypted drive

**Recommended Storage:**

| Method | Security | Notes |
|--------|----------|-------|
| Bank safe deposit box | 🟢 Excellent | Best for critical data |
| Fireproof home safe | 🟢 Good | Convenient access |
| Split storage (12 words × 2 locations) | 🟢 High | Requires both to recover |
| Sealed tamper-evident envelope | 🟡 Moderate | Use with trusted witness |

**NEVER:**
- Email it to yourself
- Store in cloud notes
- Take a photo "for backup"
- Keep with the encrypted drive

### Using Recovery (Emergency Access)

**When you need recovery:**
- Lost all YubiKeys AND forgot password
- Volume header is corrupted
- Standard mount fails with valid credentials

**Command:**
```bash
python scripts/recovery.py recover
```

**The recovery process:**

1. **Enter your 24-word phrase** (space-separated)
2. **Phrase validation** - BIP39 checksum verified
3. **Hash verification** - Confirms phrase matches this volume
4. **Container decryption** - Extracts your real credentials
5. **Container deletion** - ONE-TIME USE ENFORCEMENT
6. **Volume mount** - Uses recovered credentials
7. **Header restoration** - If corruption detected, restores from backup
8. **Mandatory rekey** - You MUST change credentials

**After successful recovery:**

⚠️ **MANDATORY ACTIONS:**

1. Complete the rekey wizard (starts automatically)
2. Generate a NEW recovery kit: `python scripts/recovery.py generate`
3. **Destroy** your old printed recovery phrase

### Offline Reconstruction

If you've lost the digital recovery files but have the printed paper backup with chunk data:

```bash
# Copy all SDRC:v1:... chunks to a text file
python scripts/recovery.py reconstruct chunks.txt
```

This rebuilds `recovery_container.bin` from the paper chunks, allowing you to then run `python scripts/recovery.py recover`.

### Security Considerations

**Threat Model:**

| Threat | Without Recovery | With Recovery | Mitigation |
|--------|------------------|---------------|------------|
| Lost YubiKey | 🔴 Data lost | 🟢 Recoverable | Backup YubiKey |
| Forgotten password | 🔴 Data lost | 🟢 Recoverable | Password manager |
| Stolen recovery phrase | ✅ N/A | 🔴 Full compromise | Physical security |
| Header corruption | 🔴 Data lost | 🟢 Recoverable | Header backup |

**When NOT to create a recovery kit:**

1. **Maximum security requirements** - No backdoor = no recovery = no attack vector
2. **Plausible deniability** - Recovery phrase proves volume exists
3. **Cannot guarantee secure storage** - Don't create what you can't protect

### Technical Reference

For developers and auditors, see [docs/RECOVERY_TECHNICAL.md](docs/RECOVERY_TECHNICAL.md) for:
- Container binary format specification
- Encryption parameters (AES-256-GCM, Argon2id)
- Chunk encoding for paper backup
- Implementation details

---

## 🔄 Rebranding & Customization

{PRODUCT_NAME} is designed to be easily rebrandable for different use cases, organizations, or deployments. The entire product name and branding can be changed by modifying a single configuration file.

### How to Rebrand

1. **Edit `constants.py`** in the project root:
   ```python
   PRODUCT_NAME = "YourCustomName"  # Change this line
   ```

2. **Rebuild the GUI executable** (if using the GUI):
   ```bash
   python -m PyInstaller KeyDriveGUI.spec
   ```

3. **Update launcher scripts** (optional, for complete rebranding):
   - Rename `KeyDrive.bat` → `YourCustomName.bat`
   - Rename `KeyDriveGUI.bat` → `YourCustomNameGUI.bat`
   - Rename `keydrive.sh` → `yourcustomname.sh`

### What Gets Automatically Updated

When you change `PRODUCT_NAME` in `constants.py`, the following are automatically updated:

- **Volume labels** on encrypted drives (e.g., "KeyDrive1" → "YourCustomName1")
- **Window titles** in the GUI application
- **CLI menu banners** and prompts
- **File deployment names** (executables, scripts, documentation)
- **Setup wizard** output and prompts
- **Configuration file** references

### What Requires Manual Updates

Some files still need manual renaming for complete rebranding:

- **Launcher scripts:** `.bat` and `.sh` files in project root
- **PyInstaller spec file:** `KeyDriveGUI.spec` → `YourCustomNameGUI.spec`
- **Documentation:** This README.md (variables render to branded names)
- **Build artifacts:** Generated executables and installers

### Example Rebranding

```python
# constants.py
PRODUCT_NAME = "SecureVault"
```

Results in:
- Drives labeled "SecureVault1", "SecureVault2", etc.
- GUI window titled "SecureVault"
- CLI menus showing "SecureVault Manager"
- Files deployed as "SecureVault.bat", "SecureVaultGUI.exe", etc.

### PDF/Documentation Rendering

When converting this README to PDF or other formats, the `{PRODUCT_NAME}` variables will automatically render to your chosen product name, making documentation automatically branded.

---

## ⚠️ CRITICAL SAFETY WARNINGS

### DO NOT Target System Drives!

**{PRODUCT_NAME} includes safety checks to prevent catastrophic data loss.**

#### Dangerous Volume Paths (Never Use These):

**Windows:**
- ❌ `C:\` or `C:\\` (system drive)
- ❌ `\\Device\Harddisk0\Partition*` (first physical disk - usually system)
- ✅ `\\Device\Harddisk1\Partition2` or higher (external drives)

**Linux:**
- ❌ `/dev/sda*` (first disk - usually system)
- ❌ `/dev/nvme0n1*` (first NVMe - usually system)
- ❌ `/dev/vda*` (first virtual disk in VMs)
- ✅ `/dev/sdb*` or `/dev/sdc*` (external drives)

**macOS:**
- ❌ `/dev/disk0*` (first disk - usually system)
- ✅ `/dev/disk2*` or higher (external drives)

#### How to Identify Your External Drive Safely:

**Windows (PowerShell):**
```powershell
Get-Disk | Format-Table Number, FriendlyName, BusType, Size
# Look for: BusType = USB or FriendlyName containing your drive brand
# Example output:
#   Number FriendlyName           BusType    Size
#   0      Samsung SSD 980        NVMe       500GB  ← System (DON'T USE)
#   1      SanDisk Ultra USB 3.0  USB        128GB  ← External (SAFE)
```

**Linux:**
```bash
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,TRAN
# Look for: TRAN = usb
# Example output:
#   NAME   SIZE TYPE MOUNTPOINT TRAN
#   sda    500G disk /          sata  ← System (DON'T USE)
#   sdb    128G disk            usb   ← External (SAFE)
```

**macOS:**
```bash
diskutil list
# External drives are typically disk2 or higher
# disk0 is usually your system drive (DON'T USE)
```

---

## 🚀 Quick Start

### Prerequisites

1. **Install dependencies:**
   - **GPG/GnuPG:**
     - Windows: [Gpg4win](https://www.gpg4win.org/)
     - Linux: `sudo apt install gnupg` (usually pre-installed)
     - macOS: `brew install gnupg`
   - **VeraCrypt:** [Download here](https://www.veracrypt.fr/en/Downloads.html)
   - **Python 3.7+**: Should be installed on most systems

2. **Configure YubiKeys:**
   - Set up GPG keys on two YubiKeys (main + backup)
   - **Get fingerprints for both keys:**
     ```bash
     # Insert YubiKey
     gpg --card-status              # Imports key if not already present
     gpg --list-keys --fingerprint  # Shows fingerprint directly
     ```
   - **Example output:**
     ```
     pub   rsa4096/183999995BCBDACD 2021-06-15 [SC]
           20795EBE7248969E0A5AE9F1183999995BCBDACD  ← Copy this line
     uid                 [ultimate] Your Name <email@example.com>
     ```
   - Copy the **40-character hex string** (the indented line)
   - Repeat for your backup YubiKey

### Step 1: Create VeraCrypt Volume (Password Only)

**Option A: Use the Setup Wizard (Recommended)**

The {PRODUCT_NAME} setup wizard provides full automation for preparing a new external drive:

```bash
cd scripts
python setup.py
```

**The wizard will:**
1. **Phase 1 - DRIVE SELECTION:** List all external drives with size/bus info, let you choose one
2. **Phase 2 - CONFIGURATION:** Set partition sizes, encryption options, optionally select YubiKeys
3. **Phase 3 - REVIEW & CONFIRM:** Show all settings, require typing `ERASE` to confirm
4. **Phase 4 - EXECUTE:** Partition drive (MBR), create VeraCrypt volume via GUI, deploy scripts
5. **Phase 5 - VERIFY:** Test-mount the new volume to confirm everything works

**⚠️ DESTRUCTIVE OPERATION:** The wizard will erase ALL data on the selected drive!

**Key Features:**
- 📋 Uses **MBR partitioning** (more compatible with USB drives than GPT)
- 🔐 **YubiKey is optional** - supports password-only or plain keyfile modes
- 🖥️ Opens **VeraCrypt GUI** for volume creation (more reliable than CLI for partitions)
- ✅ **Automatic verification** - test-mounts to confirm credentials work

---

**Option B: Manual Setup (Advanced)**

Create a VeraCrypt volume with **password only** first (no keyfile):

1. Open VeraCrypt GUI
2. Click **"Create Volume"**
3. Select **"Encrypt a non-system partition/drive"**
4. Choose your external drive's data partition
5. Set encryption algorithm (AES is fine)
6. Set a **strong password**
7. **Skip keyfile for now** (we'll add YubiKey protection next)
8. Complete the encryption process

### Step 2: Add YubiKey Protection (Manual Setup Only)

**Skip this step if you used the Setup Wizard (Option A) - it's already done!**

Use `rekey.py` to add YubiKey-encrypted keyfile protection.
This is the **recommended approach** - no plaintext keyfile ever touches disk!

```bash
cd scripts
python rekey.py
```

**You will be prompted for:**
- Current keyfile: **n** (no - you created with password only)
- New keyfile: **y** (yes)
- Select YubiKey fingerprints (main + backup recommended)
- Complete the credential change in VeraCrypt GUI
- Enter new password for verification

**Result:** Volume now protected by password + YubiKey-encrypted keyfile!

### Step 3: Configure Mount Script (Manual Setup Only)

**Skip this step if you used the Setup Wizard (Option A) - config.json is auto-generated!**

Run `mount.py` to generate config:

```bash
cd scripts
python mount.py
```

On first run, it creates `config.json`. **Edit it** with your volume path:

```json
{
  "encrypted_keyfile": "../keys/keyfile.vc.gpg",
  "windows": {
    "volume_path": "\\\\Device\\\\Harddisk1\\\\Partition2",
    "mount_letter": "V",
    "veracrypt_path": ""
  },
  "unix": {
    "volume_path": "/dev/sdX2",
    "mount_point": "~/veradrive"
  }
}
```

**Key settings to update:**
- `windows.volume_path`: Your drive's device path or container file path
  - Find device path: `wmic diskdrive list brief` → `\\Device\Harddisk#\Partition#`
  - Or use a file: `E:\\vault.hc`
- `unix.volume_path`: Linux/macOS device path (e.g., `/dev/sdb2`) or container file

### Step 4: Daily Use (Both Options)

**Mount:**
```bash
python mount.py
```

**Unmount:**
```bash
python unmount.py
```

**What happens depends on your config:**

| Config State | Behavior |
|--------------|----------|
| `encrypted_keyfile` set + file exists | GPG decrypts keyfile → YubiKey PIN required |
| `plain_keyfile` set + file exists | Uses keyfile directly (no GPG/YubiKey) |
| Neither set | Password-only mode |

**Result:** Volume mounted at:
- Windows: Drive letter (e.g., `M:`)
- Linux/macOS: Mount point (e.g., `~/veradrive`)

### Unmounting

```bash
# Unmount using config.json settings
python unmount.py

# Unmount specific drive (Windows)
python unmount.py V

# Unmount specific mount point (Linux/macOS)
python unmount.py ~/veradrive

# Unmount all VeraCrypt volumes
python unmount.py --all
```

---

## 🔄 Rotating Credentials (YubiKey Replacement / Password Change)

### When to Use `rekey.py`

Use this script when you need to:
- ✅ Replace a lost or compromised YubiKey
- ✅ Change VeraCrypt password
- ✅ Add YubiKey protection to an existing password-only volume
- ✅ Rotate encryption keys for security best practices
- ✅ Remove keyfile protection (switch to password-only)

### `rekey.py` Features

- 🎨 **Polished 4-phase UI** matching `setup.py` style
- 📋 **Step-by-step GUI instructions** for VeraCrypt credential changes
- ✅ **Automatic verification** - test-mounts before committing changes
- 🔄 **Backup creation** - old keyfile saved as `.old`
- 🗑️ **Secure cleanup** - temporary files securely deleted

### Workflow: Secure Initial Setup (Recommended)

This workflow **avoids handling plaintext keyfiles** during initial setup:

1. **Create VeraCrypt volume with simple password only** (no keyfile):
   - Use VeraCrypt GUI or `setup.py` wizard
   - Set a temporary password
   - Do NOT add a keyfile yet

2. **Copy KeyDrive scripts to LAUNCHER partition** (or use `setup.py` to auto-deploy)

3. **Run rekey.py to add YubiKey protection:**
   ```bash
   cd G:\scripts  # Your LAUNCHER partition
   python rekey.py
   ```
   
   **You'll be prompted for:**
   - Current keyfile: `n` (no)
   - Use NEW keyfile: `y` (yes)
   - Select YubiKey fingerprints: (choose main + backup)

4. **Result:**
   - Volume now protected by: **new password + YubiKey-encrypted keyfile**
   - No plaintext keyfile ever existed on disk!
   - `keys/keyfile.vc.gpg` created and ready to use

### Workflow: YubiKey Replacement

If you lose a YubiKey or want to replace it:

```bash
cd G:\scripts  # Your LAUNCHER partition
python rekey.py
```

**Example session (condensed):**
```
══════════════════════════════════════════════════════════════════════
   ╔══════════════════════════════════════════════════════════════╗
   ║             KeyDrive CREDENTIAL ROTATION                   ║
   ╚══════════════════════════════════════════════════════════════╝
══════════════════════════════════════════════════════════════════════

══[ Phase 1 of 4: CURRENT CREDENTIALS ]═══════════════════════════════
Volume: \Device\Harddisk1\Partition2
Does this volume currently use a keyfile? (y/n): y
...

══[ Phase 2 of 4: NEW CREDENTIALS ]═══════════════════════════════════
Use a NEW keyfile encrypted to YubiKeys? (y/n): y
Select YubiKey(s) - choose fingerprints for main + backup keys...

══[ Phase 3 of 4: REVIEW & CONFIRM ]══════════════════════════════════
  Volume:        \Device\Harddisk1\Partition2
  Old keyfile:   Yes → GPG-encrypted
  New keyfile:   Yes → newly generated, encrypted to 2 keys
Proceed? (yes/no): yes

══[ Phase 4 of 4: EXECUTE & VERIFY ]══════════════════════════════════
[Step 1/3] Opening VeraCrypt GUI for credential change...
           (detailed 16-step instructions displayed)

[Step 2/3] VERIFYING NEW CREDENTIALS
           Enter NEW password: ************
           ✓ Test mount successful!
           ✓ New credentials verified successfully!

[Step 3/3] FINALIZING
           ✓ Old temporary keyfile securely deleted
           ✓ New encrypted keyfile saved: keyfile.vc.gpg

══════════════════════════════════════════════════════════════════════
  ╔═══════════════════════════════════════════════════════════════╗
  ║                    ✓ SUCCESS!                                 ║
  ╚═══════════════════════════════════════════════════════════════╝
══════════════════════════════════════════════════════════════════════
  💡 Test mount.py before deleting the .old backup!
```

### Safety Features

- ✅ **Separate YubiKey selection** for decrypting old vs encrypting new keyfile
- ✅ **Automatic verification** - test mounts with new credentials before committing
- ✅ **Manual confirmation** - asks if GUI operation succeeded
- ✅ **Creates backup** of old encrypted keyfile (`.old`)
- ✅ **Secure cleanup** of temporary plaintext keyfiles
- ✅ **Multi-YubiKey support** (main + backup + more)
- ✅ **Rollback on failure** - if verification fails, original keyfile untouched

### After Rekeying

1. **Verification is automatic:**
   - The script test-mounts with your new credentials before saving
   - If verification fails, your original keyfile is NOT replaced
   - You can safely retry the rekey process

2. **If successful:**
   - ✅ Keep `keys/keyfile.vc.gpg` (new)
   - ✅ Delete `keys/keyfile.vc.gpg.old` (old backup)
   - ✅ Update any backup copies

3. **If verification failed:**
   - Original keyfile was never replaced
   - Check what went wrong in VeraCrypt GUI
   - Try rekey again with correct credentials

---

## 🔑 Keyfile Utility (`keyfile.py`)

Manual utility for YubiKey-encrypted file operations. Use for backup, recovery, or migration.

### Commands

```bash
# Create new VeraCrypt keyfile encrypted to YubiKeys
python keyfile.py create
python keyfile.py create --output /path/to/keyfile.gpg

# Encrypt any file to YubiKeys
python keyfile.py encrypt secrets.txt
python keyfile.py encrypt data.bin --output encrypted.gpg

# Decrypt any GPG-encrypted file
python keyfile.py decrypt keyfile.vc.gpg
python keyfile.py decrypt data.gpg --output decrypted.bin
```

### Use Cases

| Scenario | Command |
|----------|---------|
| Manual keyfile backup | `keyfile.py create` |
| Recover from rekey failure | `keyfile.py decrypt keys/keyfile.vc.gpg.old` |
| Migrate away from YubiKey | `keyfile.py decrypt` → use plain keyfile |
| Encrypt other sensitive files | `keyfile.py encrypt myfile` |

### Security Warning

When using `keyfile.py decrypt`, the output is a **plaintext file**!
- Use it only when absolutely necessary
- Securely delete when done:
  - Windows: `cipher /w:<path>`
  - Linux: `shred -u <path>`

---

## 🔧 Configuration Reference

### `config.json` Schema

| Field | Description | Example |
|-------|-------------|----------|
| `drive_id` | Unique UUIDv4 identifier for this drive (auto-generated) | `"a1b2c3d4-e5f6-4a7b-8c9d-e0f1a2b3c4d5"` |
| `encrypted_keyfile` | Path to GPG-encrypted keyfile (optional) | `"../keys/keyfile.vc.gpg"` |
| `plain_keyfile` | Path to plain keyfile - no GPG (optional) | `"../keys/keyfile.bin"` |
| `windows.volume_path` | Device path or container file (Windows) | `"\\Device\\Harddisk1\\Partition2"` or `"E:\\vault.hc"` |
| `windows.mount_letter` | Drive letter for mounting | `"M"` |
| `windows.veracrypt_path` | Override VeraCrypt.exe path (optional) | `"C:\\VeraCrypt\\VeraCrypt.exe"` |
| `unix.volume_path` | Device path or container file (Unix) | `"/dev/sdb2"` or `"/media/vault.hc"` |
| `unix.mount_point` | Where to mount the volume | `"~/veradrive"` |
| `lost_and_found.enabled` | Enable lost & found return message (bool) | `true` |
| `lost_and_found.message` | Message for lost drive (max 500 chars) | `"Return to alice@example.com for 10% finder's fee"` |

**Drive ID:** Automatically generated UUIDv4 on first run. Used for single-instance enforcement and drive identification. Never regenerated unless manually reset.

**Lost & Found:** Optional contact information displayed in UI. Plain text only, max 500 characters. Does not enable automatic printing/labeling.

**Keyfile Priority:** If both `encrypted_keyfile` and `plain_keyfile` are set, `encrypted_keyfile` takes precedence.

**Password-Only Mode:** Omit both keyfile fields (or set to empty string) for password-only protection.

### Finding Your Device Path

#### Windows
```powershell
# List all disks
Get-Disk

# List partitions on a specific disk (e.g., Disk 1)
Get-Partition -DiskNumber 1

# Device path format: \\Device\Harddisk<N>\Partition<M>
# Example: \\Device\Harddisk1\Partition2
```

#### Linux
```bash
# List all block devices
lsblk

# Show detailed info
sudo fdisk -l

# Example: /dev/sdb2 (second partition on second disk)
```

#### macOS
```bash
# List disks
diskutil list

# Example: /dev/disk2s2
```

## 🏗️ Deployment to External Drive

### Recommended Disk Layout

**setup.py creates this automatically using MBR partitioning:**

1. **Partition 1 – LAUNCHER** (configurable, default ~500 MB, exFAT)
   - `scripts/mount.py`
   - `scripts/unmount.py`
   - `scripts/rekey.py`
   - `scripts/config.json`
   - `keys/keyfile.vc.gpg` (if using YubiKey mode)
   - (Future) Portable Python + VeraCrypt

2. **Partition 2 – PAYLOAD** (rest of disk)
   - VeraCrypt encrypted volume

### Why MBR Instead of GPT?

- ✅ **Better USB compatibility** - works on more systems
- ✅ **BIOS and UEFI support** - boots everywhere
- ✅ **Simpler structure** - fewer hidden partitions
- ⚠️ 2TB limit per partition (sufficient for most USB drives)

### Manual Setup Instructions (if not using setup.py)

1. **Partition your external drive (MBR recommended):**
   - Windows: `diskpart` with `convert mbr`
   - Linux: `fdisk` (defaults to MBR for small disks)
   - macOS: Disk Utility → "Master Boot Record" scheme

2. **Format Partition 1** as exFAT (cross-platform compatible)

3. **Copy to LAUNCHER partition:**
   ```bash
   cp scripts/mount.py <LAUNCHER>/scripts/mount.py
   cp scripts/unmount.py <LAUNCHER>/scripts/unmount.py
   cp scripts/config.json <LAUNCHER>/scripts/config.json
   cp keys/keyfile.vc.gpg <LAUNCHER>/keys/keyfile.vc.gpg  # if using YubiKey
   ```

4. **Update `config.json`** paths if needed (keyfile path should be relative)

5. **Create VeraCrypt volume** on Partition 2 using the steps above

## 🛡️ Security Best Practices

### For All Modes
- ✅ **Use a strong VeraCrypt password** (12+ characters, mixed case, symbols)
- ✅ **Double-check device paths** before creating VeraCrypt volumes
- ✅ **Use `Get-Disk` (Windows) or `lsblk` (Linux)** to verify external drives
- ❌ **Never store plaintext `keyfile.bin`** permanently
- ❌ **Never target system drives** (C:, /dev/sda, /dev/disk0)

### For YubiKey Mode
- ✅ **Store backup YubiKey securely** (safe deposit box, trusted location)
- ✅ **Enable YubiKey touch requirement** for extra security (optional)
- ✅ **Test backup YubiKey periodically** to ensure it works
- ✅ **Keep GPG public keys backed up** (for re-encrypting if needed)
- ❌ **Don't share YubiKey PIN** with anyone

### Why Use GPG Key Fingerprints Instead of Key IDs?

**Short Answer:** Fingerprints are **more secure and unambiguous**.

**Technical Details:**

| Property | Key ID (Short) | Key ID (Long) | Fingerprint |
|----------|---------------|---------------|-------------|
| **Length** | 8 hex chars (32 bits) | 16 hex chars (64 bits) | 40 hex chars (160 bits) |
| **Example** | `5BCBDACD` | `183999995BCBDACD` | `20795EBE7248969E0A5AE9F1183999995BCBDACD` |
| **Collision Risk** | 🔴 High (easily forged) | 🟡 Moderate | 🟢 Negligible |
| **Uniqueness** | ❌ Not guaranteed | ⚠️ Reasonably unique | ✅ Globally unique |

**Security Implications:**

1. **Short Key IDs are deprecated:**
   - Only 32 bits → ~4 billion possible values
   - Attackers can generate colliding keys in minutes
   - Example: Create a malicious key with same ID as yours

2. **Long Key IDs are better but not perfect:**
   - 64 bits → harder to collide but still possible
   - Some tools still accept short IDs, causing confusion

3. **Fingerprints are cryptographically strong:**
   - 160 bits → SHA-1 hash of entire public key
   - Practically impossible to forge a colliding key
   - Uniquely identifies the exact key

**Practical Example:**

When you encrypt to a fingerprint:
```bash
gpg --encrypt -r 20795EBE7248969E0A5AE9F1183999995BCBDACD keyfile.bin
```

GPG **guarantees** it's encrypting to the **exact key** you intended, not a fake key with a colliding short ID.

**Why This Matters for KeyDrive:**

Your VeraCrypt keyfile is the master secret protecting all your data. If an attacker could trick GPG into encrypting to their malicious key (via key ID collision), they could:
- Intercept your keyfile
- Decrypt your VeraCrypt volume
- Steal all your data

Using fingerprints eliminates this attack vector entirely.

---

## 🐛 Troubleshooting

### "gpg not found in PATH"
- **Windows:** Install Gpg4win and add to PATH: `C:\Program Files (x86)\GnuPG\bin`
- **Linux/macOS:** Install via package manager
- **Note:** GPG is only needed if using YubiKey mode (encrypted keyfile)

### "Could not find VeraCrypt.exe"
- Set `windows.veracrypt_path` in `config.json` to the full path
- Or install VeraCrypt to default location
- Common paths: `C:\Program Files\VeraCrypt\VeraCrypt.exe`

### "Encrypted keyfile not found"
- Verify `encrypted_keyfile` path in `config.json` is correct
- Path should be relative to `mount.py` location
- **Alternative:** Use password-only mode by removing the keyfile field

### YubiKey not detected
- Insert YubiKey and run: `gpg --card-status`
- May need to restart `gpg-agent`: `gpgconf --kill gpg-agent`
- **Windows:** Try running as Administrator

### VeraCrypt mount fails
- Verify password is correct
- Check that `volume_path` in config matches your actual device/file
- Ensure VeraCrypt volume was created with the same keyfile (if any)
- **Check for double-escaped backslashes:** `\\Device` not `\\\\Device`

### "Permission denied" on Linux
- May need sudo: `sudo python mount.py`
- Or add user to disk group: `sudo usermod -aG disk $USER`

### "SAFETY CHECK FAILED" error
- **This is intentional protection!**
- Review your `config.json` → `volume_path` setting
- Use `Get-Disk` (Windows) or `lsblk` (Linux) to verify external drive
- Ensure you're targeting Harddisk1+ (Windows) or sdb+ (Linux)
- **Never override safety checks** unless absolutely certain

### setup.py "Convert GPT failed"
- This happens on disks already formatted as MBR
- setup.py now uses MBR by default (better USB compatibility)
- If you see this error on an older version, update setup.py

### Volume mounts but shows wrong size
- VeraCrypt CLI has issues with partition encryption
- setup.py now uses VeraCrypt GUI for volume creation
- For manual setup, always use the GUI for partition encryption

### Mount fails with "AttributeError: 'NoneType' object has no attribute 'strip'"
- **Cause:** `config.json` contains `null` values instead of empty strings
- **Example:** `"volume_path": null` or `"mount_letter": null`
- **Fix:** Replace `null` with `""` (empty string) in config.json
- **Automated fix:** Run mount operation again - the normalization layer will coerce `null`→`""`
- **Verification:** Check `.KeyDrive/logs/` for `mount.inputs.normalized` entries
- **Prevention:** Edit config.json manually using text editor, ensure all string fields use `""` not `null`
- **Root cause:** JSON `null` values bypass Python dict `.get(key, "")` default value

### Lost YubiKey or forgot password
- **YubiKey lost:** Use backup YubiKey (if you have one enrolled)
- **Password forgotten:** Use Emergency Recovery Kit (if you generated one)
- **Both YubiKey AND password lost:** Recovery Kit is your only option
- **No recovery kit generated:** Data is unrecoverable (by design - no backdoor)
- See the **🆘 Emergency Recovery Kit** section above for full details

### Recovery phrase doesn't work
- Verify word order (must be exact 1-24 sequence)
- Check for typos (BIP39 words are case-sensitive)
- Ensure using current recovery phrase (not expired/old)
- Check `config.json` → `recovery.created_date` vs last password change
- If volume was rekeyed after recovery generation, old phrase won't work

### Mount fails with "_mount_logger not defined"
- **Cause:** Module-level logger not initialized in mount.py
- **Fix:** Update to latest version with `python .KeyDrive/scripts/update.py --drive <LETTER> --yes`
- **Workaround:** Manually add `import logging` and `_mount_logger = logging.getLogger("KeyDrive.mount")` at top of mount.py
- **Verification:** Run `python -c "from scripts.mount import _mount_logger; print(_mount_logger.name)"`

### CLI Terminal window too small/large
- **Cause:** Terminal dimensions not optimized for CLI menu display
- **Solution:** The GUI opens terminals with A4 proportions (120x30 characters)
- **Manual adjustment:** Resize the terminal window after opening
- **Config:** Terminal size is set in `gui.py` → `open_cli()` → `terminal_cols`, `terminal_rows`

### CLI Terminal doesn't appear next to GUI
- **Cause:** Window positioning depends on monitor bounds detection
- **Windows:** Terminal should appear to the right of GUI (or left if insufficient space)
- **Check logs:** Look for `cli.launch.elevated` or `cli.launch.normal` in `.KeyDrive/logs/`
- **Workaround:** If positioning fails, terminal appears at default location

### Keys directory path error (looking in wrong location)
- **Symptom:** Mount fails looking for `H:\keys\seed.gpg` instead of `H:\.KeyDrive\keys\seed.gpg`
- **Cause:** Legacy config with relative paths like `"../keys/seed.gpg"`
- **Fix:** Keys MUST be stored under `.KeyDrive/keys/`, not at drive root
- **SSOT:** Path resolution uses `core/paths.py` → `Paths.seed_gpg(launcher_root)`
- **Migration:** Move keys from `<drive>:\keys\` to `<drive>:\.KeyDrive\keys\`

---

## 📁 Repository File Structure

This project uses a structured file organization for maintainability:

```
VeraCrypt_Yubikey_2FA/
├── .KeyDrive/                    # Deployed to drive (runtime files)
│   ├── core/                       # SSOT modules (authoritative)
│   │   ├── constants.py            # ConfigKeys, CryptoParams, etc.
│   │   ├── paths.py                # Filesystem paths (Paths class)
│   │   ├── modes.py                # SecurityMode, RecoveryOutcome enums
│   │   └── ...
│   ├── scripts/                    # Runtime scripts
│   │   ├── mount.py, unmount.py    # Volume operations
│   │   ├── gui.py                  # GUI implementation
│   │   ├── KeyDrive.py           # CLI menu launcher
│   │   └── ...
│   └── keys/                       # Encrypted keyfiles (per-drive)
│
├── scripts/                        # Development-only scripts
│   ├── audit_repo_health.py        # Repository health checker
│   ├── quarantine.py               # Obsolete file management
│   └── check_*.py                  # Enforcement scripts
│
├── tests/                          # Test suite
├── obsolete/                       # Quarantined files (dated folders)
└── reports/                        # Generated audit reports
```

### Repository Health Management

Run the health audit to detect unused files and deprecated references:

```bash
python scripts/audit_repo_health.py
```

To safely remove obsolete files (moves to quarantine with documentation):

```bash
python scripts/quarantine.py <file> --reason "Why obsolete" --replacement "new_file.py"
```

See `AGENT_ARCHITECTURE.md` Section 15 for detailed file management policies.

## 📜 Changelog

### v1.2.0 (December 2025)
- **New Feature:** GPG Password-Only mode (`gpg_pw_only`)
  - Mount with YubiKey PIN/touch only (no password typing)
  - Uses HKDF-SHA256 to derive VeraCrypt password from GPG-encrypted seed
  - No decrypted secrets written to persistent disk
  - Automatic RAM-backed temp handling for security
- **Schema Update:** Config schema v2 with mode-specific fields
- **Enhanced Security:** Secure deletion and memory hygiene improvements

### v1.1.3 (December 2025)
- **Security Enhancement:** Automatic RAM-backed temporary files for decrypted keyfiles
  - Uses `/dev/shm` on Linux (never touches persistent storage)
  - Falls back to secure system temp on Windows/macOS
  - Implements secure deletion with multiple overwrite passes
  - Minimizes forensic recovery risk on untrusted devices

### v1.1.2
- GUI improvements and icon handling fixes
- Enhanced phishing resistance features

### v1.1.1
- Cross-platform CLI improvements
- Drive update automation

### v1.1.0
- Initial public release
- YubiKey + GPG integration
- Emergency recovery system
- Cross-platform support (Windows, Linux, macOS)

---

## 🧪 End-to-End Hardware Verification (Release Gate)

**Before any release**, run the E2E verification to prove the system works on real hardware.

### Quick Start

```powershell
# Windows (PowerShell as Administrator for full tests)
.\tools\verify_e2e_windows.ps1

# Interactive mode - prompts for USB disk selection
# Runs 6 verification suites:
#   1. Safety Guardrail (BLOCKS source disk destruction)
#   2. Security Mode Matrix (all 4 modes validated)
#   3. Run From Anywhere (path resolution)
#   4. GUI→CLI Terminal Logic (spawn positioning)
#   5. Atomic Writes (no data loss on crash)
#   6. Disk Identity Contract (UniqueId over disk number)
```

### What E2E Verification Proves

| Verification | What It Tests | Pass Criteria |
|--------------|--------------|---------------|
| **Safety Guardrail** | Source disk cannot be wiped | SetupSafetyPolicy.validate_before_partition() returns BLOCKED for source disk |
| **Security Modes** | All 4 modes from `core/modes.py` | SecurityMode enum validates, display names correct |
| **Run From Anywhere** | Scripts work from any CWD | `KeyDrive.py --help` succeeds from Home, Temp, System32 |
| **GUI→CLI Spawn** | Terminal positioning logic | `_compute_terminal_rect_windows` calculation runs without error |
| **Atomic Writes** | Config writes are crash-safe | `write_config_atomic()` creates file with no temp remnants |
| **DiskIdentity** | Uses UniqueId not disk number | Same UniqueId matches even with different disk numbers |

### Operator Prompts

For destructive tests (USB wipe), the script requires **explicit typed confirmation**:

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  DESTRUCTIVE TEST WARNING
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  ⚠️  Disk 2: SanDisk Cruzer Blade
  ⚠️  Size: 14.5 GB
  ⚠️  ALL DATA ON THIS DISK WILL BE DESTROYED!

  To proceed, type exactly: WIPE DISK 2
```

### Log Output

Verification results are logged to `.KeyDrive/logs/e2e-<timestamp>.log`:

```
[14:32:01.123] [PASS] Safety guardrail BLOCKED source disk: Target disk is the same as source disk
[14:32:01.456] [PASS] SecurityMode.PW_ONLY validated
[14:32:01.789] [PASS] KeyDrive.py --help works from Home Directory
[14:32:02.012] [INFO] === E2E VERIFICATION SUMMARY ===
[14:32:02.013] [SUMMARY] Passed=12, Failed=0, Skipped=0
[14:32:02.014] [RESULT] PASSED
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All verifications passed |
| `1` | One or more verifications failed |

---

## 📝 License

This project is licensed under a custom non-commercial, no-derivatives license.
Commercial use and modified versions are not permitted.
See the LICENSE file for details.

## 🤝 Contributing

This is a personal project template. Feel free to fork and adapt to your needs!

## ⚠️ Disclaimer

This software is provided without warranty. The authors are not responsible for data loss or security breaches. Always maintain proper backups of important data.
