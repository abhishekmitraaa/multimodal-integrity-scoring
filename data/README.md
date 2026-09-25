# data

Local data root for **development only**. Everything here is git-ignored except `synthetic/`.

| Folder | Contents | Committed? |
|---|---|---|
| `synthetic/` | Small, hand-made or generated fixtures. Filenames must contain `synthetic`. | yes |
| `external/` | Public datasets, for example Aalto (after licence confirmation) | no |
| `raw/`, `processed/` | **Never** real participant data here: this folder is inside OneDrive. | no |

Real participant data goes to `privacy.data_root` (see `config/privacy.yaml`). It must be outside any
cloud-synced folder. The backend will refuse to start otherwise (P1).
