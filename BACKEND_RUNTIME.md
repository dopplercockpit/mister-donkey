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

Cost protection environment:

- `LLM_CACHE_TTL_SECONDS`: SQLite LLM response cache TTL in seconds. Default `10800`.
- `LLM_DAILY_LIMIT_PER_IP`: fresh LLM call limit per hashed IP per UTC day. Default `20`.
- `LLM_BURST_LIMIT_PER_MINUTE`: fresh LLM call limit per hashed IP per UTC minute. Default `5`.
- `RATE_LIMIT_SALT`: salt used before hashing client IPs. Required outside dev/local/test.
- `DISABLE_LLM`: set to `true` to skip fresh LLM calls and return deterministic fallback roasts.
