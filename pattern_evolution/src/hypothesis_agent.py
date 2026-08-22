"""Optional OpenAI-compatible Hypothesis Generation Agent.

The API response is an explanatory view. It cannot alter detector constraints,
causal acceptance, or replay gates.
"""

from __future__ import annotations

import ast
import json
import re
import urllib.request
from pathlib import Path
from typing import Any


ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def load_api_config(path: str | Path) -> dict[str, str]:
    allowed = {"api_type", "api_key", "base_url", "model_name_gene", "model_tag_gene"}
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines()[:60]:
        matched = ASSIGNMENT.match(line)
        if not matched or matched.group(1) not in allowed:
            continue
        name, raw = matched.groups()
        try:
            value = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            value = raw
        values[name] = str(value)
    required = {"api_key", "base_url", "model_name_gene"}
    missing = sorted(required - set(values))
    if missing:
        raise ValueError(f"API config missing fields: {missing}")
    return values


def _parse_json_content(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def generate_hypothesis(canonical: dict[str, Any], config_path: str | Path, timeout: int = 60) -> dict[str, Any]:
    config = load_api_config(config_path)
    prompt_payload = {
        "family": canonical["family"],
        "roles": canonical["roles"],
        "required_edges": canonical["required_edges"],
        "observations": canonical["observations"],
        "fingerprint": {
            "degree_signature": canonical["fingerprint"]["degree_signature"],
            "temporal_order": canonical["fingerprint"]["temporal_order"],
        },
    }
    system = (
        "You are the Hypothesis Generation Agent in an AML research prototype. "
        "Propose an interpretable hypothesis from anonymized graph structure only. "
        "Do not claim real-world causation or use labels. Return strict JSON with keys: "
        "hypothesis_name, mechanism, expected_invariants, limitations. "
        "Keep mechanism under 120 words, expected_invariants to at most 4 short items, "
        "limitations to at most 3 short items, and the complete response under 350 words."
    )
    user = "Analyze this causally validated structural summary:\n" + json.dumps(prompt_payload, sort_keys=True)
    request_body = {
        "model": config["model_name_gene"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 1600,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        config["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response_body = json.loads(response.read().decode("utf-8"))
    content = response_body["choices"][0]["message"]["content"]
    parsed = _parse_json_content(content)
    return {
        "status": "success",
        "model": config["model_name_gene"],
        "api_type": config.get("api_type", "openai-compatible"),
        "hypothesis": parsed,
        "raw_content": content,
        "usage": response_body.get("usage", {}),
    }
