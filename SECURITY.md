# Security

termiX reads local CLI files and process metadata.
It does not send telemetry or store hook prompt text.
The details view excludes private reasoning and tool payloads.
Credentials stay in the provider's own files.

Original integration backups can contain existing secrets.
Session logs, folder names, and notes can contain private information.
Do not attach these files to a public issue without removing private data.

## Report a security defect

1. Open the repository's private security report form, if it is available.
2. Otherwise, send the maintainer a report at `ltu46166@gmail.com`.
3. Describe the affected version and the reproduction procedure.
4. Use synthetic data instead of real credentials.

The maintainer reviews supported source and Windows package defects.
The current supported release is 0.3.x.
Older releases require an update before a security correction.

## Trust boundaries

Hooks accept bounded input and copy only selected metadata fields.
Native log readers skip invalid records.
The internal helper dispatcher accepts only known helper modules.
Terminal launch validates the provider and native session ID.
Provider hooks execute only the saved user statusline command.
Local usage requests send a bearer only to loopback without redirects or proxies.
The application does not require administrator access.
