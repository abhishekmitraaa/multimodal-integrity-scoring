# secrets

Git-ignored. Holds local keys only: `pg_password.txt`, `data_key.bin`, `chain_signing_key.pem`.
Never commit, email or sync these. The signing key must be held separately from database
credentials (SPEC 4.4).
