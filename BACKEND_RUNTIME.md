# Backend Python Runtime

This backend currently targets Python 3.12.x.

Reason:
Some pinned dependencies, especially numpy==1.26.4 and pandas==2.1.2, are not safe to install under Python 3.13 in this project without a broader dependency upgrade pass. Use Python 3.12.x for local development and deployment until the scientific/data stack is intentionally upgraded.

Local setup:

```powershell
python --version
python -m venv .venv
.venv\Scripts\activate   # Windows PowerShell
pip install --upgrade pip
pip install -r requirements.txt
```
