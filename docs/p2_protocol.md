# P2 protocol: TypeNet reproduction and the non-deep baseline

Version 0.3, 2026-10-24 (deviation 6 amended after the synthetic encoder check). Status: **decisions in §12 taken (delegated by the lead). Nothing has been
trained on real keystroke data; D1 is not yet available.** SPEC §12.7 requires this document before any P2 training.

## Sources checked

| Source | What was read | Status |
|---|---|---|
| A. Acien, A. Morales, J. V. Monaco, R. Vera-Rodriguez, J. Fierrez, "TypeNet: Deep Learning Keystroke Biometrics", arXiv:2101.05570**v3** (13 Sep 2021) | Full text, all 15 pages. Every quote below comes from this version. | read |
| Published version: *IEEE Transactions on Biometrics, Behavior, and Identity Science* (T-BIOM). arXiv lists "T-BIOM, 2021". The authors' repository README gives "vol. 4, pp. 57–70, 2022". | Not read. | **[VERIFY]** the published text may differ from arXiv v3 |
| Authors' repository README, github.com/BiDAlab/TypeNet (last pushed 2024-05-31) | Full README, including its example evaluation code | read |
| A. Acien et al., "TypeNet: Scaling up Keystroke Biometrics", IJCB 2020, arXiv:2004.03627v2 (the preliminary version, contrastive loss only) | Checked for details missing from the journal text. It adds nothing new for the triplet protocol. | read |
| V. Dhakal, A. M. Feit, P. O. Kristensson, A. Oulasvirta, "Observations on Typing from 136 Million Keystrokes", CHI 2018 (the dataset paper) | Not read. Dataset facts below are TypeNet's description of it. | **[VERIFY]** when the dataset arrives |

Section and table numbers below (§, Table, Eq.) refer to arXiv v3. "README" means the authors'
repository README.

---

## 0. What the brief said and what the paper says

| Claim in the brief | The paper | Verdict |
|---|---|---|
| About 4.5% EER at 1 enrollment sequence | Table 2, triplet loss, M = 70, G = 1: **4.5%**. §6.1: "For one-shot authentication (G = 1), our approach has an error rate of 4.5% using sequences of 70 keystrokes." | **Correct**, under the conditions in the last row |
| 1.2% at 10 | Table 2, triplet loss, M = 70, G = 10: **1.2%** (also 1.2% at M = 100 and 150). §6.1 adds "with a standard deviation of σ ≤ 4.1%". | **Correct**, same conditions |
| Desktop | The Dhakal dataset, typed "on either a desktop or a laptop physical keyboard" (§3). | Correct; laptops included |
| On 168k subjects | 168,000 is the size of the dataset. The model is trained on "the first 68,000 subjects" and "the remaining 100,000 subjects were employed only for model evaluation" (§4.4). Table 2 uses **k = 1,000** enrolled test subjects (§6.1: "For this experiment, we set k = 1,000"). Scaling to k = 100,000 is shown only in Fig. 5, for M = 50 and G ∈ {1, 5}. | **Wrong as stated.** The 4.5% and 1.2% figures are for 1,000 test subjects. |
| English free text (SPEC §1.2) | "Controlled free-text": subjects "memorize English sentences and then type them", sentences of "a minimum of 3 words and a maximum of 70 characters" (§3). One sentence per "session", 15 per subject. | **Imprecise.** It is short memorised sentences, not free composition. |
| Headline figure | The abstract's 2.2% is triplet, **M = 50, G = 5**, k = 1,000 (Table 2; §7). | Not in the brief; worth knowing |
| 50–70 keystroke plateau (SPEC §6.1) | §6.1: "for sequences longer than M = 70 there is no significant improvement in performance. Adding three times more key events (from M = 50 to M = 150) lowers the EER by only 0.7% in average for all values of G." | **Confirmed as printed.** But see the note below. |
| (not in the brief) How EER is computed | §5.1: "The error rates are calculated for each subject and then averaged over all k subjects." So every subject gets their own threshold. | Important: see §0.1 |

**The plateau probably comes from the data, not from typing.** This is our inference; the paper
does not say it. Each sequence is one sentence of at most about 70 characters (§3), and shorter
sequences are zero-padded (§4.2). So M = 100 or 150 mostly adds padding, not keystrokes. It does
not show that longer windows stop helping on continuous code typing, where every window is full.
The M ablation on our own data (SPEC §6.1) therefore stays in.

### 0.1 What the TypeNet numbers do not tell us

These conditions make the published EERs optimistic compared with our setting:

1. **Per-subject thresholds.** Averaging per-subject EERs gives each subject their own ideal
   threshold. Our system uses one global threshold τ set on validation users (SPEC §8.5). A
   global-threshold EER is normally higher.
2. **Probably one sitting.** Each "session" is one sentence (§3), and the data comes from an online
   typing test. The 15 sentences were then probably typed minutes apart, in one sitting. If so,
   genuine comparisons never cross days. **[VERIFY against Dhakal et al. 2018.]** Our study
   separates enrollment and exam by at least a day (SPEC §12.2), and cross-day typing varies more.
3. **Short memorised English sentences.** Code typing has more symbols, brackets, Shift chords,
   Enter/Tab, Backspace and long pauses for thought.
4. **Zero-effort impostors.** Impostor scores are other people's sentences (§5.1). Nobody is trying
   to imitate anyone.
5. **Identity, not authorship.** Even at 1% EER this only tells us who is typing. It says nothing
   about copy-typing (A4) or typed-in LLM code (A5), where the genuine student is the one typing.

---

## 1. Dataset subset, filtering and the train/test split

**Verified on the data (2026-10-24).** `Keystrokes.zip` from userinterfaces.aalto.fi/136Mkeystrokes
(1,572,785,433 bytes, sha256 `5fb217e0…88e270420`). Facts:

- **168,593 participants, every one with exactly 15 sentences.** So the "15 sessions" rule
  filters nobody.
- **123,108,258 keystroke rows,** against "136M" in the name; the readme does not explain the gap.
- 745 malformed lines, and 284,864 keystrokes (0.23%) with a release missing or before the press,
  which are dropped.
- **Median 46 keystrokes per sentence** (5th–95th percentile 22–80, from a 2,000-participant
  sample); only 14% reach 70.
- **Keyboard types** (metadata): laptop 91,250; full desktop 73,758; small physical 1,886;
  on-screen 1,699. About 2.1% are not desktop or laptop keyboards. TypeNet calls the set desktop
  and mentions no filter, so we keep everyone and report this.
- **Licence** (readme.txt): "free to use this data for non-commercial use in your own research or
  projects with attribution to the authors". Nothing is said about redistribution, so the data and
  anything derived from it stay outside the repository.


| Item | Quote or source | Our choice when not stated |
|---|---|---|
| Dataset | §3: "The Dhakal et al. dataset [31] comprises more than 5GB of keystroke data collected on desktop keyboards from 168,000 participants" | Aalto desktop release, downloaded by the lead. Stored under `INTEGRITY_DATA_ROOT/external/aalto_desktop/`, never in the repo. |
| Sessions per subject | §3: "All participants in the Dhakal database completed 15 sessions (i.e. one sentence for each session)" | We count subjects with exactly 15 usable sentences and report the count. **[VERIFY on arrival]** whether the release has 168,000 such subjects. |
| Filtering of users or sessions | Not stated. | No filtering beyond "15 sentences present". Every rule we add is logged with counts. |
| Handling of typing errors and Backspace | Not stated. The keycode range (0–255) suggests all keys are kept. | Keep every keydown/keyup pair, including Backspace, Shift and other modifiers. |
| Training subjects | §4.4: "we train the models using only the first 68,000 subjects from the Dhakal dataset" | "First" is not defined. We sort by participant ID ascending and take the first 68,000. |
| Test subjects | §4.4: "The remaining 100,000 subjects were employed only for model evaluation, so there is no data overlap between the two groups of subjects." | The rest of the sorted list. |
| Test subjects used in Table 2 | §6.1: "we set k = 1,000". The README code uses the first 1,000 subjects of the authors' test matrix (`range(NUM_TEST_USERS)`). | The first 1,000 of our test list. We also report the mean and SD over 5 random draws of 1,000 (seeded), because our "first 1,000" are not the authors'. |
| Validation set | None mentioned. Training runs a fixed 200 epochs (§4.4). | No model selection. If a learning-rate fallback is needed (deviation 6), its validation users come from the 68,000 training subjects, never the test pool. |

## 2. Sequences

| Item | Quote | Our choice |
|---|---|---|
| Sequence | §3 and §5.1: one session = one sentence; 15 per subject | Same |
| Length M | §6.1, Tables 2–3: M ∈ {30, 50, 70, 100, 150} | Reproduce M = 50 and M = 70 (the rows in the acceptance test). The others are optional. |
| Shorter and longer sequences | §4.2: "we truncate the end of the input sequence when N > M and zero pad at the end when N < M, in both cases to the fixed size M" | Same |
| Masking | §4.2: "Error gradients are not computed for those zeros and do not contribute to the loss function at the output layer as a result of the masking layer" | Packed sequences in PyTorch, so padding never enters the LSTM (deviation 4) |
| Keystroke order | Not stated | Ordered by press time |
| Sequences per subject in training | §4.4: all 15 | Same |

## 3. Per-keystroke features

| Item | Quote | Our choice |
|---|---|---|
| Features | §4.1: "(i) Hold Latency (HL), the elapsed time between key press and release events; (ii) Inter-key Latency (IL), the elapsed time between releasing a key and pressing the next key; (iii) Press Latency (PL), the elapsed time between two consecutive press events; and (iv) Release Latency (RL), the elapsed time between two consecutive release events." "Finally, we include the keycodes as an additional feature." Fig. 1 shows IL between release of A and press of B. | Same definitions as SPEC §6.1. IL is negative when keys overlap. |
| Input shape | §4.1: "a time series with shape N × 5" | Same |
| Units and normalisation | §4.1: "The keycodes are normalized to between 0 and 1 by dividing each keycode by 255, and the 4 timing features are converted to seconds." | Same |
| Clipping | Not done. §4.1: "Only latency features that occur either during very slow typing or long pauses exceed a value of 1." | **No clipping** in the reproduction. The 1500 ms clip in `config/features.yaml` is our own choice for our data and is not used here. |
| Keycodes | §4.1: "integers between 0 and 255 according to the ASCII code" | Use the dataset's keycode as-is. **[VERIFY on arrival]** the column name and whether it is a JavaScript `keyCode`. |
| Timer | §3: "recorded in the browser with millisecond resolution using the JavaScript function Date.now" | Nothing to do for D1. It matters when we fine-tune on our µs data (deviation 10). |
| Last keystroke of a sequence | Not stated. PL, IL and RL need a next key. | Set to 0 for the last keystroke |

## 4. Architecture

| Item | Quote | Our choice |
|---|---|---|
| Layers | §4.2: "two Long Short-Term Memory (LSTM) layers of 128 units (tanh activation function). Between the LSTM layers, we perform batch normalization and dropout at a rate of 0.5 to avoid overfitting." | Same |
| Recurrent dropout | §4.2: "each LSTM layer has a recurrent dropout rate of 0.2" | **Deviation 3** (PyTorch's LSTM has no recurrent dropout) |
| Input batch norm and masking | Fig. 2: Masking → Batch Norm → LSTM(128) → Dropout(0.5) / Batch Norm → LSTM(128) → f(x) | Same, confirmed by the parameter count below |
| Embedding | §4.2: "the output of the model f(x) is an array of size 1 × 128". No dense layer after the second LSTM. | Final hidden state of the second LSTM at the last real keystroke |
| Parameter count | §4.2: "This RNN model is composed by 200,458 trainable parameters." | See the check below |

**Parameter-count check** (our arithmetic). A Keras LSTM with input size d and u units has
4(u(d + u) + u) weights; a Keras batch-norm layer has 2 trainable weights per feature.

| Layer | Trainable parameters |
|---|---|
| BatchNorm on the 5 input features | 10 |
| LSTM(128), input 5 | 4 × (128 × 133 + 128) = 68,608 |
| BatchNorm(128) | 256 |
| LSTM(128), input 128 | 4 × (128 × 256 + 128) = 131,584 |
| **Total** | **200,458**, equal to the paper's figure |

So Fig. 2 is complete: exactly one batch norm on the input, one between the LSTMs, and no dense
layer. The count cannot tell whether dropout comes before or after the middle batch norm. We follow
the §4.2 wording order (batch norm, then dropout). PyTorch's `nn.LSTM` has two bias vectors per
layer instead of one, so the same network has 201,482 parameters in PyTorch (200,458 + 2 × 512).
The two parametrisations are equivalent. The encoder's unit test will check the 201,482 figure.

## 5. Loss and training

| Item | Quote | Our choice |
|---|---|---|
| Loss | §4.3.3, Eq. 4: L = max{0, d²(x_A, x_P) − d²(x_A, x_N) + α}, with d the Euclidean distance (Eq. 2) | Same, on squared distances |
| Margin | §4.4: "the margin set to α = 1.5" | 1.5 (already in `config/models.yaml`) |
| Triplet selection | §4.4: "Similarly, we randomly chose triplets for the Triplet loss training." §7: "Currently, the pairs are chosen randomly". No hard mining. | Anchor and positive: two different sentences of a random training subject. Negative: a random sentence of another random subject. |
| Optimiser | §4.4: "a learning rate of 0.05, Adam optimizer with β1 = 0.9, β2 = 0.999 and ϵ = 10−8" | Same. **Our config said 0.005. It is corrected to 0.05.** |
| Batch | §4.4: "512 sequences in each batch" | Unclear for triplets. We read it as 512 triplets per batch, which is what a three-input Keras model with batch size 512 gives. **[OPEN, minor]** |
| Epochs and stopping | §4.4: "trained for 200 epochs with 150 batches per epoch". No early stopping is mentioned. | 200 × 150 batches, then keep the final weights. An "epoch" is 150 random batches, not a pass over the data. |
| Framework | §4.4: "The models were built in Keras-Tensorflow." | PyTorch (D-001). Deviations 2–5 follow from this. |
| Softmax and contrastive models | §4.4 trains all three | Triplet only (SPEC §7.1). We compare against the triplet column. |

## 6. Enrollment and scoring

| Item | Quote | Our choice |
|---|---|---|
| Score | §5.1, Eq. 5: s = (1/G) Σ_g ‖f(x_gallery,g) − f(x_query)‖. The **mean of the distances** to each gallery embedding. | Eq. 5 for the reproduction. **This differs from SPEC §7.3**, which uses the distance to the mean embedding (a prototype). See decision 2 (§12). |
| Test and gallery split | §5.1: "we retain 5 sequences per subject as the test set (i.e. each subject has 5 genuine test scores) and let G vary between 1 ≤ G ≤ 10". README code: gallery = sentences 0 … G−1; genuine queries = sentences 10–14. | Same indices |
| Impostors | §5.1: "for each enrolled subject we choose one test sample from each remaining subject … each subject has 5 genuine scores and k − 1 impostor scores". README code: the impostor query is sentence 11 of every other test subject. | Same |
| G values | Table 2: G ∈ {1, 2, 5, 7, 10} | The paper's grid for the reproduction. Our own data keeps SPEC §7.3's {1, 3, 5, 10}. |

## 7. EER computation

| Item | Quote | Our choice |
|---|---|---|
| Per subject or global | §5.1: "The error rates are calculated for each subject and then averaged over all k subjects [38]." | Per subject, then the mean over subjects (reproduction). For our own data we also report the global-threshold EER, because that matches how τ is used. |
| Algorithm | README `eer_compute`: a sweep of 10,000 evenly spaced thresholds between the minimum and maximum score; the EER is the mean of FAR and FRR where they are closest. | Same algorithm for the reproduction, unit-tested on synthetic scores. With 5 genuine scores the per-subject FRR moves in steps of 20%, so the sweep's details matter. |
| Spread | §6.1 reports "σ ≤ 4.1%" for the 1.2% cell | We report the SD across subjects too |

## 8. The published table we compare against

Table 2 (desktop), EER in %, as printed, in the order softmax / contrastive / **triplet**:

| M \ G | 1 | 2 | 5 | 7 | 10 |
|---|---|---|---|---|---|
| 30 | 17.2 / 10.7 / 8.6 | 14.1 / 9.0 / 6.4 | 13.3 / 7.3 / 4.6 | 12.7 / 6.8 / 4.1 | 11.5 / 3.3 / 3.7 |
| 50 | 16.8 / 8.2 / 5.4 | 13.1 / 6.7 / 3.6 | 10.8 / 5.4 / 2.2 | 9.2 / 4.8 / 1.8 | 8.8 / 4.3 / 1.6 |
| 70 | 14.1 / 7.7 / 4.5 | 10.4 / 6.2 / 2.8 | 7.5 / 4.8 / 1.7 | 6.7 / 4.3 / 1.4 | 6.0 / 3.9 / 1.2 |
| 100 | 13.8 / 7.7 / 4.2 | 10.1 / 6.0 / 2.7 | 7.4 / 4.7 / 1.6 | 6.4 / 4.3 / 1.4 | 5.7 / 3.9 / 1.2 |
| 150 | 13.8 / 7.7 / 4.1 | 10.1 / 6.0 / 2.7 | 7.4 / 4.7 / 1.6 | 6.5 / 4.3 / 1.4 | 5.8 / 3.8 / 1.2 |

One printed cell looks wrong: contrastive at M = 30, G = 10 is 3.3, lower than 6.8 at G = 7. We
don't use the contrastive column.

**Acceptance bands** (SPEC §12.7: within max(1 point, 50% relative) of the published value), triplet
loss, k = 1,000:

| M \ G | 1 | 2 | 5 | 7 | 10 |
|---|---|---|---|---|---|
| 50 | 5.4 [2.7, 8.1] | 3.6 [1.8, 5.4] | 2.2 [1.1, 3.3] | 1.8 [0.8, 2.8] | 1.6 [0.6, 2.6] |
| 70 | 4.5 [2.25, 6.75] | 2.8 [1.4, 4.2] | 1.7 [0.7, 2.7] | 1.4 [0.4, 2.4] | 1.2 [0.2, 2.2] |

A result far **below** the band is treated as a failure too, because it usually means leakage.
Outside the band, we write a gap analysis instead of tuning towards the number.

---

## 9. Our deviations from the paper

| # | Deviation | Why | Expected effect |
|---|---|---|---|
| 1 | Training subsets may be subsampled | 6 GB GPU (SPEC §7.1) | Probably not needed: 68,000 × 15 sequences × 70 × 5 floats ≈ 1.4 GB in float32. Any subsampling is reported. |
| 2 | PyTorch instead of Keras | D-001 | Small. We copy Keras's defaults where they matter: batch-norm momentum 0.99 (PyTorch `momentum=0.01`) and ε = 10⁻³; LSTM forget-gate bias initialised to 1; Glorot-uniform input weights and orthogonal recurrent weights. The paper doesn't state its initialisation, so we assume the Keras defaults. |
| 3 | **No recurrent dropout** in the first run | PyTorch's `nn.LSTM` has none, and a custom cell loses the fast cuDNN kernel | Slightly more overfitting, so perhaps a slightly higher EER. If we land outside the band, we add a custom LSTM cell with recurrent dropout 0.2 and rerun (decision 3, §12). |
| 4 | Packed sequences; batch-norm statistics over real keystrokes only | Whether padded zeros entered Keras's batch-norm statistics depends on the Keras version, which isn't stated | Small; it matters only for short sentences |
| 5 | Final hidden state taken at the last real keystroke | This is what a Keras masked LSTM returns | None |
| 6 | **Amended 2026-10-24.** The learning rate is chosen from {0.05, 0.01, 0.005} (0.05 = the paper's value, tried first) by per-subject EER on 1,000 **validation subjects held out from the 68,000 training subjects**. The choice is made before any access to the test pool and logged. | On SYNTHETIC data (§10), 0.05 barely trains in our PyTorch setup: at separation 1.0, loss 0.69 → 0.54 and EER 34.6%, against 0.40 → 0.11 and 5.6% with 0.005. The original trigger ("if training diverges") missed this, because the loss falls slowly rather than diverging. | If a lower rate is chosen, it is a deviation from the paper, reported with both validation EERs. Possible reasons (unverified): a typo in the paper, or Keras/PyTorch differences. |
| 7 | Triplet sampling details | Not stated (§4.4) | Unknown, probably small |
| 8 | "First 68,000" and "first 1,000" by our participant-ID order | The authors' order isn't stated | Different test subjects. We report the spread over 5 random draws of 1,000. |
| 9 | Triplet loss only | SPEC §7.1 | None on the triplet column |
| 10 | Timer resolution: ms (Aalto) for pretraining, 5–20 µs (our capture) for fine-tuning | Different data sources | Nothing in P2. For P3 fine-tuning we may round our timings to 1 ms to match pretraining; that is an ablation. |
| 11 | Keycodes: Aalto gives integer keycodes; our capture stores `KeyboardEvent.code` strings | SPEC §4.5 | Nothing in P2. P3 needs a fixed `code` → keycode table (US-layout legacy keyCodes) to share the keycode feature. |

## 10. The non-deep baseline under the same protocol

**Purpose.** To show what the LSTM adds over a simple distance, on the same subjects, sequences and
EER computation. P2 builds it before the encoder.

**As specified (SPEC §7.2).** The digraph profile is built from the G gallery sentences. It keeps
ordered `code` pairs seen at least `models.digraph.min_occurrences` (3) times, with their median PL,
plus the median HL per key. The distance to a query is the mean absolute difference over shared
items (Manhattan, divided by the number of shared items). The baseline is unavailable if fewer than
5 items are shared.

**Sparsity at small G (measured on D1, 2026-10-24).** One sentence has a median of 46 keystrokes
(about 45 digraphs, most of them unique), so few items reach 3 occurrences.

- **On D1 at G = 1, the SPEC §7.2 baseline could score only 65% of comparisons.** From G = 2 up it
  scored 99–100%.
- Earlier versions of this note first predicted widespread unavailability (v0.1), then "corrected"
  that from synthetic data, where availability was 100% (v0.2). The synthetic generator has only
  27 keys, so common keys repeat far more than in real text. **The real data decides:** the
  baseline is often unavailable at G = 1, and at small G it is mostly a hold-time comparison.
- The availability rate is reported with every result. TypeNet's own digraph comparison
  (digraph/SVM, a different method) was "near chance accuracy" at G = 5, M = 50 (§6.1).

**Pipeline check on labelled synthetic data (D3).** Before any real data, the baseline and the
EER code run on generated users (filenames and figures marked SYNTHETIC; never reported as
results):

- Each synthetic user has per-key hold means and per-digraph flight means drawn from population
  log-normals, plus within-user noise. Sentences come from a fixed text pool.
- Expected outcomes, checked by tests: users with widely separated parameters give an EER near 0;
  identical users give an EER near 50%; lowering the separation raises the EER step by step.
- These checks only show the code works. They show nothing about keystroke identity.
- **Status (2026-10-24): implemented and run.** `python -m integrity_eval.p2_synthetic` runs both
  baselines under the exact TypeNet indices on 100 synthetic subjects per separation level. As
  intended, identical subjects give an EER of about 50%, the EER falls as separation grows, more
  gallery sentences help, and the per-subject EER is below the global-threshold EER. Code:
  `ml/src/integrity_ml/{eer,baselines,synthetic_keystrokes}.py` and
  `eval/src/integrity_eval/{authentication,p2_synthetic}.py`. The EER sweep matches a
  transcription of the authors' `eer_compute` to 1e-9 on random score sets.
- **Encoder on synthetic data (2026-10-24).** The encoder trains end to end on the GPU (RTX 3050).
  With the paper's learning rate it barely learns (above); with 0.005 it separates synthetic
  subjects well (EER 5.6% at separation 1.0, 0.8% at 2.0; G = 5; 200 training and 100 test
  subjects; 10 epochs). This rules out a gross bug and led to the amendment of deviation 6.
  The synthetic generator encodes identity exactly in per-digraph timing, which the digraph
  baseline measures directly. So the baseline "winning" on synthetic data says nothing about
  real typing.

## 11. Test access and data handling for D1

- Every evaluation on the 1,000 (or 100,000) D1 test subjects appends a line to the test-access
  ledger (SPEC §12.3), as for our own data. D1 is a reproduction, not our headline result, but the
  same discipline costs nothing.
- The raw Aalto data and anything derived from it (features, trained weights) live under
  `INTEGRITY_DATA_ROOT`. Nothing derived from D1 is committed until the lead has checked the
  licence's redistribution terms.

## 12. Decisions (the lead delegated these on 2026-10-24)

1. **Baseline at small G: both.** (a) The SPEC §7.2 digraph baseline as specified, reported with
   its availability rate, with the EER computed on available comparisons only. (b) An
   always-available scaled-Manhattan baseline on per-sequence timing statistics (mean and SD of
   HL, PL, IL and RL), scaled by the spread over training subjects. Both score a query against the
   pooled gallery, because a single 70-keystroke sentence is too sparse for a digraph profile.
2. **Scoring rule: Eq. 5 primary.** Eq. 5 for the reproduction. On our data both rules are
   pre-registered, with Eq. 5 primary and the prototype rule (SPEC §7.3) as an ablation.
3. **Recurrent dropout: omitted** in the first PyTorch run. It is added (custom cell) only if an
   acceptance cell falls outside its band.
4. **TypeNet Benchmark: recommended, not requested.** It needs the lead's signature on BiDA Lab's
   licence agreement, so it is an action for the lead. P2 does not depend on it: our EER code is
   unit-tested against hand-computed cases and against the authors' published algorithm.

