import json
import os
import re


MODEL = lambda: os.getenv("BRIEFING_MODEL", "claude-sonnet-5-5")
WEB_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 14}


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _stream(messages, system, max_tokens, tools=None, max_pauses=3):
    client = _client(); current = list(messages)
    for _ in range(max_pauses + 1):
        kwargs = dict(model=MODEL(), max_tokens=max_tokens, system=system, messages=current)
        if tools: kwargs["tools"] = tools
        with client.messages.stream(**kwargs) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        current.append({"role": "assistant", "content": response.content})
    raise RuntimeError("Model paused too many times")


def _json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start: raise ValueError("Model did not return a JSON object")
    return json.loads(text[start:end + 1])


def build_briefing(start, end, learner):
    system = """You are the research editor for Monday Briefing, a single-user educational weekly course. Search the web for EVERY factual claim. Never invent figures, quotes, events, names, or URLs. Only include URLs actually retrieved. Label disclosure lag such as 13F reporting. Be concise, concrete, calm, and free of hype. This informs financial understanding only: never recommend buy, sell, hold, timing, trades, allocations, or price targets. Return exactly one valid JSON object and no markdown."""
    prompt = f"""Research the completed week {start} through {end}, inclusive. Cover Markets & investing, Real estate & mortgages, Tech, AI & industry, plus Movers & investors.

Learner model (adapt level, topic mix, concepts and quiz accordingly):
{json.dumps(learner, ensure_ascii=False)}

Return this exact shape:
{{"headline":"...","tldr":["3-4 bullets"],"movers":[{{"name":"","kind":"investor|institution|market mover","what_happened":"","takeaway":"","sources":[{{"title":"","url":"https://..."}}]}}],"items":[{{"topic":"one of the three exact topics","title":"","summary":"","why_it_matters":"","concept":"one concept taught clearly","sources":[{{"title":"","url":"https://..."}}]}}],"trends":[{{"trend":"","evidence":"evidenced across several items","confidence":"low|medium|high","caveat":""}}],"concepts":[{{"topic":"one exact topic","term":"","definition":"","example":"tied to this week"}}],"decision_lens":[{{"knowledge_point":"","questions_to_ask":[""]}}],"quiz":[{{"topic":"one exact topic","concept":"","q":"","options":["","",""],"answer_index":0,"explanation":""}}]}}

Requirements: 3-5 movers, about 8 items split across all topics, 0-3 trends (empty is valid when no clear trend), 4-6 concepts, 3-5 decision lenses, exactly 6 quiz questions. Use primary sources where possible. Ground each story and mover with retrieved http(s) sources."""
    return _json(_stream([{"role": "user", "content": prompt}], system, 12000, [WEB_TOOL]))


def tutor_reply(item, history, question, level, allow_search=True):
    system = """You are a patient financial-literacy tutor. Answer in under 220 words with short structured paragraphs. Bold 2-4 key terms using Markdown, include exactly one concrete example, then end with exactly two follow-up prompts, each on its own line and beginning '→ '. Calibrate to the learner level. Never advise buy/sell/hold, market timing, allocation, or give a price target. Reframe 'should I' questions into relevant decision factors. If web search is used, cite retrieved links in Markdown and never invent a URL."""
    messages = []
    for row in history[-8:]: messages.append({"role": row["role"], "content": row["content"]})
    messages.append({"role": "user", "content": f"Learner level: {level}\nCard context: {json.dumps(item)}\nQuestion: {question}"})
    return _stream(messages, system, 1800, [dict(WEB_TOOL, max_uses=4)] if allow_search else None)


def coach_note(result, learner):
    system = "Write one coaching note under 90 words: what the learner grasps, what to slow down on, and one focus. No financial recommendations. Plain text only."
    return _stream([{"role":"user","content":json.dumps({"quiz":result,"learner":learner})}], system, 300)

