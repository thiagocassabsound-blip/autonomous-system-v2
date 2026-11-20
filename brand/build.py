#!/usr/bin/env python3
"""Generates brand/avatar.svg and brand/banner.svg (fonts embedded). Render PNGs with render.js (playwright)."""
import base64, math
from pathlib import Path
B = Path(__file__).parent
b64 = lambda p: base64.b64encode((B / p).read_bytes()).decode()
FONTS = f"""<style>
@font-face{{font-family:'Anton';src:url(data:font/ttf;base64,{b64('fonts/Anton-Regular.ttf')})}}
@font-face{{font-family:'MontX';font-weight:800;font-style:italic;src:url(data:font/woff2;base64,{b64('fonts/Montserrat-ExtraBoldItalic.woff2')})}}
</style>"""
DARK, PINK, ORANGE, YEL, CYAN = "#14042b", "#ff2e88", "#ff9a3c", "#ffe14d", "#00e5ff"

def sky(id, h): return (f'<linearGradient id="{id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b0220"/>'
    f'<stop offset=".45" stop-color="#4a1380"/><stop offset=".8" stop-color="#c2268f"/><stop offset="1" stop-color="#ff5f6d"/></linearGradient>')
SUNGRAD = (f'<linearGradient id="sun" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{YEL}"/>'
           f'<stop offset=".55" stop-color="{ORANGE}"/><stop offset="1" stop-color="{PINK}"/></linearGradient>')
GLOW = '<filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="28"/></filter>' \
       '<filter id="glow2" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="5"/></filter>'

def sun(cx, cy, r):
    cuts = "".join(f'<rect x="{cx-r}" y="{cy + r*(0.12+i*0.17):.1f}" width="{2*r}" height="{r*(0.025+i*0.03):.1f}" fill="black"/>' for i in range(5))
    return (f'<mask id="sm"><circle cx="{cx}" cy="{cy}" r="{r}" fill="white"/>{cuts}</mask>'
            f'<circle cx="{cx}" cy="{cy}" r="{r*1.15}" fill="{PINK}" opacity=".55" filter="url(#glow)"/>'
            f'<rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#sun)" mask="url(#sm)"/>')

def ground(w, y0, h, vx):
    lines = "".join(f'<path d="M{vx} {y0}L{vx+(i-6)*w*0.45} {y0+h}"/>' for i in range(13))
    hor = "".join(f'<path d="M0 {y0 + h*(k/6)**2.2:.0f}H{w}"/>' for k in range(1, 7))
    return (f'<rect y="{y0}" width="{w}" height="{h}" fill="#0c0220"/>'
            f'<g stroke="{CYAN}" stroke-width="3" opacity=".55">{lines}{hor}</g>'
            f'<rect y="{y0-3}" width="{w}" height="6" fill="{CYAN}" filter="url(#glow2)"/>')

def palm(x, y, h, lean, s=1.0):
    """Grounded palm: tapered curved trunk from (x,y) up to crown, 9 drooping fronds."""
    cx, cy = x + lean, y - h
    tw = 16 * s
    trunk = (f'M{x-tw} {y} Q{x+lean*0.2-tw*0.7} {y-h*0.55} {cx-tw*0.35} {cy} L{cx+tw*0.35} {cy} '
             f'Q{x+lean*0.2+tw*0.7} {y-h*0.55} {x+tw} {y}Z')
    fr = ""
    for a, L in [(-165, .62), (-140, .72), (-112, .6), (-80, .55), (-50, .72), (-20, .66), (5, .55), (190, .5), (160, .5)]:
        L *= h * 0.62; ra = math.radians(a); dx, dy = math.cos(ra), math.sin(ra)
        tx, ty = cx + L*dx, cy + L*dy + L*0.38
        mx, my = cx + L*0.55*dx, cy + L*0.55*dy - L*0.12
        nx, ny = -dy, dx; wd = L*0.11
        fr += f'M{cx} {cy} Q{mx+nx*wd:.1f} {my+ny*wd:.1f} {tx:.1f} {ty:.1f} Q{mx-nx*wd:.1f} {my-ny*wd:.1f} {cx} {cy}Z '
    return f'<path d="{trunk}" fill="#0a0118"/><path d="{fr}" fill="#0a0118"/>'

def wordmark(x, y, size, txt, skew=-8):
    t = lambda extra: (f'<text x="{x}" y="{y}" text-anchor="middle" font-family="Anton" font-size="{size}" letter-spacing="{size*0.01:.1f}" {extra}'
                       f' transform="skewX({skew}) translate({-y*math.tan(math.radians(skew)):.1f} 0)">{txt}</text>')
    return (t(f'fill="none" stroke="#0b0220" stroke-width="{size*0.16:.0f}" stroke-linejoin="round"') +
            t(f'fill="none" stroke="{PINK}" stroke-width="{size*0.085:.0f}" stroke-linejoin="round"') +
            t('fill="url(#txt)"'))
TXT = '<linearGradient id="txt" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#ffd0e6"/></linearGradient>'

def grain(w, h):
    return (f'<filter id="n"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/>'
            f'<feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .07 0"/></filter>'), f'<rect width="{w}" height="{h}" filter="url(#n)"/>'

# ---------------- banner 2560x1440 (YouTube safe area: x 507-2053, y 508-931) ----------------
W, H, HOR = 2560, 1440, 1010
gf, gr = grain(W, H)
banner = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{FONTS}
<defs>{sky("sky", H)}{SUNGRAD}{GLOW}{TXT}{gf}</defs>
<rect width="{W}" height="{H}" fill="url(#sky)"/>
{sun(1280, 760, 400)}
<path d="M0 {HOR} L0 {HOR-60} L120 {HOR-60} L120 {HOR-170} L260 {HOR-170} L260 {HOR-90} L420 {HOR-90} L420 {HOR}Z M2140 {HOR} L2140 {HOR-100} L2300 {HOR-100} L2300 {HOR-210} L2420 {HOR-210} L2420 {HOR-70} L2560 {HOR-70} L2560 {HOR}Z" fill="#12052b" opacity=".9"/>
{ground(W, HOR, H-HOR, 1280)}
{palm(300, HOR+30, 620, -70)}{palm(470, HOR+40, 430, -40, .8)}
{palm(2260, HOR+30, 640, 80)}{palm(2090, HOR+40, 440, 40, .8)}
{wordmark(1280, 800, 300, "CHAOS COAST")}
<text x="1280" y="905" text-anchor="middle" font-family="MontX" font-weight="800" font-style="italic" font-size="66" letter-spacing="9" fill="#0b0220" stroke="#0b0220" stroke-width="14" stroke-linejoin="round">THE WILDEST GTA 6 MOMENTS · DAILY</text>
<text x="1280" y="905" text-anchor="middle" font-family="MontX" font-weight="800" font-style="italic" font-size="66" letter-spacing="9" fill="{CYAN}">THE WILDEST GTA 6 MOMENTS · DAILY</text>
{gr}</svg>'''
(B / "banner.svg").write_text(banner)

# ---------------- avatar 800x800 ----------------
gf, gr = grain(800, 800)
avatar = f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800">{FONTS}
<defs>{sky("sky", 800)}{SUNGRAD}{GLOW}{TXT}{gf}<clipPath id="c"><circle cx="400" cy="400" r="400"/></clipPath></defs>
<g clip-path="url(#c)"><rect width="800" height="800" fill="url(#sky)"/>
{sun(400, 330, 250)}
{ground(800, 520, 280, 400)}
{wordmark(400, 690, 330, "CC")}
{gr}</g>
<circle cx="400" cy="400" r="388" fill="none" stroke="{CYAN}" stroke-width="12"/>
</svg>'''
(B / "avatar.svg").write_text(avatar)
print("ok")
