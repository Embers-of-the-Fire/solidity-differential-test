# Related work — DRAFT scaffold (anchor list)

## Compiler testing / differential testing

- **Csmith** (Yang et al., PLDI 2011) — random C program generation for
  compiler bug finding. *Difference: we replay on two live chains with an
  on-chain oracle, not a single compiled binary.*
- **EMI** (Le et al., PLDI 2014) — equivalence modulo inputs. 
- **Orion/Athena, Yarpgen** — RNG-based generator baselines.
- Historical bug rediscovery as ground truth: solc's bugs.json convention;
  our ground-truth set is `agent/data/ground_truth/` validated against
  pinned compiler versions.

## Test-case reduction

- **C-Reduce** (Regehr et al., PLDI 2012), **Perses** (Sun et al., ICSE 2018)
  — syntax-guided reduction; our AST stage is a budgeted, two-gate,
  domain-specialized analogue using the compiler's own AST spans.
- **HDD** (Misherghi & Su, ICSE 2006) — hierarchical delta debugging.
- **ddmin** (Zeller & Hildebrandt, TSE 2002) — our generic step/chunk engine.
- *Difference: our acceptance predicate is a cross-chain behavioral
  signature, and 1-minimality is verified exhaustively, not assumed.*

## Smart-contract fuzzing / analysis

- **Echidna** (property-based EVM fuzzer), **sFuzz**, **Smartian**,
  **Manticore**, **Mythril** — single-chain; none cross-compile Solidity to
  two targets and compare on-chain behavior.
- solc's own test suite / fuzzers (solc fuzzer, protobuf-mutator harness);
  solang's mock-vm integration tests — single-implementation testing; our
  oracle needs no mocks because both chains are real.

## LLM agents for testing

- LLM-guided fuzzing (FuzzGPT, TitanFuzz, Fuzz4All) — *difference: the LLM
  here is a pluggable generator inside a verified loop; witnesses are
  confirmed by execution and reduced deterministically, so LLM unsoundness
  cannot leak into the dataset.*

(solc/solang testing literature to be harvested: search Semantic Scholar for
"Solidity compiler testing", "differential testing blockchain", "wasm
smart contract".)
