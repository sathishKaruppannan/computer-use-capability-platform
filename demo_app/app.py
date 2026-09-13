from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

app = FastAPI(title="Legacy Member Servicing Demo")

MEMBERS = {
    "10001": {"name": "Alex Morgan", "balance": 4250.25},
    "10002": {"name": "Jordan Lee", "balance": 1220.00},
}


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
    return page(f"""<h1>Member Details</h1><table><tr><th>Member Number</th><td>{member_id}</td></tr>
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
