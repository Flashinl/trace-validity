import sys
import time

import torch
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

from config import (
    MODEL_NAME,
    MAX_NEW_TOKENS,
    MODEL_MAX_CONTEXT,
    PROMPT_TOKEN_SAFETY_MARGIN,
    VRAM_SAFETY_MARGIN_BYTES,
    TOP_P,
)

_GB = 1024 ** 3


class InsufficientVRAMError(RuntimeError):
    """Not enough GPU memory. We fail rather than offload to CPU."""


def estimate_fp16_weight_bytes(cfg):
    """Parameter count from the model config, at 2 bytes/param."""
    head_dim = getattr(cfg, "head_dim", None) or cfg.hidden_size // cfg.num_attention_heads
    kv_heads = getattr(cfg, "num_key_value_heads", None) or cfg.num_attention_heads

    embed = cfg.vocab_size * cfg.hidden_size
    lm_head = 0 if getattr(cfg, "tie_word_embeddings", False) else embed
    attn = (
        cfg.hidden_size * cfg.num_attention_heads * head_dim  # q
        + 2 * cfg.hidden_size * kv_heads * head_dim           # k, v
        + cfg.num_attention_heads * head_dim * cfg.hidden_size  # o
    )
    mlp = 3 * cfg.hidden_size * cfg.intermediate_size
    params = embed + lm_head + cfg.num_hidden_layers * (attn + mlp)
    return params * 2, params


def estimate_kv_cache_bytes(cfg, context, batch=1):
    head_dim = getattr(cfg, "head_dim", None) or cfg.hidden_size // cfg.num_attention_heads
    kv_heads = getattr(cfg, "num_key_value_heads", None) or cfg.num_attention_heads
    return 2 * cfg.num_hidden_layers * kv_heads * head_dim * 2 * context * batch


def resolve_context_window(cfg):
    """The model's real context window, honouring rope_scaling if present."""
    base = getattr(cfg, "max_position_embeddings", None)
    if not base:
        raise RuntimeError(
            f"{MODEL_NAME} config has no max_position_embeddings; refusing to "
            "guess a context window."
        )
    scaling = getattr(cfg, "rope_scaling", None)
    factor = 1.0
    if scaling:
        factor = float(scaling.get("factor", 1.0) or 1.0)
    return int(base * factor), base, scaling


class GoedelProver:
    def __init__(
        self,
        model_name=MODEL_NAME,
        device="cuda",
        dtype=torch.float16,
        max_batch=1,
        preflight=True,
    ):
        self.device = device
        self.model_name = model_name

        self.config = AutoConfig.from_pretrained(model_name, trust_remote_code=True)
        self.context_window, base_ctx, scaling = resolve_context_window(self.config)
        if self.context_window != MODEL_MAX_CONTEXT:
            print(
                f"[warn] config.MODEL_MAX_CONTEXT={MODEL_MAX_CONTEXT} but the model "
                f"reports {self.context_window} "
                f"(max_position_embeddings={base_ctx}, rope_scaling={scaling}). "
                "Using the model's value.",
                file=sys.stderr,
            )

        if preflight:
            self._preflight_vram(dtype)

        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        # Explicitly NOT device_map="auto": accelerate would silently offload
        # layers to CPU/disk when VRAM is short, which we must never do.
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )
        self.model.to(device)
        self.model.eval()

    def _preflight_vram(self, dtype):
        weight_bytes, params = estimate_fp16_weight_bytes(self.config)
        kv_bytes = estimate_kv_cache_bytes(self.config, self.context_window)
        required = weight_bytes + kv_bytes + VRAM_SAFETY_MARGIN_BYTES

        dtype_name = str(dtype).replace("torch.", "")
        detail = (
            f"{self.model_name}: ~{params/1e9:.2f}B params\n"
            f"  weights ({dtype_name}):".ljust(26) + f"{weight_bytes/_GB:6.2f} GiB\n"
            + f"  KV cache @ {self.context_window} tok:".ljust(26)
            + f"{kv_bytes/_GB:6.2f} GiB\n"
            + "  safety margin:".ljust(26) + f"{VRAM_SAFETY_MARGIN_BYTES/_GB:6.2f} GiB\n"
            + "  required:".ljust(26) + f"{required/_GB:6.2f} GiB"
        )

        if not torch.cuda.is_available():
            raise InsufficientVRAMError(
                "No CUDA device available. Generation needs a GPU and this "
                "pipeline will not run the model on CPU.\n" + detail
            )

        free, total = torch.cuda.mem_get_info()
        name = torch.cuda.get_device_name(0)
        print(
            f"[vram] {name}: {free/_GB:.2f} GiB free / {total/_GB:.2f} GiB total",
            file=sys.stderr,
        )
        print("[vram] " + detail.replace("\n", "\n[vram] "), file=sys.stderr)

        if free < required:
            raise InsufficientVRAMError(
                f"Insufficient VRAM on {name}: {free/_GB:.2f} GiB free, "
                f"{required/_GB:.2f} GiB required.\n{detail}\n"
                "Refusing to offload to CPU. Run this on the 24 GB L4 target."
            )

    def token_budget(self, prompt):
        """Effective max_new_tokens for this prompt, from the real context window."""
        prompt_len = len(self.tokenizer(prompt)["input_ids"])
        room = self.context_window - prompt_len - PROMPT_TOKEN_SAFETY_MARGIN
        if room <= 0:
            raise ValueError(
                f"Prompt is {prompt_len} tokens but the context window is "
                f"{self.context_window}; no room left to generate."
            )
        return min(MAX_NEW_TOKENS, room), prompt_len

    def generate(self, prompt, temperature=0.0, num_trajectories=1, batch=1, seed=None):
        """Generate trajectories for one prompt.

        Returns a list of dicts with the completion text and truncation flags.
        """
        max_new_tokens, prompt_len = self.token_budget(prompt)
        if max_new_tokens < MAX_NEW_TOKENS:
            print(
                f"[budget] prompt={prompt_len} tok -> max_new_tokens capped to "
                f"{max_new_tokens} (context {self.context_window})",
                file=sys.stderr,
            )

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        do_sample = temperature > 0.0
        eos_id = self.tokenizer.eos_token_id

        results = []
        remaining = num_trajectories
        while remaining > 0:
            k = min(batch, remaining)
            gen_kwargs = dict(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                num_return_sequences=k,
                pad_token_id=eos_id,
            )
            if do_sample:
                gen_kwargs["temperature"] = temperature
                gen_kwargs["top_p"] = TOP_P

            if seed is not None:
                torch.manual_seed(seed + len(results))

            t0 = time.perf_counter()
            with torch.no_grad():
                outputs = self.model.generate(**gen_kwargs)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            elapsed = time.perf_counter() - t0

            for row in outputs:
                gen_tokens = row[prompt_len:]
                # generate() right-pads short sequences in a batch with pad_token_id
                # (== eos here); strip that padding before measuring length.
                n_gen = int(gen_tokens.shape[0])
                while n_gen > 0 and int(gen_tokens[n_gen - 1]) == eos_id:
                    n_gen -= 1
                stopped_on_eos = n_gen < int(gen_tokens.shape[0])
                text = self.tokenizer.decode(gen_tokens, skip_special_tokens=True)

                hit_token_limit = (not stopped_on_eos) and n_gen >= max_new_tokens
                closed_fence = "```" in text
                results.append(
                    {
                        "text": text,
                        "prompt_tokens": prompt_len,
                        "generated_tokens": n_gen,
                        "max_new_tokens": max_new_tokens,
                        "stopped_on_eos": stopped_on_eos,
                        "hit_token_limit": hit_token_limit,
                        "closed_fence": closed_fence,
                        # Loud, explicit truncation signal (issue #4).
                        "truncated": hit_token_limit or not closed_fence,
                        "batch_seconds": elapsed,
                        "seconds": elapsed / k,
                    }
                )
            remaining -= k

        return results
