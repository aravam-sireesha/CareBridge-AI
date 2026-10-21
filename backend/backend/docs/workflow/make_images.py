"""Draw the CareBridge AI workflow diagrams (beginner guide, administrator hub, role journeys, professional flow)."""
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

INK, MUTED, BG = "#12292B", "#4A6663", "#F3FAF9"
TEAL, VIOLET, SKY, GREEN, AMBER, ROSE, RED = "#0F766E", "#7C3AED", "#0284C7", "#16A34A", "#D97706", "#E11D48", "#DC2626"
LIGHT = {TEAL: "#DDF3EF", VIOLET: "#EDE7FD", SKY: "#DCEFFB", GREEN: "#DDF4E4", AMBER: "#FCEFD2", ROSE: "#FDE3EA", RED: "#FDE2E2"}
plt.rcParams["font.family"] = "DejaVu Sans"


def canvas(w=16, h=9):
    fig = plt.figure(figsize=(w, h), dpi=110)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w * 100)
    ax.set_ylim(0, h * 100)
    ax.axis("off")
    fig.patch.set_facecolor(BG)
    return fig, ax


def box(ax, x, y, w, h, fc="white", ec=None, r=18, lw=1.6, z=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec or fc, lw=lw, zorder=z))


def text(ax, x, y, s, size=12, color=INK, weight="normal", ha="left", va="center", wrap=None, z=5, ls=1.25, style="normal"):
    if wrap:
        s = "\n".join(textwrap.fill(p, wrap) for p in s.split("\n"))
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, zorder=z, linespacing=ls, fontstyle=style)


def arrow(ax, x1, y1, x2, y2, color=MUTED, lw=2.4, style="-|>", rad=0.0, z=3, ms=18, alpha=1.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=ms, lw=lw, color=color, zorder=z, alpha=alpha,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0))


def badge(ax, x, y, s, color, size=10.5, pad=10):
    w = len(s) * size * 0.98 + pad * 2
    box(ax, x, y - 15, w, 30, fc=LIGHT[color], ec=color, r=15, lw=1.2, z=4)
    text(ax, x + w / 2, y, s, size=size, color=color, weight="bold", ha="center")
    return w


def header(ax, w, title, sub):
    box(ax, 0, 800, w * 100, 100, fc=INK, r=0, z=1)
    ax.add_patch(Circle((70, 850), 26, fc="#2DD4BF", ec="none", zorder=3))
    text(ax, 70, 850, "♥", size=24, color=INK, ha="center", weight="bold")
    text(ax, 120, 862, "CareBridge AI", size=26, color="white", weight="bold")
    text(ax, 120, 828, sub, size=11.5, color="#9FD8D1")
    text(ax, w * 100 - 40, 850, title, size=20, color="#5EEAD4", weight="bold", ha="right")


# --- simple drawn icons (all centred on cx, cy) -------------------------------------------------
def icon_form(ax, cx, cy, c):
    box(ax, cx - 26, cy - 32, 52, 64, fc="white", ec=c, r=6, lw=2.5, z=6)
    for i, wd in enumerate((30, 36, 24, 32)):
        ax.add_patch(Rectangle((cx - 18, cy + 18 - i * 14), wd, 5, fc=c, ec="none", zorder=7))


def icon_ai(ax, cx, cy, c):
    pts = [(cx - 28, cy - 18), (cx, cy + 26), (cx + 28, cy - 18), (cx, cy - 4)]
    for (x, y) in pts:
        ax.add_patch(Circle((x, y), 9, fc=c, ec="white", lw=2, zorder=8))
    for i in range(4):
        for j in range(i + 1, 4):
            ax.plot([pts[i][0], pts[j][0]], [pts[i][1], pts[j][1]], color=c, lw=2, zorder=7)


def icon_check(ax, cx, cy, c):
    ax.add_patch(Circle((cx, cy), 32, fc="white", ec=c, lw=3, zorder=6))
    ax.plot([cx - 15, cx - 3, cx + 17], [cy, cy - 13, cy + 14], color=c, lw=6, solid_capstyle="round", solid_joinstyle="round", zorder=8)


def icon_heart(ax, cx, cy, c):
    ax.add_patch(Circle((cx, cy), 32, fc="white", ec=c, lw=3, zorder=6))
    text(ax, cx, cy - 2, "♥", size=34, color=c, ha="center", weight="bold", z=9)


def icon_shield(ax, cx, cy, c):
    pts = [(cx - 26, cy + 28), (cx + 26, cy + 28), (cx + 26, cy - 4), (cx, cy - 32), (cx - 26, cy - 4)]
    ax.add_patch(Polygon(pts, closed=True, fc="white", ec=c, lw=3, zorder=6))
    ax.plot([cx - 12, cx - 3, cx + 14], [cy + 2, cy - 9, cy + 13], color=c, lw=5, solid_capstyle="round", solid_joinstyle="round", zorder=8)


# =============================================================================== 1. beginner guide
def beginner():
    fig, ax = canvas()
    header(ax, 16, "How it works in 5 simple steps", "Child welfare · Resource coordination · Social impact")
    steps = [
        (TEAL, "1", "Tell us what\nis needed", "Organizations, donors and volunteers add their information: needs, gifts, skills and supplies.", "WHO: Everyone", icon_form),
        (VIOLET, "2", "AI looks for\nthe best match", "The AI finds urgent needs, spots strange donations and suggests the best donors, volunteers and supplies.", "WHO: The AI", icon_ai),
        (SKY, "3", "A person checks\nand approves", "The administrator sees every AI idea in one list. Nothing happens until a person says yes.", "WHO: Administrator", icon_check),
        (GREEN, "4", "Help reaches\nthe child", "Donors and volunteers are connected, supplies are delivered and children get guidance.", "WHO: Donors, volunteers", icon_heart),
        (AMBER, "5", "Everyone can\nsee the result", "Needs are marked fulfilled. Every action is written in a record that nobody can change.", "WHO: Everyone", icon_shield),
    ]
    cw, gap, x0, top = 270, 38, 62, 760
    for i, (c, n, title, body, who, icon) in enumerate(steps):
        x = x0 + i * (cw + gap)
        box(ax, x, 285, cw, top - 285, fc="white", ec=LIGHT[c], lw=2.5, r=22)
        box(ax, x, top - 110, cw, 110, fc=c, r=22)
        ax.add_patch(Rectangle((x, top - 110), cw, 30, fc=c, ec="none", zorder=3))
        ax.add_patch(Circle((x + 38, top - 55), 25, fc="white", ec="none", zorder=4))
        text(ax, x + 38, top - 55, n, size=24, color=c, weight="bold", ha="center")
        text(ax, x + 78, top - 55, title, size=14.5, color="white", weight="bold")
        box(ax, x + cw / 2 - 52, top - 235, 104, 104, fc=LIGHT[c], r=52, z=3)
        icon(ax, x + cw / 2, top - 183, c)
        text(ax, x + 20, top - 272, body, size=11.8, color=INK, wrap=29, va="top", ls=1.4)
        badge(ax, x + 20, 322, who, c, size=10)
        if i < len(steps) - 1:
            arrow(ax, x + cw + 3, top - 183, x + cw + gap - 3, top - 183, color=MUTED, lw=3, ms=22)
    # worked example
    box(ax, 62, 78, 1476, 138, fc="white", ec=TEAL, lw=2, r=18)
    text(ax, 90, 192, "A real example", size=12.5, color=TEAL, weight="bold")
    ex = ["Hope Home asks\nfor 40 books", "AI finds donors,\nvolunteers and books", "Admin approves\nthe best choices", "Books are delivered,\nstudents get tutoring", "Request is fulfilled\nand recorded"]
    for i, e in enumerate(ex):
        xx = 90 + i * 292
        text(ax, xx, 130, e, size=11.5, color=INK, weight="bold")
        if i < 4:
            arrow(ax, xx + 232, 130, xx + 276, 130, lw=2.2, ms=16)
    text(ax, 800, 36, "Safe by design:  two-step login for administrators  •  roles limit who sees what  •  every decision is recorded", size=11.5, color=MUTED, ha="center")
    fig.savefig("carebridge-1-beginner-workflow.png", facecolor=BG)
    plt.close(fig)


# =============================================================================== 2. administrator hub
def hub():
    import math
    fig, ax = canvas()
    header(ax, 16, "The administrator is the control centre", "One person coordinates organizations, needs, donors, volunteers and resources")
    cx, cy, R = 800, 470, 118
    nodes = [("Organizations", "children's homes,\nverified by the admin", TEAL, 250, 640), ("Needs", "what children\nrequire, by urgency", ROSE, 800, 705),
             ("Donors", "money and gifts,\nmatched by interest", AMBER, 1350, 640), ("Volunteers", "skills and time,\nmatched by fit", SKY, 1235, 318), ("Resources", "books, food, health\nsupplies, services", GREEN, 365, 318)]
    for (name, sub, c, x, y) in nodes:
        dx, dy = x - cx, y - cy
        n = math.hypot(dx, dy)
        ux, uy = dx / n, dy / n
        tb = min(130 / abs(ux) if abs(ux) > 1e-6 else 1e9, 55 / abs(uy) if abs(uy) > 1e-6 else 1e9)
        arrow(ax, cx + ux * (R + 8), cy + uy * (R + 8), x - ux * (tb + 6), y - uy * (tb + 6), color=c, lw=3.6, style="<|-|>", ms=20)
    ax.add_patch(Circle((cx, cy), R, fc=INK, ec="#5EEAD4", lw=5, zorder=6))
    text(ax, cx, cy + 36, "ADMINISTRATOR", size=15, color="white", weight="bold", ha="center", z=9)
    text(ax, cx, cy - 4, "sees everything\nreviews and approves", size=11.5, color="#9FD8D1", ha="center", z=9)
    text(ax, cx, cy - 58, "★  final decision  ★", size=10.5, color="#5EEAD4", ha="center", weight="bold", z=9)
    for (name, sub, c, x, y) in nodes:
        box(ax, x - 130, y - 55, 260, 110, fc="white", ec=c, lw=3, r=20, z=4)
        text(ax, x, y + 22, name, size=15, color=c, weight="bold", ha="center")
        text(ax, x, y - 18, sub, size=10.5, color=MUTED, ha="center")
    box(ax, 62, 78, 1476, 120, fc="white", ec=VIOLET, lw=2.2, r=18)
    text(ax, 90, 175, "The AI suggests, the administrator decides", size=12.5, color=VIOLET, weight="bold")
    engines = ["Donor\nsuggestions", "Volunteer\nsuggestions", "Resource\nallocation", "Fraud\nchecks", "Demand\nforecast", "Career\nguidance", "AI assistant\n(knowledge + live data)"]
    for i, e in enumerate(engines):
        xx = 90 + i * 205
        wd = 190 if i < 6 else 215
        box(ax, xx, 92, wd, 58, fc=LIGHT[VIOLET], ec=VIOLET, lw=1.2, r=12, z=4)
        text(ax, xx + wd / 2, 121, e, size=10, color=INK, weight="bold", ha="center")
    arrow(ax, 800, 202, 800, cy - R - 8, color=VIOLET, lw=3.6, ms=22)
    text(ax, 818, 262, "ideas with reasons", size=10.5, color=VIOLET, weight="bold")
    text(ax, 800, 36, "Every decision is saved in an audit trail  •  two-step sign-in protects administrator accounts  •  children's data is never shown to donors", size=11, color=MUTED, ha="center")
    fig.savefig("carebridge-2-administrator-hub.png", facecolor=BG)
    plt.close(fig)


# =============================================================================== 3. role journeys
def journeys():
    fig, ax = canvas()
    header(ax, 16, "Who does what", "Four roles, one connected platform")
    cols = [
        (TEAL, "Organization", "A children's home", ["Sign up and wait for\nverification", "Add children and\ntheir needs", "Add resources you\ncan share", "Watch needs get\nfulfilled"]),
        (AMBER, "Donor", "A person or group who gives", ["Sign up and say what\nyou like to support", "See needs from\nverified homes", "Give money or items;\nrecord the gift", "See the impact of\nyour help"]),
        (SKY, "Volunteer", "Gives time and skills", ["Sign up with your\nskills", "Say when you are\navailable", "Get matched to a\nneed that fits", "Help, and the\nmatch is recorded"]),
        (VIOLET, "Administrator", "The control centre", ["Verify organizations\nand manage records", "Run the AI scans\nand read the ideas", "Approve or reject in\nthe review queue", "Track results in the\naudit trail"]),
    ]
    cw, gap, x0 = 340, 38, 62
    for i, (c, role, sub, steps) in enumerate(cols):
        x = x0 + i * (cw + gap)
        box(ax, x, 90, cw, 670, fc="white", ec=LIGHT[c], lw=2.5, r=22)
        box(ax, x, 650, cw, 110, fc=c, r=22)
        ax.add_patch(Rectangle((x, 650), cw, 30, fc=c, ec="none", zorder=3))
        text(ax, x + cw / 2, 722, role, size=19, color="white", weight="bold", ha="center")
        text(ax, x + cw / 2, 684, sub, size=11, color="white", ha="center")
        for j, s in enumerate(steps):
            yy = 585 - j * 138
            ax.add_patch(Circle((x + 48, yy), 22, fc=c, ec="none", zorder=4))
            text(ax, x + 48, yy, str(j + 1), size=15, color="white", weight="bold", ha="center")
            text(ax, x + 88, yy, s, size=12.2, color=INK, ls=1.3)
            if j < 3:
                arrow(ax, x + 48, yy - 28, x + 48, yy - 108, color=c, lw=2.4, ms=14, alpha=0.45)
    text(ax, 800, 45, "Roles limit what each person can see. A child's record is visible only to administrators and the child's own organization.", size=11.5, color=MUTED, ha="center")
    fig.savefig("carebridge-3-role-journeys.png", facecolor=BG)
    plt.close(fig)


# =============================================================================== 4. professional flow
def professional():
    fig, ax = canvas(16, 9.4)
    ax.set_ylim(0, 940)
    ax.set_xlim(0, 1600)
    box(ax, 0, 840, 1600, 100, fc=INK, r=0, z=1)
    ax.add_patch(Circle((70, 890), 26, fc="#2DD4BF", ec="none", zorder=3))
    text(ax, 70, 890, "♥", size=24, color=INK, ha="center", weight="bold")
    text(ax, 120, 903, "CareBridge AI", size=26, color="white", weight="bold")
    text(ax, 120, 869, "Child welfare  |  Resource coordination  |  Social impact", size=11.5, color="#9FD8D1")
    text(ax, 1560, 903, "End to end working flow", size=20, color="#5EEAD4", weight="bold", ha="right")
    text(ax, 1560, 869, "Professional view: users, AI engines, decisions, actions, outcomes", size=11.5, color="#9FD8D1", ha="right")
    cols = [
        ("Users & data sources", TEAL, ["Children: profile, needs,\neducation, career", "Organizations: programs,\nresources, requests", "Donors: interests,\ngiving history", "Volunteers: skills,\navailability", "Resources: materials,\nservices, funds"]),
        ("AI & analytics engine", VIOLET, ["Demand forecast and need\nalerts (time-series + rules)", "Fraud / anomaly detection\n(rules + scoring)", "Donor, volunteer and resource\nsuggestions (ML, learns)", "Career guidance engine\n(recommendation model)", "RAG assistant: hybrid search,\nreranking, live data,\nconfidence score"]),
        ("Decision layer", SKY, ["Administrator review queue:\nverify, approve, reject", "AI suggestion hub for\norganizations, needs,\ndonors, volunteers", "Secure sign-in: lockout,\ntwo-step code, sessions", "Audit trail: every action\nrecorded, cannot be edited", "Platform database:\nusers, needs, donations,\nvolunteers, resources,\nknowledge base"]),
        ("Services & operations", AMBER, ["Connect donors and\nvolunteers to needs", "Allocate resources:\npropose, approve, deliver", "Provide guidance:\neducation and career", "Coordinate with\norganizations", ""]),
        ("Impact & outcomes", GREEN, ["Timely support for\nchildren", "Efficient use of\nresources", "Transparency and trust", "Stronger social impact", ""]),
    ]
    cw, gap, x0 = 268, 44, 40
    for i, (title, c, items) in enumerate(cols):
        x = x0 + i * (cw + gap)
        box(ax, x, 150, cw, 660, fc=LIGHT[c], ec=c, lw=2, r=18)
        text(ax, x + 16, 782, title, size=13, color=c, weight="bold")
        n = len([t for t in items if t])
        ih = 112 if n == 5 else 130
        for j, t in enumerate([t for t in items if t]):
            yy = 745 - j * (ih + 8) - ih
            box(ax, x + 12, yy, cw - 24, ih, fc="white", ec=c, lw=1.2, r=12, z=4)
            text(ax, x + 24, yy + ih / 2, t, size=10.3, color=INK, ls=1.3)
        if i < len(cols) - 1:
            arrow(ax, x + cw + 2, 480, x + cw + gap - 2, 480, color=MUTED, lw=3, ms=20)
    box(ax, 40, 40, 1520, 80, fc="white", ec=TEAL, lw=1.6, r=14)
    foot = ["AI powered", "Human in the loop", "Secure by design", "Fully auditable"]
    for i, f in enumerate(foot):
        xx = 120 + i * 370
        ax.add_patch(Circle((xx - 36, 80), 14, fc=TEAL, ec="none", zorder=4))
        text(ax, xx - 36, 79, "✓", size=12, color="white", ha="center", weight="bold")
        text(ax, xx - 10, 80, f, size=12, color=INK, weight="bold")
    fig.savefig("carebridge-4-professional-workflow.png", facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    beginner(); hub(); journeys(); professional()
    print("done")
