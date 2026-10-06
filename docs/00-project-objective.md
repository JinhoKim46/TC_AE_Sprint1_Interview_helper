# Project Objective — Build an Interview Practice App

Source: Turing College AE, Sprint 1 *Foundations of LLM Application Development*, project brief "Build an Interview Practice App".

This document records **everything in the brief**, plus my understanding of each item. Nothing is filtered or chosen yet. Planning (which items to do, and how) happens later, from this document.

Each section has two parts:

- **Brief:** what the brief says
- **Understanding:** what I think it means, and any notes

---

## 1. Overview

**Brief:** Put the whole sprint together in one app: calling the OpenRouter API, writing system prompts with different techniques, tuning LLM settings, and adding security guards, all behind a real Streamlit UI. Move from following tutorials to making my own design decisions. The skills carry into Sprint 2 (LangChain, RAG, vector databases).

The overview diagram shows this flow:

```text
User ──► Streamlit app ──► Security guard ──► OpenRouter API (system prompt + model settings) ──► back to the app
```

**Understanding:** The app is the capstone of Sprint 1. The four building blocks are **API call**, **system prompt**, **model settings** and **security guard**. Every user request passes through the guard before it reaches the model.

| Item | Value |
| --- | --- |
| Topics | Interview Prep, ChatGPT, Prompt Engineering, Web applications |
| Prerequisites | Python or JavaScript; ChatGPT and the OpenRouter API; basic front-end building |
| Estimated time | 5 hours |

---

## 2. Task description

**Brief:**

- Build my own Interview Preparation app: a way to practise for interviews (questions, exercises, personality tests) in an efficient and interesting way, with AI assistance.
- A **single-page website**, written in VS Code (or Cursor), using **Streamlit** (Python) or **Next.js** (JavaScript).
- Call OpenRouter, write a **system prompt** as the instructions for the LLM, and write my own prompt with the interview-prep instructions.
- I choose what to practise. Examples given: interview questions, questions for a specific programming language, questions to ask at the end of the interview, analysing a job description to build an interview-prep strategy. "Experiment!"
- The brief points to "Five simple starter apps" for ideas (their contents weren't included in my copy).
- Experienced engineers may over-engineer: add optional tasks plus their own ideas, and treat it as a portfolio project.
- Use any help: ChatGPT, StackOverflow, friends.

**Understanding:**

- There are two prompt layers. The **system prompt** sets the model's role and rules. The **user prompt** carries the actual interview-prep request. I have to write both.
- The interview-prep focus is left open on purpose. Choosing it is part of the task (see R1).
- "Single page" means one screen/app, not a multi-page site.

---

## 3. Task requirements (mandatory)

| # | Brief | Understanding |
| --- | --- | --- |
| R1 | Research the exact nature of interview preparation you want to do; explore and get creative | Pick and justify an interview-prep focus. The reviewer will ask why I chose it |
| R2 | Figure out how to build the front end: Streamlit components, or HTML/CSS in Next.js | Decide which UI components to use (chat, inputs, sidebar, etc.). Streamlit is recommended for the Python track |
| R3 | Choose one of the allowed OpenRouter models (below) | The model must come from the allow-list |
| R4 | Write **at least 5 system prompts** with different techniques (few-shot, Chain-of-Thought, Zero-Shot, etc.) and check which works best | Five variants, each built on a **different** technique, run on comparable input. Pick a winner and explain why |
| R5 | Add **at least one security guard** to prevent misuse | At least one working protection, e.g. against prompt injection, off-topic use or bad input |

### Allowed models

| Purpose | Model | Note from the brief |
| --- | --- | --- |
| Chat | `openai/gpt-5-mini` | Recommended default |
| Chat | `openai/gpt-5-nano` | Cheaper option |
| Chat | `openai/gpt-5` | Higher-capability option |
| Embeddings (only if needed, e.g. RAG / vector DB) | `qwen/qwen3-embedding-8b` | Recommended default |
| Embeddings | `openai/text-embedding-3-small` | |
| Embeddings | `openai/text-embedding-3-large` | |
| Image generation (optional medium task) | `google/gemini-2.5-flash-image` | On the Sprint 1 allow-list; uses the standard `/chat/completions` endpoint |

**Understanding:** R4's list of techniques ends with "etc.", so other techniques count too: role/persona prompting, structured-output prompting, self-critique/reflection, prompt chaining, generated-knowledge, and so on.

---

## 4. Optional tasks (all of them, unfiltered)

Do these after the core works. The list is sorted by difficulty. **Caution from the brief:** some medium and hard tasks use concepts or libraries introduced later in the course, or need outside research.

### 4.1 Easy

| # | Brief | Understanding |
| --- | --- | --- |
| E1 | Ask ChatGPT to critique your solution from the usability, security and prompt-engineering sides | Get an LLM review of the app/code/prompts on those three sides; record the critique and what I changed because of it |
| E2 | Improve ChatGPT prompts for your personal domain (IT, finance, HR, communication, etc.) | Tailor the prompts to the field I'm actually interviewing in, so the questions use that domain's vocabulary and scenarios |
| E3 | Implement more security constraints, like user input validation and system prompt validation. Could ChatGPT be used to verify these? | Go beyond one guard: validate user input (length, type, content) and check that the system prompt hasn't been overridden or leaked. One option is an LLM call as a checker/classifier |
| E4 | Simulate difficulty levels: adjust the complexity of interview questions (easy, medium, hard) | A difficulty setting that changes what the prompt asks for |
| E5 | Optimise prompts for concise vs. detailed responses | Prompt variants (or a setting) for short vs. in-depth answers; compare the outputs |
| E6 | Generate interviewer guidelines: have ChatGPT create structured evaluation criteria for technical and behavioural interviews | The model produces a rubric (criteria, what good/bad looks like) for both interview types |
| E7 | Simulate a mock interview with AI personas: strict, neutral or friendly interviewer | A persona setting that changes the interviewer's tone and behaviour |
| E8 | Tune at least one model setting (temperature, max tokens, reasoning effort, etc.) and compare how it changes the output | Run the same prompt with different values of one setting and document the differences |

### 4.2 Medium

| # | Brief | Understanding |
| --- | --- | --- |
| M1 | Add all model settings (model, temperature, max tokens, etc.) for the user to tune as sliders/fields | UI controls for every relevant API parameter, sent with each call |
| M2 | Implement at least two structured JSON output formats for the interview prep | Two different JSON schemas the model returns (e.g. a question list, a feedback/score report), parsed and used by the app |
| M3 | Calculate and show the user the price of the prompt; get current pricing from the OpenRouter models endpoint | Read the token usage from each response, multiply by the per-token price from `GET /api/v1/models`, and show the cost |
| M4 | Read the OpenRouter docs, think of your own improvement, and implement it | Open-ended: pick an OpenRouter feature (e.g. streaming, model fallbacks, provider routing, usage accounting) and use it |
| M5 | Try to jailbreak your own app with invalid prompts, messages, job files, etc.; put the results in an **Excel sheet** | Red-team my own app: list each attack, the input, the expected and actual behaviour, and whether the guard held. Deliverable: `.xlsx` |
| M6 | Add a separate text field (or another field) for the job description you're applying for, and get prep for that particular position (RAG) | A JD input that grounds the prep in that role. The brief labels it "RAG", but simply putting the JD in the prompt also counts as grounding the model in my own data |
| M7 | Let the user choose from a list of LLMs (Gemini, OpenAI, etc.) | A model picker covering more than one provider through OpenRouter |
| M8 | Find a creative use of image generation in the project and implement it in code with `google/gemini-2.5-flash-image` | Call `/chat/completions` with `modalities=["image", "text"]` and decode the base64 image from the response (see OpenRouter's image-generation guide). Ideas: an interviewer avatar, an infographic of the feedback, a visual for a scenario question |
| M9 | Add at least one security guard to prevent misuse. **Design for usability:** keep developer settings (model, system-prompt choice) separate from the user experience, since the user may not know much about LLMs | Two parts: (a) a guard, as in R5; (b) a clean candidate view, with the technical controls in a separate developer area (sidebar, expander, tab or mode) |

### 4.3 Hard

| # | Brief | Understanding |
| --- | --- | --- |
| H1 | Use Streamlit (Python) or React (JS) components to build a full-fledged chatbot instead of a one-time API call | Multi-turn chat with history kept in session state; every call sends the conversation so far (system + user + assistant messages) |
| H2 | Use LangChain packages to implement the app with chains or agents | Rebuild the LLM logic with LangChain (prompt templates, chains, or an agent with tools) instead of raw API calls |
| H3 | Add a vector database to check whether the interview-prep data has been seen before, prompting the LLM to generate new data | Embed the generated questions, store them in a vector DB, and use a similarity search to catch near-duplicates; if one is found, ask the LLM for a new question. Needs an embedding model from the list |
| H4 | Use open-source LLMs (not Gemini, OpenAI, etc.) | Run the app on open-weight models (e.g. Llama, Qwen, Mistral, DeepSeek) through OpenRouter or locally |
| H5 | Assess the performance of your prompt and/or model via LLM-as-a-judge (Part 4) or other methods | Automatic evaluation: a judge model scores outputs against criteria. This can also be the method for comparing the 5 system prompts in R4 |

### 4.4 Bonus rule

**Brief:** For maximum points, implement **at least 2 medium and 1 hard** optional task.

**Understanding:** This is the minimum for full bonus. More tasks are allowed, but they don't add to the requirement.

### 4.5 Notes on how the items relate

- **Security guard** appears in R5 (mandatory), E3 (more constraints) and M9 (guard + usability split). One guard can satisfy R5; M9 also needs the developer/user separation.
- **Model settings** appear in E8 (tune one and compare) and M1 (expose all of them in the UI).
- **Prompt comparison** (R4) and **LLM-as-a-judge** (H5) fit together: the judge can score the 5 variants.
- **Structured JSON** (M2) supports the judge (H5), the cost display (M3) and the interviewer guidelines (E6).
- **H3** (vector DB) needs an embedding model; the other tasks don't.

---

## 5. Evaluation criteria (what the reviewer checks)

### 5.1 Understanding core concepts

| Brief | Understanding |
| --- | --- |
| Can explain different prompting techniques clearly | Zero-shot, few-shot, chain-of-thought, role, structured output, etc.: what each one is, when to use it, and examples from my app |
| Understands how LLM settings (temperature, max tokens, etc.) work and affect the output | Temperature = randomness/creativity; max tokens = output length limit (and cut-off risk); reasoning effort = how much the model thinks before answering; plus top_p and the like |
| Understands the differences between the user, system and assistant roles | System = instructions/rules; user = the human's input; assistant = the model's earlier replies, which keep the conversation's context |
| Demonstrates understanding of different LLM output types | Free text vs. structured output (JSON / schema), streaming vs. a complete response, and possibly images |

### 5.2 Technical implementation

| Brief | Understanding |
| --- | --- |
| The project works as intended: you can prepare for an interview by asking the app for help | A real end-to-end use case, demonstrated live |
| Calls the OpenRouter API successfully with the correct parameters | Right endpoint, model id, messages and settings; handles errors |
| Uses a front-end library to build the UI | Streamlit (or Next.js) |

### 5.3 Reflection and improvement

| Brief | Understanding |
| --- | --- |
| Can explain the choice of prompt techniques and parameter settings | Justify the winning prompt and the chosen values, ideally with comparison evidence |
| Understands the potential problems with the application | E.g. hallucination, prompt injection, cost, latency, bias, privacy of the CV/JD data, judge reliability |
| Can suggest improvements to the code and the project | A concrete next-steps list |

---

## 6. Creating the web app

**Brief:** Several ways to build it; Streamlit is recommended. Python track: Streamlit. (The "How to get started" links from the original page weren't included in my copy.)

**Understanding:** Python + Streamlit is my track. Useful Streamlit pieces: `st.chat_message`, `st.chat_input`, `st.session_state`, `st.sidebar`, `st.text_area`, `st.file_uploader`, `st.slider`, `st.selectbox`, `st.write_stream`.

---

## 7. Approach to solving the task (time guidance)

| Brief | Understanding |
| --- | --- |
| Look at "How to get started" in *Creating the web app* | Start from a minimal Streamlit + OpenRouter app |
| Spend 1–5 hours with your own knowledge + ChatGPT; use ChatGPT to understand the task, write, improve and understand the code | AI help is explicitly allowed, but I must understand the code |
| If you're missing knowledge, revisit Sprint 1 or the additional resources | |
| If you make no progress in the first 1–2 hours, spend up to 10 more hours with help from peers and JTLs | Ask for help early |
| If still stuck, study the suggested solution until you understand it | |

---

## 8. Submission and project review

**Brief:** Submit through the GitHub repository created for me, so the reviewer can see the work beforehand. Guides: *Completing a Sprint, Submitting a Project and Scheduling Reviews*, and *Git and GitHub for Beginners*.

**Understanding:** Push the finished project to the course repo, then schedule the review. The README should explain how to run the app.

---

## 9. Additional resources (listed in the brief)

- **OpenRouter Docs:** getting started with the OpenRouter API
- **ChatGPT:** experimenting with an LLM
- **What is an API? What is the OpenRouter API?:** beginner introduction
- **Streamlit YouTube channel:** building AI web apps with Streamlit

---

## 10. Checklist (everything in the brief)

### Mandatory

- [ ] R1 Interview-prep focus chosen and justified
- [ ] R2 Front end built (Streamlit)
- [ ] R3 Allowed OpenRouter model used
- [ ] R4 At least 5 system prompts with different techniques, compared, winner chosen
- [ ] R5 At least one security guard

### Optional — Easy

- [x] E1 ChatGPT critique (usability, security, prompt engineering) — [review and response](../reports/2026-10-05-E1-chatgpt-critique.md)
- [x] E2 Domain-specific prompts — ML/AI-engineering interview types and questions, prompts revised after a ChatGPT review ([PR #51](https://github.com/JinhoKim46/TC_AE_Sprint1_Interview_helper/pull/51), [question bank](02-question-bank.md))
- [ ] E3 More security constraints (input + system-prompt validation, possibly LLM-checked)
- [ ] E4 Difficulty levels (easy / medium / hard)
- [ ] E5 Concise vs. detailed responses
- [ ] E6 Interviewer guidelines / evaluation criteria (technical + behavioural)
- [ ] E7 AI interviewer personas (strict / neutral / friendly)
- [ ] E8 Tune one model setting and compare

### Optional — Medium

- [ ] M1 All model settings as sliders/fields
- [ ] M2 At least two structured JSON output formats
- [ ] M3 Prompt price shown (OpenRouter models endpoint)
- [ ] M4 Own improvement from the OpenRouter docs
- [ ] M5 Jailbreak my own app; results in an Excel sheet
- [ ] M6 Job description field for role-specific prep (RAG)
- [ ] M7 User can choose from a list of LLMs
- [ ] M8 Image generation with `google/gemini-2.5-flash-image`
- [ ] M9 Security guard + developer settings separated from the user experience

### Optional — Hard

- [ ] H1 Full chatbot (multi-turn)
- [ ] H2 LangChain chains or agents
- [ ] H3 Vector DB to detect already-seen prep data and generate new data
- [ ] H4 Open-source LLMs
- [ ] H5 LLM-as-a-judge (or other) evaluation of prompt/model

### Bonus target

- [ ] At least 2 medium + 1 hard done

### Review readiness

- [ ] Can explain prompting techniques, model settings, roles, output types
- [ ] App works end to end and calls OpenRouter correctly
- [ ] Can justify prompt/setting choices, name the app's problems, suggest improvements
- [ ] Pushed to the course GitHub repo; review scheduled
