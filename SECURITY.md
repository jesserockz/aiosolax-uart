# Security Policy

## Reporting a vulnerability

If you've found a security issue in `aiosolax-uart`, please **do not open a
public GitHub issue**. Instead, report it privately via GitHub's
[Security Advisories](https://github.com/jesserockz/aiosolax-uart/security/advisories/new)
form.

What to include:

- A description of the issue and the impact you've identified
- Steps to reproduce (a minimal Python snippet is ideal)
- The library version (`pip show aiosolax-uart`) and Python version
- Any inverter model / firmware version involved, if relevant

I'll acknowledge the report within a few days, work with you on a fix, and
coordinate disclosure. Once a fix is released, your name (or handle, or
anonymous, as you prefer) will be credited in the release notes.

## Supported versions

Only the latest minor release receives security fixes. Older versions are
best-effort.

## Threat model

This library reads data from a SolaX inverter via a local serial port (or an
ESPHome serial-proxy URL). It does not handle authentication credentials and
does not connect to the internet directly. Concerns most relevant to a
security report are likely:

- Untrusted bytes from the serial port causing parsing crashes, memory
  exhaustion, or stuck event loops
- Bugs in the dongle-serial / inverter-serial handling that could leak
  identifying device information into logs or diagnostics
- Issues in transitive dependencies (`serialx`, `aioesphomeapi`) reachable
  through this library's public API
