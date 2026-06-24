"""
GiveTrack - Nonprofit Donation Manager
---------------------------------------
Run this file to start the app:
    python run.py

Then open:
    Admin Dashboard → http://localhost:5000
    Public Website  → http://localhost:5000/public
"""
from app import app

if __name__ == "__main__":
    print("\n✅  GiveTrack is running!")
    print("   Admin Dashboard → http://localhost:5000")
    print("   Public Website  → http://localhost:5000/public\n")
    app.run(debug=True, port=5000)
