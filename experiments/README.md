# Experiments

Working experiments exploring the cognitive runtime architecture. Each experiment contains its own source, tests and setup instructions.

## LifeAI

[LifeAI](lifeai/README.md) is a Python/Pygame simulation of embodied agents in a continuous 2D world. A local OpenAI-compatible LLM selects intentions and predictions; deterministic motor systems execute movement, eating and pushing while cognition runs asynchronously.

Agents maintain bounded narrative memory, exchange experiences through arena-wide remote chat, compare predictions with measured outcomes and revisit them during sleep. Life, cognition, speech, movement and memory consolidation consume energy. Death erases the agent's memory while observer journals remain available. The chat roster exposes only participant names and IDs, never their location or private memory. Messages cross obstacles and reach sleeping agents without waking them. Visible dead agents are recognized as unavailable conversation partners without revealing their cause of death.

### Run

Requires Python 3.11 or later and access to an OpenAI-compatible model endpoint. The default endpoint in `.env.example` is reached through the experiment author's VPN; configure `LIFEAI_BASE_URL` for your own server.

```bash
cd experiments/lifeai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
# Edit .env for your model endpoint.
python -m lifeai --check-llm
python -m lifeai --agents 2
```

### Test

From `experiments/lifeai`, with the virtual environment activated:

```bash
python -m unittest discover -s tests -v
```

The automated tests use test doubles and do not require the model server or VPN. Pygame tests use a dummy display. Application code, tests, packaging and the configuration example are included; generated session data and the local environment are excluded.

See the [experiment documentation](lifeai/README.md) for controls, energy rules, memory limits, headless runs and limitations. This is an experimental system: a model's narrative or a successful action is not evidence that its causal interpretation is correct.

