CHANGED: /usr/local/bin/rawos-frontdoor (new) — copy of lockout-proof try/except wrapper, own file
CHANGED: /etc/ssh/sshd_config.d/50-rawos-frontdoor.conf — ForceCommand → rawos-frontdoor frontdoor enter
  WHY: pip install -e . regenerates /usr/local/bin/rawos from pyproject [project.scripts],
       silently drops try/except lockout fix. New file pip-untouched → permanent.
VERIFY: sshd -T -C user=root,host=x,addr=127.0.0.1 → forcecommand /usr/local/bin/rawos-frontdoor frontdoor enter
VERIFY: fresh ssh session → being greeting + "rawos>" shown, no crash
NEXT: Phase 22 (PAM Integration) — deferred, needs Opus. Confirm Phase 21 stable first.
