"""Public privacy policy page, served from the backend so the App Store /
TestFlight submission has a stable URL (https://ft-intra.guild42.net/privacy)
without needing separate hosting. Plain GET, no auth."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_PRIVACY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ft_intra — Privacy Policy</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 760px; margin: 40px auto; padding: 0 20px; line-height: 1.6;
         color: #1d1d1f; }
  h1 { font-size: 1.8rem; } h2 { margin-top: 2rem; font-size: 1.25rem; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.95rem; }
  th { background: #f5f5f7; }
  code { background: #f5f5f7; padding: 1px 5px; border-radius: 4px; }
  .muted { color: #6e6e73; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>ft_intra — Privacy Policy</h1>
<p class="muted">Last updated: 2026-06-15</p>

<p>ft_intra is an <strong>unofficial</strong> mobile client for École&nbsp;42
students. It shows your 42 intra data (profile, projects, evaluations, campus
presence) and delivers push notifications. This policy explains what data the
app handles and why.</p>

<h2>Who we are</h2>
<p>ft_intra is built and operated by the Guild42 community for 42 students. It
is not affiliated with or endorsed by École&nbsp;42 / the 42 Network.</p>
<p>Contact: <strong>bibimsoba@gmail.com</strong></p>

<h2>What data we handle</h2>
<p>The app works against the official 42 API and a self-hosted backend.
Depending on the features you enable, the following data is processed:</p>
<table>
<tr><th>Data</th><th>When</th><th>Why</th></tr>
<tr><td>42 OAuth tokens (access + refresh)</td><td>Only if you enable <em>review notifications</em></td><td>The server polls your evaluations on your behalf (the 42 API has no push)</td></tr>
<tr><td>42 intra session cookie</td><td>Only if you enable <em>cookie-based notifications</em></td><td>The server reads your intra notifications page (eval-point sales, events, friends)</td></tr>
<tr><td>FCM push token</td><td>When notifications are on</td><td>To deliver push notifications to your device</td></tr>
<tr><td>42 user id / login</td><td>When using the app</td><td>To identify you for presence, check-in and notifications</td></tr>
<tr><td>Precise location</td><td>Only if you enable <em>location check-in</em></td><td>To detect arrival/departure at your campus (geofence) and mark you present</td></tr>
<tr><td>Friend watch list (42 user ids only)</td><td>When you enable per-friend login alerts</td><td>To notify you when a watched friend logs in</td></tr>
</table>
<p>We do <strong>not</strong> collect contacts, photos, advertising
identifiers, browsing history, or any data for advertising/tracking.</p>

<h2>How it is used and stored</h2>
<ul>
<li>Credentials and tokens are used <strong>only</strong> to generate your
notifications and presence — nothing else.</li>
<li>Server-side data is stored in <strong>Google Firestore</strong> (server-only
access; not readable by other app users). Stored intra cookies are
<strong>encrypted at rest</strong>.</li>
<li>On your device, tokens are kept in the iOS Keychain (secure storage).</li>
<li>Friend <strong>nicknames</strong> and Discord links you set stay
<strong>on your device only</strong> and are never sent to the server.</li>
</ul>

<h2>Third parties</h2>
<ul>
<li><strong>Google Firebase</strong> (Cloud Messaging + Firestore) — push delivery and storage.</li>
<li><strong>42 API</strong> (api.intra.42.fr) — the source of your intra data.</li>
<li><strong>Cloudflare</strong> — network tunnel in front of the backend.</li>
</ul>
<p>We do not sell or share your data with anyone else.</p>

<h2>Your choices and deletion</h2>
<ul>
<li>All data sharing is <strong>off by default</strong>. Each notification type
is opt-in with an explicit consent screen.</li>
<li>You can <strong>delete your cookie and OAuth token from the server at any
time</strong> in Settings → "My data (server)", and turn off any notification or
check-in.</li>
<li>To request full deletion of any remaining data, contact us at the email above.</li>
</ul>

<h2>Children</h2>
<p>The app is intended for École&nbsp;42 students and is not directed at
children under 13.</p>

<h2>Changes</h2>
<p>We may update this policy; the "Last updated" date will change accordingly.</p>
</body>
</html>
"""


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return _PRIVACY_HTML
