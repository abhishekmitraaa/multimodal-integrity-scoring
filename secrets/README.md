# secrets (moved out of the repository)

The real secrets no longer live here (D-028, SPEC 10.6). They are in `INTEGRITY_SECRETS_DIR`, or
`~/.integrity-exam/secrets` by default (on Windows `C:\Users\<you>\.integrity-exam\secrets`):
`pg_password.txt`, `data_key.bin`, `reviewer_token.txt`, `admin_token.txt`.

The backend refuses a secrets folder inside this repository or inside a cloud-synced folder.
Create them with `python scripts/make_secrets.py`; back them up with
`python scripts/backup_secrets.py backup <file on an offline drive>`.

This folder stays git-ignored as a safety net. Never commit, email or sync secrets.
