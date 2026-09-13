from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

app = FastAPI(title="Legacy Member Servicing Demo")

MEMBERS = {
    "10001": {"name": "Alex Morgan", "balance": 4250.25},
    "10002": {"name": "Jordan Lee", "balance": 1220.00},
    # 10003 always triggers an unexpected session interstitial on search, for exercising the
    # human-in-the-loop pause/resume path. Not a "not found" case, not a normal happy path.
    "10003": {"name": "Riley Chen", "balance": 875.50},
    # 10004 always shows a transient "loading" banner that clears itself client-side, for
    # exercising the automated wait/retry recovery path (no human involved).
    "10004": {"name": "Morgan Blake", "balance": 3300.00},
}

INTERSTITIAL_MEMBER_ID = "10003"
TRANSIENT_LOAD_MEMBER_ID = "10004"


def page(body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html><head><title>MemberServ 7</title>
    <style>body{{font:16px Arial;background:#e8e5d8;margin:0}}header{{background:#17324d;color:white;padding:16px}}
    main{{width:760px;margin:32px auto;background:white;border:2px solid #777;padding:24px}}
    table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #777;padding:10px;text-align:left}}
    .error{{background:#ffe5e5;border:1px solid #a00;padding:12px;color:#800}}button{{padding:8px 20px}}</style>
    </head><body><header>MemberServ 7 - Internal Operations</header><main>{body}</main></body></html>""")


@app.get("/", response_class=HTMLResponse)
def home():
    return page("""<h1>Member Search</h1><form method="post" action="/search">
    <label for="member-number">Member Number</label><br>
    <input id="member-number" name="member_id" autocomplete="off" required>
    <button type="submit">Search</button></form>""")


@app.post("/search", response_class=HTMLResponse)
def search(member_id: str = Form(...)):
    member = MEMBERS.get(member_id)
    if not member:
        return page(f"""<h1>Member Search</h1><div class="error" role="alert">Member not found</div>
        <p>No record matches member number {member_id}.</p><a href="/">Return to search</a>""")
    interstitial = ""
    if member_id == INTERSTITIAL_MEMBER_ID:
        interstitial = """<div id="session-interstitial" role="alertdialog" class="error">
        <p>Session Notice: Please confirm to continue.</p>
        <button type="button" onclick="document.getElementById('session-interstitial').remove()">Continue</button>
        </div>"""
    loading = ""
    if member_id == TRANSIENT_LOAD_MEMBER_ID:
        loading = """<div id="loading-banner" role="status">Loading member details, please wait...</div>
        <script>setTimeout(function(){var el=document.getElementById('loading-banner');if(el)el.remove();}, 1200);</script>"""
    return page(f"""{interstitial}{loading}<h1>Member Details</h1><table><tr><th>Member Number</th><td>{member_id}</td></tr>
    <tr><th>Name</th><td>{member["name"]}</td></tr></table>
    <form method="get" action="/member/{member_id}/accounts"><button type="submit">Open Accounts</button></form>""")


@app.get("/member/{member_id}/accounts", response_class=HTMLResponse)
def accounts(member_id: str):
    member = MEMBERS.get(member_id)
    if not member:
        return page('<div class="error" role="alert">Member not found</div>')
    return page(f"""<h1>Savings Account</h1><table><tr><th>Account Type</th><th>Available Balance</th></tr>
    <tr><td>Primary Savings</td><td id="savings-balance">${member["balance"]:,.2f}</td></tr></table>
    <p>Status: Active</p>""")
