# How Fixel Is "Trained" (and Why It Isn't, Exactly)

> **Short version:** Fixel is not a newly trained AI. It's a program wrapped around **Claude**, a model Anthropic already trained, and around **Gemini** if you switch to it. Training a model like that costs huge amounts of money and computing power. Fixel's intelligence comes from the model, and its *personality, skills, and memory* come from the code in this repo. This document explains both halves, and every way you can make Fixel smarter yourself.

---

## Table of contents

1. [What "training an AI" actually means](#1-what-training-an-ai-actually-means)
2. [Why Fixel doesn't train its own model](#2-why-fixel-doesnt-train-its-own-model)
3. [How Fixel works instead: the five layers](#3-how-fixel-works-instead-the-five-layers)
4. [How you can make Fixel smarter, from easiest to hardest](#4-how-you-can-make-fixel-smarter-from-easiest-to-hardest)
5. [Is Fixel better than Gemini's free API?](#5-is-fixel-better-than-geminis-free-api)
6. [Glossary](#6-glossary)

---

## 1. What "training an AI" actually means

Models like Claude, Gemini, and ChatGPT are **large language models (LLMs)**. Training one happens in stages.

### Stage 1: Pretraining (learning language and facts)

- The model starts as billions of random numbers called **weights** or **parameters**.
- It reads an enormous amount of text and code, roughly a large fraction of the public internet plus books and other sources.
- Its only task is to **predict the next word** (more precisely, the next *token*, a chunk of a word).
- Each time it guesses wrong, a math procedure (**gradient descent**) nudges all the weights slightly toward the right answer.
- After trillions of these nudges, the weights encode grammar, facts, reasoning patterns, and coding knowledge.

**Cost:** thousands of specialized chips (GPUs or TPUs) running for weeks to months. For frontier models, estimates run to tens or hundreds of millions of dollars. This is the part people mean by "training an AI."

### Stage 2: Fine-tuning (learning to be an assistant)

A pretrained model can continue text, but it doesn't yet know how to *help*. It's then trained further on curated examples of good conversations, such as questions paired with ideal answers. This is called **instruction tuning** or **supervised fine-tuning**.

### Stage 3: Learning from feedback

The model writes several answers, and humans or automated graders score which one is better. The model is trained to produce more answers like the good ones. This is called **reinforcement learning**, and the human-feedback version is **RLHF**. It's a big part of what makes a model helpful, honest, and careful about safety.

### Stage 4: Testing and release

Companies test the model on benchmarks and for safety problems, then release it through an **API**, a web service your programs can send requests to. That's the point where Fixel comes in.

> **Key idea:** All of this happens *before* you ever use the model. When Fixel sends Claude a screenshot, Claude's weights don't change. Nothing Fixel does retrains Claude.

---

## 2. Why Fixel doesn't train its own model

| Option | Cost | Result |
|---|---|---|
| Train a model from scratch | Millions of dollars, a data center, months | Far worse than Claude or Gemini unless you're a major AI lab |
| Fine-tune an existing model | Hundreds to thousands of example conversations, plus money or a GPU | Better at one narrow style; still limited by the base model |
| **Use a frontier model + build a smart layer around it (what Fixel does)** | A few cents per question | Top-tier intelligence, plus features built for your workflow |

A laptop can't train anything that competes with Gemini or Claude. The way to beat a free chatbot is to **use one of the strongest available models and build a better workflow around it.** That's Fixel.

---

## 3. How Fixel works instead: the five layers

When you double-tap **Right Option**, here's what makes the answer good, and where each piece lives in the code.

### Layer 1: The brain (the pretrained model)

**Files:** `fixel/brain/claude.py`, `fixel/brain/gemini.py`

Fixel sends your screenshots and question to Claude (`claude-sonnet-5-5` by default, `claude-opus-5-5` for hard problems) or to Gemini. All the raw intelligence (reading screenshots, knowing what an error means, solving math) comes from here.

Two settings make the brain work harder for you:

- **Adaptive thinking** (`thinking = true` in `~/.fixel/config.toml`) lets Claude reason privately before answering. That gives better answers on hard problems, a bit more slowly.
- **Prompt caching** means that on follow-up questions, Claude reuses the parts it has already read (the instructions and your screenshots) instead of re-reading them from scratch. That's faster and cheaper.

### Layer 2: The instructions (Fixel's "personality training")

**File:** `fixel/prompts.py`

This is the closest thing Fixel has to training, and it's done in plain English. Every request includes a **system prompt**, a set of standing instructions that shapes how the model behaves. Fixel's system prompt tells the model:

- **Who it is:** a fast, practical problem-solver living in your terminal.
- **The output contract:** start every reply with a hidden header:
  ```
  MODE: error
  KEY: ModuleNotFoundError: No module named 'numpy'
  ---
  ```
- **How to classify the screenshot:** error, math, doc, writing, ui, or general.
- **How to answer each kind:**
  - error → **Cause**, then **Fix** as one paste-ready code block
  - math → numbered steps, then `Answer: …`
  - doc → a short summary, then a **Draft** you can copy
  - writing → the essay-feedback format defined in `WRITING_FORMAT`
  - ui → exact click-by-click steps
- **Style rules:** lead with the answer, quote exact names from the screen, no filler.

This technique is called **prompt engineering**. It changes the model's *behavior* without changing its *weights*. Edit `prompts.py` and Fixel behaves differently on your very next question.

### Layer 3: Understanding the answer (parsing)

**File:** `fixel/parse.py`

Fixel reads the hidden header out of each reply as it streams in. That lets it:

- Show a colored badge (**ERROR**, **MATH**, **DOC**, **WRITING**, **UI**) instead of raw text.
- Find "the fix" so **`/copy`** copies just that part.
- Find the shell command so **`/run`** can run it (only after you type `y`).

Chatbots usually answer every question in the same format. Fixel's answers have a structure it can act on.

### Layer 4: Memory (the "learning from experience" part)

**Files:** `fixel/casefile.py` (stored in `~/.fixel/casefile.db`), `fixel/ocr.py`, `fixel/memory.py`

The model itself forgets everything between conversations. Fixel doesn't. After every answer it saves a **case**: the mode, the key phrase (such as the exact error message), your question, the answer, the screenshots, and the text on those screenshots.

**Reading your screen, on your Mac.** When you take a screenshot, Fixel uses macOS's built-in text recognition (the same feature that lets you copy text out of photos) to read the text in it. That takes under a second and nothing is sent anywhere.

**Checking its notes before answering.** When you press Enter on a new problem, Fixel searches your past cases for ones whose key phrase shows up on your new screen. A past case counts if at least 60% of its key words appear (`recall_threshold = 0.6`). Fixel shows you what it found:

```
🧠 Using your past case from Sep 12 ✅: ModuleNotFoundError: No module named 'numpy'
   /open shows it · plus 2 notes about you
```

It then sends up to two matching cases to the AI along with your question, in a block marked `[Fixel memory]`. The AI builds on a past fix if it's relevant and ignores it if it isn't. This technique is called **retrieval-augmented generation (RAG)**: Fixel *retrieves* your history and hands it to the model, so the model's answer is *augmented* by what worked for you before. Nothing about the model itself changes.

**Mark what worked (/worked).** After a fix actually works, type `/worked`. The case gets a ✅, Fixel reaches for it first next time, and the AI is told that fix was confirmed to work.

**About-me notes.** `/remember I use Python 3.12 and zsh` saves a fact to `~/.fixel/about-me.md`. Every question includes your notes, so answers fit your setup, classes, or job. `/memory` lists them; `/forget 2` removes one. You can also edit the file in any text editor.

Search all your past cases with `/cases <words>`, and open one with `/open <number>`.

### Layer 5: Teaching modes

**Learn mode (/learn)** adds extra instructions to the system prompt: give one hint or guiding question at a time, check the user's attempts, and only reveal the full solution when they send `/answer`. Same model, completely different teaching behavior, and it all comes from instructions.

---

## 4. How you can make Fixel smarter, from easiest to hardest

### Level 1: Change settings (2 minutes, no coding)

Edit `~/.fixel/config.toml`:

| Setting | What it does |
|---|---|
| `default_model = "opus"` | Uses Claude's strongest model. Smarter, slower, and more expensive per question. |
| `thinking = true` | Claude only: think before every answer. Otherwise `/deeper` turns on deep thinking for one answer. |
| `recall_threshold = 0.5` | Makes Fixel reuse past cases more readily (0.8 = only near-exact matches). |
| `double_tap_window = 0.5` | Gives you more time between Right Option taps. |

You can also switch models anytime inside Fixel with `/model opus`, `/model sonnet`, or `/model gemini`.

### Level 2: Edit the instructions (10 minutes, plain English)

Open `fixel/prompts.py` and change `BASE_SYSTEM`. Examples:

**Make it explain more, for learning:**
```
- After the fix, add one sentence explaining the underlying concept.
```

**Specialize it for your classes or job:**
```
- The user is a high-school student taking AP Calculus and AP Physics.
  Use the notation their textbook uses and mention which unit a problem is from.
```

**Specialize it for your code:**
```
- The user mostly writes Python and JavaScript on macOS with VS Code.
  Prefer fixes that use pip/npm and paths that work in zsh.
```

Save the file and restart Fixel. Tips:

- **Be specific.** "Be concise" is weak; "at most 6 sentences" is strong.
- **Don't break the header rules** (the `MODE:` / `KEY:` / `---` section). Fixel's badges, copy, and run features depend on them.
- **Test after every change** with a few real screenshots.

### Level 3: Teach by example ("few-shot prompting," 30 minutes)

Models learn a lot from examples placed in the prompt. Add a section like this to the end of `BASE_SYSTEM`:

````text
## Examples of ideal answers

Example (error):
MODE: error
KEY: zsh: command not found: python
---
**Cause:** macOS ships `python3`, not `python`.
**Fix:**
```bash
alias python=python3
```
**Why:** Apple removed the old Python 2 `python` command in macOS 12.3.
````

Two or three excellent examples often improve answers more than paragraphs of rules. It's the closest you can get to "training" without touching the model's weights.

### Level 4: Feed it your experience (built in: just use it)

Fixel already does retrieval-augmented generation (see Layer 4). To make the most of it:

1. **Tell it about yourself** with `/remember`: your classes, languages, tools, job. Three or four good facts go a long way.
2. **Type `/worked` whenever a fix works.** Proven fixes are what Fixel reaches for first.
3. **Keep using it.** Every case you solve becomes something Fixel can bring back the next time.

Want to change how memory is used? `past_cases_context()` in `fixel/memory.py` decides what the AI is told, and `CaseFile.similar()` in `fixel/casefile.py` decides which past cases count as similar.

### Level 5: Real fine-tuning (advanced, usually not worth it here)

**Fine-tuning** means actually changing a model's weights with your own examples.

**What you'd need:**
- **Data:** typically hundreds to thousands of high-quality question → ideal-answer pairs. Your case file and saved notes (`~/Fixel Notes/`) could become a starting dataset.
- **A model you're allowed to fine-tune.** Some AI companies offer fine-tuning for certain models through their APIs, and open-weight models (such as Llama or Qwen) can be fine-tuned on your own GPU using a technique called **LoRA**. Options change often, so check each provider's current documentation.
- **Evaluation:** a set of test questions to prove the fine-tuned model is actually better.

**Why it's probably not worth it for Fixel:**
- A small fine-tuned model is usually *less* capable than Claude Sonnet or Opus with a good prompt.
- Fine-tuning teaches *style and format* well. It's a poor way to add new knowledge.
- Levels 2-4 get you most of the benefit for almost none of the cost.

### Level 6: Training from scratch

Not realistic for an individual. See [section 2](#2-why-fixel-doesnt-train-its-own-model).

---

## 5. Is Fixel better than Gemini's free API?

An honest comparison:

| | Gemini free API on its own | Fixel |
|---|---|---|
| **Raw intelligence** | Depends on the Gemini model; the free tier is rate-limited | Uses Claude Sonnet/Opus by default; also supports Gemini |
| **Getting a screenshot in** | You build that yourself | Double-tap Right Option, drag, Enter |
| **Answer format** | Whatever you get | Shaped to the problem type (fix, steps, draft, clicks) |
| **Acting on answers** | Copy by hand | `/copy` copy fix, `/run` run command, `/save` save note |
| **Memory** | None between sessions | Remembers your past fixes and facts about you, and sends them to the AI |
| **Learning mode** | No | Hints instead of answers (/learn) |
| **Cost** | Free (with limits) | Claude: pay per question (usually cents). Gemini: free tier |

Fixel's advantage isn't a smarter model of its own. It's **a stronger model plus a workflow built around how you work.** If you'd rather not pay, Fixel runs on Gemini too, and you still get every Fixel feature.

---

## 6. Glossary

| Term | Meaning |
|---|---|
| **LLM** | Large language model: an AI trained on huge amounts of text to predict and generate language. |
| **Weights / parameters** | The billions of numbers inside a model that encode what it learned. Training changes them; using the model doesn't. |
| **Token** | A chunk of text (often part of a word) that models read and write. API pricing is per token. |
| **Pretraining** | The huge, expensive first stage of learning from raw text. |
| **Fine-tuning** | Extra training on a smaller, targeted dataset to change a model's behavior. |
| **RLHF** | Reinforcement learning from human feedback: training a model toward answers people rate as better. |
| **API** | A web service programs call. Fixel calls Claude's and Gemini's APIs. |
| **API key** | A secret password that identifies you to an API and bills your account. Fixel stores it in the macOS Keychain. |
| **System prompt** | Standing instructions sent with every request. Fixel's lives in `fixel/prompts.py`. |
| **Prompt engineering** | Shaping a model's behavior by writing better instructions and examples. |
| **Few-shot prompting** | Including example answers in the prompt so the model copies their style. |
| **RAG** | Retrieval-augmented generation: looking up relevant info (like past cases) and giving it to the model with the question. |
| **Prompt caching** | Reusing already-processed parts of a request (instructions, screenshots) on follow-ups to save time and money. |
| **Adaptive thinking** | A Claude feature that lets the model reason internally before answering, taking as much time as the problem needs. |
| **LoRA** | A cheap fine-tuning technique that trains small add-on weights instead of the whole model. |

---

## What Fixel needs from you next

Fixel is built and tested, but it can't think until it has an API key:

1. Get a key: **Claude** at console.anthropic.com (pay per use) or **Gemini** at aistudio.google.com/apikey (free tier).
2. In **Terminal.app**, run `fixel setup` and paste the key. It's stored in your Mac's Keychain.
3. Turn on **Input Monitoring** and **Screen Recording** for Terminal when System Settings opens, then quit and reopen Terminal.
4. Run `fixel`, double-tap **Right Option**, and drag over something you're stuck on.
