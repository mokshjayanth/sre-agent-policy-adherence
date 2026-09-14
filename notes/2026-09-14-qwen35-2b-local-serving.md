---
date: 2026-09-14
type: investigation
status: current
evidence:
  - runs/2026-09-14T161925Z_smoke-qwen3.5-2b
  - https://huggingface.co/Qwen/Qwen3.5-2B (revision 15852e8c16360a2fea060d615a32b45270f8a8fc)
  - vllm/envs.py and vllm/v1/sample/ops/topk_topp_sampler.py in the serving environment (vLLM 0.29.0, outside the repo)
  - third_party/aiopslab/aiopslab/orchestrator/parser.py:16-18
  - agents/openai_compatible.py
---

# Can the B1 model be served locally and driven through the harness?

## Question

B1 is Qwen3.5-2B served locally with vLLM, the same serving stack T1 and T2 will use
(`notes/2026-09-14-observation-cap-and-context-budget.md`). Its architecture is new: 18 of
24 layers are linear attention. Before any trial or baseline, does vLLM serve it on the GPU
we have, and can it act through our agent and the harness? The g6e instance wasn't
available, so this ran on a g5.xlarge.

## What we checked

- **Instance:** g5.xlarge in ap-south-1a: 4 vCPUs, 15.8 GiB RAM, one NVIDIA A10G with
  23,028 MiB (compute capability 8.6). An AWS Deep Learning AMI on Ubuntu 26.04.1 LTS,
  kernel 7.0.0-1012-aws, NVIDIA driver 595.91.07 preinstalled. The kind cluster came back
  Ready after the stop/start.
- **Where weights go.** `HF_HOME` is unset in the shell, `~/.bashrc`, `~/.profile`,
  `/etc/environment`, `/etc/profile.d` and a login shell, and nothing under `/etc` points a
  cache elsewhere. The default cache is `~/.cache/huggingface` on the EBS root volume. The AMI
  mounts the instance-store SSD at `/opt/dlami/nvme` (228 GB, via LVM), which is wiped on
  every stop, so nothing is kept there. Weights were downloaded with `HF_HOME` set explicitly
  to `/home/ubuntu/.cache/huggingface`, pinned to revision
  `15852e8c16360a2fea060d615a32b45270f8a8fc` (4.3 GB).
- **Serving environment,** separate from the harness's: `~/venvs/vllm` (uv, Python 3.12),
  vLLM 0.29.0, PyTorch 2.13.0+cu130, transformers 5.17.0, flashinfer-python 0.6.18. vLLM's
  registry lists `Qwen3_5ForConditionalGeneration`.
- **Server command:**

  ```
  HF_HOME=/home/ubuntu/.cache/huggingface VLLM_USE_FLASHINFER_SAMPLER=0 \
  ~/venvs/vllm/bin/vllm serve Qwen/Qwen3.5-2B \
    --revision 15852e8c16360a2fea060d615a32b45270f8a8fc \
    --language-model-only --max-model-len 100000 --gpu-memory-utilization 0.85 \
    --generation-config vllm --host 127.0.0.1 --port 8000
  ```

  `--language-model-only` skips the unused vision tower. `--max-model-len 100000` covers the
  64,000-tiktoken limit, about 96,000 Qwen3.5 tokens, plus the 1,024-token reply.
  `--generation-config vllm` stops vLLM applying model-specific default sampling settings, so
  the agent's temperature and top_p are the only ones, as with gateway models.
- A probe through `OpenAICompatibleAgent` with a simplified prompt, three samples.
- One 30-step smoke batch of `misconfig_app_hotel_res-detection-1` (a training-split problem)
  through the runner, commit `0ef7680`: every reply, every environment response, and the
  parser's error type for each.

## Findings

1. **The first start failed on sampling, not on the model.** Weights loaded (3.63 GiB),
   `torch.compile` took 14 s, the KV cache was sized (13.41 GiB, 1,133,157 tokens, 11.33
   concurrent 100K-token requests) and CUDA graphs were captured. The kernel warmup's first
   sampling step then called FlashInfer's top-k/top-p sampler, which compiles a CUDA kernel on
   first use and raised `RuntimeError: Could not find nvcc and default
   cuda_home='/usr/local/cuda' doesn't exist`. The serving environment does contain `nvcc`,
   inside the CUDA 13 wheel, but not where FlashInfer looks.
2. **`VLLM_USE_FLASHINFER_SAMPLER=0` avoids it.** `flashinfer_sampler_supported()` returns
   False when it is 0, and the sampler then uses its PyTorch/Triton top-k/top-p and Gumbel
   path. The alternative, pointing `CUDA_HOME` at the wheel's toolkit so FlashInfer can
   compile, would also need the host C++ compiler and ninja.
3. **With the switch, the server starts on the A10G.** It was ready 158 s after launch with
   the same KV cache. GPU memory in use was 19.2 GB of 23 GB, vLLM's 85% reservation; the
   host had 9.2 GB available with the kind cluster running.
4. **The agent records the local server, but not the revision.** `describe()` recorded
   `base_url` `http://127.0.0.1:8000/v1` and `serving` `{root: "Qwen/Qwen3.5-2B",
   max_model_len: 100000, owned_by: "vllm", server_version: "0.29.0"}`. `root` is the model
   ID, so the pinned revision isn't in `batch.json`.
5. **In a probe, replies had a Thought but unquoted arguments.** With a simplified prompt
   (three API docs and the detection instructions' format text, without their quoted
   `exec_shell("ls -l")` example), three samples each wrote a Thought and exactly one fenced
   block such as `get_logs(test-hotel-reservation, service)`. All three failed the parser with
   `Unsupported AST node type: <class 'ast.BinOp'>`, because the bare
   `test-hotel-reservation` parses as a subtraction; the same call with quoted arguments
   parses. Completion tokens (76–136) matched the visible text, with no reasoning fields.
6. **In the smoke batch, Qwen3.5-2B never executed an action.**
   `runs/2026-09-14T161925Z_smoke-qwen3.5-2b` ended `step_limit` after 30 steps, `solution`
   null, `Invalid Format`, `parse_errors: 30`. All 30 replies had a Thought, and all 30
   environment responses were the parser's "Only have one pair of three ticks" error
   (`parser.py:16-18`): each reply had zero or several fenced blocks rather than exactly one.
   The episode went through three phases:
   - **Turns 1–5:** a coherent Thought followed by an inline action with no fence and
     unquoted arguments, e.g. `Action: get_logs(test-hotel-reservation, Hotel Reservation)`.
   - **Turns 6–15:** replies of 3,700–3,900 characters reasoning about the error itself. The
     parser's error message shows its own fenced examples, and the model quoted backticks
     repeatedly (up to 87 per reply) while trying to match them.
   - **Turns 16–30:** replies without any fence that give up and write
     `Action: submit("No")` inline, reasoning that it can't collect telemetry. Had one parsed,
     it would have been scored `Incorrect`.
   The largest context sent was 15,781 tiktoken tokens; the cap and trimming never fired.
   Qwen3-32B and Qwen3-Next-80B, with the same prompt and agent, wrote parseable actions on
   nearly every turn (`notes/2026-09-14-agent-prompt-and-context.md`, Finding 7;
   `notes/2026-09-14-observation-cap-and-context-budget.md`, Verification).

## Decision

- Serve B1 with the command above, and record the FlashInfer switch alongside the model
  revision whenever the serving setup is described.
- **B1's success floor is the open problem.** On this prompt Qwen3.5-2B executes no actions, so
  neither task success nor adherence can be measured for it. How to address it is not decided
  here: see Open.

## Open

- **The format floor.** Options, not yet chosen: a concrete fenced example in the shared
  per-turn text (a prompt change for every condition, needing re-verification on the other
  models); a larger B1 candidate such as Qwen3.5-4B or Qwen3-4B-Instruct-2507; the planned
  comparison with Ministral-3-3B. A single-turn replay of the recorded first turn with many
  samples would measure parse rates for each without the cluster.
- **Recording the revision.** Serving the snapshot directory
  (`~/.cache/huggingface/hub/models--Qwen--Qwen3.5-2B/snapshots/<revision>`) with
  `--served-model-name Qwen/Qwen3.5-2B` would make the reported `root` contain the revision.
  Not tested.
- The PyTorch/Triton sampler and FlashInfer's sampler draw from the same top-k/top-p
  distribution by different kernels. Keep the sampler the same across B1, T1 and T2.
- The serving flags and environment variables aren't recorded in `batch.json`; only what the
  server reports is.

## Correction (2026-09-14): the format floor is decided

The first Open item is decided in `notes/2026-09-14-b1-model-trial.md`: the per-turn text now
shows the action fenced, and B1 is Qwen3.5-4B, since Qwen3.5-2B parsed only 13 of 20 replayed
first turns even with that change.
