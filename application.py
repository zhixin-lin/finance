import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# CREATE transactions Table if not exists
db.execute("CREATE TABLE IF NOT EXISTS transactions (personID INTEGER, symbol TEXT, name TEXT, shares INTEGER, price NUMERIC, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # Get the current portfolio distribution
    # Renamed SUM(shares) column to totalShares so that Jinja could recognize the name correctly
    portfolio = db.execute(
        "SELECT symbol, name, SUM(shares) as totalShares FROM transactions WHERE personId = ? GROUP BY symbol HAVING SUM(shares) > 0", session["user_id"])

    # Add current price and subtotal to each dict in the portfolio list
    totalValue = 0
    for row in portfolio:
        quote = lookup(row["symbol"])
        row["currentPrice"] = quote["price"]
        row["total"] = quote["price"] * row["totalShares"]
        totalValue += row["total"]

    # Get current cash balance and total account value
    cashRow = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
    cash = cashRow[0]["cash"]
    totalValue += cash

    # Render index page
    return render_template("index.html", portfolio=portfolio, totalValue=totalValue, cash=cash)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    # User reached route via POST (submitting buy form)
    if request.method == "POST":
        # Turn symbol into uppercase
        symbol = request.form.get("symbol").upper()
        shares = request.form.get("shares")

        # Check if symbol is empty
        if not symbol:
            return apology("missing symbol", 400)

        # check if shares is empty or non-positive integer
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("shares not valid", 400)

        # Check if stock exists
        stock = lookup(symbol)
        if not stock:
            return apology("symbol not found", 400)

        # Check if the user has enough cash
        shares = int(shares)
        balance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
        if balance < stock["price"] * shares:
            return apology("not enough cash", 400)

        # Proceed purchasing: update transaction table record and user cash balance
        db.execute("INSERT INTO transactions (personID, symbol, shares, price, name) VALUES (?, ?, ?, ?, ?)",
                   session["user_id"], symbol, shares, stock["price"], stock["name"])
        newBalance = balance - shares * stock["price"]
        db.execute("UPDATE users SET cash = ? WHERE id = ?", newBalance, session["user_id"])
        return redirect("/")
    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    history = db.execute("SELECT symbol, shares, price, time FROM transactions WHERE personId = ?", session["user_id"])
    return render_template("history.html", history=history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    # User reach route via POST
    if request.method == "POST":

        # Check if user has input symbol
        if not request.form.get("symbol"):
            return apology("missing symbol", 400)

        dict = lookup(request.form.get("symbol"))

        # Check whether the symbol exists
        if not dict:
            return apology("stock no found", 400)

        return render_template("quoted.html", name=dict["name"], price=dict["price"], symbol=dict["symbol"])
    # User reach route via GET
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Check if user has input a username
        if not username:
            return apology("must provide username", 400)

        # Query database for username duplicate
        rows = db.execute("SELECT * FROM users WHERE username = ?", username)

        # Check whether user name exists
        if len(rows) != 0:
            return apology("username already exists", 400)

        # Check whether user have matching passwords
        if not password or password != request.form.get("confirmation"):
            return apology("passwords do not match", 400)

        # Update the database with new registrant info
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, generate_password_hash(password))
        newRow = db.execute("SELECT id FROM users WHERE username = ?", username)
        session["user_id"] = newRow[0]["id"]
        return redirect("/")

    # User reached route via GET
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    # User reached route via POST
    if request.method == "POST":
        shares = request.form.get("shares")
        symbol = request.form.get("symbol").upper()

        # Check if shares and symbol are valid
        if not symbol:
            return apology("missing symbol", 400)
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("invalid shares", 400)

        # Check if users have enough shares to sell
        shares = int(shares)
        actualShares = db.execute(
            "SELECT SUM(shares) as totalShares FROM transactions WHERE personId = ? AND symbol = ?", session["user_id"], symbol)[0]["totalShares"]
        if not actualShares:
            return apology("you do not own this stock", 400)

        if actualShares < shares:
            return apology("too many shares", 400)

        # Enquire the stock price and sell the stocks. Record shares as negative values to indicate the state of sold
        stock = lookup(symbol)
        db.execute("INSERT INTO transactions (personID, symbol, shares, price, name) VALUES (?, ?, ?, ?, ?)",
                   session["user_id"], symbol, -shares, stock["price"], stock["name"])

        # Update user cash balance
        oldBalance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
        newBalance = oldBalance + shares * stock["price"]
        db.execute("UPDATE users SET cash = ? WHERE id = ?", newBalance, session["user_id"])

        # Redirect to the home page with updated portfolio
        return redirect("/")

    # User reached route via GET
    else:
        symbols = db.execute(
            "SELECT symbol FROM transactions WHERE personId = ? GROUP BY symbol HAVING SUM(shares) > 0", session["user_id"])
        return render_template("sell.html", symbols=symbols)


# Personal Touch: Add Cash
@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    """Get stock quote."""
    # User reach route via POST
    if request.method == "POST":
        add = request.form.get("add")

        # Check if user has input cash amount
        if not add:
            return apology("missing cash amount", 400)

        # Check if top-up amount is at least 100 USD
        if not add.isdigit() or int(add) < 100:
            return apology("invalid cash amount", 400)

        # Add cash
        oldBalance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
        cash = oldBalance + int(add)
        db.execute("UPDATE users SET cash = ? WHERE id = ?", cash, session["user_id"])

        return redirect("/")

    # User reach route via GET
    else:
        return render_template("add.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
