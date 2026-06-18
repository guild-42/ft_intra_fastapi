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
         max-width: 820px; margin: 40px auto; padding: 0 20px; line-height: 1.6;
         color: #1d1d1f; }
  h1 { font-size: 1.8rem; } h2 { margin-top: 2rem; font-size: 1.25rem; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.95rem; }
  th { background: #f5f5f7; }
  code { background: #f5f5f7; padding: 1px 5px; border-radius: 4px; }
  .muted { color: #6e6e73; font-size: 0.9rem; }

  /* data-flow visualization */
  .map { display: flex; flex-wrap: wrap; gap: 14px; margin: 1.2rem 0; }
  .node { flex: 1 1 230px; border: 2px solid #d2d2d7; border-radius: 14px;
          padding: 14px 16px; background: #fbfbfd; }
  .node h3 { margin: 0 0 8px; font-size: 1.05rem; display: flex; align-items: center; gap: 8px; }
  .node.device { border-color: #00BABC; }
  .node.server { border-color: #ff9f0a; }
  .node.api    { border-color: #5e9cff; }
  .node ul { margin: 6px 0 0; padding-left: 18px; }
  .node li { font-size: 0.9rem; margin: 4px 0; }
  .badge { display: inline-block; font-size: 0.72rem; font-weight: 700;
           padding: 1px 7px; border-radius: 20px; margin-left: 4px; vertical-align: middle; }
  .b-stay { background: #def7ec; color: #03543f; }
  .b-never { background: #fde8e8; color: #9b1c1c; }
  .b-store { background: #fef3c7; color: #92400e; }
  .flow { font-size: 0.9rem; color: #3a3a3c; background: #f5f5f7;
          border-radius: 12px; padding: 12px 16px; margin: 0.6rem 0 1.4rem; }
  .flow b { color: #1d1d1f; }
  .legend { font-size: 0.82rem; color: #6e6e73; }
</style>
</head>
<body>
<h1>ft_intra — Privacy Policy</h1>
<p class="muted">Last updated: 2026-06-18</p>

<p>ft_intra is an <strong>unofficial</strong> mobile client for École&nbsp;42
students. It shows your 42 intra data (profile, projects, evaluations, campus
presence) and delivers push notifications. This policy explains what data the
app handles, where it lives, and how the design stays within the
<strong>42 API General Terms of Use</strong>.</p>

<h2>Who we are</h2>
<p>ft_intra is built and operated by the Guild42 community for 42 students. It
is not affiliated with or endorsed by École&nbsp;42 / the 42 Network.</p>
<p>Contact: <strong>ka-kun@actraise.org</strong></p>

<h2>Where your data lives (at a glance)</h2>
<p>The single most important point: <strong>your 42 credentials never reach our
server.</strong> Your 42 login token stays on your phone. Our server only ever
holds a push token, your notification preferences, and a list of mutually-agreed
friend ids — none of which is 42 account data.</p>

<div class="map">
  <div class="node device">
    <h3>📱 Your device</h3>
    <ul>
      <li>42 OAuth token <span class="badge b-stay">stays here</span> (iOS Keychain)</li>
      <li>Friend nicknames &amp; Discord links <span class="badge b-stay">stays here</span></li>
      <li>Cached profile / presence for display</li>
      <li>"Already seen" evaluation markers (for dedupe)</li>
    </ul>
  </div>
  <div class="node server">
    <h3>☁️ Our server</h3>
    <ul>
      <li>FCM push token <span class="badge b-store">stored</span></li>
      <li>Notification preferences <span class="badge b-store">stored</span></li>
      <li>Friendships: 42 ids + status <span class="badge b-store">stored</span></li>
      <li>42 OAuth token <span class="badge b-never">never</span></li>
      <li>42 session cookie <span class="badge b-never">never</span></li>
      <li>Your profile / grades / messages <span class="badge b-never">never</span></li>
    </ul>
  </div>
  <div class="node api">
    <h3>🟦 42 official API</h3>
    <ul>
      <li>Source of profile, projects, evaluations</li>
      <li>Read with the official OAuth (PKCE) flow</li>
      <li>Public campus events &amp; presence</li>
    </ul>
  </div>
</div>

<div class="flow">
  <b>Evaluation notifications:</b> the server cannot read your 42 data, so it
  sends a content-less "wake" ping &rarr; your phone uses <i>its own</i> token to
  read your evaluations from the 42 API &rarr; your phone shows the notification
  locally. <b>No 42 data passes through our server.</b>
  <br><br>
  <b>Friend-login notifications:</b> we only watch a friend's <i>public</i>
  campus presence, and only after <b>both</b> of you agreed (friend request →
  accept). Either side can revoke at any time.
</div>
<p class="legend">Legend:
  <span class="badge b-stay">stays here</span> never leaves the device ·
  <span class="badge b-store">stored</span> kept on our server ·
  <span class="badge b-never">never</span> we never receive or store it.</p>

<h2>How we comply with the 42 API Terms of Use</h2>
<p>The app is deliberately designed so that it does not store 42 credentials on
a third-party server, does not scrape the intranet, and does not process other
students' personal data without their consent. Concretely:</p>
<table>
<tr><th>Requirement (42 General Terms of Use)</th><th>What ft_intra does</th></tr>
<tr><td>Your 42 token/session must not be handed to third parties</td><td>The OAuth token lives in your device Keychain and is <strong>never stored on our server</strong>. It is transmitted only once, in memory, to verify your identity via the official <code>/v2/me</code> endpoint (so nobody can register as someone else), then discarded — never written to disk or database.</td></tr>
<tr><td>No bulk extraction / scraping of the intranet</td><td>We removed all cookie-based scraping. Data comes <strong>only</strong> from the official 42 API.</td></tr>
<tr><td>Another person's data needs that person's consent</td><td>Friend-login alerts require a <strong>mutual</strong> friend request → accept. We watch only <em>public</em> campus presence, and only of users who agreed.</td></tr>
<tr><td>Data minimisation</td><td>The server stores only a push token, preferences and friend ids — no names, grades, messages, or profile data.</td></tr>
<tr><td>Right to deletion</td><td>You can delete your server-side data anytime in the app; logging out removes the token from your device.</td></tr>
</table>

<h2>What data we handle</h2>
<p>The app works against the official 42 API and a self-hosted backend.
Depending on the features you enable, the following data is processed:</p>
<table>
<tr><th>Data</th><th>When</th><th>Why</th></tr>
<tr><td>FCM push token</td><td>When notifications are on</td><td>To deliver push notifications to your device</td></tr>
<tr><td>42 user id / login</td><td>When using the app</td><td>To identify you for presence, check-in and notifications</td></tr>
<tr><td>Friend watch list (42 user ids only)</td><td>When you enable per-friend login alerts</td><td>To notify you when a watched friend logs in</td></tr>
</table>
<p>Your <strong>42 OAuth token stays on your device</strong> (iOS Keychain) and
is never stored on the server. For evaluation notifications the server only sends
a content-less "wake" signal; your device then reads your own data from the 42
API and shows the notification locally. The server holds no 42 session cookie and
does no scraping.</p>
<p>We do <strong>not</strong> collect contacts, photos, advertising
identifiers, browsing history, or any data for advertising/tracking.</p>

<h2>How it is used and stored</h2>
<ul>
<li>Credentials and tokens are used <strong>only</strong> to generate your
notifications and presence — nothing else.</li>
<li>Server-side data (your FCM token, prefs and friend list of 42 ids) is stored
in <strong>Google Firestore</strong> (server-only access; not readable by other
app users). No 42 token or session cookie is stored on the server.</li>
<li>On your device, your 42 token is kept in the iOS Keychain (secure storage).</li>
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
<li>You can <strong>delete your server-side registration at any time</strong> in
Settings → "My data (server)", and turn off any notification or check-in. Your
42 token can be removed by logging out (it only ever lived on your device).</li>
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
