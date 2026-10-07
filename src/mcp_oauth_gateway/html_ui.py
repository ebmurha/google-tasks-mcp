"""Small shared HTML shell for browser-facing authorization pages."""

from __future__ import annotations


PAGE_STYLES = """
:root{color-scheme:light;--bg:#f7f7f8;--surface:#fff;--text:#030213;
  --muted:#717182;--border:rgba(0,0,0,.1);--input:#f3f3f5;
  --danger:#d4183d;--radius:12px}
*{box-sizing:border-box}
html{font-size:16px}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);
  font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}
main{width:min(100% - 32px,420px);margin:0 auto;padding:clamp(48px,10vh,96px) 0}
.brand{display:flex;align-items:center;justify-content:center;gap:9px;margin:0 0 20px;
  font-size:14px;font-weight:600;letter-spacing:-.01em}
.brand-mark{display:grid;width:28px;height:28px;place-items:center;border-radius:8px;
  background:var(--text);color:#fff;font-size:15px}
.card{padding:28px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);box-shadow:0 1px 2px rgba(0,0,0,.04)}
h1,h2{margin:0 0 10px;font-size:22px;font-weight:600;line-height:1.25;
  letter-spacing:-.025em}
p{margin:0 0 20px;color:var(--muted);font-size:15px;line-height:1.55}
p:last-child{margin-bottom:0}
strong{color:var(--text);font-weight:600}
form{margin-top:22px}
label{display:block;margin-bottom:7px;font-size:14px;font-weight:500}
input[type=password]{width:100%;height:44px;padding:0 12px;background:var(--input);
  color:var(--text);border:1px solid transparent;border-radius:8px;font:inherit;outline:none;
  transition:border-color .15s,box-shadow .15s}
input[type=password]:focus{border-color:#9898a3;box-shadow:0 0 0 3px rgba(3,2,19,.08)}
button,.button{display:flex;width:100%;min-height:42px;align-items:center;justify-content:center;
  margin-top:12px;padding:10px 16px;border:1px solid var(--text);border-radius:8px;
  background:var(--text);color:#fff;font:inherit;font-size:14px;font-weight:600;
  line-height:1.3;text-align:center;text-decoration:none;cursor:pointer;
  transition:opacity .15s,background .15s}
button:hover,.button:hover{opacity:.88}
button:focus-visible,.button:focus-visible{outline:3px solid rgba(3,2,19,.18);outline-offset:2px}
button.secondary{background:var(--surface);color:var(--text);border-color:var(--border)}
button.secondary:hover{background:var(--input);opacity:1}
.error{margin:16px 0 0;padding:11px 12px;border-radius:8px;background:#fff1f3;
  color:var(--danger);font-size:14px;line-height:1.45}
.meta{margin-top:20px;color:var(--muted);font-size:12px;text-align:center;
  overflow-wrap:anywhere}
code{display:block;padding:14px;border:1px solid var(--border);border-radius:8px;
  background:var(--input);font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;
  overflow-wrap:anywhere;user-select:all}
@media(max-width:480px){main{width:min(100% - 24px,420px);padding:32px 0}.card{padding:22px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""


def authorization_page(title: str, body: str, *, extra_head: str = "") -> str:
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{PAGE_STYLES}</style>{extra_head}"
        '</head><body><main><div class="brand">'
        '<span class="brand-mark" aria-hidden="true">&#10003;</span>'
        '<span>Google Tasks</span></div><section class="card">'
        f"{body}</section></main></body></html>"
    )
