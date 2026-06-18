"""Public landing page at GET / — served from the backend so
https://ft-intra.guild42.net has a real homepage (App Store marketing/support
URL) without separate hosting. Plain GET, no auth."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ft_intra — companion app for École 42 students</title>
<style>
  :root { --teal:#00BABC; --bg:#0B0E10; --fg:#e8e8ea; --muted:#9aa0a6; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         line-height:1.6; }
  .wrap { max-width:760px; margin:0 auto; padding:0 20px; }
  header { text-align:center; padding:72px 20px 40px; }
  .logo { font-size:64px; font-weight:800; color:var(--teal); letter-spacing:-2px; }
  h1 { font-size:1.6rem; margin:8px 0 4px; }
  .tagline { color:var(--muted); font-size:1.05rem; }
  .badge { display:inline-block; margin-top:16px; font-size:.8rem; color:var(--muted);
           border:1px solid #2a2f33; border-radius:999px; padding:4px 12px; }
  section { padding:24px 0; border-top:1px solid #1c2125; }
  h2 { font-size:1.15rem; }
  .features { display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:8px 0; }
  .feature { background:#11161a; border-radius:12px; padding:16px; }
  .feature h3 { margin:0 0 4px; font-size:1rem; color:var(--teal); }
  .feature p { margin:0; color:var(--muted); font-size:.92rem; }
  a { color:var(--teal); }
  footer { color:var(--muted); font-size:.85rem; padding:32px 0 56px; text-align:center; }
  @media (max-width:520px){ .features{ grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <div class="logo">42</div>
  <h1>ft_intra</h1>
  <div class="tagline">Your École&nbsp;42 intra, in your pocket.</div>
  <div class="badge">Unofficial · made by the Guild42 community</div>
</header>

<div class="wrap">
  <section>
    <div class="features">
      <div class="feature"><h3>Notifications</h3><p>Push alerts for evaluations, evaluation-point sales, events and friend logins — even when the app is closed.</p></div>
      <div class="feature"><h3>Campus presence</h3><p>See who's on campus right now and check in when you arrive.</p></div>
      <div class="feature"><h3>Evaluations</h3><p>Browse your evaluation history and your upcoming review schedule.</p></div>
      <div class="feature"><h3>Profile &amp; projects</h3><p>Your level, blackhole timer, evaluation points and project progress at a glance.</p></div>
    </div>
  </section>

  <section>
    <h2>Who makes this?</h2>
    <p>ft_intra is built and operated by the <strong>Guild42</strong> community for
    students of École&nbsp;42. It is <strong>not affiliated with or endorsed by
    École&nbsp;42 / the 42 Network</strong>. Sign-in uses your existing 42 account
    (the school's official OAuth).</p>
    <p>Contact: <a href="mailto:ka-kun@actraise.org">ka-kun@actraise.org</a></p>
  </section>

  <section>
    <h2>Get the app</h2>
    <p>Currently in TestFlight beta for the Guild42 community. <!-- App Store / TestFlight link to be added --></p>
    <p><a href="/privacy">Privacy Policy</a></p>
  </section>
</div>

<footer>© Guild42 · ft_intra</footer>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def landing():
    return _LANDING_HTML
