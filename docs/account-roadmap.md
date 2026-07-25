# Account Roadmap

## Implemented in 1.0 Beta

- Permanent invite-code registration
- Case-insensitive username and scrypt password authentication
- HttpOnly, Secure, SameSite=Lax sessions
- Per-account session cap with oldest-session eviction
- Self-service password change with revocation of older sessions
- Logout current session and logout all devices
- Account-scoped jobs and media artifacts

No account plan or cloud-ASR entitlement is enforced during the beta. Cloud
usage remains protected by server-wide provider safety limits so a public
deployment cannot silently create paid usage.

## Password Recovery

Username-only accounts cannot recover a forgotten password without an
administrator. A production recovery flow needs:

1. A verified sending domain with SPF, DKIM, and DMARC.
2. A transactional email provider such as Aliyun DirectMail, Tencent Cloud SES,
   Amazon SES, Resend, or Postmark.
3. A project-owned sender address and provider API credential stored outside Git.
4. One-time reset tokens stored only as hashes, with a 10-30 minute expiry.
5. Edge rate limits and CAPTCHA after repeated recovery attempts.

The application should not collect email addresses until a privacy notice,
retention policy, sender domain, and deletion process exist.

## Optional Social Login

OAuth login requires registering this site as an application with each provider,
configuring an exact HTTPS callback URL, and storing a client secret on the
server. GitHub is the lowest-friction option for technical users. WeChat,
QQ, and Chinese mobile-number login generally require a verified organization
or additional compliance review and should be evaluated separately.

Keep the local username/password path as a recovery-independent fallback even
after OAuth is added.
