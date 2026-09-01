# Security Policy

## Supported Versions

This project is maintained by an individual with limited resources, so security updates target the latest release line only. We strongly recommend all users always upgrade to the latest version.

| Version | Supported |
| ------- | --------- |
| v1.2.x | ✅ Currently supported, will receive security updates |
| v1.1.x and below | ❌ No longer supported, please upgrade to the latest version |

**Note**: Only the latest stable release receives security fixes. Please subscribe to Releases in this repository to stay informed.

## Reporting a Vulnerability

We take security issues seriously. If you find a potential vulnerability, please report it as follows:

### How to Report

1. **Preferred**: Email **jeanslw@qq.com** with the subject starting with `[SECURITY]`.
2. **Alternative**: Create an Issue on GitHub, clearly marking `[SECURITY]` in the title, and **do not disclose vulnerability details publicly** — we will contact you privately first.

### What to Include

Please include as much of the following as possible:
- Affected version(s) (e.g. v1.2.0) and commit hash if known
- A brief description of the vulnerability
- Steps to reproduce (provide a minimal reproducible example if possible)
- Possible attack scenarios and impact
- Your contact info (if you want a reply)

### Handling Process

1. **Acknowledgement**: We will reply to your email within 48 hours to confirm receipt.
2. **Assessment & Fix**: We will assess the severity as soon as possible and start fixing. Target is to release a patch within **7-14 days** (depends on complexity).
3. **Disclosure**: After the fix is released, we will note the fixed security issue in the Release Notes and coordinate with you on public credit.

### Handling Principles

- Every report is treated with the utmost seriousness.
- We will not publicly disclose vulnerability details until a fixed version is released.
- If the report is accepted, you will be notified after the new release; if rejected, we will provide a reasonable explanation.

### Dependency Issues

If the vulnerability involves third-party dependencies (e.g. Python packages), please also report it to the maintainers of the affected dependency.

## Recommended Security Practices

For self-hosted deployments, we recommend:
- Always use the latest version
- Restrict the admin panel (`/admin`) to an intranet or behind a VPN
- Use a strong `BLOG_INIT_ADMIN_PWD` and rotate it periodically
- Set a strong, unique `BLOG_SECRET_KEY` (e.g. `python -c 'import secrets;print(secrets.token_hex(32))'`)
- Use HTTPS in production and enable secure session cookies
- Regularly audit logs and watch for abnormal operations
- Use MySQL in production instead of SQLite (SQLite has limited concurrent write capability)

---

Thank you for helping keep MicroBlog secure!
