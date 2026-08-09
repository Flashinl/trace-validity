import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from config import MODEL_NAME, MAX_NEW_TOKENS


class GoedelProver:
    def __init__(self, model_name=MODEL_NAME, device="cuda"):
        self.device = device
        torch.set_default_device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype="auto", trust_remote_code=True
        )

    def generate(self, prompt, temperature=0.0, num_trajectories=1, max_new_tokens=MAX_NEW_TOKENS):
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        do_sample = temperature > 0.0

        outputs_list = []
        for _ in range(num_trajectories):
            gen_kwargs = dict(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
            )
            if do_sample:
                gen_kwargs["temperature"] = temperature

            outputs = self.model.generate(**gen_kwargs)
            input_length = inputs.input_ids.shape[1]
            generated_tokens = outputs[0][input_length:]
            text = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)
            outputs_list.append(text)

        return outputs_list
